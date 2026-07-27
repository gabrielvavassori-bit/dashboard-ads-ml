#!/usr/bin/env python3
"""Run the local integration suite before deployment."""
import unittest


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromName("test_integrations")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
