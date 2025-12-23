import os
import sys
import unittest


def add_project_root_to_path():
    """
    Adds the project root directory to Python path
    for consistent test imports in local + Docker environments.
    """
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "."))
    if root not in sys.path:
        sys.path.insert(0, root)


def run_tests(test_dir: str = "tests"):
    """
    Discovers and runs all unittests inside the given directory.
    Returns exit code (0 or 1).
    """
    loader = unittest.TestLoader()
    suite = loader.discover(test_dir)

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Return exit code for CI/CD compatibility
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    add_project_root_to_path()
    exit_code = run_tests()
    sys.exit(exit_code)
