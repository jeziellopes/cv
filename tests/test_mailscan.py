"""The Gmail reader: confirmations are matched by company and role."""

import json

import pytest
from typer.testing import CliRunner

import inbox
import mailscan

PAYLOAD = {
    "title": "Senior Fullstack Engineer",
    "company": "Projuris",
    "location": "Remote",
    "url": "https://www.linkedin.com/jobs/view/999/",
    "apply_url": "https://projuris.gupy.io/job/abc?source=linkedin",
    "description": "Requisitos: React.",
}


@pytest.fixture
def base(tmp_path, monkeypatch):
    monkeypatch.setattr(inbox, "LEDGER", tmp_path / "inbox.json")
    return tmp_path


def _message(subject, sender="no-reply@example.com", mid="1", date="2026-10-06"):
    return {"id": mid, "from": sender, "subject": subject, "date": date}


def test_default_query_is_confirmation_shaped():
    query = mailscan.default_query()
    assert query.startswith("subject:(")
    assert "sua candidatura" in query
    assert "thank you for applying" in query


def test_names_one_requires_the_company_with_the_role():
    entry = {"company": "Skeelo", "title": "Backend Engineer I"}
    assert mailscan.names_one(_message("Skeelo | candidatura: Backend Engineer I"), entry)
    # The role alone is not a signal, however distinctive it looks.
    assert not mailscan.names_one(_message("candidatura: Backend Engineer I"), entry)


def test_a_roles_words_do_not_match_inside_another_word():
    """'full' inside 'Fullstack' read one company's mail as another's role."""
    entry = {"company": "Rotik", "title": "Pessoa Desenvolvedora Full Stack"}
    assert not mailscan.names_one(
        _message("Skeelo | Sua candidatura para Fullstack Engineer II"), entry)


def test_names_one_accepts_a_company_only_where_it_is_alone():
    entry = {"company": "Projuris", "title": "Senior Fullstack Engineer"}
    subject = _message("Sua candidatura na Projuris")
    assert mailscan.names_one(subject, entry, company_alone=True)
    assert not mailscan.names_one(subject, entry, company_alone=False)




def test_a_confirmation_matches_without_any_apply_link(base):
    """The sender is evidence, not the reason, so the link cannot gate a match."""
    capture = inbox.save_capture(dict(PAYLOAD, apply_url=""), base)
    matches, _, _ = mailscan.find_matches(inbox.load_ledger(), [
        _message("Projuris | Senior Fullstack Engineer: candidatura recebida",
                 sender="recrutamento@projuris.com.br")])
    assert [m["slug"] for m in matches] == [capture.slug]


def test_a_confirmation_for_one_role_does_not_mark_another_at_the_same_company(base):
    """Two Skeelo postings: the pair is what identifies a capture.

    A confirmation naming Fullstack Engineer II matched Backend Engineer I when
    the company alone was enough and Backend was the only one still unmarked.
    """
    first = inbox.save_capture(dict(PAYLOAD, company="Skeelo",
                                    title="Fullstack Engineer II",
                                    url="https://x/1"), base)
    inbox.save_capture(dict(PAYLOAD, company="Skeelo",
                            title="Backend Engineer I",
                            url="https://x/2"), base)

    matches, _, _ = mailscan.find_matches(inbox.load_ledger(), [
        _message("Skeelo | Sua candidatura para Fullstack Engineer II")])
    assert [m["slug"] for m in matches] == [first.slug], "matched the wrong Skeelo role"


def test_roles_sharing_their_words_are_not_confused(base):
    """Senior Fullstack Engineer and Fullstack Engineer II share most words."""
    senior = inbox.save_capture(dict(PAYLOAD, company="Skeelo",
                                     title="Senior Fullstack Engineer",
                                     url="https://x/1"), base)
    inbox.save_capture(dict(PAYLOAD, company="Skeelo",
                            title="Fullstack Engineer II",
                            url="https://x/2"), base)

    matches, _, _ = mailscan.find_matches(inbox.load_ledger(), [
        _message("Skeelo | Sua candidatura para Senior Fullstack Engineer")])
    assert [m["slug"] for m in matches] == [senior.slug]


def test_a_confirmation_naming_no_capture_is_reported_unmatched(base):
    inbox.save_capture(PAYLOAD, base)
    matches, already, unmatched = mailscan.find_matches(inbox.load_ledger(), [
        _message("Your invoice is ready")])
    assert matches == [] and already == []
    assert [m["subject"] for m in unmatched] == ["Your invoice is ready"]


