"""Shared approval lookup for the project-name gates.

A name is approved for one application without being approved for any other,
so the gates resolve approval from the company directory rather than from a
single global list.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPANIES = ROOT / "companies"
APPROVALS = ROOT / "project-names.json"

# The untargeted CVs at the repo root, which no per-application rules cover.
GENERAL_KEY = "_general"
GENERAL_FILES = ("cv.json", "cv-pt.json")


def discover_cvs() -> list[Path]:
    """Every tailored CV, plus the untargeted general ones."""
    found: list[Path] = []
    if COMPANIES.is_dir():
        found += sorted(COMPANIES.rglob("cv-*.json"))
    for name in GENERAL_FILES:
        path = ROOT / name
        if path.exists():
            found.append(path)
    return found


def load_config() -> dict:
    return json.loads(APPROVALS.read_text())


def company_of(path: Path) -> str:
    """The application a file belongs to.

    Variants nest as `companies/<company>/<role>/`, so the company is the first
    directory under `companies/`, not the leaf. The untargeted CVs at the root
    share one key, since no per-application rule covers them.
    """
    if path.resolve().parent == ROOT.resolve():
        return GENERAL_KEY
    rel = path.resolve().relative_to(COMPANIES.resolve())
    return rel.parts[0]


def company_id(value) -> str:
    """A test id for a parameterised path.

    pytest calls the id function even when the parameter list is empty, so this
    must not raise on a clone with no companies/ directory yet.
    """
    try:
        return company_of(Path(value))
    except (AttributeError, TypeError, ValueError):
        return str(value)


def approved_for(company: str, config: dict) -> set[str]:
    """Every name this application may use, lowercased.

    Global approvals cover the employer and independently discoverable public
    bodies. Company-scoped approvals do not carry over between applications.
    """
    approved = {n.lower() for n in config.get("approved", [])}
    scoped = config.get("approved_by_company", {}).get(company, [])
    approved |= {n.lower() for n in scoped}
    return approved


def internal_names(config: dict) -> list[str]:
    return config.get("internal", [])


def leaked(text: str, company: str, config: dict) -> list[str]:
    """Internal names present in `text` but not approved for `company`."""
    lowered = text.lower()
    approved = approved_for(company, config)
    return sorted(
        {n for n in internal_names(config) if n.lower() in lowered and n.lower() not in approved}
    )