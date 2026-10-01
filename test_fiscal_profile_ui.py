import pathlib
import unittest


class FiscalProfileUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = pathlib.Path("assets/inteligencia-vendas-marketplace.html").read_text(encoding="utf-8")

    def test_account_fiscal_form_exposes_required_scenarios(self):
        for marker in (
            'id="fiscalMode"', 'value="detailed"', 'id="taxRegime"',
            'value="real"', 'value="presumed"', 'id="fiscalIcmsInput"',
            'id="fiscalIcmsOutput"', 'id="fiscalDifal"',
            'id="fiscalStDecision"', 'id="fiscalEvidence"',
        ):
            self.assertIn(marker, self.source)

    def test_fiscal_profile_is_in_remote_payload_and_local_backup(self):
        self.assertGreaterEqual(self.source.count("fiscalProfile: state.fiscalProfile || {}"), 3)
        self.assertGreaterEqual(self.source.count("fiscalBySku: state.fiscalBySku || {}"), 3)
        self.assertIn("Object.prototype.hasOwnProperty.call(profile, 'fiscalProfile')", self.source)
        self.assertIn("const fiscalProfile = payload.fiscalProfile", self.source)

    def test_ui_warns_that_detailed_formula_is_not_active_yet(self):
        self.assertIn("Ainda nao alteram o lucro exibido", self.source)


if __name__ == "__main__":
    unittest.main()
