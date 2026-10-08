"""The skill ledger: what a repository proves, and what a posting only asks for."""

import json

import pytest
from typer.testing import CliRunner

import generate
import skills


def _cv(*tags: str) -> dict:
    return {"skills": [{"group": "g", "tags": list(tags)}]}


def test_normalize_folds_tags_that_differ_only_in_script():
    assert skills.normalize("JavaScript moderno (ES6+)") == "javascript moderno"
    assert skills.normalize("JavaScript (ES6+)") == "javascript"
    assert skills.normalize("Observabilidade") == "observabilidade"
    assert skills.normalize("React.js") == "react js"


def test_soft_set_is_normalized():
    config = {"soft": ["Clean Code", "Código Limpo"]}
    assert skills.soft_set(config) == {"clean code", "codigo limpo"}


def test_allowed_map_is_normalized():
    config = {"allowed": {"jQuery": "used at Grupo Central"}}
    assert skills.allowed_map(config) == {"jquery": "used at Grupo Central"}


def test_probe_map_prefers_an_override_and_falls_back_to_the_name():
    config = {"probes": {"react": ["from \"react\""]}}
    probes = skills.probe_map(["React", "Cobol"], config)
    assert probes["React"] == ["from \"react\""]
    assert probes["Cobol"] == ["cobol"]


def test_demand_matches_a_skill_to_the_postings_that_ask_for_it(tmp_path):
    one = tmp_path / "acme" / "description.md"
    two = tmp_path / "globex" / "description.md"
    one.parent.mkdir()
    two.parent.mkdir()
    one.write_text("Requisitos: TypeScript e React.")
    two.write_text("Requisitos: Cobol.")

    wanted = skills.demand(["TypeScript", "React", "Cobol"], [one, two])
    assert wanted["React"] == {"acme"}
    assert wanted["Cobol"] == {"globex"}
    assert "TypeScript" in wanted


def test_demand_is_word_bounded_so_a_substring_does_not_match(tmp_path):
    jd = tmp_path / "acme" / "description.md"
    jd.parent.mkdir()
    jd.write_text("We value memória e nada mais.")
    assert skills.demand(["mem"], [jd]) == {}, "mem must not match memória"


def test_unproven_in_flags_an_unevidenced_tag():
    ledger = {"evidence": {"React": ["solitti/protos"]}}
    assert skills.unproven_in(_cv("React", "DynamoDB"), ledger) == ["DynamoDB"]


def test_unproven_in_accepts_soft_and_allowed():
    config = {"soft": ["Scrum"], "allowed": {"jQuery": "verified by hand"}}
    ledger = {"evidence": {"React": ["r"]}}
    assert skills.unproven_in(_cv("React", "Scrum", "jQuery"), ledger, config) == []


def test_unproven_in_matches_a_tag_regardless_of_case_and_accents():
    ledger = {"evidence": {"Cobol": ["r"]}}
    assert skills.unproven_in(_cv("cobol"), ledger) == []


def test_check_reports_one_result_per_cv(tmp_path, monkeypatch):
    folder = tmp_path / "companies" / "acme"
    folder.mkdir(parents=True)
    (folder / "cv-pt.json").write_text(json.dumps(_cv("React", "DynamoDB")))
    monkeypatch.setattr(skills, "ROOT", tmp_path)
    monkeypatch.setattr(skills, "COMPANIES", tmp_path / "companies")

    results = skills.check(ledger={"evidence": {"React": ["r"]}})
    assert len(results) == 1
    assert not results[0]["ok"]
    assert results[0]["problems"] == ["DynamoDB"]


def test_check_without_a_ledger_asks_for_a_refresh():
    results = skills.check(ledger={})
    assert results and "gaps.json" in results[0]["problem"]


def test_cv_paths_skips_backups(tmp_path, monkeypatch):
    folder = tmp_path / "companies" / "acme"
    folder.mkdir(parents=True)
    (folder / "cv-pt.json").write_text("{}")
    (folder / "cv-pt-backup.json").write_text("{}")
    monkeypatch.setattr(skills, "ROOT", tmp_path)
    monkeypatch.setattr(skills, "COMPANIES", tmp_path / "companies")
    assert [p.name for p in skills.cv_paths()] == ["cv-pt.json"]


