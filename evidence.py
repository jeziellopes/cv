"""Evidence scanning, as a command rather than a script in a corner.

Walks git repos under the configured roots, keeps only files the operator
authored, and looks for real usage rather than a declared dependency. A hit is
a CANDIDATE, not proof: substring matches pick up prose and comments, so
"elasticsearch" in a doc proposing its removal and "terraform" in landing-page
copy both read as hits. Every hit needs reading before it becomes a claim.

Both roots matter. ~/lab and ~/work split the work, and a scan of either alone
once reported a whole employer codebase as absent.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Optional

import typer

BASE_DIR = Path(__file__).resolve().parent
NAMES_FILE = BASE_DIR / "project-names.json"

NOISE_DIRS = ("node_modules", ".next", "dist", "build", ".venv", "venv",
              "__pycache__", ".terraform", "vendor", ".jskills")
NOISE_FILES = ("-lock.yaml", "-lock.json", "package-lock", "yarn.lock",
               "pnpm-lock", "bun.lock", ".min.js", ".map")
# Backup copies are the same project twice; listing them as evidence misleads.
NOISE_REPO_RE = re.compile(r"(-bkp?\d*|-backup\d*|-copy\d*|-old\d*|-chunk\d*)$",
                           re.I)

PROBES = {
    "mongodb": ("mongodb://", "mongoclient", "mongoose", "pymongo"),
    "material-ui": ("@mui/material", "@material-ui/core"),
    "cypress": ("cypress",),
    "jest": ('"jest"', "jest.config"),
    "testing-library": ("@testing-library",),
    "playwright": ("playwright",),
    "jwt": ("jsonwebtoken", "jwt.", "passport-jwt", "jwtservice", "createhmac"),
    "aws": ("aws-sdk", "@aws-sdk", "boto3", "botocore"),
    "hetzner": ("hcloud_", 'provider "hcloud"', "hetzner"),
    "terraform": ('resource "', 'provider "', "terraform"),
    "elastic": ("elastic/apm", "@elastic/apm", "elasticsearch", "opensearch"),
    "otel": ("opentelemetry", "@opentelemetry"),
    "prometheus": ("prometheus",),
    "grafana": ("grafana",),
    "storybook": ("storybook",),
    "design-system": ("design-system", "designsystem"),
    "docker": ("dockerfile", "docker-compose"),
    "kubernetes": ("k3s", "argocd", "kubernetes", "kubeconfig"),
    "tailwind": ("tailwind",),
    "rag": ("retriev", "rerank", "rag_", "retrieval-augmented"),
    "embeddings": ("embedding", "sentence-transformer", "text-embedding"),
    "vector-db": ("pgvector", "chroma", "faiss", "pinecone", "weaviate", "qdrant"),
}

MAX_BYTES = 2_000_000
SUFFIXES = ("*.ts", "*.tsx", "*.js", "*.jsx", "*.py", "*.json", "*.yml",
            "*.yaml", "*.tf", "*.sql", "*.md", "Dockerfile")


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True).stdout


def is_noise(rel: str) -> bool:
    low = rel.lower()
    if any(part in low.split("/") for part in NOISE_DIRS):
        return True
    return any(low.endswith(n) or n in low.split("/")[-1] for n in NOISE_FILES)


def default_author() -> str:
    """The identity used to attribute evidence, preferring the stable email.

    Display names change between employers: the same author has committed as
    Jeziel Lopes, Jeziel Carvalho and jlllo. The email is the constant, so it is
    what the scan matches on, or a whole backup volume reads as unclaimed.
    """
    for key in ("user.email", "user.name"):
        for args in (["config", key], ["config", "--global", key]):
            out = subprocess.run(["git", *args], capture_output=True,
                                 text=True).stdout.strip()
            if out:
                return out
    return ""


def authored_files(repo: Path, suffixes=SUFFIXES, author: str = "") -> list[str]:
    """Files the author committed and that still exist.

    The author match is case-insensitive because git's --author is not, and a
    single spelling silently skips every repo committed under another casing.
    """
    args = ["log", "--name-only", "--pretty=format:"]
    if author:
        args[1:1] = [f"--author={author}", "-i"]
    out = git(repo, *args, "--", *suffixes)
    return sorted({r.strip() for r in out.splitlines()
                   if r.strip() and not is_noise(r.strip())
                   and (repo / r.strip()).is_file()})


def scan_repo(repo: Path, probes: dict, author: str = "") -> dict:
    hits = {}
    for rel in authored_files(repo, SUFFIXES, author):
        path = repo / rel
        try:
            if path.stat().st_size > MAX_BYTES:
                continue
            text = path.read_text(errors="replace").lower()
        except OSError:
            continue
        for label, needles in probes.items():
            if label in hits:
                continue
            if any(n in text for n in needles):
                hits[label] = rel
    return hits


def is_noise_repo(repo: Path) -> bool:
    if any(part in repo.parts for part in NOISE_DIRS):
        return True
    return bool(NOISE_REPO_RE.search(repo.name))


def find_repos(roots) -> list[Path]:
    found = []
    for root in roots:
        if not root.is_dir():
            continue
        for gitdir in root.rglob(".git"):
            repo = gitdir.parent if gitdir.is_dir() else gitdir
            if is_noise_repo(repo):
                continue
            found.append(repo)
    return sorted(found)


def resolve_roots(raw) -> list[Path]:
    if raw:
        return [Path(r).expanduser() for r in raw]
    return [Path.home() / "lab", Path.home() / "work"]


def repo_label(repo: Path, roots) -> str:
    for root in roots:
        try:
            return str(repo.relative_to(root))
        except ValueError:
            continue
    return str(repo)


def scan(roots, probes=None, author: Optional[str] = None,
         only_repos=None) -> dict:
    """Repo -> {probe: file} for everything the author has evidence for."""
    probes = probes or PROBES
    author = default_author() if author is None else author
    limit = set(only_repos or [])
    found = {}
    scanned = 0
    for repo in find_repos(roots):
        if limit and repo.name not in limit:
            continue
        scanned += 1
        hits = scan_repo(repo, probes, author)
        if hits:
            found[repo_label(repo, roots)] = hits
    return {"scanned": scanned, "found": found, "author": author}


def load_names(path: Optional[Path] = None) -> dict:
    path = path or NAMES_FILE
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text())
    except ValueError:
        return {}


def approval_for(name: str, config: dict, company: Optional[str] = None) -> str:
    """How a repo name stands: approved, masked, or not on any list."""
    low = name.lower()
    if low in {n.lower() for n in config.get("approved", [])}:
        return "approved"
    per_company = config.get("approved_by_company", {})
    if company:
        if low in {n.lower() for n in per_company.get(company, [])}:
            return f"approved for {company}"
    holders = [c for c, names in per_company.items()
               if low in {n.lower() for n in names}]
    if holders:
        return f"approved for {', '.join(sorted(holders))}"
    if low in {n.lower() for n in config.get("internal", [])}:
        return "masked"
    return "unlisted"


app = typer.Typer(help="Scan repositories for real, authored evidence.")


@app.command("evidence")
def evidence_command(
    root: Optional[list[str]] = typer.Option(None, "--root",
                                              help="directory to walk, repeatable"),
    probe: Optional[list[str]] = typer.Option(None, "--probe", "-p"),
    repo: Optional[list[str]] = typer.Option(None, "--repo", help="limit by repo name"),
    author: Optional[str] = typer.Option(None, "--author"),
) -> None:
    """Show where each probe has authored evidence, and where it does not."""
    roots = resolve_roots(root)
    probes = {k: v for k, v in PROBES.items() if not probe or k in probe}
    if probe:
        unknown = sorted(set(probe) - set(PROBES))
        if unknown:
            typer.echo(f"unknown probe(s): {', '.join(unknown)}", err=True)
            raise typer.Exit(code=2)

    result = scan(roots, probes, author, repo)
    typer.echo(f"scanned {result['scanned']} repos under "
               f"{', '.join(str(r) for r in roots)}")
    typer.echo(f"author filter: {result['author'] or '(none: every commit counts)'}\n")

    for name, hits in sorted(result["found"].items()):
        typer.echo(name)
        for label in sorted(hits):
            typer.echo(f"    {label:16} {hits[label]}")

    present = {label for hits in result["found"].values() for label in hits}
    missing = sorted(set(probes) - present)
    if missing:
        typer.echo("\nno authored evidence (do NOT claim these):")
        for label in missing:
            typer.echo(f"    {label}")


@app.command("projects")
def projects_command(
    root: Optional[list[str]] = typer.Option(None, "--root"),
    company: Optional[str] = typer.Option(None, "--company", "-c",
                                          help="show approval as this application sees it"),
    author: Optional[str] = typer.Option(None, "--author"),
) -> None:
    """List repos with authored work, and whether each name may be published."""
    roots = resolve_roots(root)
    config = load_names()
    result = scan(roots, PROBES, author)

    if not result["found"]:
        typer.echo("No authored evidence found.")
        return

    typer.echo(f"author: {result['author'] or '(none)'}\n")
    for name, hits in sorted(result["found"].items()):
        verdict = approval_for(Path(name).name, config, company)
        typer.echo(f"  {name:44} [{verdict}]")
        typer.echo(f"      evidence: {', '.join(sorted(hits))}")

    typer.echo("\nverdicts: approved = publishable; masked = keep unnamed; "
               "unlisted = not on any list")


if __name__ == "__main__":
    app()
