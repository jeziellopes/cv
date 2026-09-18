"""CLI behaviour for ats-check: --jd, --judge, --json, exit codes, strict mode."""

import json
import subprocess

import ats
import generate
from conftest import GOOD_CV, GOOD_LINES, GOOD_TEXT
from typer.testing import CliRunner

runner = CliRunner()


def _fake_report(gates_ok=True, overall=90):
    gates = [
        ats.Check(f"G{i}", "ATS Essentials", f"Gate {i}", 100 if gates_ok else 0, "", gate=True)
        for i in range(1, 10)
    ]
    checks = [
        ats.Check("content.quantify", "Content", "Quantify impact", overall),
        ats.Check("sections.essential", "Sections", "Essential sections", overall),
        ats.Check("sections.contact", "Sections", "Contact information", overall),
        ats.Check("sections.order", "Sections", "Sections order", overall),
        ats.Check("ats.gates", "ATS Essentials", "Format gates", overall),
        ats.Check("ats.filename", "ATS Essentials", "File name", overall),
        ats.Check("hr.gaps", "HR Red Flags", "Employment gaps", overall),
        ats.Check("hr.overlaps", "HR Red Flags", "Overlapping roles", overall),
        ats.Check("hr.transitions", "HR Red Flags", "Tight transitions", overall),
        ats.Check("discrimination.bias", "Discrimination", "Bias signals", overall),
        ats.Check("seniority.skills", "Seniority", "Skill evidence", overall),
        ats.Check("seniority.leadership", "Seniority", "Leadership signals", overall),
    ]
    return ats.AtsReport(gates=gates, checks=checks)


def _mock_run(monkeypatch, report):
    monkeypatch.setattr(ats, "extract_pdf_text", lambda path: GOOD_TEXT)
    monkeypatch.setattr(ats, "extract_lines", lambda path: GOOD_LINES)
    monkeypatch.setattr(ats, "run_checks", lambda pdf, cv=None, jd_text="": report)


def _write_fixtures(tmp_path):
    pdf = tmp_path / "cv.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    cv = tmp_path / "cv.json"
    cv.write_text(json.dumps(GOOD_CV), encoding="utf-8")
    return pdf, cv


def test_jd_accepts_local_file(tmp_path, monkeypatch):
    pdf, cv = _write_fixtures(tmp_path)
    jd = tmp_path / "jd.txt"
    jd.write_text("TypeScript Docker", encoding="utf-8")
    report = _fake_report()
    report.checks.append(ats.Check("tailoring.keywords", "Tailoring", "Keyword coverage", 100))
    monkeypatch.setattr(ats, "run_checks", lambda pdf, cv=None, jd_text="": report)
    monkeypatch.setattr(ats, "extract_pdf_text", lambda path: GOOD_TEXT)
    result = runner.invoke(
        generate.app,
        ["ats-check", "--pdf", str(pdf), "--cv", str(cv), "--jd", str(jd), "--json"],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["categories"]["Tailoring"] == 100


def test_fetch_jd_reads_local_file(tmp_path):
    jd = tmp_path / "jd.md"
    jd.write_text("Backend Engineer role", encoding="utf-8")
    assert ats.fetch_jd(str(jd)) == "Backend Engineer role"


def test_fetch_jd_fetches_url_and_strips_html(monkeypatch):
    class FakeResponse:
        def read(self):
            return b"<html><body><h1>Backend Engineer</h1><p>TypeScript role</p></body></html>"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(
        ats.urllib.request,
        "urlopen",
        lambda url, timeout=15: FakeResponse(),
    )
    text = ats.fetch_jd("https://example.com/job")
    assert "Backend Engineer" in text
    assert "<h1>" not in text


def test_jd_accepts_http_url_in_cli(tmp_path, monkeypatch):
    pdf, cv = _write_fixtures(tmp_path)
    report = _fake_report()
    report.checks.append(ats.Check("tailoring.keywords", "Tailoring", "Keyword coverage", 100))
    monkeypatch.setattr(ats, "run_checks", lambda pdf, cv=None, jd_text="": report)
    monkeypatch.setattr(ats, "extract_pdf_text", lambda path: GOOD_TEXT)

    class FakeResponse:
        def read(self):
            return b"<p>TypeScript Docker</p>"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(ats.urllib.request, "urlopen", lambda url, timeout=15: FakeResponse())
    result = runner.invoke(
        generate.app,
        ["ats-check", "--pdf", str(pdf), "--cv", str(cv), "--jd", "https://example.com/job", "--json"],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["categories"]["Tailoring"] == 100


def test_judge_runs_only_when_requested(tmp_path, monkeypatch):
    pdf, cv = _write_fixtures(tmp_path)
    calls = []
    monkeypatch.setattr(ats, "extract_pdf_text", lambda path: GOOD_TEXT)
    monkeypatch.setattr(ats, "run_judge", lambda cmd, text, jd: calls.append(cmd) or "judged")
    monkeypatch.setattr(ats, "run_checks", lambda pdf, cv=None, jd_text="": _fake_report())

    result = runner.invoke(generate.app, ["ats-check", "--pdf", str(pdf), "--cv", str(cv)])
    assert result.exit_code == 0
    assert calls == []

    result = runner.invoke(
        generate.app,
        ["ats-check", "--pdf", str(pdf), "--cv", str(cv), "--judge", "--judge-cmd", "fake", "--json"],
    )
    assert result.exit_code == 0, result.output
    assert calls == ["fake"]
    assert json.loads(result.output)["judge"] == "judged"


def test_run_judge_feeds_prompt_to_mocked_command(monkeypatch):
    captured = {}

    class FakeProc:
        returncode = 0
        stdout = "mock judge verdict"
        stderr = ""

    def fake_run(command, input, capture_output, text, timeout, check):
        captured["command"] = command
        captured["input"] = input
        return FakeProc()

    monkeypatch.setattr(subprocess, "run", fake_run)
    output = ats.run_judge("claude -p", "resume text", "jd text")
    assert output == "mock judge verdict"
    assert captured["command"] == ["claude", "-p"]
    assert "RESUME:" in captured["input"]
    assert "JOB DESCRIPTION:" in captured["input"]


def test_default_run_never_invokes_llm(tmp_path, monkeypatch):
    pdf, cv = _write_fixtures(tmp_path)
    monkeypatch.setattr(ats, "run_checks", lambda pdf, cv=None, jd_text="": _fake_report())
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("LLM invoked")))
    result = runner.invoke(generate.app, ["ats-check", "--pdf", str(pdf), "--cv", str(cv)])
    assert result.exit_code == 0