def test_classify_sends_an_asked_demanded_skill_to_the_operator():
    ledger = {
        "skills": ["React", "DynamoDB", "Scrum"],
        "evidence": {"React": ["r"]},
        "demand": {"DynamoDB": ["acme"], "React": ["acme"]},
    }
    config = {"soft": ["Scrum"]}
    parts = skills.classify(ledger, config)
    # Demand + no evidence + no answer is a question for the operator (ADR 0007),
    # not yet a gap.
    assert "DynamoDB" in parts["needs_answer"]
    assert "DynamoDB" not in parts["gaps"]
    assert "React" not in parts["needs_answer"]
    assert "Scrum" not in parts["needs_answer"]


def test_an_answered_skill_leaves_the_gaps():
    ledger = {"skills": ["Cobol"], "evidence": {}, "allowed": {},
              "demand": {"Cobol": ["acme"]}, "soft": []}
    conf = {"Cobol": {"engagement": "Foodway app"}}
    parts = skills.classify(ledger, confirmations=conf)
    assert "Cobol" in parts["confirmed"]
    assert parts["confirmed"]["Cobol"]["engagement"] == "Foodway app"
    assert "Cobol" not in parts["gaps"]
    assert "Cobol" not in parts["needs_answer"]


def test_a_skill_the_operator_could_not_place_stays_a_gap():
    ledger = {"skills": ["Cobol"], "evidence": {}, "allowed": {},
              "demand": {"Cobol": ["acme"]}, "soft": []}
    conf = {"Cobol": {"engagement": None, "note": "asked, could not place"}}
    parts = skills.classify(ledger, confirmations=conf)
    assert "Cobol" in parts["gaps"]
    assert "Cobol" not in parts["needs_answer"]
    assert "Cobol" not in parts["confirmed"]


def test_unproven_in_accepts_an_operator_confirmation():
    ledger = {"evidence": {}}
    conf = {"Cobol": {"engagement": "Foodway app"}}
    assert skills.unproven_in(_cv("Cobol"), ledger, confirmations=conf) == []


def test_unproven_in_still_flags_a_skill_that_could_not_be_placed():
    conf = {"Cobol": {"engagement": None}}
    assert skills.unproven_in(_cv("Cobol"), {"evidence": {}},
                              confirmations=conf) == ["Cobol"]


def test_pkg_base_reduces_specifiers_and_drops_stdlib():
    assert skills._pkg_base("@scope/a/b") == "@scope/a"
    assert skills._pkg_base("lodash/snakeCase") == "lodash"
    assert skills._pkg_base("react/jsx-runtime") == "react"
    assert skills._pkg_base("./local") == ""
    assert skills._pkg_base("../up") == ""
    assert skills._pkg_base("fs") == "", "node builtins carry no signal"
    assert skills._pkg_base("os") == "", "python stdlib carries no signal"


def test_packages_line_reads_each_language_import():
    js = 'import React from "react"; const q = require("lodash");' \
         ' import "@tanstack/react-query";'
    assert skills._packages_line(js, "app/details.tsx") == {
        "react", "lodash", "@tanstack/react-query"}
    py = "from django.http import JsonResponse\nimport requests\n" \
         "from .local import thing"
    assert skills._packages_line(py, "app/views.py") == {"django", "requests"}
    assert skills._packages_line('import "github.com/gin-gonic/gin"',
                                 "main.go") == {"github.com/gin-gonic/gin"}
    assert skills._packages_line('require "rack"', "app.rb") == {"rack"}


def test_import_evidence_maps_imported_packages_to_skills():
    config = {"mapping": {"TanStack Query": ["@tanstack/react-query"],
                          "Expo": ["expo"]}}
    per_repo = {"employer/app": ["@tanstack/react-query", "expo"],
                "personal/site": ["lodash"]}
    got = skills.import_evidence(config, per_repo=per_repo)
    assert got == {"TanStack Query": ["employer/app"], "Expo": ["employer/app"]}


