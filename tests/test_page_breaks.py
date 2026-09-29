"""Page-break CSS: short sections and skill groups must not split across pages."""

import generate
from conftest import GOOD_CV


def html_for_cv(cv):
    return generate.build_html(cv, "classic")


def test_skill_group_avoids_breaking():
    """A skill group cut mid-list reads as a broken document."""
    html = html_for_cv(GOOD_CV)
    start = html.index(".skill-group {")
    line = html[start : html.index("}", start)]
    assert "break-inside: avoid" in line


def test_short_sections_are_keep_together():
    html = html_for_cv(GOOD_CV)
    for heading in ("Education", "Training / Courses", "Skills", "Languages"):
        assert f'class="section keep-together">\n    <h2 class="section-title">{heading}' in html


def test_experience_section_may_break():
    """Experience is long, so it must stay flowable rather than keep-together."""
    html = html_for_cv(GOOD_CV)
    assert 'class="section">\n    <h2 class="section-title">Experience' in html


def test_experience_item_avoids_breaking():
    """A role that fits on a page must not be split mid-block."""
    html = html_for_cv(GOOD_CV)
    assert ".item { padding: 6px 12px; break-inside: avoid; }" in html


def test_role_header_stays_with_its_bullets():
    """Orphaning the org header at a page foot reads as a broken split."""
    html = html_for_cv(GOOD_CV)
    for cls in (".item-org", ".item-role", ".item-meta"):
        start = html.index(cls)
        line = html[start : html.index("}", start)]
        assert "break-after: avoid" in line


def test_bullets_do_not_split_mid_sentence():
    html = html_for_cv(GOOD_CV)
    assert ".bullet-list li { font-family" in html
    start = html.index(".bullet-list li {")
    line = html[start : html.index("}", start)]
    assert "break-inside: avoid" in line
