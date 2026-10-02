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
            'data-view="finance"', 'id="view-finance"', 'id="skuFiscalTaxRegime"',
            'value="simple"', 'value="real"', 'value="presumed"',
            'id="skuFiscalSimpleTax"', 'id="skuFiscalFlexCost"',
            'id="skuFiscalIcmsInput"', 'id="skuFiscalIcmsOutput"',
            'id="skuFiscalDifal"', 'id="skuFiscalStDecision"', 'id="skuFiscalEvidence"',
            'id="financeSkuRows"', 'data-finance-edit=', 'id="financeSkuModal"',
            'id="skuFiscalOrigin"', 'id="skuFiscalOriginState"',
            'id="skuFiscalCalculationMode"', 'id="skuFiscalDestinationState"',
            'id="skuFiscalSaleType"', 'id="skuFiscalFreightCredit"',
            'id="skuFiscalFreightIcms"', 'id="financeSelectAll"',
            'id="financeBulkEdit"', 'data-finance-select=',
        ):
            self.assertIn(marker, self.source)
        self.assertNotIn('Regra geral da conta', self.source)

    def test_fiscal_profile_is_in_remote_payload_and_local_backup(self):
        self.assertIn("fetch('/api/finance-profile'", self.source)
        self.assertIn("costProfile:financeProfile", self.source)
        self.assertIn("costBySku:costs", self.source)
        self.assertIn("fiscalProfile:", self.source)
        self.assertIn("fiscalBySku", self.source)
        self.assertIn("const stored = payload.profile || payload", self.source)
        self.assertIn("O servidor não confirmou a leitura dos dados salvos", self.source)

    def test_ui_states_that_detailed_formula_feeds_promotions(self):
        self.assertIn("alimentam a margem líquida estimada das promoções", self.source)

    def test_new_fiscal_editor_is_not_exposed_in_sales_intelligence(self):
        self.assertNotIn('id="fiscalConfig"', self.intelligence)

    def test_primary_navigation_is_sticky_and_hides_technical_online_beta_tab(self):
        self.assertIn('.page-nav {{ position:sticky; top:0;', self.source)
        self.assertNotIn('data-view="online-beta" type="button"', self.source)
        self.assertIn('id="view-online-beta"', self.source)
        self.assertLess(self.source.index('<nav class="page-nav"'), self.source.index("{f'<section class=\"online-notice\""))

    def test_detailed_tax_data_is_saved_per_sku(self):
        self.assertIn('skus.forEach(sku =>', self.source)
        self.assertIn('fiscalBySku[sku] = {{...profile}}', self.source)
        self.assertIn('taxRegime:', self.source)
        self.assertIn('simpleTaxRate:', self.source)
        self.assertIn('flexCarrierCost:', self.source)
        self.assertIn('originState:', self.source)
        self.assertIn('icmsInputRate:', self.source)
        self.assertIn('destinationState:', self.source)
        self.assertIn('freightCreditEnabled:', self.source)

    def test_search_includes_family_and_saved_state_does_not_require_evidence(self):
        self.assertIn('item.familyId, item.familyName', self.source)
        self.assertIn("const saved = value !== '' || Object.keys(profile).length > 0", self.source)
        self.assertNotIn("const hasDetailedProfile = ['user_informed','document_confirmed']", self.source)

    def test_promotions_use_the_tax_regime_saved_on_each_sku(self):
        self.assertIn("const legacyRegime = ['simple','presumed','real'].includes(financeProfile.taxRegime)", self.source)
        self.assertIn("profile.taxRegime) ? profile.taxRegime : legacyRegime", self.source)
        self.assertIn("if (regime === 'simple')", self.source)
        self.assertIn("const real = regime === 'real'", self.source)

    def test_selected_page_survives_reload(self):
        self.assertIn("localStorage.setItem('dashboardAdsActiveView'", self.source)
        self.assertIn("localStorage.getItem('dashboardAdsActiveView'", self.source)

    def test_save_response_reads_profile_back_from_database(self):
        self.assertIn('persisted = db.get_intelligence_finance_cache', self.app_source)
        self.assertIn('"profile": persisted.get("profile") or {}', self.app_source)


if __name__ == "__main__":
    unittest.main()
