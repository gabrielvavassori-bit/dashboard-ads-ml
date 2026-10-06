import json
import subprocess
import unittest
from pathlib import Path


class PromotionPriceReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = Path('gerar_dashboard_ads_ml.py').read_text(encoding='utf-8')
        cls.helpers = source[source.index('    function promotionCategory'):source.index('    function promotionRankRows')].replace('{{', '{').replace('}}', '}')
        cls.row = source[source.index('    function promotionTableRow'):source.index('    function promotionTableHtml')].replace('{{', '{').replace('}}', '}')
        cls.stubs = '''
        const safe=x=>String(x??''); const brl=x=>`R$ ${Number(x).toFixed(2)}`;
        const promotionMarginTarget=15;
        const promotionFinancialResult=row=>row.financial||({available:false});
        const promotionSimulationFinancialResult=promotionFinancialResult;
        const promotionEffectivePrice=row=>Number(row.price);
        const promotionQuoteMatchesPrice=(row,p)=>Math.abs(Number(row.receipt_quote?.price)-p)<0.01;
        const promotionState=new Map(); const promotionSameOpportunity=()=>false;
        const promotionDiscountAllocation=()=>({});
        const promotionDisplayName=row=>row.name||'Oferta'; const promotionPeriod=()=>'';
        const promotionStatusClass=()=>''; const promotionStatusLabel=()=>'';
        const promotionAllocationCell=()=>''; const promotionTotalCell=()=>'';
        const promotionLimits=()=>''; const promotionReceiptCell=()=>'';
        const promotionMarginCell=()=>''; const promotionPreviewHtml=()=>'';
        const productImage=()=>'';
        '''

    def run_js(self, script):
        result = subprocess.run(['node', '-e', self.stubs + self.helpers + self.row + script], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_exact_mlb_average_boundaries_and_last_sale(self):
        script = '''
        const DATA={items:[{code:'MLB1',units:0,totalRevenue:0},{code:'MLB1',units:10,totalRevenue:1000,lastSalePrice:98,lastSaleDate:'2026-10-01'},{code:'MLB2',units:1,totalRevenue:500}],meta:{onlineMode:{onlinePeriod:{dateFrom:'2026-09-03',dateTo:'2026-10-02'}}}};
        console.log(JSON.stringify([94.99,95,100,105,105.01,120].map(price=>promotionTableRow({code:'MLB1',units:1,totalRevenue:999},{row:{price,promotion_type:'DEAL'},index:7},false))));
        '''
        rows = json.loads(self.run_js(script))
        for html in rows:
            self.assertIn('Média vendida: R$ 100.00', html)
            self.assertIn('Última venda: R$ 98.00', html)
            self.assertIn('2026-09-03 a 2026-10-02', html)
        self.assertIn('Abaixo da média', rows[0])
        for html in rows[1:4]:
            self.assertIn('Na faixa da média', html)
        self.assertIn('Acima da média', rows[4])
        self.assertIn('20% acima da média', rows[5])

    def test_missing_mlb_never_inherits_sku_average(self):
        html = self.run_js("const DATA={items:[]}; console.log(promotionTableRow({code:'MLB1',units:10,totalRevenue:1000},{row:{price:120},index:0},false));")
        self.assertIn('Sem referência de vendas', html)
        self.assertNotIn('20% acima', html)

    def test_gray_order_coupons_separation_and_action_indices(self):
        html = self.run_js('''
        const DATA={items:[]};
        const rows=[['DEAL',43,0],['SELLER_COUPON_CAMPAIGN',99,1],['DEAL',54,2],['DEAL',null,3]].map(([promotion_type,value,index])=>promotionTableRow({code:'MLB1'},{row:{promotion_type,price:70,can_join:true,receipt_quote:{available:value!==null,price:70,receipt_before_cost_tax:value}},index},true));
        console.log(promotionOrganizeTables('<table><tbody>'+rows.join('')+'</tbody></table>'));
        ''')
        self.assertLess(html.index('data-promo-campaign="2"'), html.index('data-promo-campaign="0"'))
        self.assertLess(html.index('data-promo-campaign="0"'), html.index('data-promo-campaign="3"'))
        self.assertLess(html.index('data-promo-campaign="3"'), html.index('Cupons e benefícios condicionais'))
        self.assertIn('Maior recebimento disponível — margem não apurada', html)

    def test_unknown_and_mismatched_quotes_are_not_ranked_as_receipts(self):
        result = json.loads(self.run_js('''console.log(JSON.stringify([
          promotionPriority({promotion_type:'DEAL',price:70,receipt_quote:{available:true,price:90,receipt_before_cost_tax:100}}),
          promotionPriority({promotion_type:'UNKNOWN',price:70}),
          promotionPriority({promotion_type:'DEAL',price:70,financial:{available:true,margin:20,profit:14}})
        ]));'''))
        self.assertEqual(result[0][2], 3)
        self.assertEqual(result[1][0], 2)
        self.assertEqual(result[2][2:], [0, -14])


if __name__ == '__main__':
    unittest.main()
