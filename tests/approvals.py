"""Compatibility shim: the naming logic now lives in guards.py.

The gates in this directory import from here; the implementation moved so the
`cv names` command and the tests share one source instead of two.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from guards import (  # noqa: E402,F401
    APPROVALS,
    COMPANIES,
    GENERAL_FILES,
    GENERAL_KEY,
    ROOT,
    approved_for,
    company_id,
    company_of,
    discover_cvs,
    internal_names,
    leaked,
    load_config,
    load_names,
)
