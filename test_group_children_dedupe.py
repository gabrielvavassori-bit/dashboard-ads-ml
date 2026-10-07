"""Regressão: agrupamentos SKU/Campanha remontados no navegador são idênticos ao original.

Roda a MESMA função JavaScript da página (GROUP_CHILDREN_EXPAND_JS) no Node e compara
toda a estrutura de dados, campo por campo. Também cobre a falha da REGRESSION-035
original (filhos de agrupamento ficavam com série diária vazia).
"""
import copy
import json
import os
import shutil
import subprocess
import tempfile
import unittest

import app
import gerar_dashboard_ads_ml as G


def sample():
    item_a = {"code": "MLB1", "sku": "A", "title": "Produto A", "revenue": 10.0, "campaignId": "",
              "performance7d": {"units": 2}, "alerts": ["x"]}
    item_b = {"code": "MLBU9", "title": "Familia", "revenue": 5.0,
              "children": [{"code": "MLB2", "sku": "B", "revenue": 3.0, "campaignId": "c1"},
                           {"code": "MLB3", "sku": "B", "revenue": 2.0, "campaignId": "c1"}]}
    sku_child_a = dict(item_a, campaignId="c9", campaignBudget=50.0)            # campo muda + campo novo
    sku_child_2 = {k: v for k, v in item_b["children"][0].items() if k != "campaignId"}  # campo removido
    return {
        "items": [item_a, item_b],
        "skuAds": [{"code": "A", "revenue": 10.0, "children": [sku_child_a]},
                   {"code": "B", "revenue": 5.0, "children": [sku_child_2, dict(item_b["children"][1])]}],
        "campaignAds": [{"code": "c1", "revenue": 5.0, "children": [dict(item_b["children"][0]), dict(item_b["children"][1])]},
                        {"code": "sem", "children": [{"code": "MLB_FORA_DA_TABELA", "revenue": 1.0}]}],
        "kpis": {"revenue": 15.0},
    }


@unittest.skipUnless(shutil.which("node"), "node é necessário para provar a remontagem da página")
class GroupChildrenDedupeTest(unittest.TestCase):
    def roundtrip(self, data):
        compact = G._dedupe_group_children(copy.deepcopy(data))
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "x.js"), "w", encoding="utf-8") as f:
                f.write(G.GROUP_CHILDREN_EXPAND_JS + "\nconst fs=require('fs');"
                        "process.stdout.write(JSON.stringify(expandGroupChildren(JSON.parse(fs.readFileSync(0,'utf8')))));")
            out = subprocess.run(["node", os.path.join(d, "x.js")], input=json.dumps(compact),
                                 capture_output=True, text=True, check=True).stdout
        return compact, json.loads(out)

    def test_rebuilt_page_data_is_identical_field_by_field(self):
        data = sample()
        compact, rebuilt = self.roundtrip(data)
        self.assertEqual(rebuilt, data)
        self.assertIn("$base", compact["skuAds"][0]["children"][0])          # de fato compactado
        self.assertEqual(compact["campaignAds"][1]["children"][0]["code"], "MLB_FORA_DA_TABELA")  # sem base: intacto

    def test_rebuilt_children_are_independent_copies(self):
        _compact, rebuilt = self.roundtrip(sample())
        rebuilt["skuAds"][0]["children"][0]["performance7d"]["units"] = 99
        self.assertEqual(rebuilt["items"][0]["performance7d"]["units"], 2)


class GroupDailySeriesTest(unittest.TestCase):
    def test_strip_also_clears_group_children_series(self):
        data = {"items": [{"code": "MLB1", "dailySeries": [1]}],
                "skuAds": [{"children": [{"code": "MLB1", "dailySeriesItemIndex": 0}, {"code": "MLB2", "dailySeries": [2]}]}],
                "campaignAds": [{"children": [{"code": "MLB1", "dailySeriesItemIndex": 0}]}]}
        app._strip_item_daily_series(data)
        for key in ("skuAds", "campaignAds"):
            for child in data[key][0]["children"]:
                self.assertNotIn("dailySeries", child)
                self.assertNotIn("dailySeriesItemIndex", child)

    def test_loader_requests_every_chunk_and_never_shows_partial_sum(self):
        src = open(G.__file__, encoding="utf-8").read()
        self.assertNotIn(".slice(0, 50)", src)
        self.assertIn("start += 50", src)
        self.assertIn("payloads.some(payload => !payload || payload.ok !== true)", src)


if __name__ == "__main__":
    unittest.main()
