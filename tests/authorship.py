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
    """Files matching `pattern` that `author` committed and that still exist.

    Matching is case-insensitive because git's own --author is case-sensitive
    and the operator commits under several identities that differ only in case:
    "Jeziel Lopes" and "jeziellopes" share one address. Keying on the name
    exactly once hid a whole project whose commits were all lowercase.

    Intersecting with the working tree matters too: git log reports files that
    were later deleted or renamed, which inflated a skill count from 14 to 15
    and a migration count from 52 to 53. A claim about a project describes what
    is there now.

    An empty author means no filter, so the caller sees every file rather than
    an empty set that would look like an absent repository.
    """
    args = ["git", "-C", str(base), "log"]
    if author:
        args += [f"--author={author}", "-i"]
    args += ["--name-only", "--pretty=format:", "--", pattern]
    out = subprocess.run(args, capture_output=True, text=True).stdout
    return {
        line.strip()
        for line in out.splitlines()
        if line.strip()
        and "node_modules" not in line
        and (base / line.strip()).is_file()
    }


def authored_count(base: Path, pattern: str, author: str = "") -> int:
    return len(authored_files(base, pattern, author))