def test_build_merges_codepath_evidence_with_import_evidence(
        tmp_path, monkeypatch):
    monkeypatch.setattr(skills, "scan_evidence",
                        lambda names, roots=None, author=None: {"React": ["a"]})
    monkeypatch.setattr(skills, "import_evidence",
                        lambda config=None, roots=None, author=None:
                        {"TanStack Query": ["employer/app"]})
    ledger = skills.build(["React", "TanStack Query"])
    assert ledger["evidence"]["React"] == ["a"]
    assert ledger["evidence"]["TanStack Query"] == ["employer/app"]


def test_skillscan_reports_mapped_skills_and_candidates(tmp_path, monkeypatch):
    monkeypatch.setattr(skills, "scan_packages",
                        lambda roots=None, author=None:
                        {"employer/app": ["@tanstack/react-query", "expo", "lodash"],
                         "employer/site": ["lodash", "expo"]})
    monkeypatch.setattr(skills, "CANDIDATES_FILE", tmp_path / "candidates.json")

    result = CliRunner().invoke(skills.skillscan_app, [])
    assert result.exit_code == 0
    assert "TanStack Query" in result.output
    assert "employer/app" in result.output
    assert "lodash" in result.output, "two repos use it, so it is a candidate"
    data = json.loads((tmp_path / "candidates.json").read_text())
    assert "lodash" in data["candidates"]


def test_gaps_answer_records_an_engagement(tmp_path, monkeypatch):
    monkeypatch.setattr(skills, "CONFIRMATIONS_FILE",
                        tmp_path / "confirmations.json")
    result = CliRunner().invoke(skills.app,
                                ["answer", "Cobol", "--engagement", "Foodway app"])
    assert result.exit_code == 0
    data = json.loads((tmp_path / "confirmations.json").read_text())
    assert data["Cobol"]["engagement"] == "Foodway app"


def test_gaps_answer_accepts_could_not_place(tmp_path, monkeypatch):
    monkeypatch.setattr(skills, "CONFIRMATIONS_FILE",
                        tmp_path / "confirmations.json")
    result = CliRunner().invoke(skills.app,
                                ["answer", "Cobol", "--could-not-place"])
    assert result.exit_code == 0
    data = json.loads((tmp_path / "confirmations.json").read_text())
    assert data["Cobol"]["engagement"] is None
    assert "stays a gap" in result.output


def test_gaps_answer_requires_one_flag(tmp_path, monkeypatch):
    monkeypatch.setattr(skills, "CONFIRMATIONS_FILE",
                        tmp_path / "confirmations.json")
    result = CliRunner().invoke(skills.app, ["answer", "Cobol"])
    assert result.exit_code == 2


def test_generate_refuses_a_cv_that_claims_an_unproven_skill(tmp_path, monkeypatch):
    folder = tmp_path / "companies" / "acme"
    folder.mkdir(parents=True)
    (folder / "cv-pt.json").write_text(json.dumps(_cv("DynamoDB")))

    ledger = tmp_path / "gaps.json"
    ledger.write_text(json.dumps({"evidence": {"React": ["r"]}}))

    monkeypatch.setattr(generate, "BASE_DIR", tmp_path)
    monkeypatch.setattr(skills, "GAPS_FILE", ledger)
    monkeypatch.setattr(skills, "ROOT", tmp_path)
    monkeypatch.setattr(skills, "COMPANIES", tmp_path / "companies")

    result = CliRunner().invoke(
        generate.app, ["generate", "--company", "acme", "--lang", "pt"])
    assert result.exit_code == 1
    assert "refusing" in result.output
    assert not (folder / "index.html").exists(), "no HTML on a refused CV"


