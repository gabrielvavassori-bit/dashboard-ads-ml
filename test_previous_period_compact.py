"""Regressão: comparação não pode montar e segurar a página inteira do período anterior a cada acesso."""
import unittest
from unittest.mock import patch

import app
from period_comparison import summary


def _full(period):
    return {
        'meta': {'period': period},
        'kpis': {'revenue': 100.0, 'units': 4, 'adsRevenue': 30.0, 'organicRevenue': 70.0,
                 'investment': 10.0, 'tacosBaseRevenue': 100.0, 'tacos': 0.1, 'roas': 3.0,
                 'adsNoSales': 2, 'investmentNoAdsSales': 1.5, 'returnsAvailable': True,
                 'returnsAmount': 5.0, 'returnsOrdersCount': 1},
        'items': [{'orders': 2, 'visitsCoverageComplete': True, 'title': 'x' * 1000, 'dailySeries': [1] * 500},
                  {'orders': 1, 'visitsCoverageComplete': True, 'title': 'y' * 1000, 'dailySeries': [1] * 500}],
        'accountDailySeries': [{'date': '2026-08-07', 'partial': False, 'visits': 7, 'revenue': 100.0}],
    }


class PreviousPeriodCompactTest(unittest.TestCase):
    def setUp(self):
        app._PREVIOUS_PERIOD_CACHE.clear()
        self.sel = {'dateFrom': '2026-08-07', 'dateTo': '2026-09-05'}

    def tearDown(self):
        app._PREVIOUS_PERIOD_CACHE.clear()

    def test_compact_summary_equals_full_and_is_reused(self):
        full = _full(dict(self.sel))
        with patch.object(app, '_build_online_dashboard_data', return_value=(_full(dict(self.sel)), '')) as build:
            first = app._previous_period_compact('c', '', self.sel)
            second = app._previous_period_compact('c', '', self.sel)
        self.assertEqual(build.call_count, 1)
        self.assertEqual(summary(first), summary(full))
        self.assertEqual(summary(second), summary(full))
        self.assertNotIn('title', first['items'][0])  # página inteira não fica em memória
        self.assertFalse(any(r['partial'] for r in first['accountDailySeries']))
        second['kpis']['revenue'] = -1  # cópia: quem lê não altera o cache
        self.assertEqual(app._previous_period_compact('c', '', self.sel)['kpis']['revenue'], 100.0)

    def test_failed_build_is_not_cached(self):
        with patch.object(app, '_build_online_dashboard_data', return_value=(None, 'erro')) as build:
            self.assertIsNone(app._previous_period_compact('c', '', self.sel))
            self.assertIsNone(app._previous_period_compact('c', '', self.sel))
        self.assertEqual(build.call_count, 2)

    def test_other_account_or_window_never_shares_entry(self):
        with patch.object(app, '_build_online_dashboard_data', side_effect=lambda c, a, f, t: (_full({'dateFrom': f, 'dateTo': t}), '')) as build:
            app._previous_period_compact('c1', '', self.sel)
            app._previous_period_compact('c2', '', self.sel)
            app._previous_period_compact('c1', '', {'dateFrom': '2026-08-08', 'dateTo': '2026-09-06'})
        self.assertEqual(build.call_count, 3)


if __name__ == '__main__':
    unittest.main()
