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
        script = function + "\nconsole.log(JSON.stringify([promotionFlexPolicy(18.99,{billable_weight_kg:.5,seller_reputation_green:true}),promotionFlexPolicy(30,{billable_weight_kg:2,seller_reputation_green:true}),promotionFlexPolicy(60,{billable_weight_kg:6,seller_reputation_green:true}),promotionFlexPolicy(100,{billable_weight_kg:2,seller_reputation_green:true})]));"
        rows = json.loads(subprocess.run(['node', '-e', script], capture_output=True, text=True, encoding='utf-8', check=True).stdout)
        self.assertEqual((rows[0]['fixedFee'], rows[0]['bonus']), (6.25, 9.89))
        self.assertEqual((rows[1]['fixedFee'], rows[1]['bonus']), (6.65, 10.89))
        self.assertEqual((rows[2]['fixedFee'], rows[2]['bonus']), (7.75, 14.89))
        self.assertEqual(rows[3]['fixedFee'], 0)
        self.assertAlmostEqual(rows[3]['bonus'], 1.089, places=6)

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
        script = "function promotionDisplayName(row){return row.name;}\n" + function + '\nconst results=' + json.dumps(results) + ';\nconsole.log(JSON.stringify(promotionCampaignGroups(results)));'
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
        self.assertIn('data-promo-bulk-preview=', source)
        self.assertIn('Somente prepara as prévias; nenhuma alteração é aplicada.', source)
        runner = source[source.index('    async function promotionRunCollectivePreview'):source.index('    function activatePromotionPanels')]
        handler = source[source.index("document.querySelectorAll('[data-promo-bulk-preview]'"):source.index("document.querySelectorAll('[data-promo-load]'")]
        self.assertIn("promotionApiRequest('/api/promotions/preview'", runner)
        self.assertNotIn("promotionApiRequest('/api/promotions/confirm'", runner)
        self.assertIn('selectedListingKeys', handler)
        self.assertIn('promotionRunCollectivePreview', handler)

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

    def test_bulk_preview_summary_keeps_confirmation_per_mlb(self):
        source = Path('gerar_dashboard_ads_ml.py').read_text(encoding='utf-8')
        self.assertIn('function promotionBulkSummaryHtml(state)', source)
        self.assertIn('Resumo das prévias coletivas', source)
        self.assertIn('Confirmar individualmente', source)
        self.assertIn('promotionBulkRunUpdate(scopeKey, selectionKey, patch)', source)
        summary = source[source.index('    function promotionBulkSummaryHtml'):source.index('    function promotionScopePanelHtml')]
        self.assertIn('data-promo-confirm=', summary)
        self.assertNotIn("promotionApiRequest('/api/promotions/confirm'", summary)
        self.assertIn("item.status === 'error'", summary)


if __name__ == '__main__':
    unittest.main()
