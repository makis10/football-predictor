"""Shared pytest fixtures / path setup for the backend test suite."""
import os
import sys

# Allow `import backend.app...` when pytest is run from the repo root or /app.
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
