#!/usr/bin/env python3
import unittest
import sys

try:
    import xmlrunner  # type: ignore
except Exception as e:
    sys.stderr.write("xmlrunner is required. Install with: pip install unittest-xml-reporting\n")
    raise


def main():
    suite = unittest.defaultTestLoader.discover('tests', pattern='test_*.py')
    # Write JUnit XML files into test-results/ (one file per test case)
    runner = xmlrunner.XMLTestRunner(output='test-results')
    result = runner.run(suite)
    # Return non-zero exit code on failures/errors to fail the CI job
    if not result.wasSuccessful():
        sys.exit(1)


if __name__ == '__main__':
    main()

