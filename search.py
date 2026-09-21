"""Job search and match scoring for cv.

Searches pluggable job sources by a free-text query and ranks the results by
deterministic fit against the base CV: how much of the JD is covered by the CV,
how many of the CV's skill tags the JD mentions, and title-token overlap.

No LLM is involved. The ranking reuses the deterministic keyword machinery in
ats.py. A source is a function `(query, cap) -> list[Job]`; add one to SOURCES.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from ats import JD_STOPWORDS, _looks_like_domain

# Generic role boilerplate that carries no match signal.

# ---- model ------------------------------------------------

@dataclass
class Job:
    title: str
    company: str
    location: str
    url: str
    description: str
    source: str
    tags: list[str] = field(default_factory=list)


@dataclass
class Ranked:
    job: Job
    fit: int


# ---- transport --------------------------------------------

def _get_json(url: str, timeout: int = 20) -> object:
    req = urllib.request.Request(
        url, headers={"User-Agent": "cv/0.1 (job search)"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _get_text(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(
        url, headers={"User-Agent": "cv/0.1 (job search)"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return resp.read().decode("utf-8", errors="replace")


def _matches(query: str, text: str) -> bool:
    hay = text.lower()
    terms = [t for t in re.findall(r"[a-z0-9+#.-]+", query.lower()) if len(t) >= 2]
    return all(t in hay for t in terms)


# ---- sources ----------------------------------------------

def _remotive(query: str, cap: int) -> list[Job]:
    url = "https://remotive.com/api/remote-jobs?search=" + urllib.parse.quote(query)
    data = _get_json(url)
    jobs = []
    for entry in data.get("jobs", []):
        jobs.append(
            Job(
                title=entry.get("title") or "",
                company=entry.get("company_name") or "",
                location=entry.get("candidate_required_location") or "",
                url=entry.get("url") or "",
                description=entry.get("description") or "",
                source="remotive",
                tags=list(entry.get("tags") or []),
            )
        )
    return jobs[:cap]


def _remoteok(query: str, cap: int) -> list[Job]:
    data = _get_json("https://remoteok.com/api")
    jobs = []
    for entry in data:
        if not isinstance(entry, dict) or "position" not in entry:
            continue
        position = entry.get("position") or ""
        body = (entry.get("description") or "") + " " + " ".join(entry.get("tags") or [])
        if not _matches(query, position + " " + body):
            continue
        jobs.append(
            Job(
                title=position,
                company=entry.get("company") or "",
                location=entry.get("location") or "",
                url=entry.get("url") or "",
                description=body,
                source="remoteok",
                tags=list(entry.get("tags") or []),
            )
        )
    return jobs[:cap]


def _linkedin(query: str, cap: int) -> list[Job]:
    """Best-effort LinkedIn guest search. May be blocked; the extension path
    (--import) is the robust replacement."""
    url = (
        "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
        "?keywords=" + urllib.parse.quote(query) + "&f_WT=2"
    )
    html = _get_text(url)
    jobs = []
    for card in re.split(r"(?=<li)", html):
        href_m = re.search(r'href="([^"]*/jobs/view/[0-9]+[^"]*)"', card)
        if not href_m:
            continue
        def strip(s):
            return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s or "")).strip()
        title_m = re.search(r"base-search-card__title.*?>(.*?)</a>", card, re.S)
        company_m = re.search(r"base-search-card__subtitle.*?>(.*?)</a>", card, re.S)
        location_m = re.search(r"job-search-card__location.*?>(.*?)</span>", card, re.S)
        jobs.append(
            Job(
                title=strip(title_m.group(1)) if title_m else "",
                company=strip(company_m.group(1)) if company_m else "",
                location=strip(location_m.group(1)) if location_m else "",
                url=href_m.group(1),
                description="",
                source="linkedin",
            )
        )
    return jobs[:cap]


SOURCES = {
    "remotive": _remotive,
    "remoteok": _remoteok,
    "linkedin": _linkedin,
}


def known_sources() -> str:
    return ", ".join(sorted(SOURCES))


def from_file(path: Path) -> list[Job]:
    """Load jobs from a JSON file, e.g. a browser extension export.

    The file is an array of {title, company, location, url, description, tags?}.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    jobs = []
    for entry in data:
        jobs.append(
            Job(
                title=entry.get("title") or "",
                company=entry.get("company") or "",
                location=entry.get("location") or "",
                url=entry.get("url") or "",
                description=entry.get("description") or "",
                source=entry.get("source") or "import",
                tags=list(entry.get("tags") or []),
            )
        )
    return jobs


