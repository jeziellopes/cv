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


def test_classify_separates_gaps_from_claims():
    ledger = {
        "skills": ["React", "DynamoDB", "Scrum"],
        "evidence": {"React": ["r"]},
        "demand": {"DynamoDB": ["acme"], "React": ["acme"]},
    }
    config = {"soft": ["Scrum"]}
    parts = skills.classify(ledger, config)
    assert "DynamoDB" in parts["gaps"]
    assert "React" not in parts["gaps"]
    assert "Scrum" not in parts["gaps"]


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
