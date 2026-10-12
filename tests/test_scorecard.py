"""The deterministic scorecard: composition, formulas, and stable --json output."""

import json
from pathlib import Path

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
    """Remove the LinkedIn URL via the fixture, so the two cannot drift apart."""
    text = GOOD_TEXT.replace(GOOD_CV["personal"]["linkedin"], "")
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
    stem = "".join(GOOD_CV["personal"]["name"].split())
    check = ats.score_filename(Path(f"{stem}-en.pdf"))
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


def test_jd_keywords_strip_url_lines():
    jd = ("Vaga: TypeScript\n"
          "https://sttartpay.inhire.app/vagas/cf7c725a?source=linkedin\n"
          "Node.js")
    keywords = ats.jd_keywords(jd)
    for noise in ("vagas", "source", "linkedin", "inhire", "sttartpay", "cf7c725a",
                  "vaga"):
        assert noise not in keywords, f"{noise!r} is a URL fragment or a label"
    assert "typescript" in keywords
    assert "node.js" in keywords


def test_jd_keyword_stats_splits_total_from_kept():
    jd = (
        "https://www.linkedin.com/jobs/view/4471964889/\n\n"
        "Precisamos de TypeScript, Node.js e vivência em meios de pagamento."
    )
    kept, total = ats.jd_keyword_stats(jd)
    for noise in ("precisamos", "pessoa", "uma", "de", "em", "meios",
                  "pagamento"):
        assert noise not in kept, noise
    assert "typescript" in kept and "node.js" in kept
    assert total > len(kept), "function words still count in the pre-filter total"


def test_sentence_openers_and_labels_are_not_demands():
    """A capitalised first word and a section label are prose (ADR 0012)."""
    jd = ("Desired Skills\n"
          "Vivência com metodologias ágeis (SCRUM);\n"
          "Requisitos: Python e PostgreSQL.")
    assert ats.jd_keywords(jd) == ["scrum", "python", "postgresql"]


def test_a_jd_the_filter_cannot_read_is_not_a_free_pass():
    """Coverage nobody measured must not report as 100 (ADR 0012)."""
    jd = "we are looking for someone to join the team soon"
    check, missing = ats.score_tailoring("Python and React.", jd)
    assert check.score == 0
    assert "no demand found" in check.detail
    assert ats.score_tailoring("Python and React.", "")[0].score == 100


def test_role_contract_and_parent_company_words_are_not_demands():
    """ADR 0012: 'Senior Software Engineer' and 'CLT paid in BRL' name a job,
    not a technology, so they never read as demanded skills."""
    jd = ("Senior Software Engineer (Fullstack). This contract is CLT and paid "
          "in BRL. We are part of the Hotmart Company portfolio. Requirements: "
          "JavaScript, TypeScript and React.")
    assert ats.jd_keywords(jd) == ["javascript", "typescript", "react"]
    check, missing = ats.score_tailoring(
        "React, JavaScript and TypeScript for five years.", jd)
    assert check.score == 100
    assert missing == []


def test_tailoring_coverage_ignores_url_and_function_word_noise():
    text = "TypeScript, Node.js e meios de pagamento com Stripe."
    jd = (
        "https://www.linkedin.com/jobs/view/4471964889/\n\n"
        "Precisamos de uma pessoa com TypeScript, Node.js e vivência em "
        "meios de pagamento."
    )
    check, missing = ats.score_tailoring(text, jd)
    assert check.score == 100
    assert missing == []
    for noise in ("precisamos", "pessoa", "vivência", "uma", "com"):
        assert noise not in ats.jd_keywords(jd), noise


def test_alternatives_are_one_demand_and_either_side_covers_it():
    """'Vue.js ou React' is one requirement: React alone satisfies it."""
    jd = "Vue.js ou React e TypeScript."
    assert ats.jd_alternatives(jd) == [["react", "vue.js"]]
    assert ats.jd_demands(jd) == [["react", "vue.js"], ["typescript"]]

    check, missing = ats.score_tailoring(
        "Desenvolvimento com React e TypeScript.", jd)
    assert missing == []
    assert check.score == 100

    # Without either alternative the demand is still unmet, and it is reported
    # once, naming the choice the posting left open.
    check, missing = ats.score_tailoring("TypeScript.", jd)
    assert missing == ["react or vue.js"]
    assert check.score == 50


def test_alternatives_span_lists_and_slash_connectors():
    assert ats.jd_alternatives("Node.js ou Typescript ou Python") == [
        ["node.js", "python", "typescript"]]
    assert ats.jd_alternatives("AWS, Azure ou GCP") == [
        ["aws", "azure", "gcp"]]
    assert ats.jd_alternatives("Windows e/ou Linux") == [["linux", "windows"]]
    assert ats.jd_alternatives("REST, GraphQL and/or gRPC") == [
        ["graphql", "grpc", "rest"]]


def test_a_broken_alternative_run_stays_separate_demands():
    """Prose around a connector must not quietly drop a real requirement."""
    for jd, expected in (("Vivência com Node ou , React", ["node", "react"]),
                          ("Vivência com Node ou ; React", ["node"])):
        assert ats.jd_alternatives(jd) == []
        assert [d[0] for d in ats.jd_demands(jd)] == expected


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