# ---- ranking ----------------------------------------------

def _tokens(text: str) -> set[str]:
    return {t.lower() for t in re.findall(r"[A-Za-z][A-Za-z0-9+#.-]*", text or "")}


def _jd_terms(text: str, skill_vocab: set[str]) -> list[str]:
    """Distinctive terms in a JD: tokens that are capitalized, carry tech
    punctuation (node.js, ci/cd, es6+), or name a CV skill. Generic prose is
    ignored, so coverage reflects real tech overlap, not description length."""
    out: list[str] = []
    seen: set[str] = set()
    for m in re.finditer(r"[A-Za-z][A-Za-z0-9+#./-]*", text or ""):
        raw = m.group(0)
        low = raw.lower()
        if len(low) < 3 or low in JD_STOPWORDS or low in seen:
            continue
        if any(ch.isdigit() for ch in low) or _looks_like_domain(low):
            continue
        if raw[0].isupper() or "/" in raw or "." in raw or "+" in raw or "#" in raw or low in skill_vocab:
            seen.add(low)
            out.append(low)
    return out


def _cv_text(cv: dict) -> str:
    parts = [cv.get("summary", "")]
    for section in ("experience", "education"):
        for item in cv.get(section, []):
            parts.extend(item.get("bullets", []) or [])
    for group in cv.get("skills", []):
        parts.extend(group.get("tags", []) or [])
    return " ".join(parts)


def rank(jobs: list[Job], cv: dict) -> list[Ranked]:
    """Score each job 0-100 by fit against the CV, best first."""
    cv_body = _cv_text(cv).lower()
    cv_tokens = _tokens(cv_body)
    title_tokens = _tokens(cv.get("personal", {}).get("title", ""))
    skill_tags = [t for g in cv.get("skills", []) for t in g.get("tags", [])]
    skill_vocab = {t.lower() for t in skill_tags} | {
        token for t in skill_tags for token in _tokens(t)
    }

    ranked = []
    for job in jobs:
        keywords = _jd_terms(job.description, skill_vocab)
        jd_coverage = (
            sum(1 for k in keywords if k in cv_tokens) / len(keywords)
            if keywords
            else 0.0
        )
        body = (job.title + " " + job.description).lower()
        skill_coverage = (
            sum(1 for t in skill_tags if t.lower() in body) / len(skill_tags)
            if skill_tags
            else 0.0
        )
        job_tokens = _tokens(job.title)
        title_overlap = (
            len(job_tokens & title_tokens) / len(job_tokens)
            if job_tokens
            else 0.0
        )
        fit = round(100 * (0.5 * jd_coverage + 0.3 * skill_coverage + 0.2 * title_overlap))
        ranked.append(Ranked(job=job, fit=fit))
    ranked.sort(key=lambda r: (-r.fit, r.job.title.lower()))
    return ranked


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "job"


def ingest(job: Job, base_dir: Path) -> Path:
    """Write a job's JD to companies/<slug>/description.md for the pipeline."""
    out = base_dir / "companies" / slugify(job.company) / "description.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        f"{job.title}\n{job.company}\n{job.location}\n{job.url}\n\n{job.description}\n",
        encoding="utf-8",
    )
    return out