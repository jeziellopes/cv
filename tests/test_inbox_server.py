"""End-to-end: the endpoint accepts a capture, refuses a bad token, and the
CLI sub-app is reachable."""

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

import inbox


@pytest.fixture
def server(tmp_path, monkeypatch):
    """A real server on an ephemeral port, with the ledger redirected."""
    monkeypatch.setattr(inbox, "LEDGER", tmp_path / "inbox.json")
    token = "test-token-abc"
    handler = inbox.make_handler(token, tmp_path)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    port = httpd.server_address[1]
    yield f"http://127.0.0.1:{port}", token, tmp_path
    httpd.shutdown()
    httpd.server_close()


def post(url, payload, token=None):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url + "/capture", data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("X-CV-Token", token)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read())


PAYLOAD = {
    "title": "Senior Fullstack",
    "company": "Projuris",
    "location": "Remote",
    "url": "https://www.linkedin.com/jobs/view/999/",
    "description": "Requisitos: React, NestJS, RAG e banco vetorial.",
}


def test_capture_over_http(server):
    base, token, tmp = server
    status, body = post(base, PAYLOAD, token)
    assert status == 200 and body["ok"]
    assert body["path"] == f"companies/{body['slug']}/description.md"
    written = tmp / body["path"]
    assert written.is_file()
    assert "Requisitos: React" in written.read_text()


def test_bad_token_is_refused(server):
    base, _token, tmp = server
    status, body = post(base, PAYLOAD, "wrong-token")
    assert status == 401 and not body["ok"]
    assert not (tmp / "companies").exists()


def test_missing_token_is_refused(server):
    base, _token, _tmp = server
    status, _body = post(base, PAYLOAD, None)
    assert status == 401


def test_missing_fields_are_rejected_with_422(server):
    base, token, _tmp = server
    status, body = post(base, {"title": "Dev"}, token)
    assert status == 422 and not body["ok"]
    assert "required" in body["error"]


def test_unknown_path_is_404(server):
    base, _token, _tmp = server
    try:
        urllib.request.urlopen(base + "/nope", timeout=5)
        status = 200
    except urllib.error.HTTPError as err:
        status = err.code
    assert status == 404


def test_health_needs_no_token(server):
    base, _token, _tmp = server
    with urllib.request.urlopen(base + "/health", timeout=5) as resp:
        assert resp.status == 200


def test_cli_subapp_is_registered():
    """`cv inbox` must exist, not only the module."""
    import generate

    names = {g.name or getattr(g, "info_name", "") for g in generate.app.registered_groups}
    assert "inbox" in names


def post_diag(url, payload, token=None):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url + "/diagnose", data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("X-CV-Token", token)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read())


def test_diagnose_writes_a_file_for_the_repo(server):
    """The failure report must land where the selector can be fixed."""
    base, token, tmp = server
    payload = {
        "url": "https://www.linkedin.com/jobs/view/1/",
        "documentTitle": "x",
        "classHints": ["H1.job-title"],
        "domSample": "<div class='job-details'>...</div>",
    }
    status, body = post_diag(base, payload, token)
    assert status == 200 and body["ok"]
    out = tmp / "inbox-diagnose.json"
    assert out.is_file()
    written = json.loads(out.read_text())
    assert written["domSample"].startswith("<div")
    assert written["classHints"] == ["H1.job-title"]
    assert "received_at" in written


def test_diagnose_requires_the_token(server):
    base, _token, tmp = server
    status, _body = post_diag(base, {"url": "x"}, "wrong")
    assert status == 401
    assert not (tmp / "inbox-diagnose.json").exists()


def test_diagnose_writes_no_capture(server):
    """A diagnosis must not pollute the queue."""
    base, token, tmp = server
    post_diag(base, {"url": "x", "domSample": "y"}, token)
    assert not (tmp / "inbox.json").exists()
    assert not (tmp / "companies").exists()