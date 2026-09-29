import copy
import subprocess
import unittest
from unittest.mock import patch

import app
from gerar_dashboard_ads_ml import render_dashboard
from test_operational_availability import OperationalAvailabilityTests


class MainPerformance7dTests(unittest.TestCase):
    def test_main_and_demo_render_responsive_metric_section(self):
        html = render_dashboard({"items": [], "meta": {}})
        self.assertIn('id="performance7dItems"', html)
        self.assertIn("renderPerformance7d(rows)", html)
        self.assertIn("grid-template-columns:repeat(3,minmax(0,1fr))", html)
        self.assertIn("grid-template-columns:repeat(2,minmax(0,1fr))", html)
        self.assertIn(".performance-7d-grid { grid-template-columns:1fr", html)
        self.assertIn("value.complete === true", html)
        self.assertIn("'N/D'", html)

    def test_only_matching_account_performance_is_attached(self):
        payload = OperationalAvailabilityTests().payload()
        evidence = {"complete": True, "previous": 28, "current": 14}
        payload["performance_7d"] = {
            "client_id": "demo", "date_from": "2026-09-09", "previous_to": "2026-09-15",
            "current_from": "2026-09-16", "date_to": "2026-09-22",
            "items": {"MLB123": {"sales": evidence}},
        }
        with patch.object(app, "_fetch_dash_ads_json", return_value=payload):
            data, error = app._build_online_dashboard_data("demo", "7", "2026-09-01", "2026-09-02")
        self.assertEqual(error, "")
        self.assertEqual(data["items"][0]["performance7d"]["sales"], evidence)

        other_account = copy.deepcopy(payload)
        other_account["performance_7d"]["client_id"] = "other"
        with patch.object(app, "_fetch_dash_ads_json", return_value=other_account):
            data, error = app._build_online_dashboard_data("demo", "7", "2026-09-01", "2026-09-02")
        self.assertEqual(error, "")
        self.assertEqual(data["items"][0]["performance7d"], {})

    def test_browser_metric_renderer_keeps_missing_history_as_nd(self):
        html = render_dashboard({"items": [], "meta": {}})
        function = html.split("function renderPerformance7d(rows)", 1)[1].split("function renderTable()", 1)[0]
        script = (
            "let output=''; const document={getElementById:()=>({set innerHTML(value){output=value}})};"
            "const safe=value=>String(value); function renderPerformance7d(rows)" + function +
            "renderPerformance7d([{code:'MLB1',title:'Produto',performance7d:{"
            "current_from:'2026-09-16',date_to:'2026-09-22',"
            "sales:{complete:true,previous:20,current:10},"
            "visits:{complete:false,previous:100,current:50}}}]); console.log(output);"
        )
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, encoding="utf-8", check=True)
        self.assertIn("Vendas 7d</span><b>10</b>", result.stdout)
        self.assertIn("Visitas 7d</span><b>N/D</b>", result.stdout)
        self.assertIn("Conversão 7d</span><b>N/D</b>", result.stdout)


if __name__ == "__main__":
    unittest.main()
