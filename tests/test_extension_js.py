"""Run the extension's behavioural tests from pytest.

The content script runs in a browser, which the suite cannot drive, so it is
executed in a stubbed DOM by node. Skipped when node is absent rather than
silently passing, because a green run must mean the behaviour was checked.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
JS_TEST = ROOT / "extension" / "tests" / "content.test.js"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node is not installed"
)


def test_content_script_behaviour():
    assert JS_TEST.is_file(), f"missing {JS_TEST}"
    out = subprocess.run(
        ["node", str(JS_TEST)], cwd=ROOT, capture_output=True, text=True
    )
    assert out.returncode == 0, (
        "content-script behaviour failed:\n" + out.stdout + out.stderr
    )
    assert "ALL CONTENT-SCRIPT TESTS PASS" in out.stdout


def test_no_javascript_syntax_errors():
    for name in ("content.js", "background.js", "popup.js"):
        path = ROOT / "extension" / name
        out = subprocess.run(
            ["node", "--check", str(path)], capture_output=True, text=True
        )
        assert out.returncode == 0, f"{name}: {out.stderr.strip()[:200]}"