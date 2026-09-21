import json

import pytest
from typer.testing import CliRunner

import generate
import search as searchmod


FAKE_REMOTIVE = {
    "job-count": 2,
    "jobs": [
        {
            "title": "Senior React Engineer",
            "company_name": "Acme",
            "candidate_required_location": "Remote",
            "url": "https://remotive.com/1",
            "description": "React, TypeScript, Next.js, and automated testing with Jest.",
            "tags": ["react", "typescript"],
        },
        {
            "title": "Python Data Scientist",
            "company_name": "Otherco",
            "candidate_required_location": "Remote",
            "url": "https://remotive.com/2",
            "description": "Python, Pandas, and machine learning pipelines.",
            "tags": ["python"],
        },
    ],
}

FAKE_REMOTEOK = [
    {"_type": "marker"},
    {
        "position": "Senior React Frontend Developer",
        "company": "Corp",
        "location": "Worldwide",
        "url": "https://remoteok.com/1",
        "description": "Build React UIs with TypeScript.",
        "tags": ["react", "frontend"],
    },
    {
        "position": "Go Backend Engineer",
        "company": "Backendco",
        "location": "Worldwide",
        "url": "https://remoteok.com/2",
        "description": "Build services in Go.",
        "tags": ["go"],
    },
]

FAKE_LINKEDIN = """
<li class="base-card base-search-card">
  <a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/123"></a>
  <div class="base-search-card__info">
    <h3 class="base-search-card__title"><a href="https://www.linkedin.com/jobs/view/123">Senior React Developer</a></h3>
    <h4 class="base-search-card__subtitle"><a href="/company/acme">Acme Corp</a></h4>
    <span class="job-search-card__location">Remote</span>
  </div>
</li>
<li class="base-card base-search-card">
  <a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/456"></a>
  <div class="base-search-card__info">
    <h3 class="base-search-card__title"><a href="https://www.linkedin.com/jobs/view/456">QA Engineer</a></h3>
    <h4 class="base-search-card__subtitle"><a href="/company/other">Other</a></h4>
    <span class="job-search-card__location">Remote</span>
  </div>
</li>
"""


@pytest.fixture
def cv():
    return {
        "personal": {"title": "Full Stack Software Engineer"},
        "summary": "Building web apps with React, TypeScript, and Node.js.",
        "skills": [{"group": "g", "tags": ["React", "TypeScript", "Node.js", "PostgreSQL"]}],
        "experience": [{"bullets": ["Wrote unit tests with Jest and React Testing Library."]}],
        "education": [],
    }


@pytest.fixture
def mock_transport(monkeypatch):
    def fake_get_json(url, timeout=20):
        if "remoteok" in url:
            return FAKE_REMOTEOK
        return FAKE_REMOTIVE
    monkeypatch.setattr(searchmod, "_get_json", fake_get_json)
    monkeypatch.setattr(searchmod, "_get_text", lambda url, timeout=20: FAKE_LINKEDIN)
    return searchmod


def test_remotive_parsing(mock_transport):
    jobs = searchmod.SOURCES["remotive"]("react", 10)
    assert len(jobs) == 2
    assert jobs[0].title == "Senior React Engineer"
    assert jobs[0].company == "Acme"
    assert jobs[0].url == "https://remotive.com/1"
    assert "Jest" in jobs[0].description


def test_remoteok_filters_client_side(mock_transport):
    jobs = searchmod.SOURCES["remoteok"]("react", 10)
    assert [j.title for j in jobs] == ["Senior React Frontend Developer"]


def test_linkedin_guest_parsing(mock_transport):
    jobs = searchmod.SOURCES["linkedin"]("react", 10)
    assert len(jobs) == 2
    assert jobs[0].title == "Senior React Developer"
    assert jobs[0].company == "Acme Corp"
    assert jobs[0].location == "Remote"
    assert jobs[0].url.endswith("/jobs/view/123")


