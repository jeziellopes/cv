"""The honesty gates, as logic a command can run rather than only a test.

Two guards live here, and the pytest suites use them too so there is one
implementation:

  claims - every quantified figure a CV asserts is re-derived from the repos,
           so a claim that cannot be reproduced is caught before it ships
  names  - a project name is publishable only where the operator approved it,
           per application, and never in prose that reaches a stranger

Both are data driven. The per-application facts live in gitignored files
(claim-evidence.json, project-names.json) because they name proprietary work.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Optional

import typer

ROOT = Path(__file__).resolve().parent
COMPANIES = ROOT / "companies"
APPROVALS = ROOT / "project-names.json"
CLAIMS = ROOT / "claim-evidence.json"

GENERAL_KEY = "_general"
GENERAL_FILES = ("cv.json", "cv-pt.json")
PROSE_PATTERNS = ("question.md", "question-*.md", "cover-letter*.md")


# ---- files ------------------------------------------------

def discover_cvs() -> list[Path]:
    """Every tailored CV, plus the untargeted ones at the root."""
    found: list[Path] = []
    if COMPANIES.is_dir():
        found += sorted(COMPANIES.rglob("cv-*.json"))
    for name in GENERAL_FILES:
        path = ROOT / name
        if path.exists():
            found.append(path)
    return found


def discover_prose() -> list[Path]:
    if not COMPANIES.is_dir():
        return []
    seen = set()
    for pattern in PROSE_PATTERNS:
        seen.update(COMPANIES.rglob(pattern))
    return sorted(seen)


def company_of(path: Path) -> str:
    """The application a file belongs to; root CVs share one key."""
    if path.resolve().parent == ROOT.resolve():
        return GENERAL_KEY
    return path.resolve().relative_to(COMPANIES.resolve()).parts[0]


def company_id(value) -> str:
    try:
        return company_of(Path(value))
    except (AttributeError, TypeError, ValueError):
        return str(value)


def load_names(path: Optional[Path] = None) -> dict:
    path = path or APPROVALS
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text())
    except ValueError:
        return {}


# The gates in tests/ predate this module and use these spellings.
load_config = load_names


def load_claims(path: Optional[Path] = None) -> dict:
    path = path or CLAIMS
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text())
    except ValueError:
        return {}


# ---- authorship -------------------------------------------

def default_author() -> str:
    for args in (["config", "user.name"], ["config", "--global", "user.name"]):
        out = subprocess.run(["git", *args], capture_output=True,
                             text=True).stdout.strip()
        if out:
            return out
    return ""


def authored_files(base: Path, pattern: str, author: str = "") -> set[str]:
    """Files matching `pattern` the author committed and that still exist.

    Case-insensitive, because git's --author is not. Intersected with the
    working tree, because git log reports deleted files too, which once
    inflated a skill count from 14 to 15 and a migration count from 52 to 53.
    """
    args = ["git", "-C", str(base), "log"]
    if author:
        args += [f"--author={author}", "-i"]
    args += ["--name-only", "--pretty=format:", "--", pattern]
    out = subprocess.run(args, capture_output=True, text=True).stdout
    return {line.strip() for line in out.splitlines()
            if line.strip() and "node_modules" not in line
            and (base / line.strip()).is_file()}


def authored_count(base: Path, pattern: str, author: str = "") -> int:
    return len(authored_files(base, pattern, author))


# ---- naming -----------------------------------------------

def internal_names(config: dict) -> list[str]:
    return config.get("internal", [])


def approved_for(company: str, config: dict) -> set[str]:
    approved = {n.lower() for n in config.get("approved", [])}
    scoped = config.get("approved_by_company", {}).get(company, [])
    return approved | {n.lower() for n in scoped}


def leaked(text: str, company: str, config: dict) -> list[str]:
    """Internal names present in `text` but not approved for `company`.

    Word boundaries, not substrings: a short name like "memo" otherwise flags
    every document that contains "memoria".
    """
    approved = approved_for(company, config)
    found = []
    for name in config.get("internal", []):
        if name.lower() in approved:
            continue
        if re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text, re.IGNORECASE):
            found.append(name)
    return sorted(found)


def check_names(config: Optional[dict] = None,
                company: Optional[str] = None) -> list[dict]:
    """One result per document: which unapproved names it carries."""
    config = config if config is not None else load_names()
    targets = discover_cvs() + discover_prose()
    results = []
    for path in targets:
        owner = company or company_of(path)
        found = leaked(path.read_text(errors="replace"), owner, config)
        results.append({
            "path": str(path.relative_to(ROOT)),
            "company": owner,
            "leaked": found,
            "ok": not found,
        })
    return results


def approve_name(company: str, project: str, config: Optional[dict] = None,
                 path: Optional[Path] = None) -> dict:
    """Record that `company` may name `project`."""
    path = path or APPROVALS
    config = load_names(path)
    config.setdefault("approved_by_company", {})
    names = config["approved_by_company"].setdefault(company, [])
    if project not in names:
        names.append(project)
    if project not in config.setdefault("internal", []):
        config["internal"].append(project)
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n")
    return config


# ---- claims -----------------------------------------------

def verify_claims(config: Optional[dict] = None,
                  lab_root: Optional[Path] = None) -> list[dict]:
    """Re-derive every configured figure and report any that disagree."""
    config = config if config is not None else load_claims()
    lab = Path(config.get("lab_root", "~/lab")).expanduser() if not lab_root else lab_root
    author = config.get("author", "") or default_author()

    results = []
    for company, entries in config.get("figures", {}).items():
        if company == GENERAL_KEY:
            targets = [ROOT / name for name in GENERAL_FILES if (ROOT / name).exists()]
        else:
            folder = COMPANIES / company
            targets = sorted(folder.glob("cv-*.json")) if folder.is_dir() else []

        if not targets:
            results.append({"company": company, "problem": "no CV found",
                            "ok": False})
            continue
        text = "\n".join(p.read_text(errors="replace") for p in targets)

        for entry in entries:
            phrase, repo, glob, expect = (entry["phrase"], entry["repo"],
                                          entry["glob"], entry["expect"])
            if phrase not in text:
                results.append({"company": company, "phrase": phrase,
                                "problem": "the CV does not contain the phrase",
                                "ok": False})
                continue
            base = lab / repo
            if not (base / ".git").is_dir():
                results.append({"company": company, "phrase": phrase,
                                "problem": f"{repo} not present", "ok": False})
                continue
            actual = authored_count(base, glob, author)
            results.append({
                "company": company, "phrase": phrase, "repo": repo,
                "glob": glob, "expect": expect, "actual": actual,
                "ok": actual == expect,
                "problem": "" if actual == expect
                else f"claims {expect}, repo has {actual}",
            })
    return results


# ---- commands ---------------------------------------------

claims_app = typer.Typer(help="Verify that a CV's figures are reproducible.")


@claims_app.command("verify")
def claims_verify(
    company: Optional[str] = typer.Option(None, "--company", "-c",
                                          help="check one application only"),
) -> None:
    """Re-derive every figure a CV asserts, straight from the repos."""
    results = verify_claims()
    if company:
        results = [r for r in results if r.get("company") == company]
    if not results:
        typer.echo("No figures configured, or none for that application.")
        return

    failures = 0
    for r in results:
        if r["ok"]:
            typer.echo(f"  ok    {r.get('company', ''):9} {r.get('phrase', '')!r:32} "
                       f"{r.get('repo', '')} = {r.get('actual')}")
        else:
            failures += 1
            typer.echo(f"  FAIL  {r.get('company', ''):9} {r.get('phrase', '')!r:32} "
                       f"{r.get('problem', '')}")
    typer.echo(f"\n{len(results) - failures}/{len(results)} figures verified.")
    if failures:
        raise typer.Exit(code=1)


names_app = typer.Typer(help="See and record which project names may be used.")


@names_app.command("check")
def names_check(
    company: Optional[str] = typer.Option(None, "--company", "-c"),
) -> None:
    """List every document that names a project it is not approved for."""
    results = check_names(company=company)
    if not results:
        typer.echo("No CVs or prose found.")
        return

    bad = [r for r in results if not r["ok"]]
    for r in results:
        mark = "ok  " if r["ok"] else "LEAK"
        detail = "" if r["ok"] else f"  <- {', '.join(r['leaked'])}"
        typer.echo(f"  {mark} {r['company']:9} {r['path']}{detail}")
    typer.echo(f"\n{len(results) - len(bad)}/{len(results)} documents clean.")
    if bad:
        raise typer.Exit(code=1)


@names_app.command("approve")
def names_approve(company: str, project: str) -> None:
    """Record that an application may name a project."""
    approve_name(company, project)
    typer.echo(f"{project} approved for {company}.")


@names_app.command("list")
def names_list() -> None:
    """Show the recorded approvals."""
    config = load_names()
    global_ok = config.get("approved", [])
    if global_ok:
        typer.echo("approved everywhere:")
        for name in sorted(global_ok):
            typer.echo(f"    {name}")
    for company, names in sorted(config.get("approved_by_company", {}).items()):
        typer.echo(f"{company}:")
        for name in sorted(names):
            typer.echo(f"    {name}")


if __name__ == "__main__":
    claims_app()
