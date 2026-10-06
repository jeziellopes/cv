"""The LinkedIn source: reading its cards, and fetching a description."""

import pytest

import search


CARD_HTML = """
<li>
  <div class="base-card base-search-card job-search-card"
       data-entity-urn="urn:li:jobPosting:4474601740">
    <a class="base-card__full-link"
       href="https://www.linkedin.com/jobs/view/frontend-engineer-at-evlo-ai-4474601740?position=1&amp;pageNum=0">
      <h3 class="base-search-card__title">Frontend Engineer</h3>
      <h4 class="base-search-card__subtitle">
        <a class="hidden-nested-link" href="https://www.linkedin.com/company/evlo-ai">Evlo AI</a>
      </h4>
      <span class="job-search-card__location">San Francisco, CA</span>
      <time class="job-search-card__listdate" datetime="2026-10-02">2 weeks ago</time>
    </a>
  </div>
</li>
"""

DETAIL_HTML = """
<div class="show-more-less-html__markup show-more-less-html__markup--clamp-after-5">
  <p>We build <strong>tools</strong>.</p>
  <ul><li>React</li><li>TypeScript &amp; Node</li></ul>
</div>
<div class="other">Trailing chrome</div>
"""


def test_linkedin_reads_the_id_from_the_card_urn():
    assert search._linkedin_id(
        "https://www.linkedin.com/jobs/view/frontend-engineer-at-evlo-ai-4474601740/?x=1"
    ) == "4474601740"
    assert search._linkedin_id(
        "https://www.linkedin.com/jobs/view/4474601740/") == "4474601740"
    assert search._linkedin_id("https://example.com/jobs/view/none") == ""


def test_linkedin_parses_a_card_whose_href_carries_a_slug(monkeypatch):
    """The href no longer starts with digits, which is how the source broke."""
    monkeypatch.setattr(search, "_get_text", lambda url, timeout=20: CARD_HTML)
    jobs = search._linkedin("frontend", 5)
    assert len(jobs) == 1
    job = jobs[0]
    assert job.title == "Frontend Engineer"
    assert job.company == "Evlo AI"
    assert job.location == "San Francisco, CA"
    assert job.url == "https://www.linkedin.com/jobs/view/4474601740/"
    assert job.description == ""
    assert job.posted == "2026-10-02"


def test_linkedin_applies_the_verified_filters(monkeypatch):
    seen = {}

    def fake(url, timeout=20):
        seen["url"] = url
        return "<html></html>"

    monkeypatch.setattr(search, "_get_text", fake)
    search._linkedin("react", 5, since="week", location="Brazil", remote=True)
    assert "f_TPR=r604800" in seen["url"]
    assert "location=Brazil" in seen["url"]
    assert "f_WT=2" in seen["url"]


def test_linkedin_rejects_an_unknown_since():
    with pytest.raises(ValueError):
        search._linkedin("react", 5, since="year")


def test_linkedin_stops_once_the_cap_is_met(monkeypatch):
    """The cap is met on page one, so no second request is made."""
    calls = []

    def fake(url, timeout=20):
        calls.append(url)
        return CARD_HTML

    monkeypatch.setattr(search, "_get_text", fake)
    jobs = search._linkedin("frontend", 1)
    assert len(jobs) == 1
    assert len(calls) == 1


def test_the_detail_body_is_text_with_its_blocks_kept(monkeypatch):
    monkeypatch.setattr(search, "_get_text", lambda url, timeout=20: DETAIL_HTML)
    body = search._linkedin_detail(
        search.Job("Frontend Engineer", "Evlo AI", "", 
                   "https://www.linkedin.com/jobs/view/4474601740/", "", "linkedin"))
    assert "We build tools." in body
    assert "TypeScript & Node" in body, "the entity was not unescaped"
    assert "<" not in body
    assert "Trailing chrome" not in body
    assert "\n" in body, "the block structure was flattened"


def test_add_details_fills_only_what_it_can(monkeypatch):
    def fake(job):
        if "broken" in job.url:
            raise OSError("blocked")
        return "a description"

    monkeypatch.setitem(search.DETAILS, "linkedin", fake)
    ranked = [
        search.Ranked(search.Job("A", "X", "", "https://x/1", "", "linkedin"), 10),
        search.Ranked(search.Job("B", "X", "", "https://x/broken", "", "linkedin"), 9),
        search.Ranked(search.Job("C", "X", "", "https://x/3", "already", "linkedin"), 8),
    ]
    filled, failed = search.add_details(ranked)
    assert (filled, failed) == (1, 1)
    assert ranked[0].job.description == "a description"
    assert ranked[2].job.description == "already", "an existing body was refetched"


def test_add_details_ignores_a_source_with_no_fetcher():
    ranked = [search.Ranked(search.Job("A", "X", "", "https://x/1", "", "remotive"), 10)]
    assert search.add_details(ranked) == (0, 0)