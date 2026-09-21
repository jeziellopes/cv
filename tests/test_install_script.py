import subprocess
from pathlib import Path

import pytest

import generate

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


def test_resolve_browsers_path_uses_env_first(tmp_path, monkeypatch):
    monkeypatch.setattr(generate, "BASE_DIR", tmp_path)
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "/env/browsers")
    assert generate.resolve_browsers_path() == "/env/browsers"


def test_resolve_browsers_path_falls_back_to_cv_env(tmp_path, monkeypatch):
    (tmp_path / ".cv-env").write_text(
        'PLAYWRIGHT_BROWSERS_PATH=/stored/browsers\n', encoding="utf-8"
    )
    monkeypatch.setattr(generate, "BASE_DIR", tmp_path)
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    assert generate.resolve_browsers_path() == "/stored/browsers"


def test_resolve_browsers_path_defaults_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(generate, "BASE_DIR", tmp_path)
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    assert generate.resolve_browsers_path() == ""