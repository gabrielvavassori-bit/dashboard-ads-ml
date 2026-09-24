import json
import subprocess
import unittest
from pathlib import Path
from urllib.parse import unquote


class PromotionsGuideLookupTests(unittest.TestCase):
    def test_campaign_row_shows_product_identity_and_keeps_actions_in_settings(self):
        source = Path('gerar_dashboard_ads_ml.py').read_text(encoding='utf-8')
        function = source[
            source.index('    function promotionTableRow'):
            source.index('    function promotionTableHtml')
        ].replace('{{', '{').replace('}}', '}')
        stubs = """
        const safe = value => String(value ?? '');
        const productImage = item => `<img src="${item.thumbnailUrl}">`;
        const promotionDisplayName = row => row.name;
        const promotionPeriod = () => 'Período';
        const promotionStatusClass = () => '';
        const promotionStatusLabel = () => 'Elegível';
        const promotionValueCell = () => '0%';
        const promotionTotalCell = () => '10%';
        const promotionLimits = () => '';
        const promotionReceiptCell = () => 'Não calculado';
        const promotionMarginCell = () => 'MC parcial';
        const brl = value => `R$ ${value}`;
        """
        script = stubs + function + "\nconsole.log(promotionTableRow({code:'MLB111'}, {row:{name:'10.10',can_join:true,suggested_discounted_price:71.9},index:2}, true, {code:'MLB111',title:'Lona Azul',sku:'LAZ-3X3',thumbnailUrl:'https://example.test/foto.jpg'}));"
        html = subprocess.run(['node', '-e', script], capture_output=True, text=True, encoding='utf-8', check=True).stdout
        self.assertIn('Lona Azul', html)
        self.assertIn('SKU LAZ-3X3', html)
        self.assertIn('foto.jpg', html)
        self.assertIn('<dialog class="promotion-config-dialog"', html)
        self.assertIn('data-promo-config-open', html)
        self.assertLess(html.index('<dialog'), html.index('data-promo-campaign-price="2"'))
        self.assertIn('Gerar prévia para participar', html)
        self.assertIn('data-promo-item="MLB111"', html)

    def test_partial_margin_shows_breakdown_without_inventing_cost_or_tax(self):
        source = Path('gerar_dashboard_ads_ml.py').read_text(encoding='utf-8')
        function = source[
            source.index('    function promotionMarginCell'):
            source.index('    function promotionTableRow')
        ].replace('{{', '{').replace('}}', '}')
        stubs = "const safe = value => String(value ?? ''); const brl = value => `R$ ${Number(value).toFixed(2)}`;\n"
        script = stubs + function + "\nconsole.log(promotionMarginCell({receipt_quote:{available:true,price:74.9,sale_fee:8.61,shipping_cost:8.75,rebate:0,receipt_before_cost_tax:57.54}})); console.log(promotionMarginCell({receipt_quote:{available:false,reason:'Frete ausente'}}));"
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True, encoding='utf-8', check=True).stdout.splitlines()
        self.assertIn('R$ 57.54', result[0])
        self.assertIn('76,82%', result[0])
        tooltip = unquote(result[0].split('data-metrics-tip="')[1].split('"')[0])
        self.assertIn('Tarifa de venda', tooltip)
        self.assertIn('Frete do vendedor', tooltip)
        self.assertIn('Não informado', tooltip)
        self.assertNotIn('Custo do produto</span><b>R$ 0.00', tooltip)
        self.assertNotIn('Imposto</span><b>R$ 0.00', tooltip)
        self.assertIn('N/D', result[1])
        self.assertNotIn('Frete ausente', result[1])

    def test_promotion_row_retains_descriptive_margin_hover(self):
        source = Path('gerar_dashboard_ads_ml.py').read_text(encoding='utf-8')
        functions = source[
            source.index('    function promotionMarginCell'):
            source.index('    function promotionTableHtml')
        ].replace('{{', '{').replace('}}', '}')
        stubs = """
        const safe = value => String(value ?? '');
        const brl = value => `R$ ${Number(value).toFixed(2)}`;
        const productImage = () => '<img src="foto.jpg">';
        const promotionDisplayName = row => row.name;
        const promotionPeriod = () => 'Período';
        const promotionStatusClass = () => '';
        const promotionStatusLabel = () => 'Elegível';
        const promotionValueCell = () => '0%';
        const promotionTotalCell = () => '10%';
        const promotionLimits = () => '';
        const promotionReceiptCell = () => 'R$ 57.54';
        """
        row = {'name': '10.10', 'original_price': 124.9, 'price': 74.9,
               'receipt_quote': {'available': True, 'price': 74.9, 'sale_fee': 8.61,
                                 'shipping_cost': 8.75, 'rebate': 0, 'receipt_before_cost_tax': 57.54}}
        script = stubs + functions + '\nconsole.log(promotionTableRow({code:"MLB6188463888"}, {row:' + json.dumps(row) + ',index:0}, false));'
        html = subprocess.run(['node', '-e', script], capture_output=True, text=True, encoding='utf-8', check=True).stdout
        self.assertIn('data-promotion-margin-tip', html)
        self.assertIn('76,82%', html)
        tooltip = unquote(html.split('data-metrics-tip="')[1].split('"')[0])
        self.assertIn('Tarifa de venda', tooltip)
        self.assertIn('Frete do vendedor', tooltip)
        self.assertIn('Custo do produto', tooltip)

    def test_campaign_view_groups_variations_without_losing_individual_prices(self):
        source = Path('gerar_dashboard_ads_ml.py').read_text(encoding='utf-8')
        function = source[
            source.index('    function promotionCampaignGroups'):
            source.index('    function promotionScopePanelHtml')
        ].replace('{{', '{').replace('}}', '}')
        results = [
            {'code': 'MLB111', 'data': {'item': {'title': 'Azul', 'user_product_id': 'MLBU765'}, 'promotions': [
                {'name': '10.10', 'promotion_type': 'DEAL', 'promotion_id': 'A', 'suggested_discounted_price': 71.9, 'discount_meli_boost_amount': 5},
                {'name': 'Setembro', 'promotion_type': 'DEAL', 'promotion_id': 'B'}]}},
            {'code': 'MLB222', 'data': {'item': {'title': 'Preta', 'user_product_id': 'MLBU765'}, 'promotions': [
                {'name': '10.10', 'promotion_type': 'DEAL', 'promotion_id': 'A', 'suggested_discounted_price': 69.8, 'discount_meli_boost_amount': 10}]}},
        ]
        script = "function promotionDisplayName(row){return row.name;}\n" + function + '\nconst results=' + json.dumps(results) + ';\nconsole.log(JSON.stringify(promotionCampaignGroups(results)));'
        groups = json.loads(subprocess.run(['node', '-e', script], capture_output=True, text=True, encoding='utf-8', check=True).stdout)
        campaign = next(group for group in groups if group['name'] == '10.10')
        self.assertEqual([(entry['code'], entry['index'], entry['row']['suggested_discounted_price'], entry['row']['discount_meli_boost_amount']) for entry in campaign['listings']],
                         [('MLB111', 0, 71.9, 5), ('MLB222', 0, 69.8, 10)])
        self.assertEqual(len(groups), 2)

    def test_family_mlbu_and_mlb_route_to_individual_ads(self):
        source = Path('gerar_dashboard_ads_ml.py').read_text(encoding='utf-8')
        function = source[
            source.index('    function resolvePromotionGuideItem'):
            source.index('    function renderPromotionGuide')
        ].replace('{{', '{').replace('}}', '}').replace('\\\\s', '\\s')
        items = [
            {'code': 'MLB111', 'familyId': '5064438396869903', 'userProductId': '765'},
            {'code': 'MLB222', 'familyId': '5064438396869903', 'userProductId': '765'},
            {'code': 'MLB333', 'familyId': '5064438396869903', 'userProductId': '999'},
        ]
        script = function + '\nconst items=' + json.dumps(items) + ';\n' + (
            "for (const query of ['5064438396869903','MLBU765','MLB111','111','MLBU404']) "
            "console.log(JSON.stringify(resolvePromotionGuideItem(query, items)));"
        )
        output = subprocess.run(
            ['node', '-e', script], capture_output=True, text=True, encoding='utf-8', check=True
        ).stdout.splitlines()
        family, mlbu, mlb, numeric_mlb, missing = map(json.loads, output)
        self.assertEqual(family['item']['detailScope'], 'family')
        self.assertEqual([row['code'] for row in family['item']['children']], ['MLB111', 'MLB222', 'MLB333'])
        self.assertEqual(mlbu['item']['detailScope'], 'mlbu')
        self.assertEqual([row['code'] for row in mlbu['item']['children']], ['MLB111', 'MLB222'])
        self.assertEqual(mlb['item']['code'], 'MLB111')
        self.assertEqual(numeric_mlb['item']['code'], 'MLB111')
        self.assertIn('não foi encontrado', missing['error'])


if __name__ == '__main__':
    unittest.main()
