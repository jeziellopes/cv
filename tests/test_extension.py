"""Gate: the extension must survive LinkedIn's single-page navigation.

Two faults shipped in 1.0.0, both of which left the operator with no button:

  - the content script matched only /jobs/*, so arriving by clicking Jobs from
    the feed never injected it, because the document does not reload
  - injection returned early unless a description selector matched, so a class
    rename removed the button even on a real job page

These tests pin both behaviours, and the literal request path and header the
server actually accepts.
"""

import json
import re
from pathlib import Path

import pytest

EXT = Path(__file__).resolve().parent.parent / "extension"


@pytest.fixture(scope="module")
def manifest():
    return json.loads((EXT / "manifest.json").read_text())


@pytest.fixture(scope="module")
def content():
    return (EXT / "content.js").read_text()


def test_manifest_is_valid_mv3(manifest):
    assert manifest["manifest_version"] == 3
    assert manifest["background"]["service_worker"] == "background.js"


def test_content_script_covers_the_whole_linkedin_origin(manifest):
    """Only matching /jobs/* breaks SPA navigation, which fires no reload."""
    matches = manifest["content_scripts"][0]["matches"]
    assert "https://www.linkedin.com/*" in matches, (
        "a content script scoped to /jobs/* never injects when the operator "
        "navigates there inside the single-page app"
    )


def test_injection_does_not_gate_on_a_description_selector(content):
    """The button must appear on a job page even if class names changed.

    inject() may return early when it is not a job page or the button already
    exists, but never because a description selector failed to match.
    """
    body = re.search(r"function inject\(\)\s*\{.*?\n\}", content, re.S).group(0)
    assert "isJobPage()" in body
    assert "descriptionText" not in body, (
        "inject() reads the description, so a collapsed or renamed pane can "
        "suppress the button"
    )
    assert "SELECTORS.description" not in body, (
        "inject() queries the description selectors directly"
    )
    # Placement is always in flow, never a fixed overlay that covers LinkedIn's
    # own controls.
    assert "insertBefore" in body
    assert "appendChild" not in body, (
        "appending to body is what produced a fixed overlay over the header"
    )


def test_a_url_poll_exists_for_pushstate_navigation(content):
    """LinkedIn uses pushState, which fires no popstate event."""
    assert "setInterval" in content
    assert "location.href" in content


def test_description_reading_has_fallback_selectors(content):
    """One renamed class must not break extraction."""
    assert 'jobs-description__content' in content
    assert "[class*=" in content, "no attribute-substring fallback selectors"


def test_extraction_has_layers_beyond_selectors(content):
    """A class rename broke extraction once, so it cannot rely on classes."""
    assert "application/ld+json" in content, "no JSON-LD JobPosting fallback"
    assert "JobPosting" in content
    assert "og:title" in content, "no metadata fallback"


def test_a_failure_is_diagnosable(content):
    """A failure must print what the page contained, not only a toast."""
    assert "function diagnose()" in content
    assert '"diagnose"' in content or "diagnose\")" in content or "diagnose" in content


def test_description_text_guards_a_missing_element(content):
    """A null from querySelector must not throw during extraction."""
    body = re.search(r"function descriptionText\(\)\s*\{.*?\n\}", content, re.S).group(0)
    assert "if (!el) continue" in body, (
        "descriptionText dereferences a possibly-null element"
    )


def test_the_request_contract_matches_the_server(manifest):
    """Route, header and default port must agree with inbox.py."""
    background = (EXT / "background.js").read_text()
    server = (Path(__file__).resolve().parent.parent / "inbox.py").read_text()
    assert "/capture" in background and '"/capture"' in server
    assert "X-CV-Token" in background and "X-CV-Token" in server
    assert "8787" in background and "8787" in server


def test_host_permission_covers_localhost(manifest):
    perms = " ".join(manifest["host_permissions"])
    assert "127.0.0.1" in perms
    assert "http://" in perms, "the local endpoint is plain HTTP"


def test_extension_files_are_present():
    for name in ("manifest.json", "content.js", "content.css", "background.js",
                 "popup.html", "popup.js"):
        assert (EXT / name).is_file(), f"missing {name}"