def test_generate_writes_when_every_claim_is_proven(tmp_path, monkeypatch):
    folder = tmp_path / "companies" / "acme"
    folder.mkdir(parents=True)
    (folder / "cv-pt.json").write_text(json.dumps({
        "personal": {"name": "Test Person", "title": "Engineer", "phone": "+55",
                     "email": "a@b.co", "linkedin": "https://linkedin.com/in/x",
                     "portfolio": "https://x.dev", "github": "https://github.com/x",
                     "location": "Remote"},
        "summary": "s",
        "experience": [],
        "education": [],
        "courses": [],
        "skills": [{"group": "g", "tags": ["React"]}],
        "languages": [],
    }))

    ledger = tmp_path / "gaps.json"
    ledger.write_text(json.dumps({"evidence": {"React": ["r"]}}))

    monkeypatch.setattr(generate, "BASE_DIR", tmp_path)
    monkeypatch.setattr(skills, "GAPS_FILE", ledger)
    monkeypatch.setattr(skills, "ROOT", tmp_path)
    monkeypatch.setattr(skills, "COMPANIES", tmp_path / "companies")

    result = CliRunner().invoke(
        generate.app, ["generate", "--company", "acme", "--lang", "pt"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "index.html").exists(), "render writes to BASE_DIR"


@pytest.mark.parametrize("tag", ["DynamoDB", "APIGEE"])
def test_a_known_gap_is_recognised_as_unproven(tag):
    assert skills.unproven_in(_cv(tag), {"evidence": {}}) == [tag]


def test_short_needles_are_word_bounded():
    # "ecs" inside "specs" and "aws" inside "laws" cost the first ledger
    # hundreds of phantom repos, including 66 for ECS alone.
    assert not skills._matches("ecs", "see the specs for details")
    assert not skills._matches("aws", "laws and flaws")
    assert skills._matches("ecs", "the ecs cluster")
    assert skills._matches("aws", "deployed on aws")


def test_code_pattern_needles_stay_substring():
    assert skills._matches("@aws-sdk", 'deps: "@aws-sdk/client-s3"')
    assert skills._matches('from "react"', "import x from \"react\";")


@pytest.mark.parametrize("rel", ["src/app.tsx", "svc/main.py", "infra/main.tf",
                                 "deploy/lambda.tf", "ci.yml"])
def test_source_files_can_evidence_usage(rel):
    assert skills._is_usage_file(rel)


@pytest.mark.parametrize("rel", ["docs/spec.md", "package.json", "pnpm-lock.yaml",
                                 "docs/specs/0007-storage.md"])
def test_prose_manifests_and_locks_cannot(rel):
    # A dependency declared in a manifest, or an option discussed in a spec, is
    # not evidence that the operator built with it.
    assert not skills._is_usage_file(rel)


def test_cv_gaps_reports_a_capture_whose_cv_claims_an_unproven_skill(
        tmp_path, monkeypatch):
    import inbox

    folder = tmp_path / "companies" / "acme"
    folder.mkdir(parents=True)
    (folder / "cv-pt.json").write_text(json.dumps(_cv("React", "DynamoDB")))
    ledger = tmp_path / "gaps.json"
    ledger.write_text(json.dumps({"evidence": {"React": ["r"]}}))

    monkeypatch.setattr(skills, "GAPS_FILE", ledger)
    monkeypatch.setattr(inbox, "BASE_DIR", tmp_path)

    assert inbox.cv_gaps("acme") == {"cv-pt.json": ["DynamoDB"]}


def test_cv_gaps_is_none_without_a_ledger(tmp_path, monkeypatch):
    import inbox

    monkeypatch.setattr(skills, "GAPS_FILE", tmp_path / "missing.json")
    monkeypatch.setattr(inbox, "BASE_DIR", tmp_path)

    assert inbox.cv_gaps("acme") is None, "absent ledger is unknown, not clean"


def test_cv_gaps_is_empty_for_a_clean_cv(tmp_path, monkeypatch):
    import inbox

    folder = tmp_path / "companies" / "acme"
    folder.mkdir(parents=True)
    (folder / "cv-pt.json").write_text(json.dumps(_cv("React")))
    ledger = tmp_path / "gaps.json"
    ledger.write_text(json.dumps({"evidence": {"React": ["r"]}}))

    monkeypatch.setattr(skills, "GAPS_FILE", ledger)
    monkeypatch.setattr(inbox, "BASE_DIR", tmp_path)

    assert inbox.cv_gaps("acme") == {}
