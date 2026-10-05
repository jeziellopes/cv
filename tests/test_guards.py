"""The honesty guards: claim verification, naming checks, approvals."""

import json

import guards


def test_approve_name_records_and_backfills_internal(tmp_path):
    path = tmp_path / "project-names.json"
    path.write_text("{}")
    guards.approve_name("acme", "Protos", path=path)

    config = json.loads(path.read_text())
    assert config["approved_by_company"]["acme"] == ["Protos"]
    assert "Protos" in config["internal"], "an approved name must still be known"


def test_approve_name_is_idempotent(tmp_path):
    path = tmp_path / "project-names.json"
    path.write_text("{}")
    guards.approve_name("acme", "Protos", path=path)
    guards.approve_name("acme", "Protos", path=path)
    assert json.loads(path.read_text())["approved_by_company"]["acme"] == ["Protos"]


def test_check_names_flags_an_unapproved_name(tmp_path, monkeypatch):
    companies = tmp_path / "companies" / "acme"
    companies.mkdir(parents=True)
    (companies / "cv-pt.json").write_text(json.dumps({"x": "we use Protos"}))
    (companies / "question.md").write_text("We use Protos in production.")

    monkeypatch.setattr(guards, "ROOT", tmp_path)
    monkeypatch.setattr(guards, "COMPANIES", tmp_path / "companies")
    config = {"approved": [], "approved_by_company": {}, "internal": ["Protos"]}

    results = guards.check_names(config)
    assert len(results) == 2
    assert all(not r["ok"] for r in results)
    assert all("Protos" in r["leaked"] for r in results)


def test_check_names_passes_when_approved_for_that_company(tmp_path, monkeypatch):
    folder = tmp_path / "companies" / "acme"
    folder.mkdir(parents=True)
    (folder / "cv-pt.json").write_text(json.dumps({"x": "we use Protos"}))

    monkeypatch.setattr(guards, "ROOT", tmp_path)
    monkeypatch.setattr(guards, "COMPANIES", tmp_path / "companies")
    config = {"approved": [], "approved_by_company": {"acme": ["Protos"]},
              "internal": ["Protos"]}

    assert all(r["ok"] for r in guards.check_names(config))


def test_general_cvs_share_one_key(tmp_path, monkeypatch):
    (tmp_path / "cv.json").write_text("{}")
    monkeypatch.setattr(guards, "ROOT", tmp_path)
    assert guards.company_of(tmp_path / "cv.json") == guards.GENERAL_KEY


def test_verify_claims_reports_a_missing_cv(tmp_path, monkeypatch):
    monkeypatch.setattr(guards, "ROOT", tmp_path)
    monkeypatch.setattr(guards, "COMPANIES", tmp_path / "companies")
    config = {"figures": {"acme": [{"phrase": "1 file", "repo": "demo",
                                    "glob": "*.ts", "expect": 1}]}}
    results = guards.verify_claims(config)
    assert len(results) == 1
    assert results[0]["ok"] is False
    assert "no CV" in results[0]["problem"]


def test_verify_claims_flags_a_phrase_the_cv_lacks(tmp_path, monkeypatch):
    folder = tmp_path / "companies" / "acme"
    folder.mkdir(parents=True)
    (folder / "cv-pt.json").write_text(json.dumps({"summary": "no numbers here"}))

    monkeypatch.setattr(guards, "ROOT", tmp_path)
    monkeypatch.setattr(guards, "COMPANIES", tmp_path / "companies")
    config = {"figures": {"acme": [{"phrase": "99 files", "repo": "demo",
                                    "glob": "*.ts", "expect": 99}]}}
    results = guards.verify_claims(config)
    assert results[0]["ok"] is False
    assert "does not contain" in results[0]["problem"]