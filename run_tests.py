#!/usr/bin/env python3
"""Run tests for ssh_proxy package"""

import unittest
import sys
from pathlib import Path

# Add parent directory to path so we can import ssh_proxy
sys.path.insert(0, str(Path(__file__).parent))

if __name__ == '__main__':
    # Discover and run all tests
    loader = unittest.TestLoader()
    start_dir = 'tests'
    suite = loader.discover(start_dir, pattern='test_*.py')

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Exit with appropriate code
    sys.exit(0 if result.wasSuccessful() else 1)
