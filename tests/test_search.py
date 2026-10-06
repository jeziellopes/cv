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

FAKE_PROGRAMATHOR = """
<a href="/jobs/1-desenvolvedor-full-stack-senior">
  <h3 class="text-24 line-height-30">Desenvolvedor Full-Stack Sênior</h3>
  <span><i class='fa fa-briefcase'></i>Acme BR</span>
  <span><i class='fas fa-map-marker-alt'></i>Remoto</span>
  <span><i class='fa fa-building'></i>Média empresa</span>
  <span><i class='far fa-chart-bar'></i>Sênior</span>
  <span><i class='far fa-file-alt'></i>PJ</span>
</a>
<a href="/jobs/2-analista-dados">
  <h3 class="text-24 line-height-30">Analista de Dados</h3>
  <span><i class='fa fa-briefcase'></i>Otherco BR</span>
  <span><i class='fas fa-map-marker-alt'></i>São Paulo/SP</span>
</a>
"""

FAKE_PROGRAMATHOR_DETAIL = """
<html><body>
<div>Requisitos Node.js (preferencialmente NestJS), TypeScript, React, PostgreSQL</div>
<div>Como se candidatar: envie seu currículo</div>
</body></html>
"""

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
    def fake_get_text(url, timeout=20):
        if "programathor" in url:
            return FAKE_PROGRAMATHOR
        return FAKE_LINKEDIN
    def fake_get_html(url, timeout=20):
        if "/jobs/" in url and not url.endswith("/jobs"):
            return FAKE_PROGRAMATHOR_DETAIL
        return FAKE_PROGRAMATHOR
    monkeypatch.setattr(searchmod, "_get_json", fake_get_json)
    monkeypatch.setattr(searchmod, "_get_text", fake_get_text)
    monkeypatch.setattr(searchmod, "_get_html", fake_get_html)
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
    assert jobs[0].url == "https://www.linkedin.com/jobs/view/123/"


def test_programathor_parsing(mock_transport):
    jobs = searchmod.SOURCES["programathor"]("full stack", 10)
    assert len(jobs) == 1
    assert jobs[0].title == "Desenvolvedor Full-Stack Sênior"
    assert jobs[0].company == "Acme BR"
    assert jobs[0].location == "Remoto"
    assert jobs[0].url == "https://programathor.com.br/jobs/1-desenvolvedor-full-stack-senior"
    assert "Node.js" in jobs[0].description
    assert "candidatar" not in jobs[0].description


def test_programathor_filters_by_query(mock_transport):
    jobs = searchmod.SOURCES["programathor"]("dados", 10)
    assert [j.title for j in jobs] == ["Analista de Dados"]


def test_jd_terms_drop_portuguese_boilerplate(cv):
    skill_vocab = {"react", "docker", "typescript"}
    terms = searchmod._jd_terms(
        "Desenvolvedor React Sênior com experiência em Docker e TypeScript.", skill_vocab
    )
    assert "react" in terms
    assert "docker" in terms
    assert "typescript" in terms
    assert "desenvolvedor" not in terms
    assert "experiência" not in terms


def test_query_steers_ranking(cv):
    jobs = [
        searchmod.Job("Senior QA Engineer", "Lemon.io", "Remote", "u",
                      "Quality assurance for the platform.", "remotive"),
        searchmod.Job("Senior React Full-stack Developer", "Lemon.io", "Remote", "u",
                      "React, TypeScript, Next.js, and Jest.", "remotive"),
    ]
    ranked = searchmod.rank(jobs, cv, query="full stack engineer")
    assert ranked[0].job.title == "Senior React Full-stack Developer"


def test_rank_without_query_uses_cv_fit(cv):
    jobs = [
        searchmod.Job("Senior React Engineer", "Acme", "Remote", "u",
                      "React, TypeScript, Next.js, Jest.", "remotive"),
        searchmod.Job("Python Data Scientist", "Other", "Remote", "u",
                      "Python, Pandas, ML.", "remotive"),
    ]
    ranked = searchmod.rank(jobs, cv)
    assert ranked[0].job.title == "Senior React Engineer"


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
    result = CliRunner().invoke(generate.app, ["search", "react", "--source", "remotive"])
    assert result.exit_code == 0
    assert "Senior React Engineer" in result.stdout
    assert "%" in result.stdout


def test_cli_search_json(tmp_path, cv, mock_transport, monkeypatch):
    (tmp_path / "cv.json").write_text(json.dumps(cv), encoding="utf-8")
    monkeypatch.setattr(generate, "BASE_DIR", tmp_path)
    result = CliRunner().invoke(generate.app, ["search", "react", "--source", "remotive", "--json"])
    assert result.exit_code == 0
    rows = json.loads(result.stdout)
    assert rows[0]["fit"] >= rows[1]["fit"]


def test_cli_search_ingest(tmp_path, cv, mock_transport, monkeypatch):
    (tmp_path / "cv.json").write_text(json.dumps(cv), encoding="utf-8")
    monkeypatch.setattr(generate, "BASE_DIR", tmp_path)
    result = CliRunner().invoke(generate.app, ["search", "react", "--source", "remotive", "--ingest", "1"])
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


def test_cli_search_uses_tailored_cv(tmp_path, mock_transport, monkeypatch):
    base = {"personal": {"title": "General Engineer"}, "summary": "x",
            "skills": [{"group": "g", "tags": ["React"]}], "experience": [], "education": []}
    tailored = {"personal": {"title": "Senior React Frontend Developer"}, "summary": "x",
                "skills": [{"group": "g", "tags": ["React", "TypeScript", "Jest", "PostgreSQL"]}],
                "experience": [], "education": []}
    (tmp_path / "cv.json").write_text(json.dumps(base), encoding="utf-8")
    (tmp_path / "tailored.json").write_text(json.dumps(tailored), encoding="utf-8")
    monkeypatch.setattr(generate, "BASE_DIR", tmp_path)
    base_result = CliRunner().invoke(generate.app, ["search", "react", "--source", "remotive", "--json"])
    tailored_result = CliRunner().invoke(
        generate.app, ["search", "react", "--source", "remotive", "--cv", str(tmp_path / "tailored.json"), "--json"]
    )
    assert base_result.exit_code == 0
    assert tailored_result.exit_code == 0
    base_fit = json.loads(base_result.stdout)[0]["fit"]
    tailored_fit = json.loads(tailored_result.stdout)[0]["fit"]
    assert tailored_fit > base_fit