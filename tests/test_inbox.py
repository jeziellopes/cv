"""The inbox: slug safety, queue integrity, and the capture endpoint."""

from pathlib import Path

import pytest

import inbox

ROOT = Path(__file__).resolve().parent.parent


PAYLOAD = {
    "title": "Pessoa Desenvolvedora Fullstack Sr",
    "company": "Starian",
    "location": "Remote",
    "url": "https://www.linkedin.com/jobs/view/123",
    "description": "Requisitos: React, Next.js, NestJS, IA.",
}


@pytest.fixture
def base(tmp_path, monkeypatch):
    monkeypatch.setattr(inbox, "LEDGER", tmp_path / "inbox.json")
    return tmp_path


def test_slugify_strips_path_separators():
    """A company name must never become a path traversal."""
    assert "/" not in inbox.slugify("../../etc/passwd")
    assert ".." not in inbox.slugify("../../etc/passwd")
    assert inbox.slugify("../../etc/passwd") == "etc-passwd"


def test_slugify_handles_unicode_and_empty():
    assert inbox.slugify("Projuris ADV") == "projuris-adv"
    assert inbox.slugify("Árvore & Cia.") == "arvore-cia"
    assert inbox.slugify("") == "job"


def test_capture_writes_the_description_in_pipeline_format(base):
    cap = inbox.save_capture(PAYLOAD, base)
    out = base / "companies" / cap.slug / "description.md"
    assert out.is_file()
    text = out.read_text()
    assert text.startswith("Pessoa Desenvolvedora Fullstack Sr\nStarian\nRemote\n")
    assert "Requisitos: React" in text
    assert cap.path == f"companies/{cap.slug}/description.md"


def test_capture_is_queued(base):
    inbox.save_capture(PAYLOAD, base)
    entries = inbox.load_ledger()
    assert len(entries) == 1
    assert entries[0]["status"] == "new"
    assert entries[0]["company"] == "Starian"
    assert entries[0]["captured_at"]


def test_missing_company_or_title_is_rejected(base):
    with pytest.raises(ValueError, match="required"):
        inbox.save_capture({"company": "Acme"}, base)
    with pytest.raises(ValueError, match="required"):
        inbox.save_capture({"title": "Dev"}, base)
    assert inbox.load_ledger() == []


def test_second_role_at_one_company_gets_its_own_slug(base):
    first = inbox.save_capture(PAYLOAD, base)
    second = inbox.save_capture(PAYLOAD, base)
    assert first.slug != second.slug
    assert second.slug.startswith(first.slug)
    assert (base / "companies" / second.slug / "description.md").is_file()


def test_token_is_stable(tmp_path, monkeypatch):
    tok = tmp_path / "token"
    monkeypatch.setattr(inbox, "TOKEN_FILE", tok)
    first = inbox.get_token()
    second = inbox.get_token()
    assert first == second
    assert len(first) > 20


def test_token_file_is_restricted_where_the_filesystem_allows(tmp_path, monkeypatch):
    """chmod is a no-op on some mounts, so this asserts the attempt, not fate."""
    probe = tmp_path / "probe"
    probe.write_text("x")
    probe.chmod(0o600)
    if probe.stat().st_mode & 0o077:
        pytest.skip("filesystem ignores chmod")

    tok = tmp_path / "token"
    monkeypatch.setattr(inbox, "TOKEN_FILE", tok)
    inbox.get_token()
    assert tok.stat().st_mode & 0o077 == 0


def test_ledger_survives_corruption(tmp_path, monkeypatch):
    bad = tmp_path / "inbox.json"
    bad.write_text("{ not json")
    monkeypatch.setattr(inbox, "LEDGER", bad)
    assert inbox.load_ledger() == []
