"""Staleness by content fingerprint, so a NEW RULE invalidates old output.

Timestamps cannot see the case that matters most: a PDF built before a check
existed passes a mtime comparison forever, then fails the check the moment it
runs. As checks move out of scratch scripts and into `cv` commands, that becomes
the common case rather than an edge one.

So a build records what it was built from. Each generated PDF gets a stamp
holding three hashes:

  data    the CV JSON it rendered
  render  the code that produced the layout
  rules   the code that decides whether the result is acceptable

`cv stale` recomputes them. When `rules` moves, every earlier PDF is reported,
which is exactly the "we added a check" case. Nothing is stored about *what* the
rules are, so the stamp cannot itself go stale.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# The code that renders a PDF.
RENDER_FILES = ("generate.py", "staleness.py")
# The code that decides whether a CV is acceptable.
RULE_FILES = ("ats.py", "guards.py", "evidence.py")


@dataclass
class Stale:
    label: str
    lang: str
    reason: str
    cv_path: Path
    pdf_path: Path


def _digest(names, root: Path) -> str:
    """A stable hash over the named files that exist under root."""
    h = hashlib.sha256()
    for name in sorted(names):
        p = root / name
        if not p.is_file():
            continue
        h.update(name.encode())
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


def _master_for(root: Path, cv_path: Path) -> Optional[Path]:
    """The master a company CV is composed from, or None for the master itself.

    A company CV is a projection of the master profile, so a master edit makes
    every projection out of date even though the company's own file is
    untouched. The master is therefore part of the data a build is stamped
    against.
    """
    lang = "pt" if cv_path.stem.endswith("-pt") else "en"
    master = root / ("cv.json" if lang == "en" else f"cv-{lang}.json")
    if master.is_file() and master != cv_path:
        return master
    return None


def fingerprint(root: Path, cv_path: Path) -> dict:
    h = hashlib.sha256()
    h.update(cv_path.read_bytes())
    master = _master_for(root, cv_path)
    if master is not None:
        h.update(master.read_bytes())
    return {
        "data": h.hexdigest()[:16],
        "render": _digest(RENDER_FILES, root),
        "rules": _digest(RULE_FILES, root),
    }


def stamp_path(cv_path: Path, lang: str) -> Path:
    """The build record, kept beside the CV it describes."""
    return cv_path.parent / f".build-{lang}.json"


def write_stamp(root: Path, cv_path: Path, lang: str) -> Path:
    out = stamp_path(cv_path, lang)
    payload = fingerprint(root, cv_path)
    payload["cv"] = str(cv_path.relative_to(root))
    out.write_text(json.dumps(payload, indent=2) + "\n")
    return out


def read_stamp(cv_path: Path, lang: str) -> dict:
    p = stamp_path(cv_path, lang)
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text())
    except ValueError:
        return {}


def cv_files(root: Path, languages=("en", "pt")) -> list[Path]:
    """Exact language files for every tailored CV, plus the untargeted ones."""
    found: list[Path] = []
    companies = root / "companies"
    if companies.is_dir():
        for lang in languages:
            found += sorted(companies.rglob(f"cv-{lang}.json"))
    for lang in languages:
        p = root / (f"cv-{lang}.json" if lang != "en" else "cv.json")
        if p.exists():
            found.append(p)
    return found


def stem_of(cv_path: Path) -> str:
    """The PDF is named for the candidate, taken from the CV itself."""
    try:
        name = json.loads(cv_path.read_text())["personal"]["name"]
    except (OSError, ValueError, KeyError, TypeError):
        return "cv"
    import unicodedata

    folded = "".join(c for c in unicodedata.normalize("NFKD", name)
                     if not unicodedata.combining(c))
    return "".join(folded.split()) or "cv"


def backup_pdf(pdf_path: Path, when: Optional[str] = None) -> Path:
    """Copy a company CV's PDF aside before a rebuild overwrites it.

    A stale rebuild replaces the exact file that may have been submitted, and
    the ledger cannot know every CV that was sent: applications made before the
    ledger existed, or never captured, carry no applied status. So every company
    PDF is preserved, not only the recorded ones. The copy lives in a `sent/`
    folder beside it, so it is gitignored with the rest of `companies/`.
    """
    stamp = when or datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out_dir = pdf_path.parent / "sent"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{pdf_path.stem}-{stamp}{pdf_path.suffix}"
    shutil.copy2(pdf_path, out)
    return out


def label_of(cv_path: Path, root: Path) -> str:
    rel = cv_path.relative_to(root)
    parts = rel.parts
    if parts and parts[0] == "companies":
        return "/".join(parts[1:-1])
    return rel.name


def lang_of(cv_path: Path) -> str:
    stem = cv_path.stem
    return stem.split("-")[-1] if "-" in stem else "en"


REASONS = {
    "data": "CV data changed",
    "render": "renderer changed",
    "rules": "checks changed since this was built",
}


def find_stale(root: Path, languages=("en", "pt")) -> list[Stale]:
    """Every CV whose PDF is missing, or older than what it was built from."""
    out: list[Stale] = []

    for cv_path in cv_files(root, languages):
        lang = lang_of(cv_path)
        pdf = cv_path.parent / f"{stem_of(cv_path)}-{lang}.pdf"
        label = label_of(cv_path, root)

        if not pdf.exists():
            out.append(Stale(label, lang, "no PDF", cv_path, pdf))
            continue

        stamp = read_stamp(cv_path, lang)
        if not stamp:
            out.append(Stale(label, lang, "no build record", cv_path, pdf))
            continue

        current = fingerprint(root, cv_path)
        changed = [REASONS[key] for key in ("rules", "render", "data")
                   if stamp.get(key) != current[key]]
        if changed:
            out.append(Stale(label, lang, ", ".join(changed), cv_path, pdf))
    return out