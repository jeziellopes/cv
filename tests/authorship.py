"""Shared: whose authored files to count.

The author filter is configuration, not a literal. Hardcoding a person's name
in a published script both personalises the repository and breaks for anyone
else running it.
"""

import subprocess
from pathlib import Path


def default_author() -> str:
    """The git identity configured for this repository, else the global one."""
    for args in (["config", "user.name"], ["config", "--global", "user.name"]):
        out = subprocess.run(["git", *args], capture_output=True, text=True).stdout.strip()
        if out:
            return out
    return ""


def authored_files(base: Path, pattern: str, author: str = "") -> set[str]:
    """Files in `base` matching `pattern` that `author` committed.

    An empty author means no filter, so the caller sees every file rather than
    an empty set that would look like an absent repository.
    """
    args = ["git", "-C", str(base), "log"]
    if author:
        args.append(f"--author={author}")
    args += ["--name-only", "--pretty=format:", "--", pattern]
    out = subprocess.run(args, capture_output=True, text=True).stdout
    return {
        line.strip()
        for line in out.splitlines()
        if line.strip() and "node_modules" not in line
    }


def authored_count(base: Path, pattern: str, author: str = "") -> int:
    return len(authored_files(base, pattern, author))