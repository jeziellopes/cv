"""The deterministic scorecard: composition, formulas, and stable --json output."""

import json

import ats
from conftest import GOOD_CV, GOOD_LINES, GOOD_TEXT


def cv_with_bullets(bullets):
    return {
        "personal": {"name": "Test Person"},
        "experience": [{"org": "Acme", "role": "Engineer", "bullets": bullets}],
        "education": [],
        "skills": [],
        "languages": [],
    }


def test_quantify_scores_zero_without_numbers():
    check = ats.score_quantify(cv_with_bullets(["Built a thing.", "Shipped a thing."]))
    assert check.score == 0


def test_quantify_reaches_cap_at_forty_percent():
    bullets = ["Built 3 services.", "Shipped a thing.", "Ran 2 migrations.", "Wrote docs.", "Fixed 1 bug."]
    check = ats.score_quantify(cv_with_bullets(bullets))
    assert check.score == 100


def test_repetition_deducts_per_tripled_verb():
    bullets = ["Built one.", "Built two.", "Built three."]
    check = ats.score_repetition(cv_with_bullets(bullets))
    assert check.score == 90


def test_bullet_length_scores_share_in_range():
    bullets = [
        "Short",
        "This bullet has exactly twelve words in it for testing purposes",
        "A" * 400,
    ]
    check = ats.score_bullet_length(cv_with_bullets(bullets))
    assert check.score == 33


def test_essential_sections_full_credit():
    assert ats.score_essential_sections(GOOD_TEXT).score == 100


def test_essential_sections_proportional_when_missing():
    text = GOOD_TEXT.replace("\nSkills\nPython, Docker, TypeScript", "")
    assert ats.score_essential_sections(text).score == 75


def test_contact_information_full_credit():
    assert ats.score_contact_information(GOOD_TEXT).score == 100


def test_contact_information_proportional_when_missing():
    text = GOOD_TEXT.replace("https://www.linkedin.com/in/jezielcarvalho", "")
    assert ats.score_contact_information(text).score == 67


def test_sections_order_full_credit():
    assert ats.score_order(GOOD_TEXT).score == 100


def test_gaps_scale_down_per_gap():
    cv = {
        "experience": [
            {"org": "B", "start": "01/2023", "end": "Present"},
            {"org": "A", "start": "01/2022", "end": "06/2022"},
        ]
    }
    assert ats.score_gaps(cv).score == 75


def test_overlaps_scale_down_per_overlap():
    cv = {
        "experience": [
            {"org": "B", "start": "04/2022", "end": "Present"},
            {"org": "A", "start": "01/2022", "end": "06/2022"},
        ]
    }
    assert ats.score_overlaps(cv).score == 75


def test_tight_transitions_scale_down_per_short_role():
    cv = {
        "experience": [
            {"org": "B", "start": "01/2023", "end": "Present"},
            {"org": "A", "start": "01/2022", "end": "12/2024"},
        ]
    }
    assert ats.score_tight_transitions(cv).score == 90


def test_bias_detects_photo_marker():
    assert ats.score_bias("Please see attached photo.").score == 0
    assert ats.score_bias(GOOD_TEXT).score == 100


def test_skill_evidence_penalises_orphans():
    cv = {
        "experience": [{"org": "A", "role": "R", "bullets": ["Built apps in Python."]}],
        "education": [],
        "skills": [{"group": "G", "tags": ["Python", "Kubernetes"]}],
    }
    check = ats.score_skill_evidence(cv)
    assert check.score == 50


def test_skill_evidence_full_credit_when_all_evidenced():
    cv = {
        "experience": [
            {"org": "A", "role": "R", "bullets": ["Built apps in Python and Kubernetes."]}
        ],
        "education": [],
        "skills": [{"group": "G", "tags": ["Python", "Kubernetes"]}],
    }
    assert ats.score_skill_evidence(cv).score == 100


def test_leadership_scales_with_vocabulary():
    bullets = [
        "Led the platform team.",
        "Managed two engineers.",
        "Owned the delivery roadmap.",
        "Mentored juniors.",
        "Drove the strategy.",
    ]
    assert ats.score_leadership(cv_with_bullets(bullets)).score == 100
    assert ats.score_leadership(cv_with_bullets(["Built a thing."])).score == 0


def test_filename_full_credit_for_first_last():
    check = ats.score_filename(__import__("pathlib").Path("JezielLopesCarvalho-en.pdf"))
    assert check.score == 100


def test_filename_half_credit_otherwise():
    check = ats.score_filename(__import__("pathlib").Path("cv.pdf"))
    assert check.score == 50


def test_tailoring_coverage_counts_present_keywords():
    check, missing = ats.score_tailoring(
        "I know TypeScript and Docker.", "We need TypeScript and Docker skills."
    )
    assert check.score == 100
    assert missing == []


def test_tailoring_coverage_scales_down_for_missing_keywords():
    check, missing = ats.score_tailoring(
        "I know TypeScript.", "We need TypeScript and Docker skills."
    )
    assert check.score == 50
    assert missing == ["docker"]


def test_scorecard_is_deterministic_and_json_stable(good_pdf, mock_extraction):
    report_one = ats.run_checks(good_pdf, cv=GOOD_CV)
    report_two = ats.run_checks(good_pdf, cv=GOOD_CV)
    assert json.dumps(report_one.to_dict(), sort_keys=True) == json.dumps(
        report_two.to_dict(), sort_keys=True
    )


def test_scorecard_report_values_are_asserted(good_pdf, mock_extraction):
    report = ats.run_checks(good_pdf, cv=GOOD_CV)
    data = report.to_dict()
    assert data["gates_passed"] is True
    assert data["overall"] == 75
    assert data["categories"] == {
        "Content": 33,
        "Sections": 100,
        "ATS Essentials": 75,
        "HR Red Flags": 97,
        "Discrimination": 100,
        "Seniority": 44,
    }
    keys = [c["key"] for c in data["checks"]]
    assert "sections.essential" in keys
    assert "sections.contact" in keys
    assert "sections.order" in keys
    assert "ats.gates" in keys
    assert "ats.filename" in keys
    assert "ats.email" not in keys
    assert "ats.links" not in keys
    assert "tailoring.keywords" not in keys


def test_tailoring_category_only_appears_with_jd(good_pdf, mock_extraction):
    report = ats.run_checks(good_pdf, cv=GOOD_CV, jd_text="TypeScript Docker")
    assert report.categories["Tailoring"] == 100
    assert "tailoring.keywords" in [c.key for c in report.checks]
    assert report.overall == 78


def test_ats_gates_check_is_mean_of_gate_scores(tmp_path, monkeypatch):
    pdf = tmp_path / "cv.txt"
    pdf.write_bytes(b"not a pdf")
    monkeypatch.setattr(ats, "extract_pdf_text", lambda path: GOOD_TEXT)
    monkeypatch.setattr(ats, "extract_lines", lambda path: GOOD_LINES)
    report = ats.run_checks(pdf, cv=GOOD_CV)
    gates_check = next(c for c in report.checks if c.key == "ats.gates")
    assert gates_check.score == 89


def test_missing_pdf_reports_g0_and_no_checks(tmp_path):
    report = ats.run_checks(tmp_path / "absent.pdf", cv=GOOD_CV)
    assert report.gates[0].key == "G0"
    assert not report.gates_passed
    assert report.checks == []