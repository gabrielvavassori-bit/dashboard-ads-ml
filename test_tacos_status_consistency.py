import json
import subprocess
import unittest
from unittest.mock import patch

import app
from gerar_dashboard_ads_ml import render_dashboard
import test_operational_availability as operational_tests


class TacosStatusConsistencyTests(unittest.TestCase):
    def test_same_turnover_base_for_kpi_item_groups_and_daily(self):
        payload = operational_tests.OperationalAvailabilityTests().payload()
        payload['ads']['items'][0].update(total_amount=15, direct_amount=10, indirect_amount=5)
        payload['daily_ads'] = [dict(item_id='MLB123', snapshot_date='2026-09-01', cost=10,
                                    total_amount=15, direct_amount=10, indirect_amount=5)]
        payload['daily_sales'] = [dict(item_id='MLB123', snapshot_date='2026-09-01',
                                      revenue_total=20, units_total=1, orders_count=1)]
        with patch.object(app, '_fetch_dash_ads_json', return_value=payload):
            data, error = app._build_online_dashboard_data('demo', '7', '2026-09-01', '2026-09-02')
        self.assertEqual(error, '')
        for row in [data['kpis'], data['items'][0], data['skuAds'][0],
                    data['campaignAds'][0], data['accountDailySeries'][0]]:
            self.assertEqual(row['tacosBaseRevenue'], 20)
            self.assertEqual(row['tacos'], .5)
        self.assertTrue(data['accountDailySeries'][0]['partial'])
        self.assertEqual(data['items'][0]['adsRevenue'], 15)

    def test_browser_does_not_classify_absence_as_ended(self):
        html = render_dashboard({'items': [], 'meta': {}})
        functions = 'function advertisingState(item)' + html.split('function advertisingState(item)', 1)[1].split('function renderAlerts()', 1)[0]
        cases = [{}, {'campaignStatus': 'Status do anuncio nao informado'},
                 {'campaignStatus': 'Sem campanha ativa'}, {'campaignStatus': 'Inativo'},
                 {'campaignStatus': 'Ativa'}, {'campaignStatus': 'Encerrada'},
                 {'campaignStatus': 'Inativo', 'children': [{}]}]
        script = functions + '\nconsole.log(JSON.stringify(' + json.dumps(cases) + ".map(x => [matchesContext(x,'active'), matchesContext(x,'ended'), matchesContext(x,'unknownAds')])));"
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout), [[False, False, True]] * 4 +
                         [[True, False, False], [False, True, False], [False, False, True]])
        self.assertIn("['Publicidade ativa confirmada', rows.filter", html)
        self.assertIn("['Publicidade encerrada confirmada', rows.filter", html)
        self.assertNotIn("rows.some(item => matchesContext(item, 'unknownAds')) ? null", html)

    def test_browser_keeps_confirmed_counts_visible_with_unknown_rows(self):
        html = render_dashboard({'items': [], 'meta': {}})
        functions = 'function advertisingState(item)' + html.split(
            'function advertisingState(item)', 1
        )[1].split('function renderAlerts()', 1)[0]
        rows = [
            {'campaignStatus': 'Ativa'},
            {'campaignStatus': 'Encerrada'},
            {},
            {'campaignStatus': 'Pausada'},
        ]
        script = functions + "\nconst rows = " + json.dumps(rows) + ";" + """
const counts = {
  active: rows.filter(item => matchesContext(item, 'active')).length,
  ended: rows.filter(item => matchesContext(item, 'ended')).length,
  unknown: rows.filter(item => matchesContext(item, 'unknownAds')).length,
};
console.log(JSON.stringify(counts));
"""
        result = subprocess.run(
            ['node', '-e', script], capture_output=True, text=True, check=True
        )
        self.assertEqual(
            json.loads(result.stdout),
            {'active': 1, 'ended': 1, 'unknown': 2},
        )


if __name__ == '__main__':
    unittest.main()
