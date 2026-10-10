"""Gate: every module the CLI imports must be declared for packaging.

The installed `cv` console script imports generate, which imports its local
siblings. A module that exists in the repo but is missing from py-modules works
in the test suite, which runs from the repo root, and fails only for the
installed entry point. That is exactly how `inbox` shipped broken.
"""

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def declared_modules() -> set[str]:
    text = (ROOT / "pyproject.toml").read_text()
    match = re.search(r"py-modules\s*=\s*\[(.*?)\]", text, re.S)
    assert match, "pyproject.toml has no py-modules list"
    return set(re.findall(r'"([^"]+)"', match.group(1)))


def local_imports(path: Path) -> set[str]:
    """Top-level names imported by a module that are files beside it."""
    tree = ast.parse(path.read_text())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    siblings = {p.stem for p in ROOT.glob("*.py")}
    return names & siblings


def test_py_modules_list_exists():
    assert declared_modules(), "py-modules is empty"


def test_declared_modules_all_exist():
    missing = [m for m in declared_modules() if not (ROOT / f"{m}.py").is_file()]
    assert not missing, f"declared but absent: {missing}"


@pytest.mark.parametrize("entry", ["generate.py"])
def test_entry_point_imports_are_all_declared(entry):
    """Anything the CLI imports must be installed alongside it."""
    needed = local_imports(ROOT / entry)
    undeclared = sorted(needed - declared_modules())
    assert not undeclared, (
        f"{entry} imports {undeclared}, which py-modules does not declare. "
        "The suite runs from the repo root, so this only breaks the installed "
        "console script."
    )


def test_transitively_declared():
    """A declared module's own local imports must be declared too."""
    declared = declared_modules()
    for module in sorted(declared):
        path = ROOT / f"{module}.py"
        if not path.is_file():
            continue
        undeclared = sorted(local_imports(path) - declared)
        assert not undeclared, f"{module}.py imports undeclared {undeclared}"


def test_orange_theme_is_the_default_generate():
    import generate
    assert generate.DEFAULT_THEME == "orange"
    assert "orange" in generate.THEMES


def test_orange_theme_is_classic_with_an_orange_line():
    import generate
    classic = generate.THEMES["classic"]
    orange = generate.THEMES["orange"]
    assert orange["fonts_url"] == classic["fonts_url"]
    assert "#ff4c00" in orange["css_vars"]          # orange border
    assert "--color-text:   #000000" in orange["css_vars"]  # black text
    assert "--color-accent: #000000" in orange["css_vars"]  # no orange text


def test_orange_theme_builds_css():
    import generate
    css = generate.build_css("orange")
    assert "#ff4c00" in css
    assert "Volkhov" in css