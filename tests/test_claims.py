"""Gate: every claim and figure in a tailored CV must be evidenced.

This is deliberately company agnostic. It holds no CV names and no figures;
the per-application data lives in `claim-evidence.json`, which is gitignored
because it names repos and customer work.

Two kinds of check:

Structural, always on, no data needed:
  - a bullet must not claim the same technology on two clouds

Data driven, from the local config:
  - declined terms stay out of every CV
  - a technology attributed to one employer only appears in that employer's role
  - every quantified phrase is reproduced by counting authored files in a repo

A hit from `tools/evidence_scan.py` is a candidate, not proof. Substring
matches pick up prose and comments, so each figure here is checked by
reproducing it, not by trusting a grep.
"""

import json
from pathlib import Path

import pytest

from authorship import authored_count, default_author

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "claim-evidence.json"
COMPANIES = ROOT / "companies"


def _load():
    if not CONFIG.exists():
        pytest.skip("claim-evidence.json absent (gitignored, local only)")
    return json.loads(CONFIG.read_text())


def _cvs():
    if not COMPANIES.is_dir():
        return []
    return sorted(COMPANIES.rglob("cv-*.json"))


def _count(lab: Path, repo: str, pattern: str) -> int:
    base = lab / repo
    if not (base / ".git").is_dir():
        pytest.skip(f"{repo} not present")
    return authored_count(base, pattern, config_author())


def config_author() -> str:
    """Whose commits count, from the local config, then the git identity."""
    if CONFIG.exists():
        author = json.loads(CONFIG.read_text()).get("author", "")
        if author:
            return author
    return default_author()


# ---- structural, no config required -----------------------------------

def test_cvs_exist():
    if not COMPANIES.is_dir():
        pytest.skip("no companies/ yet: candidate data is gitignored")
    assert _cvs(), "no tailored CVs found; the claim gate would pass vacuously"


def test_no_technology_claimed_on_two_clouds_in_one_bullet():
    """Fusing separate infra work into one bullet is how a claim becomes false."""
    clouds = ("hetzner", "aws", "azure", "gcp", "cloudflare")
    offenders = []
    for path in _cvs():
        cv = json.loads(path.read_text())
        for job in cv.get("experience", []):
            for bullet in job.get("bullets", []):
                low = bullet.lower()
                present = [c for c in clouds if c in low]
                if len(present) > 1 and "terraform" in low:
                    offenders.append(f"{path.parts[-2]}: {bullet[:70]}")
    assert not offenders, "bullet fuses Terraform across clouds:\n" + "\n".join(offenders)


# ---- data driven ------------------------------------------------------

def test_config_declares_something():
    config = _load()
    assert config.get("declined_terms") or config.get("figures"), \
        "claim-evidence.json declares nothing, so the gate catches nothing"


def test_declined_terms_absent_everywhere():
    config = _load()
    offenders = []
    for path in _cvs():
        low = path.read_text(errors="replace").lower()
        for term in config.get("declined_terms", []):
            if term.lower() in low:
                offenders.append(f"{path.parts[-2]}: {term}")
    assert not offenders, (
        "terms the operator declined appear in a CV: " + ", ".join(offenders)
    )


def test_single_org_claims_stay_in_their_org():
    """A technology the operator tied to one employer belongs to that role only."""
    config = _load()
    single = config.get("single_org_claims", {})
    offenders = []
    for path in _cvs():
        cv = json.loads(path.read_text())
        company = path.parts[-2]
        allowed = single.get(company, {})
        for tech, orgs in allowed.items():
            for job in cv.get("experience", []):
                mentions = any(tech.lower() in b.lower() for b in job.get("bullets", []))
                if mentions and job["org"] not in orgs:
                    offenders.append(
                        f"{company}: {tech} in {job['org']} (allowed: {', '.join(orgs)})"
                    )
    assert not offenders, "claim attributed to the wrong role:\n" + "\n".join(offenders)


def test_figures_are_reproducible():
    """Each quantified phrase must be re-derivable from the repository."""
    config = _load()
    lab = Path(config.get("lab_root", "~/lab")).expanduser()
    offenders, checked = [], 0

    for company, entries in config.get("figures", {}).items():
        matches = [p for p in _cvs() if p.parts[-2] == company]
        if not matches:
            offenders.append(f"{company}: no CV found for the configured figures")
            continue
        text = "\n".join(p.read_text(errors="replace") for p in matches)

        for entry in entries:
            phrase = entry["phrase"]
            if phrase not in text:
                offenders.append(f"{company}: CV does not contain {phrase!r}")
                continue
            actual = _count(lab, entry["repo"], entry["glob"])
            checked += 1
            if actual != entry["expect"]:
                offenders.append(
                    f"{company}: {phrase!r} claims {entry['expect']} "
                    f"but {entry['repo']} has {actual}"
                )

    assert not offenders, "figures disagree with the repos:\n" + "\n".join(offenders)
    if config.get("figures"):
        assert checked, "figures configured but none were verified"