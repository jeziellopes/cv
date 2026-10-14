"""The evidence helpers: noise filtering, labels, and approval verdicts."""

from pathlib import Path

import pytest

import evidence


def test_backup_repos_are_noise():
    """Backup copies are the same project twice and misreport as evidence."""
    for name in ("agent-runtime-lab-bkp1", "thing-backup", "x-copy", "y-old2",
                 "docs-bkp", "proj-chunk"):
        assert evidence.is_noise_repo(Path("/tmp") / name), name


def test_real_repos_are_not_noise():
    for name in ("protos", "xray", "nomos", "mis-monorepo", "sic"):
        assert not evidence.is_noise_repo(Path("/tmp") / name), name


def test_node_modules_is_noise():
    assert evidence.is_noise_repo(Path("/tmp/repo/node_modules/pkg"))


def test_repo_label_is_relative_to_its_root(tmp_path):
    root = tmp_path / "lab"
    repo = root / "acme" / "protos"
    assert evidence.repo_label(repo, [root]) == "acme/protos"


def test_repo_label_falls_back_to_the_full_path(tmp_path):
    repo = tmp_path / "elsewhere" / "thing"
    assert evidence.repo_label(repo, [tmp_path / "lab"]) == str(repo)


CONFIG = {
    "approved": ["Acme", "jagents"],
    "approved_by_company": {"pavago": ["XRay", "Protos"]},
    "internal": ["XRay", "Protos", "SEAH"],
}


def test_approval_for_global_and_scoped():
    assert evidence.approval_for("jagents", CONFIG) == "approved"
    assert evidence.approval_for("Protos", CONFIG) == "approved for pavago"
    assert evidence.approval_for("Protos", CONFIG, "pavago") == "approved for pavago"


def test_approval_for_masked_and_unlisted():
    assert evidence.approval_for("SEAH", CONFIG) == "masked"
    assert evidence.approval_for("something-else", CONFIG) == "unlisted"


def test_resolve_roots_defaults_to_both_work_roots():
    roots = evidence.resolve_roots(None)
    assert [r.name for r in roots] == ["lab", "work"]


def test_authored_additions_carry_only_the_authors_lines(tmp_path):
    """ADR 0008: the contribution is the diff, so a teammate's added line is
    not evidence, however much the author touched the same file."""
    import subprocess

    repo = tmp_path / "proj"
    repo.mkdir()

    def git(*args):
        return subprocess.run(["git", "-C", str(repo), *args],
                              capture_output=True, text=True).stdout

    git("init", "-q")
    git("config", "user.name", "Author A")
    git("config", "user.email", "a@example.com")
    (repo / "app.py").write_text("import react\n")
    git("add", "-A")
    git("commit", "-q", "-m", "a")

    git("config", "user.name", "Author B")
    git("config", "user.email", "b@example.com")
    with (repo / "app.py").open("a") as f:
        f.write("import lodash\n")
    git("add", "-A")
    git("commit", "-q", "-m", "b")

    additions = evidence.authored_additions(repo, "author a", ("*.py",))
    assert "import react" in additions
    assert "import lodash" not in additions, \
        "B's added line must not read as A's contribution"


def test_authored_additions_reach_unmerged_branches(tmp_path):
    """Work finished on a feature branch is the author's evidence even when it
    was never merged, so the walk must cross branches, not just HEAD."""
    import subprocess

    repo = tmp_path / "proj"
    repo.mkdir()

    def git(*args):
        return subprocess.run(["git", "-C", str(repo), *args],
                              capture_output=True, text=True).stdout

    git("init", "-q")
    git("config", "user.name", "Author A")
    git("config", "user.email", "a@example.com")
    (repo / "app.py").write_text("import react\n")
    git("add", "-A")
    git("commit", "-q", "-m", "a")
    base = git("rev-parse", "--abbrev-ref", "HEAD").strip()

    git("checkout", "-q", "-b", "feature/criteria")
    with (repo / "app.py").open("a") as f:
        f.write("class CriteriaBuilder\n")
    git("add", "-A")
    git("commit", "-q", "-m", "criteria")
    git("checkout", "-q", base)

    additions = evidence.authored_additions(repo, "author a", ("*.py",))
    assert "class CriteriaBuilder" in additions, \
        "a branch-only line must still count as the author's evidence"


def test_resolve_roots_expands_given_paths():
    roots = evidence.resolve_roots(["~/lab"])
    assert len(roots) == 1 and roots[0].name == "lab"


@pytest.mark.parametrize("probe", ["rag", "embeddings", "vector-db"])
def test_ai_probes_are_declared(probe):
    """The BRQ gap showed these were missing from the scanner."""
    assert probe in evidence.PROBES