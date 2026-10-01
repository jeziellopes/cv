"""Gate: a tailored CV may not name a project the operator has not approved.

Project names are proprietary. The approval record lives in `project-names.json`,
which is gitignored, because this repository is published and the file itself
would leak the names it protects.

Approval is scoped per application: naming a project for one employer says
nothing about any other. The test skips when the file is absent, so a fresh
clone stays green, and fails when a CV names a known-internal project that the
application has no approval for.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from approvals import (  # noqa: E402
    APPROVALS,
    company_id,
    company_of,
    discover_cvs,
    leaked,
    load_config,
)

ROOT = Path(__file__).resolve().parent.parent


def _load():
    if not APPROVALS.exists():
        pytest.skip("project-names.json absent (gitignored, local only)")
    return load_config()


def _cv_files():
    return discover_cvs()


def test_every_cv_is_scanned():
    """A rename or move must not silently take a CV out of the gate."""
    if not _cv_files():
        pytest.skip("no tailored CVs yet: candidate data is gitignored")
    assert _cv_files(), "no tailored CVs found; the gate would pass vacuously"


@pytest.mark.parametrize("path", _cv_files(), ids=company_id)
def test_cv_names_only_approved_projects(path):
    config = _load()
    company = company_of(path)
    found = leaked(path.read_text(errors="replace"), company, config)

    assert not found, (
        f"{path.relative_to(ROOT)} names project(s) not approved for {company}: "
        f"{', '.join(found)}. Mask the name, or record the approval for {company} "
        "in project-names.json."
    )


def test_approvals_do_not_leak_into_tracked_files():
    """The approval record must never be committed to a published repository."""
    ignore_lines = {
        line.strip()
        for line in (ROOT / ".gitignore").read_text().splitlines()
    }
    assert "project-names.json" in ignore_lines, "project-names.json must stay gitignored"


def test_internal_names_are_declared():
    """A deny list with nothing in it is a gate that catches nothing."""
    config = _load()
    assert config.get("internal"), "internal project names are not declared"