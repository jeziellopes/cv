#!/usr/bin/env python3
"""Compatibility shim: the scan now lives in evidence.py as `cv evidence`.

Kept so any existing reference still works.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evidence import app  # noqa: E402

if __name__ == "__main__":
    app()