def test_rank_orders_best_fit_first(cv):
    jobs = [
        searchmod.Job("Senior React Engineer", "Acme", "Remote", "https://x/1",
                      "React, TypeScript, Next.js, Jest, React Testing Library, PostgreSQL.", "remotive"),
        searchmod.Job("Python Data Scientist", "Other", "Remote", "https://x/2",
                      "Python, Pandas, machine learning.", "remotive"),
    ]
    ranked = searchmod.rank(jobs, cv)
    assert ranked[0].job.title == "Senior React Engineer"
    assert ranked[0].fit > ranked[1].fit


def test_rank_is_deterministic(cv):
    jobs = [
        searchmod.Job("A", "Acme", "Remote", "u", "React TypeScript Jest", "remotive"),
        searchmod.Job("B", "Acme", "Remote", "u", "React TypeScript Jest", "remotive"),
    ]
    a = [r.fit for r in searchmod.rank(jobs, cv)]
    b = [r.fit for r in searchmod.rank(jobs, cv)]
    assert a == b


def test_slugify():
    assert searchmod.slugify("Acme Corp") == "acme-corp"
    assert searchmod.slugify(" Loft! ") == "loft"


def test_ingest_writes_jd(tmp_path):
    job = searchmod.Job("Senior React Engineer", "Acme Corp", "Remote", "https://x",
                        "React and TypeScript.", "remotive")
    path = searchmod.ingest(job, tmp_path)
    assert path == tmp_path / "companies" / "acme-corp" / "description.md"
    text = path.read_text(encoding="utf-8")
    assert "Senior React Engineer" in text
    assert "React and TypeScript." in text


def test_from_file(tmp_path):
    f = tmp_path / "jobs.json"
    f.write_text(json.dumps([
        {"title": "T", "company": "C", "location": "Remote", "url": "u", "description": "d"},
    ]), encoding="utf-8")
    jobs = searchmod.from_file(f)
    assert jobs[0].company == "C"


def test_cli_search_ranks(tmp_path, cv, mock_transport, monkeypatch):
    (tmp_path / "cv.json").write_text(json.dumps(cv), encoding="utf-8")
    monkeypatch.setattr(generate, "BASE_DIR", tmp_path)
    result = CliRunner().invoke(generate.app, ["search", "react"])
    assert result.exit_code == 0
    assert "Senior React Engineer" in result.stdout
    assert "%" in result.stdout


def test_cli_search_json(tmp_path, cv, mock_transport, monkeypatch):
    (tmp_path / "cv.json").write_text(json.dumps(cv), encoding="utf-8")
    monkeypatch.setattr(generate, "BASE_DIR", tmp_path)
    result = CliRunner().invoke(generate.app, ["search", "react", "--json"])
    assert result.exit_code == 0
    rows = json.loads(result.stdout)
    assert rows[0]["fit"] >= rows[1]["fit"]


def test_cli_search_ingest(tmp_path, cv, mock_transport, monkeypatch):
    (tmp_path / "cv.json").write_text(json.dumps(cv), encoding="utf-8")
    monkeypatch.setattr(generate, "BASE_DIR", tmp_path)
    result = CliRunner().invoke(generate.app, ["search", "react", "--ingest", "1"])
    assert result.exit_code == 0
    jd = tmp_path / "companies" / "acme" / "description.md"
    assert jd.exists()
    assert "Senior React Engineer" in jd.read_text(encoding="utf-8")


def test_cli_search_import(tmp_path, cv, monkeypatch):
    (tmp_path / "cv.json").write_text(json.dumps(cv), encoding="utf-8")
    export = tmp_path / "linkedin-export.json"
    export.write_text(json.dumps([
        {"title": "Senior React Developer", "company": "Acme", "location": "Remote",
         "url": "u", "description": "React, TypeScript, Jest, PostgreSQL."},
    ]), encoding="utf-8")
    monkeypatch.setattr(generate, "BASE_DIR", tmp_path)
    result = CliRunner().invoke(generate.app, ["search", "--import", str(export)])
    assert result.exit_code == 0
    assert "Senior React Developer" in result.stdout


def test_cli_unknown_source(cv, monkeypatch):
    result = CliRunner().invoke(generate.app, ["search", "react", "--source", "nope"])
    assert result.exit_code == 2