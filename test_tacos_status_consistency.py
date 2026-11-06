import json
import subprocess
import unittest
from unittest.mock import patch

import app
from gerar_dashboard_ads_ml import aggregate_by_sku, render_dashboard
import test_operational_availability as operational_tests


class TacosStatusConsistencyTests(unittest.TestCase):
    def test_same_mlb_multiple_ads_rows_keeps_sales_once_and_all_ads_costs(self):
        payload = operational_tests.OperationalAvailabilityTests().payload()
        payload['ads']['items'] = [
            dict(item_id='MLB123', ad_group_id='99', campaign_id='', cost=10,
                 total_amount=15, direct_amount=15, units_quantity=2),
            dict(item_id='MLB123', ad_group_id='99', campaign_id='7', cost=5,
                 total_amount=8, direct_amount=8, units_quantity=1),
        ]
        payload['sales']['items']['MLB123'].update(
            revenue_total=100, units_total=4, orders_count=3, sku='TAM-42'
        )
        with patch.object(app, '_fetch_dash_ads_json', return_value=payload):
            data, error = app._build_online_dashboard_data('demo', '7', '2026-09-01', '2026-09-02')
        self.assertEqual(error, '')
        self.assertEqual(len(data['items']), 2)
        self.assertEqual(sum(row['investment'] for row in data['items']), 15)
        self.assertEqual(sum(row['adsRevenue'] for row in data['items']), 23)
        self.assertEqual(sum(row['units'] for row in data['items']), 4)
        self.assertEqual(sum(row['orders'] for row in data['items']), 3)
        self.assertEqual(sum(row['totalRevenue'] for row in data['items']), 100)
        self.assertEqual(data['kpis']['tacos'], .15)
        self.assertEqual(data['items'][1]['tacosBaseRevenue'], 0)
        self.assertFalse(data['items'][1]['tacosDefined'])
        self.assertTrue(all(row['skuIsReference'] for row in data['items']))
        self.assertEqual(len(data['skuAds']), 1)
        self.assertEqual(data['skuAds'][0]['units'], 4)
        self.assertEqual(data['skuAds'][0]['investment'], 15)
        self.assertEqual(data['skuAds'][0]['tacos'], .15)

    def test_reference_sku_does_not_merge_unrelated_mlbs(self):
        rows = [dict(code=code, sku='TAM-42', skuIsReference=True, totalRevenue=100,
                     tacosBaseRevenue=100, investment=10)
                for code in ('MLB123', 'MLB456')]
        groups = aggregate_by_sku(rows)
        self.assertEqual(len(groups), 2)
        self.assertEqual({group['code'] for group in groups}, {'MLB123', 'MLB456'})
        self.assertEqual(sum(group['totalRevenue'] for group in groups), 200)

    def test_zero_base_is_rendered_as_unknown_not_zero_percent(self):
        html = render_dashboard({'items': [], 'meta': {}})
        self.assertIn("const tacosText = item => Number(item?.tacosBaseRevenue || 0) > 0", html)
        self.assertIn("'N/D'", html)
        self.assertIn('Linhas de Ads preservadas no detalhe.', html)

    def test_mlb_view_consolidates_duplicate_ads_rows_without_losing_children(self):
        html = render_dashboard({'items': [], 'meta': {}})
        fn = 'function groupedMlbBodies(rows)' + html.split(
            'function groupedMlbBodies(rows)', 1
        )[1].split('function groupedSkuBodies(rows)', 1)[0]
        script = """
const num = value => String(value);
const seen = [];
const row = item => { seen.push(item); return `<tr>${item.code}:${item.investment}:${item.units}</tr>`; };
const aggregateDetailItem = (children, meta) => ({
  ...meta, children, code:meta.id,
  investment:children.reduce((n,x) => n + x.investment, 0),
  units:children.reduce((n,x) => n + x.units, 0)
});
const aggregateDetailRows = () => '';
""" + fn + """
const html = groupedMlbBodies([
  {code:'MLB123', investment:10, units:4},
  {code:'MLB123', investment:5, units:0},
  {code:'MLB456', investment:3, units:2}
]);
console.log(JSON.stringify({html, rows:seen.map(x => [x.code, x.investment, x.units, x.children?.length || 0])}));
"""
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True, check=True)
        rendered = json.loads(result.stdout)
        self.assertEqual(rendered['rows'], [['MLB123', 15, 4, 2], ['MLB456', 3, 2, 0]])
        self.assertIn('Linhas de Ads preservadas no detalhe', rendered['html'])

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
