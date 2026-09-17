"""Suite comportamental da REGRESSION-001 no consumidor Dashboard Ads."""

import unittest

from test_integrations import HTTPRouteTests
from test_online_periods import OnlinePeriodTests
from test_operational_availability import OperationalAvailabilityTests


CASES = (
    # Emergency policy authorized 2026-09-17: availability with explicit partial warning.
    (OperationalAvailabilityTests, "test_partial_cache_renders_without_billing_or_repair"),
    (OperationalAvailabilityTests, "test_rejects_other_account_period_and_advertiser"),
    (OperationalAvailabilityTests, "test_empty_cache_not_presented_as_zero"),
    (OperationalAvailabilityTests, "test_sales_only_still_opens"),
    (OperationalAvailabilityTests, "test_intelligence_remains_strict"),
    (OnlinePeriodTests, "test_sales_intelligence_blocks_daily_partial_coverage_before_recommendations"),
    (HTTPRouteTests, "test_sales_intelligence_integrity_block_hides_online_recommendations"),
)


def load_tests(_loader, _tests, _pattern):
    suite = unittest.TestSuite()
    for case, method in CASES:
        suite.addTest(case(method))
    return suite


if __name__ == "__main__":
    unittest.main()
