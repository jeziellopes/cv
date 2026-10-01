"""Reusable: the evidence scan that belongs in the skill scripts.

Earlier scans were written per application and hardcoded a repo list. That
blind spot is how a real Terraform tree under ~/lab/infra was reported as
missing, and how lockfile noise read as MongoDB and Elastic evidence.

This walks every git repo under a root, restricts to files the candidate
actually authored, excludes lockfiles and generated output, and separates a
declared dependency from real usage.

A hit is a CANDIDATE, not proof. Every hit needs reading before it becomes a
CV claim, because substring matches pick up prose and comments. Observed false
positives: "elasticsearch" in a doc proposing its removal, "cypress" in the ATS
scorer's own keyword list, "terraform" in landing-page copy, "elastic" in a
comment naming an example system.

Usage:
    python3 evidence_scan.py --root ~/lab
    python3 evidence_scan.py --root ~/lab --probes mongodb jwt
"""

import argparse
import subprocess
import sys
from pathlib import Path

# Lockfiles and caches carry every transitive dependency and prove nothing.
NOISE_DIRS = ("node_modules", ".next", "dist", "build", ".venv", "venv",
              "__pycache__", ".terraform", "vendor", ".jskills")
NOISE_FILES = ("-lock.yaml", "-lock.json", "package-lock", "yarn.lock",
               "pnpm-lock", "bun.lock", ".min.js", ".map")

# probe -> substrings that indicate real usage in source
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
}

MAX_BYTES = 2_000_000


def git(root: Path, *args):
    return subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True).stdout


def is_noise(rel: str) -> bool:
    low = rel.lower()
    if any(part in low.split("/") for part in NOISE_DIRS):
        return True
    return any(low.endswith(n) or n in low.split("/")[-1] for n in NOISE_FILES)


def authored_files(repo: Path, suffixes):
    """Files the candidate authored, by git log over their extensions."""
    out = git(repo, "log", "--author=Jeziel", "--name-only", "--pretty=format:",
              "--", *suffixes)
    return sorted({r.strip() for r in out.splitlines()
                   if r.strip() and not is_noise(r.strip())})


def scan_repo(repo: Path, probes):
    hits = {}
    suffixes = ("*.ts", "*.tsx", "*.js", "*.jsx", "*.py", "*.json",
                "*.yml", "*.yaml", "*.tf", "*.sql", "*.md", "Dockerfile")
    for rel in authored_files(repo, suffixes):
        path = repo / rel
        try:
            if not path.is_file() or path.stat().st_size > MAX_BYTES:
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


def find_repos(root: Path):
    for gitdir in root.rglob(".git"):
        repo = gitdir.parent if gitdir.is_dir() else gitdir
        if any(part in repo.parts for part in NOISE_DIRS):
            continue
        yield repo


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(Path.home() / "lab"))
    ap.add_argument("--probes", nargs="*", default=None)
    ap.add_argument("--repo", action="append", default=None,
                    help="limit to these repo names")
    args = ap.parse_args()

    probes = PROBES if not args.probes else {
        k: PROBES[k] for k in args.probes if k in PROBES}
    root = Path(args.root).expanduser().resolve()
    limit = set(args.repo or [])

    found = {}
    scanned = 0
    for repo in find_repos(root):
        if limit and repo.name not in limit:
            continue
        scanned += 1
        hits = scan_repo(repo, probes)
        if hits:
            found[str(repo.relative_to(root))] = hits

    print(f"scanned {scanned} authored repos under {root}\n")
    for repo, hits in sorted(found.items()):
        print(f"{repo}")
        for label in sorted(hits):
            print(f"    {label:16} {hits[label]}")

    present = {label for hits in found.values() for label in hits}
    missing = sorted(set(probes) - present)
    print("\nno authored evidence anywhere in the fleet (do NOT claim these):")
    for label in missing:
        print(f"    {label}")


if __name__ == "__main__":
    sys.exit(main())