"""Staleness by fingerprint: data, renderer, and the checks themselves."""

import json
from pathlib import Path

import staleness


def make_cv(folder: Path, name: str, lang: str = "en") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / f"cv-{lang}.json"
    p.write_text(json.dumps({"personal": {"name": name}}))
    return p


def make_pdf(folder: Path, stem: str, lang: str = "en") -> Path:
    p = folder / f"{stem}-{lang}.pdf"
    p.write_bytes(b"%PDF-1.4 fake")
    return p


def build(tmp_path, name="Ada Lovelace", lang="en") -> Path:
    """A CV with a PDF and a matching build record, as generate leaves it."""
    folder = tmp_path / "companies" / "acme"
    cv = make_cv(folder, name, lang)
    make_pdf(folder, staleness.stem_of(cv), lang)
    staleness.write_stamp(tmp_path, cv, lang)
    return cv


def test_a_missing_pdf_is_stale(tmp_path):
    make_cv(tmp_path / "companies" / "acme", "Ada Lovelace")
    found = staleness.find_stale(tmp_path)
    assert [s.label for s in found] == ["acme"]
    assert found[0].reason == "no PDF"


def test_a_pdf_with_no_build_record_is_stale(tmp_path):
    """Anything built before the stamp existed must be reported, not assumed."""
    folder = tmp_path / "companies" / "acme"
    cv = make_cv(folder, "Ada Lovelace")
    make_pdf(folder, staleness.stem_of(cv))
    found = staleness.find_stale(tmp_path)
    assert found and found[0].reason == "no build record"


def test_a_fresh_build_is_not_stale(tmp_path):
    build(tmp_path)
    assert staleness.find_stale(tmp_path) == []


def test_changed_cv_data_is_stale(tmp_path):
    cv = build(tmp_path)
    data = json.loads(cv.read_text())
    data["summary"] = "edited"
    cv.write_text(json.dumps(data))
    found = staleness.find_stale(tmp_path)
    assert found and found[0].reason == "CV data changed"


def test_a_changed_renderer_is_stale(tmp_path):
    build(tmp_path)
    (tmp_path / "generate.py").write_text("# renderer changed")
    found = staleness.find_stale(tmp_path)
    assert found and found[0].reason == "renderer changed"


def test_a_new_check_marks_old_pdfs_stale(tmp_path):
    """The case timestamps cannot see: a rule that did not exist at build time."""
    build(tmp_path)
    assert staleness.find_stale(tmp_path) == []

    (tmp_path / "ats.py").write_text("# a new rule")
    found = staleness.find_stale(tmp_path)
    assert found, "adding a check must invalidate PDFs built before it"
    assert found[0].reason == "checks changed since this was built"


def test_every_rule_file_is_watched(tmp_path):
    for name in staleness.RULE_FILES:
        folder = tmp_path / "companies" / "acme"
        if folder.exists():
            import shutil

            shutil.rmtree(folder)
        build(tmp_path)
        (tmp_path / name).write_text(f"# {name}")
        assert staleness.find_stale(tmp_path), f"{name} is not watched"


def test_the_stem_comes_from_the_cv_name(tmp_path):
    cv = make_cv(tmp_path / "companies" / "acme", "João Gonçalves")
    assert staleness.stem_of(cv) == "JoaoGoncalves"


def test_a_broken_cv_does_not_crash(tmp_path):
    folder = tmp_path / "companies" / "acme"
    folder.mkdir(parents=True)
    bad = folder / "cv-en.json"
    bad.write_text("{ not json")
    assert staleness.stem_of(bad) == "cv"
    assert staleness.find_stale(tmp_path)


def test_nested_company_labels(tmp_path):
    folder = tmp_path / "companies" / "bairesdev" / "ai-native"
    make_cv(folder, "Ada Lovelace")
    assert staleness.find_stale(tmp_path)[0].label == "bairesdev/ai-native"


def test_the_general_cv_is_covered(tmp_path):
    (tmp_path / "cv.json").write_text(
        json.dumps({"personal": {"name": "Ada Lovelace"}}))
    assert [s.label for s in staleness.find_stale(tmp_path)] == ["cv.json"]


def test_language_filter(tmp_path):
    make_cv(tmp_path / "companies" / "acme", "Ada Lovelace", "pt")
    assert staleness.find_stale(tmp_path, ("en",)) == []
    assert staleness.find_stale(tmp_path, ("pt",))


def test_lang_is_read_from_the_filename(tmp_path):
    assert staleness.lang_of(tmp_path / "cv-pt.json") == "pt"
    assert staleness.lang_of(tmp_path / "cv.json") == "en"