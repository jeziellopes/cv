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


def test_the_ledger_does_not_duplicate_the_jd(base):
    """The JD belongs in description.md; a second copy goes stale and bloats."""
    inbox.save_capture(PAYLOAD, base)
    entry = inbox.load_ledger()[0]
    assert "description" not in entry
    assert (base / "companies" / entry["slug"] / "description.md").is_file()


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


def test_has_cv_reports_whether_a_capture_is_still_pending(base):
    """The queue's real question: which captures have no CV yet."""
    assert inbox.has_cv("acme", base) is False

    folder = base / "companies" / "acme"
    folder.mkdir(parents=True)
    (folder / "description.md").write_text("JD only")
    assert inbox.has_cv("acme", base) is False, "a description is not a CV"

    (folder / "cv-pt.json").write_text("{}")
    assert inbox.has_cv("acme", base) is True


def test_has_cv_is_false_for_an_unknown_slug(base):
    assert inbox.has_cv("never-captured", base) is False


def test_apply_url_lands_in_the_file_and_the_ledger(base):
    """A non-Easy-Apply job's company link must survive the capture."""
    payload = dict(PAYLOAD,
                   apply_url="https://rotik.inhire.app/vagas/1?source=linkedin")
    cap = inbox.save_capture(payload, base)
    text = (base / "companies" / cap.slug / "description.md").read_text()
    assert "apply: https://rotik.inhire.app/vagas/1?source=linkedin" in text
    assert inbox.load_ledger()[0]["apply_url"] == \
        "https://rotik.inhire.app/vagas/1?source=linkedin"


def test_easy_apply_writes_no_apply_line(base):
    cap = inbox.save_capture(dict(PAYLOAD, apply_url=""), base)
    text = (base / "companies" / cap.slug / "description.md").read_text()
    assert "apply:" not in text
    assert inbox.load_ledger()[0]["apply_url"] == ""


def test_a_non_http_apply_value_is_rejected(base):
    """A stray string must not be written into the JD file as a link."""
    cap = inbox.save_capture(dict(PAYLOAD, apply_url="javascript:alert(1)"), base)
    text = (base / "companies" / cap.slug / "description.md").read_text()
    assert "apply:" not in text
    assert inbox.load_ledger()[0]["apply_url"] == ""


def test_the_header_order_is_unchanged_without_an_apply_link(base):
    """Existing consumers read title, company, location, url in order."""
    cap = inbox.save_capture(PAYLOAD, base)
    lines = (base / "companies" / cap.slug / "description.md").read_text().splitlines()
    assert lines[0] == PAYLOAD["title"]
    assert lines[1] == PAYLOAD["company"]
    assert lines[3] == PAYLOAD["url"]
