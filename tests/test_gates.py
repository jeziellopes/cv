"""Every format gate G1-G9 has a passing and a failing case."""

import ats
from conftest import GOOD_CV, GOOD_TEXT, make_line, stacked_lines


def test_g1_text_layer_passes_when_enough_chars():
    gate = ats.gate_lines("x" * 500, [])
    assert gate.passed


def test_g1_text_layer_fails_when_too_few_chars():
    gate = ats.gate_lines("x" * 100, [])
    assert not gate.passed


def test_g2_single_column_passes_when_same_row_gap_is_small():
    lines = [
        make_line("Phone", x0=50.0, x1=110.0, y0=0.0, y1=12.0, index=0),
        make_line("Email", x0=118.0, x1=180.0, y0=0.0, y1=12.0, index=1),
        make_line("Next row", x0=50.0, x1=150.0, y0=30.0, y1=42.0, index=2),
    ]
    assert ats.gate_single_column(lines).passed


def test_g2_single_column_passes_when_rows_are_stacked():
    lines = [
        make_line("Left row one", x0=50.0, x1=200.0, y0=0.0, y1=12.0, index=0),
        make_line("Offset row two", x0=300.0, x1=500.0, y0=30.0, y1=42.0, index=1),
    ]
    assert ats.gate_single_column(lines).passed


def test_g2_single_column_fails_on_wide_gap_in_one_visual_row():
    lines = [
        make_line("Left column", x0=50.0, x1=150.0, y0=0.0, y1=50.0, index=0),
        make_line("Right column", x0=300.0, x1=400.0, y0=20.0, y1=70.0, index=1),
    ]
    assert not ats.gate_single_column(lines).passed


def test_g3_reading_order_passes_for_org_role_bullets():
    lines = stacked_lines(["Acme Corp", "Engineer", "Built the platform."])
    cv = {
        "experience": [
            {"org": "Acme Corp", "role": "Engineer", "bullets": ["Built the platform."]}
        ]
    }
    assert ats.gate_reading_order(lines, cv).passed


def test_g3_reading_order_fails_when_role_precedes_org():
    lines = stacked_lines(["Built the platform.", "Acme Corp", "Engineer"])
    cv = {
        "experience": [
            {"org": "Acme Corp", "role": "Engineer", "bullets": ["Built the platform."]}
        ]
    }
    assert not ats.gate_reading_order(lines, cv).passed


def test_g3_reading_order_fails_when_items_break_cv_order():
    lines = stacked_lines(
        ["Beta Corp", "Engineer", "Beta bullet.", "Acme Corp", "Engineer", "Acme bullet."]
    )
    cv = {
        "experience": [
            {"org": "Acme Corp", "role": "Engineer", "bullets": ["Acme bullet."]},
            {"org": "Beta Corp", "role": "Engineer", "bullets": ["Beta bullet."]},
        ]
    }
    assert not ats.gate_reading_order(lines, cv).passed


def test_g4_sections_pass_when_all_present():
    assert ats.gate_sections(GOOD_TEXT).passed


def test_g4_sections_fail_when_one_missing():
    text = GOOD_TEXT.replace("\nLanguages\nEnglish", "\nEnglish")
    assert not ats.gate_sections(text).passed


def test_g5_dates_pass_when_ranges_render():
    cv = {
        "experience": [{"start": "01/2023", "end": "Present"}],
        "education": [{"start": "01/2012", "end": "01/2016"}],
    }
    assert ats.gate_dates(GOOD_TEXT, cv).passed


def test_g5_dates_fail_on_bad_field_format():
    cv = {
        "experience": [{"start": "2023-01", "end": "Present"}],
        "education": [],
    }
    assert not ats.gate_dates(GOOD_TEXT, cv).passed


def test_g5_dates_fail_when_range_not_rendered():
    cv = {
        "experience": [{"start": "05/2020", "end": "06/2020"}],
        "education": [],
    }
    assert not ats.gate_dates(GOOD_TEXT, cv).passed


def test_g6_characters_pass_when_clean():
    assert ats.gate_characters(GOOD_TEXT).passed


def test_g6_characters_fail_on_banned_glyphs():
    assert not ats.gate_characters("clean text\nwith an en \u2013 dash").passed
    assert not ats.gate_characters("zero width \u200b space").passed


def test_g7_contact_passes_with_email_phone_linkedin():
    assert ats.gate_contact(GOOD_TEXT, GOOD_CV).passed


def test_g7_contact_fails_when_linkedin_missing():
    text = GOOD_TEXT.replace(
        "https://www.linkedin.com/in/jezielcarvalho", "linkedin.com"
    )
    assert not ats.gate_contact(text, GOOD_CV).passed


def test_g8_completeness_passes_when_values_present():
    assert ats.gate_completeness(GOOD_TEXT, GOOD_CV).passed


def test_g8_completeness_fails_on_missing_skill():
    cv = {
        **GOOD_CV,
        "skills": [
            {"group": "Core", "tags": ["Python", "Docker", "TypeScript", "Kubernetes"]}
        ],
    }
    assert not ats.gate_completeness(GOOD_TEXT, cv).passed


def test_g9_file_passes_for_small_pdf(tmp_path):
    pdf = tmp_path / "JezielLopesCarvalho-en.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    assert ats.gate_file(pdf).passed


def test_g9_file_fails_for_non_pdf_suffix(tmp_path):
    txt = tmp_path / "cv.txt"
    txt.write_bytes(b"not a pdf")
    assert not ats.gate_file(txt).passed


def test_g9_file_fails_for_oversized_file(tmp_path):
    pdf = tmp_path / "big.pdf"
    pdf.write_bytes(b"x" * (2 * 1024 * 1024))
    assert not ats.gate_file(pdf).passed