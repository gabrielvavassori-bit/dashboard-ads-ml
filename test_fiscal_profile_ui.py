import pathlib
import unittest


class FiscalProfileUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = pathlib.Path("gerar_dashboard_ads_ml.py").read_text(encoding="utf-8")
        cls.intelligence = pathlib.Path("assets/inteligencia-vendas-marketplace.html").read_text(encoding="utf-8")

    def test_account_fiscal_form_exposes_required_scenarios(self):
        for marker in (
            'data-view="finance"', 'id="view-finance"', 'id="financeFiscalMode"',
            'value="detailed"', 'id="financeTaxRegime"', 'value="real"',
            'value="presumed"', 'id="financeIcmsInput"', 'id="financeIcmsOutput"',
            'id="financeDifal"', 'id="financeStDecision"', 'id="financeEvidence"',
            'id="financeSkuRows"', 'data-finance-sku=',
        ):
            self.assertIn(marker, self.source)

    def test_fiscal_profile_is_in_remote_payload_and_local_backup(self):
        self.assertIn("fetch('/api/finance-profile'", self.source)
        self.assertIn("costProfile:financeProfile", self.source)
        self.assertIn("costBySku: costs", self.source)
        self.assertIn("fiscalProfile:", self.source)
        self.assertIn("fiscalBySku", self.source)

    def test_ui_warns_that_detailed_formula_is_not_active_yet(self):
        self.assertIn("ainda não altera automaticamente lucro, margem ou promoções", self.source)

    def test_new_fiscal_editor_is_not_exposed_in_sales_intelligence(self):
        self.assertNotIn('id="fiscalConfig"', self.intelligence)


if __name__ == "__main__":
    unittest.main()
