"""Shared pytest bootstrap for tests outside the legacy unit-test package."""

import sys
from pathlib import Path


SERVER_ROOT = str(Path(__file__).resolve().parents[1])
if SERVER_ROOT not in sys.path:
    sys.path.insert(0, SERVER_ROOT)
