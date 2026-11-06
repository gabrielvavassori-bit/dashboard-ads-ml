"""Regressão: séries diárias grandes (Lonas, 06/10/2026) não podem ser cortadas em 8 MB."""
import io
import json
import os
import unittest
from unittest.mock import patch

import app


class _Resp(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _payload(n_bytes):
    rows = []
    row = {"item_id": "MLB0000000000", "snapshot_date": "2026-09-06", "visits_total": 1}
    size = len(json.dumps(row)) + 2
    rows = [row] * (n_bytes // size)
    return json.dumps({"ok": True, "rows": rows}).encode()


class DailyResponseSizeTest(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"DASH_ADS_INTERNAL_SECRET": "x"})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_visits_daily_above_8mb_is_parsed_whole(self):
        body = _payload(8_600_000)  # tamanho real da Lonas
        with patch.object(app, "urlopen", return_value=_Resp(body)):
            out = app._fetch_dash_ads_json("/internal/dash-ads/visits-daily", {"client": "c"})
        self.assertTrue(out.get("ok"))
        self.assertGreater(len(out["rows"]), 100_000)

    def test_truncated_response_is_explicit_error_never_parsed(self):
        limit = app._dash_ads_max_response_bytes("/internal/dash-ads/account-metrics")
        body = _payload(limit + 50_000)
        with patch.object(app, "urlopen", return_value=_Resp(body)):
            out = app._fetch_dash_ads_json("/internal/dash-ads/account-metrics", {"client": "c"})
        self.assertFalse(out.get("ok"))
        self.assertEqual(out["error"], "agent_response_too_large")
        self.assertNotIn("rows", out)

    def test_daily_series_paths_have_large_cap(self):
        for path in ("visits-daily", "sales-daily", "ads-daily", "order-financials"):
            self.assertEqual(app._dash_ads_max_response_bytes(f"/internal/dash-ads/{path}"), 64_000_000)


if __name__ == "__main__":
    unittest.main()
