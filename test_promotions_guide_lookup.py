import json
import subprocess
import unittest
from pathlib import Path


class PromotionsGuideLookupTests(unittest.TestCase):
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
