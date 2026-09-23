import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch
import app
from test_operational_availability import OperationalAvailabilityTests


class PerformanceTests(unittest.TestCase):
    def test_partial_financial_cache_keeps_independent_performance(self):
        payload = OperationalAvailabilityTests().payload()
        evidence = dict(complete=True, previous=28, current=14)
        payload['performance_7d'] = dict(client_id='demo', date_from='2026-09-09', date_to='2026-09-22', items={'MLB123': {'sales': evidence}})
        with patch.object(app, '_fetch_dash_ads_json', return_value=payload):
            data, error = app._build_online_dashboard_data('demo', '7', '2026-09-01', '2026-09-02')
        self.assertFalse(data['items'][0]['salesCoverageComplete'])
        self.assertEqual(data['items'][0]['performance7d']['sales'], evidence)

    def test_actual_js_partial_cache_groups_and_missing_visits(self):
        source = Path('gerar_dashboard_ads_ml.py').read_text(encoding='utf-8')
        function = source[source.index('    function salesTrendInline'):source.index('    // Portal outside')].replace('{{', '{').replace('}}', '}')
        evidence = dict(date_from='2026-09-09', date_to='2026-09-22', current_from='2026-09-16', previous_to='2026-09-15', sales=dict(complete=True, previous=100, current=50), visits=dict(complete=True, previous=1000, current=500))
        item = dict(code='MLB1', salesCoverageComplete=False, performance7d=evidence)
        script = function + '\nconst item=' + json.dumps(item) + '; console.log(salesTrendInline({children:[item,item]})); item.performance7d.visits.complete=false; console.log(salesTrendInline(item));'
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True, encoding='utf-8', check=True).stdout.splitlines()
        self.assertIn('Vendas 7d: <b>50</b>', result[0])
        self.assertIn('Visitas: <b>500</b>', result[0])
        self.assertIn('Conversão: <b>10%</b>', result[0])
        self.assertIn('▼ 50%', result[0])
        self.assertIn('Visitas: <b>N/D</b>', result[1])
        self.assertIn('Vendas 7d: <b>50</b>', result[1])
