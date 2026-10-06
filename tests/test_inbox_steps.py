"""The capture lifecycle: captured -> cv-ready -> applied, and the panel feed.

"cv-ready" is derived from the files on disk and only "applied" is stored, so
these tests care as much about what is NOT assumed as about what is recorded.
"""

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

import inbox

PAYLOAD = {
    "title": "Senior Fullstack",
    "company": "Projuris",
    "location": "Remote",
    "url": "https://www.linkedin.com/jobs/view/999/",
    "description": "Requisitos: React, NestJS.",
}


@pytest.fixture
def base(tmp_path, monkeypatch):
    monkeypatch.setattr(inbox, "LEDGER", tmp_path / "inbox.json")
    return tmp_path


def _with_cv(base, slug):
    folder = base / "companies" / slug
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "cv-pt.json").write_text("{}")


def test_step_is_captured_until_a_cv_exists(base):
    capture = inbox.save_capture(PAYLOAD, base)
    assert inbox.step_of(capture.slug, inbox.load_ledger()[0], base) == "captured"


def test_step_becomes_cv_ready_when_a_cv_exists(base):
    capture = inbox.save_capture(PAYLOAD, base)
    _with_cv(base, capture.slug)
    assert inbox.step_of(capture.slug, inbox.load_ledger()[0], base) == "cv-ready"


def test_step_is_applied_only_after_it_is_recorded(base):
    capture = inbox.save_capture(PAYLOAD, base)
    _with_cv(base, capture.slug)
    assert inbox.mark_applied(capture.slug, base) == "projuris"
    assert inbox.step_of(capture.slug, inbox.load_ledger()[0], base) == "applied"


def test_a_finished_capture_is_not_assumed_applied(base):
    """Legacy "done" meant the CV was finished, not that it was sent.

    Treating it as applied would put a submission on the record that never
    happened, which is the whole reason the step is now explicit.
    """
    capture = inbox.save_capture(PAYLOAD, base)
    entries = inbox.load_ledger()
    entries[0]["status"] = "done"
    inbox.save_ledger(entries)
    _with_cv(base, capture.slug)
    assert inbox.step_of(capture.slug, inbox.load_ledger()[0], base) == "cv-ready"


def test_mark_applied_accepts_a_posting_url(base):
    capture = inbox.save_capture(PAYLOAD, base)
    assert inbox.mark_applied(PAYLOAD["url"], base) == capture.slug


def test_mark_applied_accepts_a_linkedin_job_id(base):
    capture = inbox.save_capture(PAYLOAD, base)
    assert inbox.mark_applied("999", base) == capture.slug


def test_mark_applied_returns_none_for_an_unknown_job(base):
    inbox.save_capture(PAYLOAD, base)
    assert inbox.mark_applied("does-not-exist", base) is None


def test_jobs_are_listed_newest_first(base):
    inbox.save_capture(PAYLOAD, base)
    inbox.save_capture(dict(PAYLOAD, title="Second role", url="https://x/2"), base)
    entries = inbox.load_ledger()
    entries[0]["captured_at"] = "2026-01-01T00:00:00+00:00"
    entries[1]["captured_at"] = "2026-02-01T00:00:00+00:00"
    inbox.save_ledger(entries)

    order = [job["title"] for job in inbox.jobs(base)]
    assert order == ["Second role", "Senior Fullstack"]


def test_reconcile_marks_only_the_postings_it_is_given(base):
    first = inbox.save_capture(PAYLOAD, base)
    second = inbox.save_capture(
        dict(PAYLOAD, company="Outra", url="https://www.linkedin.com/jobs/view/555/"),
        base)

    applied = inbox.reconcile(["999"], base)
    assert applied == [first.slug]
    steps = {job["slug"]: job["step"] for job in inbox.jobs(base)}
    assert steps[first.slug] == "applied"
    assert steps[second.slug] == "captured"


def test_reconcile_with_nothing_to_match_changes_nothing(base):
    capture = inbox.save_capture(PAYLOAD, base)
    assert inbox.reconcile([], base) == []
    assert inbox.jobs(base)[0]["step"] == "captured"
    assert capture.slug == "projuris"


