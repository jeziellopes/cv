"""Gate: the candidate's identity is data, never a literal in code.

A tailored PDF is named for the candidate it describes. That name belongs in
cv.json. Hardcoding it means the generator only works for one person, and it
publishes a personal identity in a repository anyone can clone.
"""

import json
from pathlib import Path

import pytest

import generate

ROOT = Path(__file__).resolve().parent.parent

NAME_PATTERNS = ("Jeziel", "jeziel", "JeziellCarvalho")


def test_no_literal_candidate_name_in_shipped_code():
    """Shipped modules carry no candidate identity literal."""
    offenders = []
    for rel in ("generate.py", "ats.py", "search.py",
                "tools/evidence_scan.py", "tests/approvals.py",
                "tests/test_claims.py"):
        path = ROOT / rel
        if not path.exists():
            continue
        text = path.read_text(errors="replace")
        for i, line in enumerate(text.splitlines(), 1):
            if any(p in line for p in NAME_PATTERNS):
                offenders.append(f"{rel}:{i}: {line.strip()[:80]}")
    assert not offenders, "candidate name hardcoded in code:\n" + "\n".join(offenders)


def test_filename_stem_comes_from_the_cv(tmp_path):
    cv_path = tmp_path / "cv-en.json"
    cv_path.write_text(json.dumps({"personal": {"name": "Ada Lovelace"}}))
    assert generate.candidate_filename_stem(cv_path) == "AdaLovelace"


def test_filename_stem_strips_accents(tmp_path):
    """A Portuguese name must still yield a filename the ATS gate accepts."""
    cv_path = tmp_path / "cv-pt.json"
    cv_path.write_text(json.dumps({"personal": {"name": "João Gonçalves"}}))
    assert generate.candidate_filename_stem(cv_path) == "JoaoGoncalves"


def test_filename_stem_survives_a_broken_cv(tmp_path):
    cv_path = tmp_path / "cv-en.json"
    cv_path.write_text("{ not json")
    assert generate.candidate_filename_stem(cv_path) == "cv"

    missing = tmp_path / "absent.json"
    assert generate.candidate_filename_stem(missing) == "cv"


@pytest.mark.parametrize("lang", ["en", "pt"])
def test_resolve_paths_names_the_pdf_after_the_cv(tmp_path, monkeypatch, lang):
    company = "acme"
    company_dir = tmp_path / "companies" / company
    company_dir.mkdir(parents=True)
    (company_dir / f"cv-{lang}.json").write_text(
        json.dumps({"personal": {"name": "Grace Hopper"}})
    )
    monkeypatch.setattr(generate, "BASE_DIR", tmp_path)

    cv_path, pdf_out, _html = generate.resolve_paths(company, lang)
    assert pdf_out.name == f"GraceHopper-{lang}.pdf"
    assert cv_path == company_dir / f"cv-{lang}.json"