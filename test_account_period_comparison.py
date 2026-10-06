import copy
import json
import subprocess
import unittest
from unittest.mock import patch
from datetime import datetime
import app
from period_comparison import summary, compare
from gerar_dashboard_ads_ml import render_dashboard


class AccountPeriodComparisonTests(unittest.TestCase):
    def data(self, start='2026-09-01', end='2026-09-30'):
        return {'meta': {'period': {'dateFrom': start, 'dateTo': end}},
                'kpis': {'revenue': 300, 'units': 3},
                'items': [{'orders': 2, 'visitsCoverageComplete': False}],
                'accountDailySeries': [{'partial': False, 'visits': 99}]}

    def test_exact_window_same_account_no_recursive_comparison(self):
        period = app._resolve_online_period('30d', compare='previous', now=datetime(2026, 10, 1))
        self.assertEqual(period['comparePeriod']['dateFrom'], '2026-08-02')
        self.assertEqual(period['comparePeriod']['dateTo'], '2026-08-31')
        current = self.data()
        previous = self.data('2026-08-02', '2026-08-31')
        previous['kpis'].update(revenue=200, units=4)
        with patch.object(app, '_build_online_dashboard_data', return_value=(previous, '')) as fetch:
            app._attach_account_period_comparison(current, 'account-a', '7', period)
        fetch.assert_called_once_with('account-a', '7', '2026-08-02', '2026-08-31')
        metrics = current['periodComparison']['metrics']
        self.assertEqual(metrics['revenue']['change'], .5)
        self.assertEqual(metrics['price']['change'], 1)
        self.assertEqual(metrics['units']['change'], -.25)
        self.assertEqual(metrics['visits']['status'], 'unavailable')
        self.assertIsNone(metrics['cancelledOrders']['current'])

    def test_partial_wrong_window_and_none(self):
        p = app._resolve_online_period('30d', compare='previous', now=datetime(2026, 10, 1))
        for previous in (None, self.data(), self.data('2026-08-02', '2026-08-31')):
            if previous: previous['accountDailySeries'][0]['partial'] = True
            current = self.data()
            with patch.object(app, '_build_online_dashboard_data', return_value=(previous, 'missing')):
                app._attach_account_period_comparison(current, 'a', '7', p)
            self.assertEqual(current['periodComparison']['metrics']['revenue']['status'], 'unavailable')
        with patch.object(app, '_build_online_dashboard_data') as fetch:
            app._attach_account_period_comparison(self.data(), 'a', '7', {'compareMode':'none'})
            fetch.assert_not_called()

    def test_zero_baseline_never_infinity(self):
        self.assertEqual(compare({'x': 10}, {'x': 0}, verified=True)['x']['status'], 'zero_baseline')
        self.assertEqual(compare({'x': 0}, {'x': 0}, verified=True)['x']['change'], 0)
        self.assertIsNone(compare({'x': 10}, {}, verified=True)['x']['change'])

    def test_renderer_is_shared_by_kpis_and_account_chart(self):
        html = render_dashboard({'items': [], 'meta': {}})
        functions = 'function periodMetricFormat' + html.split('function periodMetricFormat', 1)[1].split('function renderKpis()', 1)[0]
        script = "const DATA={periodComparison:{enabled:true,period:{dateFrom:'2026-08-02',dateTo:'2026-08-31'},metrics:{units:{status:'available',change:-.25,previous:4}}}}; const safe=String,num=String;" + functions + "console.log(periodComparisonInline('units'));"
        result = subprocess.run(['node', '-e', script], check=True, text=True, encoding='utf-8', capture_output=True)
        self.assertIn('▼ -25%', result.stdout)
        self.assertIn('2026-08-02 a 2026-08-31', result.stdout)
        self.assertIn('periodComparisonInline(metric)', html)
