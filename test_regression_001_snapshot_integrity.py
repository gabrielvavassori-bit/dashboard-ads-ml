"""Suite comportamental da REGRESSION-001 no consumidor Dashboard Ads."""

import unittest

from test_integrations import HTTPRouteTests
from test_online_periods import OnlinePeriodTests


CASES = (
    (OnlinePeriodTests, "test_account_daily_chart_does_not_invent_missing_snapshot_dates"),
    (OnlinePeriodTests, "test_online_integrity_blocks_when_central_rule_cannot_be_consulted"),
    (OnlinePeriodTests, "test_online_builder_rejects_ads_from_a_different_period"),
    (OnlinePeriodTests, "test_online_builder_blocks_partial_ads_coverage_before_financial_rendering"),
    (OnlinePeriodTests, "test_online_builder_blocks_when_daily_sales_coverage_turns_partial"),
    (OnlinePeriodTests, "test_online_builder_blocks_daily_ads_without_explicit_complete_coverage"),
    (OnlinePeriodTests, "test_online_builder_never_renders_a_completed_snapshot_from_another_period"),
    (OnlinePeriodTests, "test_sales_intelligence_blocks_daily_partial_coverage_before_recommendations"),
    (HTTPRouteTests, "test_online_integrity_block_hides_financial_kpis_exports_and_auto_refresh"),
    (HTTPRouteTests, "test_sales_intelligence_integrity_block_hides_online_recommendations"),
)


def load_tests(_loader, _tests, _pattern):
    suite = unittest.TestSuite()
    for case, method in CASES:
        suite.addTest(case(method))
    return suite


if __name__ == "__main__":
    unittest.main()
