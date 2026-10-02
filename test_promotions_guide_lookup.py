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
        const promotionPreviewHtml = () => '';
        const promotionState = new Map();
        const brl = value => `R$ ${value}`;
        const promotionEffectivePrice = (row, item={}) => Number(row.price || row.suggested_discounted_price || item.suggestedTestPrice || 0);
        const promotionQuoteMatchesPrice = (row, price) => row.receipt_quote?.available !== true || Math.abs(Number(row.receipt_quote.price) - price) <= 0.01;
        """
        script = stubs + function + "\nconsole.log(promotionTableRow({code:'MLB111'}, {row:{name:'10.10',can_join:true,suggested_discounted_price:71.9},index:2}, true, {code:'MLB111',title:'Lona Azul',sku:'LAZ-3X3',thumbnailUrl:'https://example.test/foto.jpg'}));"
        html = subprocess.run(['node', '-e', script], capture_output=True, text=True, encoding='utf-8', check=True).stdout
        self.assertIn('Lona Azul', html)
        self.assertIn('SKU LAZ-3X3', html)
        self.assertIn('foto.jpg', html)
        self.assertIn('<dialog class="promotion-config-dialog"', html)
        self.assertIn('data-promo-config-open', html)
        self.assertIn('data-promo-direct="2"', html)
        self.assertIn('>Participar</button>', html)
        self.assertLess(html.index('<dialog'), html.index('data-promo-campaign-price="2"'))
        self.assertIn('data-promo-campaign="2"', html)
        self.assertNotIn('Gerar prévia para participar', html)
        self.assertIn('data-promo-item="MLB111"', html)

        mismatch_script = stubs + function + "\nconsole.log(promotionTableRow({code:'MLB111'}, {row:{name:'Oferta relâmpago',can_join:true,original_price:32.9,price:19.94,suggested_discounted_price:27.97,receipt_quote:{available:true,price:27.97}},index:2}, true));"
        mismatch = subprocess.run(['node', '-e', mismatch_script], capture_output=True, text=True, encoding='utf-8', check=True).stdout
        self.assertIn('R$ 19.94', mismatch)
        self.assertIn('Cotação divergente', mismatch)
        self.assertNotIn('value="27.97"', mismatch)
        self.assertNotIn('>Participar</button>', mismatch)

    def test_partial_margin_shows_breakdown_without_inventing_cost_or_tax(self):
        source = Path('gerar_dashboard_ads_ml.py').read_text(encoding='utf-8')
        function = source[
            source.index('    function promotionMarginCell'):
            source.index('    function promotionTableRow')
        ].replace('{{', '{').replace('}}', '}')
        stubs = "const safe = value => String(value ?? ''); const brl = value => `R$ ${Number(value).toFixed(2)}`; const promotionEffectivePrice = row => Number(row.price || row.receipt_quote?.price || 0); const promotionQuoteMatchesPrice = (row, price) => Math.abs(Number(row.receipt_quote?.price) - price) < 0.01; const promotionFinancialResult=()=>({available:false});\n"
        script = stubs + function + "\nconsole.log(promotionMarginCell({price:74.9,receipt_quote:{available:true,price:74.9,sale_fee:8.61,shipping_cost:8.75,rebate:0,receipt_before_cost_tax:57.54}})); console.log(promotionMarginCell({receipt_quote:{available:false,reason:'Frete ausente'}})); console.log(promotionMarginCell({price:19.94,receipt_quote:{available:true,price:27.97,sale_fee:3.22,shipping_cost:7.45,rebate:0,receipt_before_cost_tax:17.30}}));"
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
        self.assertIn('N/D', result[2])
        self.assertIn('Cotação divergente', result[2])
        self.assertNotIn('R$ 17.30', result[2])

    def test_effective_offer_price_precedes_unconfirmed_api_suggestion(self):
        source = Path('gerar_dashboard_ads_ml.py').read_text(encoding='utf-8')
        functions = source[
            source.index('    function promotionEffectivePrice'):
            source.index('    function promotionDiscountBreakdown')
        ].replace('{{', '{').replace('}}', '}')
        script = functions + "\nconst row={price:19.94,suggested_discounted_price:27.97,receipt_quote:{available:true,price:27.97}}; console.log(JSON.stringify({price:promotionEffectivePrice(row),matches:promotionQuoteMatchesPrice(row,promotionEffectivePrice(row))}));"
        result = json.loads(subprocess.run(['node', '-e', script], capture_output=True, text=True, encoding='utf-8', check=True).stdout)
        self.assertEqual(result['price'], 19.94)
        self.assertFalse(result['matches'])

    def test_promotion_row_retains_descriptive_margin_hover(self):
        source = Path('gerar_dashboard_ads_ml.py').read_text(encoding='utf-8')
        functions = source[
            source.index('    function promotionMarginCell'):
            source.index('    function promotionTableHtml')
        ].replace('{{', '{').replace('}}', '}')
        stubs = """
        const safe = value => String(value ?? '');
        const brl = value => `R$ ${Number(value).toFixed(2)}`;
        const promotionFinancialResult=()=>({available:false});
        const productImage = () => '<img src="foto.jpg">';
        const promotionDisplayName = row => row.name;
        const promotionPeriod = () => 'Período';
        const promotionStatusClass = () => '';
        const promotionStatusLabel = () => 'Elegível';
        const promotionValueCell = () => '0%';
        const promotionTotalCell = () => '10%';
        const promotionLimits = () => '';
        const promotionReceiptCell = () => 'R$ 57.54';
        const promotionEffectivePrice = (row, item={}) => Number(row.price || row.suggested_discounted_price || item.suggestedTestPrice || 0);
        const promotionQuoteMatchesPrice = (row, price) => row.receipt_quote?.available !== true || Math.abs(Number(row.receipt_quote.price) - price) <= 0.01;
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

    def test_laz_real_tax_and_freight_credits_match_calculator(self):
        source = Path('gerar_dashboard_ads_ml.py').read_text(encoding='utf-8')
        functions = source[
            source.index('    function promotionDifalValue'):
            source.index('    function promotionMarginCell')
        ].replace('{{', '{').replace('}}', '}')
        stubs = """
        const financeDifalDoubleBaseStates=new Set(['SP']);
        const financeProfile={
          fiscalMode:'simple', taxRegime:'real', flexCarrierCost:0,
          costBySku:{'LAZ-2X2':5.8},
          fiscalBySku:{'LAZ-2X2':{
            evidenceStatus:'user_informed', costBasis:'gross', ipiInputRate:0, icmsInputRate:4, pisCofinsInputRate:9.25,
            ipiOutputRate:0, icmsOutputRate:4, pisCofinsOutputRate:9.25,
            difalEnabled:false, saleType:'b2c', originState:'SP', destinationState:'SP',
            destinationIcmsRate:18, freightCreditEnabled:true, freightIcmsCreditRate:12
          }}
        };
        const promotionEffectivePrice = row => Number(row.price || row.suggested_discounted_price || row.receipt_quote?.price || 0);
        const promotionQuoteMatchesPrice = (row, price) => row.receipt_quote?.available === true && Math.abs(Number(row.receipt_quote.price) - price) <= 0.01;
        """
        row = {'receipt_quote': {'available': True, 'price': 16.51, 'sale_fee': 1.89865,
                                 'shipping_cost': 6.15, 'rebate': 0,
                                 'receipt_before_cost_tax': 8.46135}}
        script = stubs + functions + '\nconsole.log(JSON.stringify(promotionFinancialResult(' + json.dumps(row) + ',{sku:"LAZ-2X2"})));'
        result = json.loads(subprocess.run(['node', '-e', script], capture_output=True, text=True, encoding='utf-8', check=True).stdout)
        self.assertAlmostEqual(result['difal'], 0, places=6)
        self.assertAlmostEqual(result['profit'], 2.48, delta=0.02)
        self.assertAlmostEqual(result['margin'], 15.0, delta=0.1)

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

    def test_sku_family_mlbu_and_mlb_route_to_individual_ads(self):
        source = Path('gerar_dashboard_ads_ml.py').read_text(encoding='utf-8')
        function = source[
            source.index('    function resolvePromotionGuideItem'):
            source.index('    function renderPromotionGuide')
        ].replace('{{', '{').replace('}}', '}').replace('\\\\s', '\\s')
        items = [
            {'code': 'MLB111', 'familyId': '5064438396869903', 'userProductId': '765', 'sku': 'LAZ-2X2'},
            {'code': 'MLB222', 'familyId': '5064438396869903', 'userProductId': '765'},
            {'code': 'MLB333', 'familyId': '5064438396869903', 'userProductId': '999'},
        ]
        script = function + '\nconst items=' + json.dumps(items) + ';\n' + (
            "for (const query of ['LAZ-2X2','5064438396869903','MLBU765','MLB111','111','MLBU404']) "
            "console.log(JSON.stringify(resolvePromotionGuideItem(query, items)));"
        )
        output = subprocess.run(
            ['node', '-e', script], capture_output=True, text=True, encoding='utf-8', check=True
        ).stdout.splitlines()
        sku, family, mlbu, mlb, numeric_mlb, missing = map(json.loads, output)
        self.assertEqual(sku['item']['detailScope'], 'sku')
        self.assertEqual(sku['item']['detailId'], 'LAZ-2X2')
        self.assertEqual([row['code'] for row in sku['item']['children']], ['MLB111'])
        self.assertEqual(family['item']['detailScope'], 'family')
        self.assertEqual([row['code'] for row in family['item']['children']], ['MLB111', 'MLB222', 'MLB333'])
        self.assertEqual(mlbu['item']['detailScope'], 'mlbu')
        self.assertEqual([row['code'] for row in mlbu['item']['children']], ['MLB111', 'MLB222'])
        self.assertEqual(mlb['item']['code'], 'MLB111')
        self.assertEqual(mlb['item']['sku'], 'LAZ-2X2')
        self.assertEqual(numeric_mlb['item']['code'], 'MLB111')
        self.assertEqual(numeric_mlb['item']['sku'], 'LAZ-2X2')
        self.assertIn('não foi encontrado', missing['error'])

    def test_scope_selector_offers_campaign_sku_hybrid_and_listing_views(self):
        source = Path('gerar_dashboard_ads_ml.py').read_text(encoding='utf-8')
        self.assertIn('data-promo-scope-view="campaign"', source)
        self.assertIn('data-promo-scope-view="sku"', source)
        self.assertIn('data-promo-scope-view="hybrid"', source)
        self.assertIn('data-promo-scope-view="listing"', source)

    def test_campaign_inventory_cards_filter_the_loaded_scope(self):
        source = Path('gerar_dashboard_ads_ml.py').read_text(encoding='utf-8')
        self.assertIn('Campanhas encontradas neste grupo', source)
        self.assertIn('data-promo-campaign-filter=', source)
        self.assertIn("campaignKey:button.dataset.promoCampaignFilter || '', view:'campaign'", source)
        self.assertIn('group.key === selectedCampaignKey', source)
        self.assertIn('Todas as campanhas', source)
        self.assertIn("const view = state.view || 'hybrid';", source)

    def test_bulk_campaign_action_only_generates_individual_previews(self):
        source = Path('gerar_dashboard_ads_ml.py').read_text(encoding='utf-8')
        self.assertIn('data-promo-bulk-select=', source)
        self.assertIn('data-promo-bulk-operation', source)
        self.assertIn('data-promo-bulk-preview=', source)
        self.assertIn('Somente prepara as prévias; nenhuma alteração é aplicada.', source)
        handler = source[source.index("document.querySelectorAll('[data-promo-bulk-preview]'"):source.index("document.querySelectorAll('[data-promo-load]'")]
        self.assertIn("promotionApiRequest('/api/promotions/preview'", handler)
        self.assertNotIn("promotionApiRequest('/api/promotions/confirm'", handler)
        self.assertIn('selectedListingKeys', handler)


if __name__ == '__main__':
    unittest.main()
