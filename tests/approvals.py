"""Shared approval lookup for the project-name gates.

A name is approved for one application without being approved for any other,
so the gates resolve approval from the company directory rather than from a
single global list.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPANIES = ROOT / "companies"
APPROVALS = ROOT / "project-names.json"


def load_config() -> dict:
    return json.loads(APPROVALS.read_text())


def company_of(path: Path) -> str:
    """The application a file belongs to.

    Variants nest as `companies/<company>/<role>/`, so the company is the first
    directory under `companies/`, not the leaf.
    """
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
    """Internal names present in `text` but not approved for `company`.

    Matching is on word boundaries rather than substrings. A substring check
    makes a short name dangerous: adding "memo" to the deny list flagged every
    CV containing "memória" or "memorável", which is unrelated prose.
    """
    approved = approved_for(company, config)
    found = []
    for name in internal_names(config):
        if name.lower() in approved:
            continue
        if re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text, re.IGNORECASE):
            found.append(name)
    return sorted(found)