def test_a_confirmation_for_an_applied_capture_is_reported_as_already(base):
    capture = inbox.save_capture(PAYLOAD, base)
    inbox.mark_applied(capture.slug, base)
    matches, already, unmatched = mailscan.find_matches(inbox.load_ledger(), [
        _message("Projuris | Senior Fullstack Engineer candidatura")])
    assert matches == [] and unmatched == []
    assert [a["slug"] for a in already] == [capture.slug]


def test_dry_run_writes_nothing(base, monkeypatch):
    inbox.save_capture(PAYLOAD, base)
    before = (base / "inbox.json").read_text()
    monkeypatch.setattr(mailscan, "fetch", lambda query, limit=50: [
        _message("Projuris | Senior Fullstack Engineer candidatura recebida")])

    result = CliRunner().invoke(inbox.app, ["mail"])
    assert result.exit_code == 0, result.output
    assert "dry run" in result.output
    assert (base / "inbox.json").read_text() == before


def test_apply_records_only_the_matched_capture(base, monkeypatch):
    first = inbox.save_capture(PAYLOAD, base)
    second = inbox.save_capture(dict(PAYLOAD, company="Outra",
                                     title="Backend Engineer I", url="https://x/2"), base)
    monkeypatch.setattr(mailscan, "fetch", lambda query, limit=50: [
        _message("Projuris | Senior Fullstack Engineer candidatura recebida")])

    result = CliRunner().invoke(inbox.app, ["mail", "--apply"])
    assert result.exit_code == 0, result.output
    steps = {job["slug"]: job["step"] for job in inbox.jobs(base)}
    assert steps[first.slug] == "applied"
    assert steps[second.slug] == "captured"


def test_unmatched_is_counted_unless_all_is_asked_for(base, monkeypatch):
    inbox.save_capture(PAYLOAD, base)
    monkeypatch.setattr(mailscan, "fetch", lambda query, limit=50: [
        _message("Your invoice is ready", sender="billing@example.com", mid="9")])

    quiet = CliRunner().invoke(inbox.app, ["mail"])
    assert quiet.exit_code == 0, quiet.output
    assert "unmatched:" not in quiet.output
    assert "1 unmatched" in quiet.output
    assert "--all" in quiet.output

    loud = CliRunner().invoke(inbox.app, ["mail", "--all"])
    assert loud.exit_code == 0, loud.output
    assert "unmatched:" in loud.output
    assert "Your invoice is ready" in loud.output


def test_a_match_is_shown_without_all(base, monkeypatch):
    inbox.save_capture(PAYLOAD, base)
    monkeypatch.setattr(mailscan, "fetch", lambda query, limit=50: [
        _message("Projuris | Senior Fullstack Engineer candidatura recebida")])

    result = CliRunner().invoke(inbox.app, ["mail"])
    assert result.exit_code == 0, result.output
    assert "1 match(es)" in result.output
    assert "projuris" in result.output


def test_a_mail_failure_exits_non_zero(base, monkeypatch):
    inbox.save_capture(PAYLOAD, base)

    def boom(query, limit=50):
        raise mailscan.MailError(mailscan.E_MAIL_API, "HTTP 403")

    monkeypatch.setattr(mailscan, "fetch", boom)
    result = CliRunner().invoke(inbox.app, ["mail"])
    assert result.exit_code == 1
    assert mailscan.E_MAIL_API in result.output


def test_the_ledger_round_trips_through_json(base):
    inbox.save_capture(PAYLOAD, base)
    written = json.loads((base / "inbox.json").read_text())
    assert written[0]["apply_url"].startswith("https://projuris.gupy.io")


def test_authorize_maps_a_denied_consent_to_an_identity():
    """Google raises several types for a refusal; each becomes one identity."""

    class Denied:
        def run_local_server(self, port=0):
            raise Warning("access_denied")

    with pytest.raises(mailscan.MailError) as caught:
        mailscan._authorize(Denied())
    assert caught.value.identity == mailscan.E_MAIL_NO_TOKEN
    assert "access_denied" in caught.value.detail
    assert "test user" in caught.value.detail


def test_authorize_returns_what_the_flow_produced():
    marker = object()

    class Fine:
        def run_local_server(self, port=0):
            return marker

    assert mailscan._authorize(Fine()) is marker