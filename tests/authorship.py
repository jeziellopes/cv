"""Compatibility shim: authorship counting now lives in guards.py.

The claim gate imports from here; the implementation moved so `cv claims
verify` and the tests share one source instead of two.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from guards import (  # noqa: E402,F401
    authored_count,
    authored_files,
    default_author,
)
