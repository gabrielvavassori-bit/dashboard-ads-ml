import pathlib
import unittest


class FiscalProfileUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = pathlib.Path("gerar_dashboard_ads_ml.py").read_text(encoding="utf-8")
        cls.intelligence = pathlib.Path("assets/inteligencia-vendas-marketplace.html").read_text(encoding="utf-8")
        cls.app_source = pathlib.Path("app.py").read_text(encoding="utf-8")

    def test_account_fiscal_form_exposes_required_scenarios(self):
        for marker in (
            'data-view="finance"', 'id="view-finance"', 'id="financeFiscalMode"',
            'value="detailed"', 'id="financeTaxRegime"', 'value="real"',
            'value="presumed"', 'id="skuFiscalIcmsInput"', 'id="skuFiscalIcmsOutput"',
            'id="skuFiscalDifal"', 'id="skuFiscalStDecision"', 'id="skuFiscalEvidence"',
            'id="financeSkuRows"', 'data-finance-edit=', 'id="financeSkuModal"',
            'id="skuFiscalOrigin"', 'id="skuFiscalOriginState"',
        ):
            self.assertIn(marker, self.source)

    def test_fiscal_profile_is_in_remote_payload_and_local_backup(self):
        self.assertIn("fetch('/api/finance-profile'", self.source)
        self.assertIn("costProfile:financeProfile", self.source)
        self.assertIn("costBySku:costs", self.source)
        self.assertIn("fiscalProfile:", self.source)
        self.assertIn("fiscalBySku", self.source)
        self.assertIn("const stored = payload.profile || payload", self.source)
        self.assertIn("O servidor não confirmou a leitura dos dados salvos", self.source)

    def test_ui_warns_that_detailed_formula_is_not_active_yet(self):
        self.assertIn("ainda não altera automaticamente lucro, margem ou promoções", self.source)

    def test_new_fiscal_editor_is_not_exposed_in_sales_intelligence(self):
        self.assertNotIn('id="fiscalConfig"', self.intelligence)

    def test_primary_navigation_is_sticky_and_hides_technical_online_beta_tab(self):
        self.assertIn('.page-nav {{ position:sticky; top:0;', self.source)
        self.assertNotIn('data-view="online-beta" type="button"', self.source)
        self.assertIn('id="view-online-beta"', self.source)
        self.assertLess(self.source.index('<nav class="page-nav"'), self.source.index("{f'<section class=\"online-notice\""))

    def test_detailed_tax_data_is_saved_per_sku(self):
        self.assertIn('fiscalBySku:{{...(financeProfile.fiscalBySku || {{}}), [sku]:profile}}', self.source)
        self.assertIn('originState:', self.source)
        self.assertIn('icmsInputRate:', self.source)

    def test_selected_page_survives_reload(self):
        self.assertIn("localStorage.setItem('dashboardAdsActiveView'", self.source)
        self.assertIn("localStorage.getItem('dashboardAdsActiveView'", self.source)

    def test_save_response_reads_profile_back_from_database(self):
        self.assertIn('persisted = db.get_intelligence_finance_cache', self.app_source)
        self.assertIn('"profile": persisted.get("profile") or {}', self.app_source)


if __name__ == "__main__":
    unittest.main()