def test_json_output_is_stable_across_runs(tmp_path, monkeypatch):
    pdf, cv = _write_fixtures(tmp_path)
    monkeypatch.setattr(ats, "run_checks", lambda pdf, cv=None, jd_text="": _fake_report())
    args = ["ats-check", "--pdf", str(pdf), "--cv", str(cv), "--json"]
    first = runner.invoke(generate.app, args)
    second = runner.invoke(generate.app, args)
    assert first.exit_code == 0
    assert first.output == second.output
    data = json.loads(first.output)
    assert set(data.keys()) == {
        "gates_passed", "gates", "categories", "overall", "missing_keywords", "judge", "checks",
    }


def test_failed_gate_exits_one(tmp_path, monkeypatch):
    pdf, cv = _write_fixtures(tmp_path)
    monkeypatch.setattr(ats, "run_checks", lambda pdf, cv=None, jd_text="": _fake_report(gates_ok=False))
    result = runner.invoke(generate.app, ["ats-check", "--pdf", str(pdf), "--cv", str(cv)])
    assert result.exit_code == 1


def test_strict_exits_when_overall_below_default_min_score(tmp_path, monkeypatch):
    pdf, cv = _write_fixtures(tmp_path)
    monkeypatch.setattr(ats, "run_checks", lambda pdf, cv=None, jd_text="": _fake_report(overall=85))
    result = runner.invoke(generate.app, ["ats-check", "--pdf", str(pdf), "--cv", str(cv), "--strict"])
    assert result.exit_code == 1
    assert "85" in result.output


def test_strict_passes_at_or_above_min_score(tmp_path, monkeypatch):
    pdf, cv = _write_fixtures(tmp_path)
    monkeypatch.setattr(ats, "run_checks", lambda pdf, cv=None, jd_text="": _fake_report(overall=90))
    result = runner.invoke(generate.app, ["ats-check", "--pdf", str(pdf), "--cv", str(cv), "--strict"])
    assert result.exit_code == 0


def test_strict_exits_when_jd_coverage_below_floor(tmp_path, monkeypatch):
    pdf, cv = _write_fixtures(tmp_path)
    report = _fake_report(overall=95)
    report.checks.append(ats.Check("tailoring.keywords", "Tailoring", "Keyword coverage", 50))
    monkeypatch.setattr(ats, "run_checks", lambda pdf, cv=None, jd_text="": report)
    monkeypatch.setattr(ats, "fetch_jd", lambda source: "TypeScript Docker")
    result = runner.invoke(
        generate.app,
        ["ats-check", "--pdf", str(pdf), "--cv", str(cv), "--jd", "jd.txt", "--strict"],
    )
    assert result.exit_code == 1