import sys, os, unittest

# Force root folder into Python path
ROOT = os.path.abspath(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Run tests
loader = unittest.TestLoader()
suite = loader.discover('tests')

runner = unittest.TextTestRunner()
runner.run(suite)