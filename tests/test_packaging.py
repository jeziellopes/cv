"""Gate: every module the CLI imports must be declared for packaging.

The installed `cv` console script imports generate, which imports its local
siblings. A module that exists in the repo but is missing from py-modules works
in the test suite, which runs from the repo root, and fails only for the
installed entry point. That is exactly how `inbox` shipped broken.
"""

import ast
import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

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


MASTER = {
    "experience": [
        {"org": "Orange", "role": "Founder & Principal Full Stack Engineer",
         "bullets": ["a1", "a2"]},
        {"org": "Other", "role": "Dev", "bullets": ["c1"]},
    ]
}


def test_course_item_renders_an_optional_detail():
    import generate
    from conftest import GOOD_CV

    with_detail = dict(GOOD_CV, courses=[
        {"title": "6.00x: Intro to CS", "institution": "MIT",
         "detail": "algorithms and complexity"}])
    html = generate.build_html(with_detail, "classic")
    assert '<span class="course-detail">algorithms and complexity</span>' in html

    plain = dict(GOOD_CV, courses=[
        {"title": "Técnico", "institution": "Senac"}])
    assert '<span class="course-detail">' not in generate.build_html(plain, "classic")


def test_compose_cv_empty_scope_equals_master():
    import generate
    assert generate.compose_cv(MASTER, {}) == MASTER


def test_compose_cv_applies_the_frame_and_narrows():
    import generate
    out = generate.compose_cv(
        MASTER, {"frame": {"Orange": {"role": "Principal Full Stack Engineer"}}})
    assert out["experience"][0]["role"] == "Principal Full Stack Engineer"
    narrowed = generate.compose_cv(
        MASTER, {"experiences": [{"org": "Other", "bullets": [0]}]})
    assert [e["org"] for e in narrowed["experience"]] == ["Other"]
    assert narrowed["experience"][0]["bullets"] == ["c1"]


def test_compose_cv_refuses_a_scope_that_names_no_master_experience():
    import generate
    with pytest.raises(ValueError, match="unknown experience"):
        generate.compose_cv(MASTER, {"experiences": [{"org": "Never"}]})


def test_compose_cv_overrides_title_and_summary():
    import generate
    out = generate.compose_cv(
        MASTER, {"title": "Analista de TI", "summary": "Suporte e infraestrutura."})
    assert out["personal"]["title"] == "Analista de TI"
    assert out["summary"] == "Suporte e infraestrutura."


def test_compose_cv_orders_duplicate_orgs_by_start():
    import generate
    master = {
        "experience": [
            {"org": "CSP", "role": "Aux.", "start": "02/2011", "bullets": ["b"]},
            {"org": "CSP", "role": "Técnico", "start": "08/2014", "bullets": ["b2"]},
        ],
        "summary": "s", "skills": [],
    }
    scope = {"experiences": [
        {"org": "CSP", "start": "08/2014"},
        {"org": "CSP", "start": "02/2011"},
    ]}
    out = generate.compose_cv(master, scope)
    assert [e["role"] for e in out["experience"]] == ["Técnico", "Aux."]


def test_generate_company_projects_the_master_plus_scope(tmp_path, monkeypatch):
    import generate as g
    monkeypatch.setattr(g, "BASE_DIR", tmp_path)
    monkeypatch.setattr(g.skills, "GAPS_FILE", tmp_path / "gaps.json")
    (tmp_path / "gaps.json").write_text(json.dumps({"evidence": {"React": ["r"]}}))
    (tmp_path / "cv.json").write_text(json.dumps({
        "personal": {"name": "Jo", "title": "Full Stack Software Engineer",
                     "phone": "x", "email": "a@b.co",
                     "linkedin": "https://linkedin.com/in/jo", "location": "Remote"},
        "summary": "s",
        "experience": [
            {"org": "Orange", "role": "Founder & Principal Full Stack Engineer",
             "location": "Remote", "start": "01/2025", "end": "Present",
             "bullets": ["a"]}],
        "education": [], "courses": [],
        "skills": [{"group": "g", "tags": ["React"]}],
        "languages": [],
    }), encoding="utf-8")
    folder = tmp_path / "companies" / "acme"
    folder.mkdir(parents=True)
    (folder / "scope-en.json").write_text(json.dumps(
        {"frame": {"Orange": {"role": "Principal Full Stack Engineer"}}}))
    result = CliRunner().invoke(g.app, ["generate", "--company", "acme", "--lang", "en"])
    assert result.exit_code == 0, result.output
    derived = json.loads((folder / "cv-en.json").read_text(encoding="utf-8"))
    assert derived["experience"][0]["role"] == "Principal Full Stack Engineer"


def test_new_and_translate_are_removed_from_the_cli(tmp_path, monkeypatch):
    """Pruned commands must fail loudly, not silently vanish into the list."""
    import generate as g
    monkeypatch.setattr(g, "BASE_DIR", tmp_path)
    for command in ("new", "translate"):
        result = CliRunner().invoke(g.app, [command])
        assert result.exit_code != 0, command
        assert "No such command" in result.output, command