import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
INSTALL = REPO / "install.sh"


@pytest.mark.skipif(not INSTALL.exists(), reason="install.sh not present")
def test_install_script_exists_and_is_executable():
    assert INSTALL.is_file()
    assert INSTALL.stat().st_mode & 0o111


@pytest.mark.skipif(not INSTALL.exists(), reason="install.sh not present")
def test_install_script_help_exits_zero():
    result = subprocess.run(["bash", str(INSTALL), "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    assert "usage: ./install.sh" in result.stdout


@pytest.mark.skipif(not INSTALL.exists(), reason="install.sh not present")
def test_install_script_rejects_unknown_option():
    result = subprocess.run(["bash", str(INSTALL), "--nope"], capture_output=True, text=True)
    assert result.returncode == 2
    assert "unknown option" in result.stderr