def test_a_skipped_capture_has_its_own_step(base):
    capture = inbox.save_capture(PAYLOAD, base)
    assert inbox.mark_skipped(capture.slug, "no fit", base) == "projuris"
    assert inbox.step_of(capture.slug, inbox.load_ledger()[0], base) == "skipped"


def test_a_skipped_capture_keeps_the_reason(base):
    capture = inbox.save_capture(PAYLOAD, base)
    inbox.mark_skipped(capture.slug, "needs VS Code extension experience", base)
    entry = inbox.load_ledger()[0]
    assert entry["skip_reason"] == "needs VS Code extension experience"
    assert entry["skipped_at"]


def test_a_skipped_capture_is_not_made_ready_by_a_cv(base):
    """A posting passed over must not re-enter the queue because a CV sits there."""
    capture = inbox.save_capture(PAYLOAD, base)
    _with_cv(base, capture.slug)
    assert inbox.step_of(capture.slug, inbox.load_ledger()[0], base) == "cv-ready"
    inbox.mark_skipped(capture.slug, "no fit", base)
    assert inbox.step_of(capture.slug, inbox.load_ledger()[0], base) == "skipped"


def test_a_skipped_capture_is_not_applied(base):
    capture = inbox.save_capture(PAYLOAD, base)
    inbox.mark_skipped(capture.slug, "no fit", base)
    assert inbox.jobs(base)[0]["step"] == "skipped"


def test_mark_skipped_returns_none_for_an_unknown_job(base):
    inbox.save_capture(PAYLOAD, base)
    assert inbox.mark_skipped("nope", "", base) is None


# ---- over HTTP -------------------------------------------------------------

@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setattr(inbox, "LEDGER", tmp_path / "inbox.json")
    handler = inbox.make_handler("tok", tmp_path)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", "tok", tmp_path
    httpd.shutdown()
    httpd.server_close()


def _call(method, url, payload=None, token=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("X-CV-Token", token)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read())


def test_jobs_refuses_a_request_without_the_token(server):
    base, token, _ = server
    _call("POST", base + "/capture", PAYLOAD, token)
    status, _ = _call("GET", base + "/jobs")
    assert status == 401


def test_jobs_feeds_the_panel_with_the_derived_step(server):
    base, token, tmp = server
    _, body = _call("POST", base + "/capture", PAYLOAD, token)
    slug = body["slug"]

    status, body = _call("GET", base + "/jobs", token=token)
    assert status == 200 and body["ok"]
    assert body["jobs"][0]["slug"] == slug
    assert body["jobs"][0]["step"] == "captured"

    _with_cv(tmp, slug)
    _, body = _call("GET", base + "/jobs", token=token)
    assert body["jobs"][0]["step"] == "cv-ready"


def test_jobs_can_look_up_one_posting(server):
    base, token, _ = server
    _call("POST", base + "/capture", PAYLOAD, token)
    status, body = _call("GET", base + "/jobs?id=999", token=token)
    assert status == 200 and body["job"]["slug"] == "projuris"


def test_applied_endpoint_records_one_posting(server):
    base, token, _ = server
    _call("POST", base + "/capture", PAYLOAD, token)
    status, body = _call("POST", base + "/applied", {"slug": "projuris"}, token)
    assert status == 200 and body["slug"] == "projuris"
    _, feed = _call("GET", base + "/jobs", token=token)
    assert feed["jobs"][0]["step"] == "applied"


def test_applied_endpoint_404s_an_unknown_posting(server):
    base, token, _ = server
    status, _ = _call("POST", base + "/applied", {"slug": "nope"}, token)
    assert status == 404


def test_reconcile_endpoint_marks_the_ids_it_is_given(server):
    base, token, _ = server
    _call("POST", base + "/capture", PAYLOAD, token)
    status, body = _call("POST", base + "/reconcile", {"ids": ["999", "1"]}, token)
    assert status == 200 and body["applied"] == ["projuris"]


def test_reconcile_rejects_a_non_list(server):
    base, token, _ = server
    status, _ = _call("POST", base + "/reconcile", {"ids": "999"}, token)
    assert status == 422