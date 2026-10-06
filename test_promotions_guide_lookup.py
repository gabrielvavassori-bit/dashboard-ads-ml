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
        const promotionDiscountAllocation = () => ({meli:null,seller:null,meliDerived:false,sellerDerived:false});
        const promotionAllocationCell = () => 'N/D';
        const promotionTotalCell = () => '10%';
        const promotionLimits = () => '';
        const promotionReceiptCell = () => 'Não calculado';
        const promotionMarginCell = () => 'MC parcial';
        const promotionFinancialResult = () => ({available:false});
        const promotionSimulationFinancialResult = promotionFinancialResult;
        const promotionPriority = () => [0,0,1,-50];
        const promotionSameOpportunity = () => true;
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
        self.assertLess(html.index('data-promo-campaign-price="2"'), html.index('<dialog'))
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
        stubs = "const safe = value => String(value ?? ''); const brl = value => `R$ ${Number(value).toFixed(2)}`; const promotionEffectivePrice = row => Number(row.price || row.receipt_quote?.price || 0); const promotionQuoteMatchesPrice = (row, price) => Math.abs(Number(row.receipt_quote?.price) - price) < 0.01; const promotionFinancialResult=()=>({available:false}); const promotionSkuFinance=()=>({hasCost:false,cost:NaN,profile:null});\n"
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

    def test_saved_cost_is_applied_even_when_tax_profile_is_pending(self):
        source = Path('gerar_dashboard_ads_ml.py').read_text(encoding='utf-8')
        helpers = source[
            source.index('    function financeSkuKey'):
            source.index('    function promotionFinancialResult')
        ].replace('{{', '{').replace('}}', '}')
        margin = source[
            source.index('    function promotionMarginCell'):
            source.index('    function promotionTableRow')
        ].replace('{{', '{').replace('}}', '}')
        stubs = """
        const financeProfile={costBySku:{'  xt2502-preto-pink   29  ':140},fiscalBySku:{}};
        const safe=value=>String(value ?? '');
        const brl=value=>`R$ ${Number(value).toFixed(2)}`;
        const promotionEffectivePrice=row=>Number(row.price || row.receipt_quote?.price || 0);
        const promotionQuoteMatchesPrice=(row,price)=>Math.abs(Number(row.receipt_quote?.price)-price)<.01;
        const promotionFinancialResult=()=>({available:false});
        """
        row = {'price': 289.9, 'receipt_quote': {'available': True, 'price': 289.9,
               'sale_fee': 55.08, 'shipping_cost': 25.45, 'rebate': 0,
               'receipt_before_cost_tax': 209.37}}
        script = stubs + helpers + margin + '\nconsole.log(promotionMarginCell(' + json.dumps(row) + ',{sku:"XT2502-PRETO-PINK 29"}));'
        html = subprocess.run(['node', '-e', script], capture_output=True, text=True, encoding='utf-8', check=True).stdout
        tooltip = unquote(html.split('data-metrics-tip="')[1].split('"')[0])
        self.assertIn('Custo do produto</span><b>−R$ 140.00', tooltip)
        self.assertIn('Saldo após custo · antes de imposto</span><b>R$ 69.37', tooltip)
        self.assertIn('Custo aplicado · imposto pendente', html)
        self.assertNotIn('Custo do produto</span><b>Não informado', tooltip)

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
        const promotionSkuFinance=()=>({hasCost:false,cost:NaN,profile:null});
        const promotionPriority = () => [0,0,1,-50];
        const productImage = () => '<img src="foto.jpg">';
        const promotionDisplayName = row => row.name;
        const promotionPeriod = () => 'Período';
        const promotionStatusClass = () => '';
        const promotionStatusLabel = () => 'Elegível';
        const promotionValueCell = () => '0%';
        const promotionDiscountAllocation = () => ({meli:null,seller:null,meliDerived:false,sellerDerived:false});
        const promotionAllocationCell = () => 'N/D';
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

    def test_flex_cost_is_only_a_consultative_promotion_scenario(self):
        source = Path('gerar_dashboard_ads_ml.py').read_text(encoding='utf-8')
        functions = source[
            source.index('    function promotionDifalValue'):
            source.index('    function promotionMarginCell')
        ].replace('{{', '{').replace('}}', '}')
        stubs = """
        const financeDifalDoubleBaseStates=new Set();
        const financeProfile={taxRegime:'simple', flexCarrierCost:13, costBySku:{SKU1:40}, fiscalBySku:{SKU1:{taxRegime:'simple', simpleTaxRate:8}}};
        const promotionEffectivePrice=row=>Number(row.price);
        const promotionQuoteMatchesPrice=(row,price)=>row.receipt_quote.available === true && Math.abs(row.receipt_quote.price-price) <= .01;
        """
        row = {'price': 100,
               'receipt_quote': {'available': True, 'price': 100, 'sale_fee': 12,
                                 'shipping_cost': 10, 'rebate': 0,
                                 'receipt_before_cost_tax': 78},
               'flex_receipt_quote': {'available': True, 'price': 100, 'sale_fee': 11,
                                      'shipping_cost': 5, 'rebate': 0,
                                      'receipt_before_cost_tax': 84,
                                      'billable_weight_kg': 2,
                                      'billable_weight_unit': 'kg',
                                      'billable_weight_source': 'shipping_options_quote',
                                      'seller_reputation_green': True}}
        script = stubs + functions + '\nconsole.log(JSON.stringify(promotionFinancialResult(' + json.dumps(row) + ',{sku:"SKU1"})));'
        result = json.loads(subprocess.run(['node', '-e', script], capture_output=True, text=True, encoding='utf-8', check=True).stdout)
        self.assertEqual(result['profit'], 30)
        self.assertEqual(result['margin'], 30)
        self.assertTrue(result['flexActive'])
        self.assertTrue(result['flexAvailable'])
        self.assertEqual(result['flexCarrierCost'], 13)
        self.assertAlmostEqual(result['flexProfit'], 28.089, places=6)
        self.assertAlmostEqual(result['flexMargin'], 28.089, places=6)
        self.assertEqual(result['flexFee'], 12)
        self.assertEqual(result['flexFixedFee'], 0)
        self.assertAlmostEqual(result['flexBonus'], 1.089, places=6)
        self.assertEqual(result['flexWeightBand'], '0,5 a 5 kg')
        self.assertEqual(result['flexDistance'], 'média distância')
        self.assertAlmostEqual(result['flexNetCost'], 11.911, places=6)
        self.assertEqual(result['flexIgnoredShippingCost'], 10)

    def test_flex_alert_only_appears_below_selected_margin_target(self):
        source = Path('gerar_dashboard_ads_ml.py').read_text(encoding='utf-8')
        function = source[
            source.index('    function promotionMarginCell'):
            source.index('    function promotionTableRow')
        ].replace('{{', '{').replace('}}', '}')
        stubs = """
        const brl=value=>`R$ ${Number(value).toFixed(2)}`;
        const safe=value=>String(value ?? '');
        const promotionMarginTarget=15;
        const promotionEffectivePrice=row=>Number(row.price);
        const promotionQuoteMatchesPrice=()=>true;
        let flexMargin=11;
        const promotionFinancialResult=()=>({available:true,price:100,receipt:78,cost:40,tax:8,difal:0,
          profit:30,margin:30,credits:0,debits:8,fee:12,freight:10,rebate:0,flexActive:true,
          flexAvailable:true,flexCarrierCost:13,flexProfit:16,flexMargin,flexFee:12,flexFixedFee:0,
          flexBonus:1.089,flexWeight:2,flexWeightBand:'0,5 a 5 kg',flexWeightEstimated:false,
          flexWeightSource:'peso faturável da cotação na API',flexPriceBand:'a partir de R$ 79 com reputação verde',
          flexDistance:'média distância',flexNetCost:11.911,flexIgnoredShippingCost:5});
        const row={price:100,receipt_quote:{available:true,price:100,receipt_before_cost_tax:78,sale_fee:12,shipping_cost:10,rebate:0}};
        """
        script = stubs + function + "\nconst low=promotionMarginCell(row,{sku:'SKU1'}); flexMargin=16; const ok=promotionMarginCell(row,{sku:'SKU1'}); console.log(JSON.stringify({low,ok}));"
        rendered = json.loads(subprocess.run(['node', '-e', script], capture_output=True, text=True, encoding='utf-8', check=True).stdout)
        self.assertIn('Flex ativo: margem 11,00%, abaixo da meta de 15%', rendered['low'])
        self.assertNotIn('promotion-flex-warning', rendered['ok'])
        decoded = __import__('urllib.parse', fromlist=['unquote']).unquote(rendered['low'])
        self.assertIn('Cenário consultivo Flex · média distância', decoded)
        self.assertIn('Taxa Flex · a partir de R$ 79 com reputação verde', decoded)
        self.assertIn('Bônus ML · 0,5 a 5 kg', decoded)
        self.assertIn('transportador + taxa Flex − bônus do Mercado Livre', decoded)
        self.assertIn('Frete tradicional', decoded)
        self.assertIn('Desconsiderado', decoded)
        self.assertNotIn('Cobrança logística ML no Flex', decoded)

    def test_flex_medium_distance_price_and_weight_bands_match_calculator(self):
        source = Path('gerar_dashboard_ads_ml.py').read_text(encoding='utf-8')
        function = source[
            source.index('    function promotionFlexPolicy'):
            source.index('    function promotionFinancialResult')
        ].replace('{{', '{').replace('}}', '}')
        script = function + "\nconsole.log(JSON.stringify([promotionFlexPolicy(18.99,{billable_weight_kg:.5,billable_weight_unit:'kg',seller_reputation_green:true}),promotionFlexPolicy(30,{billable_weight_kg:2,billable_weight_unit:'kg',seller_reputation_green:true}),promotionFlexPolicy(60,{billable_weight_kg:6,billable_weight_unit:'kg',seller_reputation_green:true}),promotionFlexPolicy(100,{billable_weight_kg:2,billable_weight_unit:'kg',seller_reputation_green:true})]));"
        rows = json.loads(subprocess.run(['node', '-e', script], capture_output=True, text=True, encoding='utf-8', check=True).stdout)
        self.assertEqual((rows[0]['fixedFee'], rows[0]['bonus']), (6.25, 9.89))
        self.assertEqual((rows[1]['fixedFee'], rows[1]['bonus']), (6.65, 10.89))
        self.assertEqual((rows[2]['fixedFee'], rows[2]['bonus']), (7.75, 14.89))
        self.assertEqual(rows[3]['fixedFee'], 0)
        self.assertAlmostEqual(rows[3]['bonus'], 1.089, places=6)

    def test_flex_uses_normalized_300_grams_and_rejects_legacy_untyped_weight(self):
        source = Path('gerar_dashboard_ads_ml.py').read_text(encoding='utf-8')
        function = source[
            source.index('    function promotionFlexPolicy'):
            source.index('    function promotionFinancialResult')
        ].replace('{{', '{').replace('}}', '}')
        script = function + "\nconsole.log(JSON.stringify([promotionFlexPolicy(30,{billable_weight_kg:.3,billable_weight_unit:'kg',seller_reputation_green:true}),promotionFlexPolicy(30,{billable_weight_kg:300,seller_reputation_green:true})]));"
        rows = json.loads(subprocess.run(['node', '-e', script], capture_output=True, text=True, encoding='utf-8', check=True).stdout)
        self.assertEqual(rows[0]['weightBand'], 'até 0,5 kg')
        self.assertFalse(rows[0]['weightEstimated'])
        self.assertEqual(rows[1]['weightBand'], '0,5 a 5 kg')
        self.assertTrue(rows[1]['weightEstimated'])
        self.assertEqual(rows[1]['weight'], 2)

    def test_flex_uses_medium_weight_band_when_api_weight_and_flex_quote_are_unavailable(self):
        source = Path('gerar_dashboard_ads_ml.py').read_text(encoding='utf-8')
        functions = source[
            source.index('    function promotionFlexPolicy'):
            source.index('    function promotionMarginCell')
        ].replace('{{', '{').replace('}}', '}')
        stubs = """
        const financeDifalDoubleBaseStates=new Set();
        const financeProfile={taxRegime:'simple', flexCarrierCost:13, costBySku:{SKU1:140},
          fiscalBySku:{SKU1:{taxRegime:'simple', simpleTaxRate:8}}};
        const promotionEffectivePrice=row=>Number(row.price);
        const promotionQuoteMatchesPrice=(row,price)=>row.receipt_quote.available === true
          && Math.abs(row.receipt_quote.price-price) <= .01;
        """
        row = {'price': 234.9,
               'receipt_quote': {'available': True, 'price': 234.9, 'sale_fee': 44.63,
                                 'shipping_cost': 25.45, 'rebate': 0,
                                 'receipt_before_cost_tax': 164.82,
                                 'seller_reputation_green': True},
               'flex_receipt_quote': {'available': False, 'reason': 'Cotação indisponível'}}
        script = stubs + functions + '\nconsole.log(JSON.stringify(promotionFinancialResult(' + json.dumps(row) + ',{sku:"SKU1"})));'
        result = json.loads(subprocess.run(['node', '-e', script], capture_output=True, text=True, encoding='utf-8', check=True).stdout)
        self.assertTrue(result['flexAvailable'])
        self.assertTrue(result['flexWeightEstimated'])
        self.assertEqual(result['flexWeight'], 2)
        self.assertEqual(result['flexWeightBand'], '0,5 a 5 kg')
        self.assertEqual(result['flexWeightSource'], 'faixa intermediária estimada')
        self.assertAlmostEqual(result['flexBonus'], 1.089, places=6)
        self.assertAlmostEqual(result['flexNetCost'], 11.911, places=6)
        self.assertAlmostEqual(result['flexProfit'], 19.567, places=6)
        self.assertAlmostEqual(result['flexMargin'], 8.329928, places=5)

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
        script = "function promotionDisplayName(row){return row.name;} function promotionCompare(){return 0;}\n" + function + '\nconst results=' + json.dumps(results) + ';\nconsole.log(JSON.stringify(promotionCampaignGroups(results)));'
        groups = json.loads(subprocess.run(['node', '-e', script], capture_output=True, text=True, encoding='utf-8', check=True).stdout)
        campaign = next(group for group in groups if group['name'] == '10.10')
        self.assertEqual([(entry['code'], entry['index'], entry['row']['suggested_discounted_price'], entry['row']['discount_meli_boost_amount']) for entry in campaign['listings']],
                         [('MLB111', 0, 71.9, 5), ('MLB222', 0, 69.8, 10)])
        self.assertEqual(len(groups), 2)

    def test_margin_recommendation_selects_best_receipt_per_listing_without_applying(self):
        source = Path('gerar_dashboard_ads_ml.py').read_text(encoding='utf-8')
        functions = source[
            source.index('    function promotionMarginRecommendations'):
            source.index('    function promotionScopePanelHtml')
        ].replace('{{', '{').replace('}}', '}')
        stubs = """
        function promotionDisplayName(row){return row.name;}
        function promotionMatchesScopeSearch(){return true;}
        function promotionCampaignGroups(results){
          const groups=new Map();
          results.forEach(result=>(result.data.promotions||[]).forEach((row,index)=>{
            const key='DEAL:id:'+row.promotion_id;
            if(!groups.has(key)) groups.set(key,{key,name:row.name,row,listings:[]});
            groups.get(key).listings.push({code:result.code,row,index});
          }));
          return [...groups.values()];
        }
        function promotionFinancialResult(row){return row.financial || {available:false};}
        """
        results = [
            {'code': 'MLB1', 'data': {'promotions': [
                {'name': 'A', 'promotion_id': 'A', 'can_join': True, 'financial': {'available': True, 'margin': 18, 'receipt': 80, 'profit': 18, 'flexActive': True, 'flexAvailable': True, 'flexMargin': 11}},
                {'name': 'B', 'promotion_id': 'B', 'can_join': True, 'financial': {'available': True, 'margin': 20, 'receipt': 85, 'profit': 20, 'flexActive': True, 'flexAvailable': True, 'flexMargin': 10}},
            ]}},
            {'code': 'MLB2', 'data': {'promotions': [
                {'name': 'A', 'promotion_id': 'A', 'can_join': True, 'financial': {'available': True, 'margin': 12, 'receipt': 70, 'profit': 12}},
                {'name': 'B', 'promotion_id': 'B', 'can_join': True, 'financial': {'available': False}},
            ]}},
            {'code': 'MLB3', 'data': {'promotions': [
                {'name': 'A', 'promotion_id': 'A', 'can_join': False, 'financial': {'available': True, 'margin': 30, 'receipt': 90, 'profit': 30}},
            ]}},
        ]
        script = stubs + functions + '\nconsole.log(JSON.stringify(promotionMarginRecommendations(' + json.dumps(results) + ',[{code:"MLB1"},{code:"MLB2"},{code:"MLB3"}],15)));'
        result = json.loads(subprocess.run(['node', '-e', script], capture_output=True, text=True, encoding='utf-8', check=True).stdout)
        self.assertEqual([row['selectionKey'] for row in result['recommended']], ['DEAL:id:B|MLB1|1'])
        self.assertEqual(result['qualifying'], 2)
        self.assertEqual(result['belowTarget'], 1)
        self.assertEqual(result['blocked'], 1)
        self.assertEqual(result['unavailable'], 1)
        self.assertEqual(result['flexAlerts'], 1)
        self.assertEqual(result['flexPending'], 0)

    def test_margin_recommendation_respects_campaign_and_loaded_scope_filter(self):
        source = Path('gerar_dashboard_ads_ml.py').read_text(encoding='utf-8')
        functions = source[
            source.index('    function promotionMarginRecommendations'):
            source.index('    function promotionScopePanelHtml')
        ].replace('{{', '{').replace('}}', '}')
        stubs = """
        function promotionDisplayName(row){return row.name;}
        function promotionMatchesScopeSearch(result,query){return !query || result.data.item.seller_sku.includes(query);}
        function promotionCampaignGroups(results){
          const groups=new Map();
          results.forEach(result=>(result.data.promotions||[]).forEach((row,index)=>{
            const key='DEAL:id:'+row.promotion_id;
            if(!groups.has(key)) groups.set(key,{key,name:row.name,row,listings:[]});
            groups.get(key).listings.push({code:result.code,row,index});
          }));
          return [...groups.values()];
        }
        function promotionFinancialResult(row){return row.financial || {available:false};}
        """
        results = [
            {'code': 'MLB1', 'data': {'item': {'seller_sku': 'LAZ-2X2'}, 'promotions': [
                {'name': 'A', 'promotion_id': 'A', 'can_join': True, 'financial': {'available': True, 'margin': 18, 'receipt': 90, 'profit': 18}},
                {'name': 'B', 'promotion_id': 'B', 'can_join': True, 'financial': {'available': True, 'margin': 20, 'receipt': 95, 'profit': 20}},
            ]}},
            {'code': 'MLB2', 'data': {'item': {'seller_sku': 'OUTRO'}, 'promotions': [
                {'name': 'A', 'promotion_id': 'A', 'can_join': True, 'financial': {'available': True, 'margin': 30, 'receipt': 120, 'profit': 30}},
            ]}},
        ]
        script = stubs + functions + '\nconsole.log(JSON.stringify(promotionMarginRecommendations(' + json.dumps(results) + ',[{code:"MLB1"},{code:"MLB2"}],15,"DEAL:id:A","LAZ")));'
        result = json.loads(subprocess.run(['node', '-e', script], capture_output=True, text=True, encoding='utf-8', check=True).stdout)
        self.assertEqual([row['selectionKey'] for row in result['recommended']], ['DEAL:id:A|MLB1|0'])
        self.assertEqual(result['qualifying'], 1)

    def test_margin_recommendation_ui_is_explicitly_non_mutating(self):
        source = Path('gerar_dashboard_ads_ml.py').read_text(encoding='utf-8')
        self.assertIn('Seleção consultiva por margem', source)
        self.assertIn('Selecionar apenas marca as linhas', source)
        self.assertIn('não confirma nem aplica nenhuma promoção', source)
        self.assertIn("data-promo-recommend", source)
        handler = source[source.index("document.querySelectorAll('[data-promo-recommend]')"):source.index("document.querySelectorAll('[data-promo-recommend-preview]')")]
        self.assertNotIn('/api/promotions/preview', handler)
        self.assertNotIn('/api/promotions/confirm', handler)

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

    def test_campaign_scope_can_filter_loaded_rows_by_sku_mlb_mlbu_or_title(self):
        source = Path('gerar_dashboard_ads_ml.py').read_text(encoding='utf-8')
        self.assertIn('data-promo-scope-search', source)
        self.assertIn('SKU, MLB, MLBU ou título', source)
        self.assertIn('item.seller_sku, item.user_product_id, item.title', source)
        self.assertIn('anúncios carregados', source)
        self.assertIn("input.addEventListener('input'", source)

    def test_campaign_catalog_percentages_are_preserved_and_seller_remainder_is_derived(self):
        source = Path('gerar_dashboard_ads_ml.py').read_text(encoding='utf-8')
        self.assertIn('meli_percentage:entry.promotion.meli_percentage ?? campaignMeli', source)
        self.assertIn('seller_percentage:entry.promotion.seller_percentage ?? campaignSeller', source)
        functions = source[
            source.index('    function promotionTotalCellValue'):
            source.index('    function promotionReceiptValue')
        ].replace('{{', '{').replace('}}', '}')
        script = "const promotionEffectivePrice=row=>Number(row.price); const promotionValueCell=(value)=>String(value);\n" + functions + "\nconsole.log(JSON.stringify(promotionDiscountAllocation({original_price:259.8,price:123.9,meli_percentage:0})));"
        allocation = json.loads(subprocess.run(['node', '-e', script], capture_output=True, text=True, encoding='utf-8', check=True).stdout)
        self.assertEqual(allocation['meli'], 0)
        self.assertAlmostEqual(allocation['seller'], 52.31, places=2)
        self.assertTrue(allocation['sellerDerived'])

    def test_discount_allocation_estimates_seller_when_api_omits_both_parts(self):
        source = Path('gerar_dashboard_ads_ml.py').read_text(encoding='utf-8')
        functions = source[
            source.index('    function promotionTotalCellValue'):
            source.index('    function promotionReceiptValue')
        ].replace('{{', '{').replace('}}', '}')
        script = "const promotionEffectivePrice=row=>Number(row.price); const promotionValueCell=(value)=>String(value); const safe=value=>String(value);\n" + functions + "\nconsole.log(JSON.stringify(promotionDiscountAllocation({original_price:259.8,price:123.9})));"
        allocation = json.loads(subprocess.run(['node', '-e', script], capture_output=True, text=True, encoding='utf-8', check=True).stdout)
        self.assertIsNone(allocation['meli'])
        self.assertAlmostEqual(allocation['seller'], 52.31, places=2)
        self.assertTrue(allocation['sellerDerived'])
        self.assertTrue(allocation['sellerEstimatedFromTotal'])

    def test_total_discount_uses_the_same_effective_offer_price_as_seller_allocation(self):
        source = Path('gerar_dashboard_ads_ml.py').read_text(encoding='utf-8')
        total_cell = source[source.index('    function promotionTotalCell(row)'):source.index('    function promotionFriendlyType(row)')]
        self.assertIn('const price = promotionEffectivePrice(row);', total_cell)

    def test_editable_price_lives_in_price_column_and_requotes_before_confirmation(self):
        source = Path('gerar_dashboard_ads_ml.py').read_text(encoding='utf-8')
        row = source[source.index('    function promotionTableRow'):source.index('    function promotionTableHtml')]
        self.assertIn('const priceCell = editablePrice', row)
        self.assertIn('data-promo-campaign-price=', row)
        self.assertIn('Preço para simular', row)
        self.assertIn('min_discounted_price', row)
        self.assertIn('max_discounted_price', row)
        self.assertIn('<td class="num">${{priceCell}}${{referenceHtml}}</td><td class="num">${{promotionReceiptCell(row)}}</td>', row)
        self.assertNotIn('<label>Preço promocional<input', row[row.index('const actionControls'):row.index('const quote =')])
        self.assertIn('function promotionRequoteEditedPrice(input)', source)
        requote = source[source.index('    async function promotionRequoteEditedPrice'):source.index('    function activatePromotionPanels')]
        self.assertIn("promotionApiRequest('/api/promotions/preview'", requote)
        self.assertIn('receipt_quote:preview.summary?.receipt_quote', requote)
        self.assertNotIn("promotionApiRequest('/api/promotions/confirm'", requote)

    def test_target_margin_requotes_price_within_marketplace_limits(self):
        source = Path('gerar_dashboard_ads_ml.py').read_text(encoding='utf-8')
        row = source[source.index('    function promotionTableRow'):source.index('    function promotionTableHtml')]
        self.assertIn('Margem para simular (%)', row)
        self.assertIn('data-promo-target-margin=', row)
        self.assertIn('min_discounted_price', row)
        self.assertIn('max_discounted_price', row)
        solver = source[source.index('    async function promotionPreviewAtPrice'):source.index('    function activatePromotionPanels')]
        self.assertIn("promotionApiRequest('/api/promotions/preview'", solver)
        self.assertIn('promotionSimulationFinancialResult(quotedRow, item)', solver)
        self.assertIn('for (let attempt = 0; attempt < 8', solver)
        self.assertIn('(target - lower.financial.margin)', solver)
        self.assertIn('Margem de ${{target.toLocaleString', solver)
        self.assertIn('target_margin:target', solver)
        self.assertIn('const storedTargetMargin = Number(row.target_margin)', row)
        self.assertIn('targetMarginValue.toFixed(2)', row)
        self.assertIn('currentPrice - 0.01', solver)
        self.assertIn('Simulação não concluída:', solver)
        self.assertNotIn("promotionApiRequest('/api/promotions/confirm'", solver)

    def test_target_margin_can_use_partial_margin_when_cost_is_known(self):
        source = Path('gerar_dashboard_ads_ml.py').read_text(encoding='utf-8')
        helper = source[source.index('    function promotionSimulationFinancialResult'):source.index('    function promotionTableRow')]
        self.assertIn('if (complete.available)', helper)
        self.assertIn('promotionSkuFinance(item)', helper)
        self.assertIn('!finance.hasCost', helper)
        self.assertIn('profit = receipt - finance.cost', helper)
        self.assertIn('partial:true', helper)
        self.assertNotIn('tax:0', helper)

    def test_price_and_margin_fields_are_identified_as_simulators(self):
        source = Path('gerar_dashboard_ads_ml.py').read_text(encoding='utf-8')
        row = source[source.index('    function promotionTableRow'):source.index('    function promotionTableHtml')]
        self.assertIn('Preço para simular', row)
        self.assertIn('Margem para simular (%)', row)
        self.assertIn('Simulação apenas:', row)
        self.assertIn('Nada é aplicado até abrir a revisão', row)

    def test_confirmed_promotion_refreshes_loaded_scope_without_page_reload(self):
        source = Path('gerar_dashboard_ads_ml.py').read_text(encoding='utf-8')
        propagation = source[source.index('    function promotionMergeFreshData'):source.index('    async function waitForPromotionConfirmation')]
        self.assertIn('promotionPropagateFreshData', propagation)
        self.assertIn('state.results.map', propagation)
        self.assertIn('promotionSameOpportunity', propagation)
        self.assertIn('preview_price:null', propagation)
        poller = source[source.index('    async function pollPromotionConfirmation'):source.index('    function restorePromotionConfigDialog')]
        self.assertIn('promotionPropagateFreshData(code, outcome.data)', poller)

    def test_listing_identity_keeps_campaign_name_period_and_status(self):
        source = Path('gerar_dashboard_ads_ml.py').read_text(encoding='utf-8')
        row = source[source.index('    function promotionTableRow'):source.index('    function promotionTableHtml')]
        self.assertIn('promotion-listing-campaign', row)
        self.assertIn('promotionDisplayName(row)', row)
        self.assertIn('promotionPeriod(row)', row)
        self.assertIn('promotionStatusLabel(row)', row)
        status = source[source.index('    function promotionStatusLabel'):source.index('    function promotionStatusClass')]
        self.assertIn("['scheduled','programmed','pending']", status)

    def test_individual_campaign_button_generates_preview_without_immediate_confirmation(self):
        source = Path('gerar_dashboard_ads_ml.py').read_text(encoding='utf-8')
        handler = source[source.index("document.querySelectorAll('[data-promo-campaign]')"):source.index("document.querySelectorAll('[data-promo-create-campaign]')")]
        self.assertIn("promotionApiRequest('/api/promotions/preview'", handler)
        self.assertNotIn("promotionApiRequest('/api/promotions/confirm'", handler)

    def test_grouped_price_uses_live_mlb_state_and_direct_action_opens_local_review(self):
        source = Path('gerar_dashboard_ads_ml.py').read_text(encoding='utf-8')
        row = source[source.index('    function promotionTableRow'):source.index('    function promotionTableHtml')]
        handler = source[source.index("document.querySelectorAll('[data-promo-direct]')"):source.index("document.querySelectorAll('[data-promo-campaign]')")]
        self.assertIn('liveRows.find(candidate => promotionSameOpportunity(candidate, sourceRow))', row)
        self.assertIn('const row = liveRow || sourceRow;', row)
        self.assertIn('data-promo-dialog-key=', row)
        self.assertIn('promotionPreviewHtml(item, directState)', row)
        self.assertIn('Rejeitar e fechar', row)
        self.assertIn("canUpdate", row)
        self.assertIn('data-promo-operation="update"', row)
        self.assertIn("Alterando...", row)
        self.assertIn('rowRoot?.querySelector(`[data-promo-campaign-price=', handler)
        self.assertIn('body.deal_price = editedPrice;', handler)
        self.assertIn('activePromotionConfigKey = `${{code}}:${{index}}`;', handler)

    def test_direct_mlb_preview_is_local_modal_and_not_appended_below_the_page(self):
        source = Path('gerar_dashboard_ads_ml.py').read_text(encoding='utf-8')
        table = source[source.index('    function promotionTableHtml'):source.index('    function promotionScopeLabel')]
        panel = source[source.index('    function promotionPanelHtml'):source.index('    async function promotionApiRequest')]
        self.assertIn('const listing = allowAction ?', table)
        self.assertIn('promotionTableRow(item, entry, allowAction, listing)', table)
        self.assertNotIn('${{promotionPreviewHtml(item, state)}}', panel)
        self.assertIn('abrir a revisão local antes da aplicação', panel)

    def test_campaign_catalog_retries_read_only_request_once_on_transient_failure(self):
        source = Path('gerar_dashboard_ads_ml.py').read_text(encoding='utf-8')
        loader = source[source.index('    async function loadPromotionCampaignCatalog'):source.index('    async function openPromotionAccountCampaign')]
        self.assertEqual(loader.count("promotionApiRequest('/api/promotions/campaigns')"), 2)
        self.assertIn('setTimeout(resolve, 800)', loader)

    def test_bulk_execution_keeps_one_collective_confirmation(self):
        source = Path('gerar_dashboard_ads_ml.py').read_text(encoding='utf-8')
        self.assertIn('data-promo-bulk-execute', source)
        self.assertIn('Confirmo a aplicação destas promoções no Mercado Livre', source)
        bulk_handler = source[source.index("document.querySelectorAll('[data-promo-bulk-execute]')"):source.index("document.querySelectorAll('[data-promo-create-campaign]')")]
        self.assertIn("promotionApiRequest('/api/promotions/confirm'", bulk_handler)

    def test_account_campaign_inventory_loads_without_product_search(self):
        source = Path('gerar_dashboard_ads_ml.py').read_text(encoding='utf-8')
        app_source = Path('app.py').read_text(encoding='utf-8')
        self.assertIn('id="promotionAccountCampaigns"', source)
        self.assertIn("promotionApiRequest('/api/promotions/campaigns')", source)
        self.assertIn('/api/promotions/campaign-items?promotion_id=', source)
        self.assertIn("button.dataset.view === 'promotions'", source)
        self.assertIn('loadPromotionCampaignCatalog()', source)
        self.assertIn("detailScope:'campaign'", source)
        self.assertIn('promotionState.set(code', source)
        self.assertIn('"/api/promotions/campaigns"', app_source)
        self.assertIn('"/internal/dash-ads/promotions/campaign-items"', app_source)

    def test_campaign_cards_show_eligible_and_participating_totals(self):
        source = Path('gerar_dashboard_ads_ml.py').read_text(encoding='utf-8')
        catalog = source[source.index('    function renderPromotionCampaignCatalog'):source.index('    async function loadPromotionCampaignCatalog')]
        self.assertIn('campaign.eligible_count', catalog)
        self.assertIn('campaign.participating_count', catalog)
        self.assertIn('Elegíveis:', catalog)
        self.assertIn('Participando:', catalog)
        self.assertIn("? 'N/D'", catalog)

    def test_campaign_inventory_enriches_rows_and_loads_cursor_pages(self):
        source = Path('gerar_dashboard_ads_ml.py').read_text(encoding='utf-8')
        app_source = Path('app.py').read_text(encoding='utf-8')
        self.assertIn("const remote = entry.item", source)
        self.assertIn("remote.thumbnail", source)
        self.assertIn("remote.seller_sku", source)
        self.assertIn("data-promo-campaign-more", source)
        self.assertIn("search_after=${{encodeURIComponent(state.nextSearchAfter)}}", source)
        self.assertIn('params["search_after"] = search_after', app_source)

    def test_campaign_checkboxes_keep_fixed_proportions(self):
        source = Path('gerar_dashboard_ads_ml.py').read_text(encoding='utf-8')
        self.assertIn('.promotion-listing-select', source)
        self.assertIn('flex:0 0 18px', source)
        self.assertIn('width:18px; min-width:18px; height:18px', source)
        self.assertIn('<div class="promotion-listing-select">${{selectionControl}}', source)

    def test_missing_subsidy_is_not_rendered_as_zero(self):
        source = Path('gerar_dashboard_ads_ml.py').read_text(encoding='utf-8')
        function = source[source.index('    function promotionValueCell'):source.index('    function promotionTotalCell')]
        self.assertIn("value == null || value === ''", function)
        self.assertIn('N/D', function)

    def test_bulk_campaign_action_only_generates_individual_previews(self):
        source = Path('gerar_dashboard_ads_ml.py').read_text(encoding='utf-8')
        self.assertIn('data-promo-bulk-select=', source)
        self.assertIn('data-promo-bulk-operation', source)
        self.assertIn('data-promo-bulk-preview-visible', source)
        self.assertIn('nenhuma alteração é aplicada nesta etapa.', source)
        runner = source[source.index('    async function promotionRunCollectivePreview'):source.index('    function activatePromotionPanels')]
        handler = source[source.index("document.querySelectorAll('[data-promo-bulk-preview-visible]'"):source.index("document.querySelectorAll('[data-promo-bulk-approve]'")]
        self.assertIn("promotionApiRequest('/api/promotions/preview'", runner)
        self.assertNotIn("promotionApiRequest('/api/promotions/confirm'", runner)
        self.assertIn('selectedListingKeys', handler)
        self.assertIn('promotionRunCollectivePreview', handler)

    def test_bulk_action_is_available_in_every_scope_view_and_respects_visible_filter(self):
        source = Path('gerar_dashboard_ads_ml.py').read_text(encoding='utf-8')
        self.assertIn('function promotionVisibleListings(state)', source)
        self.assertIn('data-promo-bulk-all-visible', source)
        self.assertIn('data-promo-bulk-preview-visible', source)
        self.assertIn('Selecionar os ${{num(visibleKeys.length)}} anúncios desta visão', source)
        self.assertIn("campaign:'Campanha', sku:'SKU', hybrid:'Híbrida', listing:'Anúncio/variação'", source)
        visible = source[source.index('function promotionVisibleListings(state)'):source.index('function promotionScopeBulkToolbarHtml')]
        self.assertIn('promotionMatchesScopeSearch', visible)
        self.assertIn('selectedCampaignKey', visible)
        self.assertIn('selectionKey:', visible)
        panel = source[source.index('function promotionScopePanelHtml(item)'):source.index('function promotionPanelHtml(item)')]
        self.assertIn('${{scopeBulkToolbar}}${{recommendationHtml}}', panel)
        self.assertGreaterEqual(panel.count('checked:selectedListingKeys.has('), 4)

    def test_recommended_candidates_generate_one_collective_preview_queue_without_confirmation(self):
        source = Path('gerar_dashboard_ads_ml.py').read_text(encoding='utf-8')
        self.assertIn('data-promo-recommend-preview', source)
        self.assertIn('Gerar ${{num(selectedRecommended)}} prévia(s) consultiva(s)', source)
        handler = source[source.index("document.querySelectorAll('[data-promo-recommend-preview]'"):source.index("document.querySelectorAll('[data-promo-bulk-preview]'")]
        self.assertIn('recommendation.recommended.filter', handler)
        self.assertIn("'Recomendações por margem', 'join'", handler)
        self.assertIn('promotionRunCollectivePreview', handler)
        self.assertNotIn("/api/promotions/confirm", handler)
        runner = source[source.index('    async function promotionRunCollectivePreview'):source.index('    function activatePromotionPanels')]
        self.assertIn('Math.min(3, pending.length)', runner)
        self.assertIn("'/api/promotions/preview'", runner)
        self.assertNotIn("'/api/promotions/confirm'", runner)

    def test_bulk_preview_summary_stages_reviewed_batch_without_execution(self):
        source = Path('gerar_dashboard_ads_ml.py').read_text(encoding='utf-8')
        self.assertIn('function promotionBulkSummaryHtml(state, scopeKey)', source)
        self.assertIn('Resumo das prévias coletivas', source)
        self.assertIn('Aprovar para execução', source)
        self.assertIn('Aprovar todas as prévias válidas', source)
        self.assertIn('para próxima etapa', source)
        self.assertIn('Nenhuma promoção foi aplicada.', source)
        self.assertIn('promotionBulkRunUpdate(scopeKey, selectionKey, patch)', source)
        summary = source[source.index('    function promotionBulkSummaryHtml'):source.index('    function promotionScopePanelHtml')]
        self.assertNotIn('data-promo-confirm=', summary)
        self.assertNotIn("promotionApiRequest('/api/promotions/confirm'", summary)
        self.assertIn("item.status === 'error'", summary)

    def test_collective_approval_handlers_only_create_local_confirmation(self):
        source = Path('gerar_dashboard_ads_ml.py').read_text(encoding='utf-8')
        handler = source[source.index("document.querySelectorAll('[data-promo-bulk-approve]'"):source.index("document.querySelectorAll('[data-promo-bulk-execution-ack]'")]
        self.assertIn('approvedSelectionKeys', handler)
        self.assertIn('confirmation:null', handler)
        self.assertIn('confirmedAt:Date.now()', handler)
        self.assertNotIn('/api/promotions/preview', handler)
        self.assertNotIn('/api/promotions/confirm', handler)
        runner = source[source.index('    async function promotionRunCollectivePreview'):source.index('    function activatePromotionPanels')]
        self.assertIn('approvedSelectionKeys:[]', runner)
        self.assertIn('confirmation:null', runner)

    def test_collective_execution_requires_explicit_ack_and_runs_sequentially(self):
        source = Path('gerar_dashboard_ads_ml.py').read_text(encoding='utf-8')
        summary = source[source.index('    function promotionBulkSummaryHtml'):source.index('    function promotionScopePanelHtml')]
        self.assertIn('Confirmo a aplicação destas promoções no Mercado Livre', summary)
        self.assertIn('data-promo-bulk-execute', summary)
        self.assertIn('Execução sequencial por MLB', summary)
        handler = source[source.index("document.querySelectorAll('[data-promo-bulk-execute]'"):source.index("document.querySelectorAll('[data-promo-load]'")]
        self.assertIn('if (!bulkRun.executionAcknowledged', handler)
        self.assertIn('for (const item of candidates)', handler)
        self.assertNotIn('Promise.all', handler)
        self.assertEqual(handler.count("promotionApiRequest('/api/promotions/confirm'"), 1)
        self.assertIn('executionStatus:\'success\'', handler)
        self.assertIn('executionStatus:\'error\'', handler)
        self.assertIn('executionStatus:\'pending\'', handler)
        self.assertIn('waitForPromotionConfirmation', handler)
        self.assertIn('loadPromotionAudit()', handler)

    def test_collective_retry_targets_only_failed_items_and_skips_successes(self):
        source = Path('gerar_dashboard_ads_ml.py').read_text(encoding='utf-8')
        handler = source[source.index("document.querySelectorAll('[data-promo-bulk-execute]'"):source.index("document.querySelectorAll('[data-promo-load]'")]
        self.assertIn("hasFailures ? item.executionStatus === 'error' : !['success','pending'].includes(item.executionStatus)", handler)
        self.assertIn('Prévia ausente ou expirada. Gere uma nova prévia antes de executar.', handler)
        self.assertIn('Repetir ${{executionCandidates}} falha(s)', source)
        self.assertIn("!['success','pending'].includes(item.executionStatus)", source)

    def test_collective_confirmation_polls_read_only_and_never_resends_pending_items(self):
        source = Path('gerar_dashboard_ads_ml.py').read_text(encoding='utf-8')
        waiter = source[source.index('    async function waitForPromotionConfirmation'):source.index('    async function pollPromotionConfirmation')]
        self.assertIn('maxAttempts = 30', waiter)
        self.assertIn('setTimeout(resolve, 2000)', waiter)
        self.assertIn('/api/promotions?item_id=', waiter)
        self.assertNotIn("'/api/promotions/confirm'", waiter)
        handler = source[source.index("document.querySelectorAll('[data-promo-bulk-execute]'"):source.index("document.querySelectorAll('[data-promo-load]'")]
        self.assertEqual(handler.count("promotionApiRequest('/api/promotions/confirm'"), 1)
        self.assertIn('confirmation_state_unknown', handler)
        self.assertIn('Não será reenviada automaticamente.', handler)

    def test_individual_confirmation_polls_without_resending_mutation(self):
        source = Path('gerar_dashboard_ads_ml.py').read_text(encoding='utf-8')
        poller = source[source.index('    async function waitForPromotionConfirmation'):source.index('    function restorePromotionConfigDialog')]
        self.assertIn('maxAttempts = 30', poller)
        self.assertIn('setTimeout(resolve, 2000)', poller)
        self.assertIn('/api/promotions?item_id=', poller)
        self.assertNotIn("'/api/promotions/confirm'", poller)
        self.assertIn("status:'approved'", poller)
        self.assertIn("status:'pending'", poller)
        handler = source[source.index("document.querySelectorAll('[data-promo-confirm]'"):source.index('    function pricingPreviewBlock')]
        self.assertEqual(handler.count("promotionApiRequest('/api/promotions/confirm'"), 1)
        self.assertIn('promotion_confirmation_unverified', handler)
        self.assertIn("status:'rejected'", handler)

    def test_individual_confirmation_shows_processing_spinner(self):
        source = Path('gerar_dashboard_ads_ml.py').read_text(encoding='utf-8')
        preview = source[source.index('    function promotionPreviewHtml'):source.index('    function promotionWriteAccessHtml')]
        self.assertIn("state.confirmation?.status === 'processing'", preview)
        self.assertIn('promotion-spinner', preview)
        self.assertIn('Consultando a confirmação no Mercado Livre', preview)


if __name__ == '__main__':
    unittest.main()
