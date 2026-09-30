"""Gate: customer-facing prose may not name a project the operator has not approved.

`test_project_names.py` covers the CV JSON. Prose is the other half of the leak
surface: an answer pasted into a web form discloses a project name exactly as
much as a CV does, and is easier to send by accident. This module scans it,
which the previous gate did not.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from approvals import (  # noqa: E402
    APPROVALS,
    COMPANIES,
    company_id,
    company_of,
    leaked,
    load_config,
)

ROOT = Path(__file__).resolve().parent.parent

PROSE_PATTERNS = ("question.md", "question-*.md", "cover-letter*.md")


def _load():
    if not APPROVALS.exists():
        pytest.skip("project-names.json absent (gitignored, local only)")
    return load_config()


def _prose_files():
    if not COMPANIES.is_dir():
        return []
    seen = set()
    for pattern in PROSE_PATTERNS:
        seen.update(COMPANIES.rglob(pattern))
    return sorted(seen)


def _corpus() -> str:
    text = ""
    for path in _prose_files():
        text += path.read_text(errors="replace")
    if COMPANIES.is_dir():
        for path in COMPANIES.rglob("cv-*.json"):
            text += path.read_text(errors="replace")
    return text.lower()


def test_answer_prose_is_scanned():
    """Prose must not be an unmonitored path out of the gate."""
    if not COMPANIES.is_dir():
        pytest.skip("no companies/ yet: candidate data is gitignored")
    assert _prose_files(), "no answer prose found; prose scanning would be untested"


@pytest.mark.parametrize("path", _prose_files(), ids=company_id)
def test_prose_names_only_approved_projects(path):
    config = _load()
    company = company_of(path)
    found = leaked(path.read_text(errors="replace"), company, config)

    assert not found, (
        f"{path.relative_to(ROOT)} names project(s) not approved for {company}: "
        f"{', '.join(found)}. Mask the name in the prose too, or record the "
        f"approval for {company}."
    )


def test_masked_names_stay_masked():
    """A name kept hidden by policy must not reappear in any CV or answer."""
    config = _load()
    masked = [n.lower() for n in config.get("always_masked", [])]
    assert masked, "always_masked is empty, so nothing is enforced as hidden"

    corpus = _corpus()
    found = sorted({n for n in masked if n in corpus})

    assert not found, f"masked name(s) reappeared in a tailored document: {', '.join(found)}"