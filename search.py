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
import unicodedata
import urllib.parse
import urllib.request
import html as _html
from dataclasses import dataclass, field
from pathlib import Path

from ats import (
    JD_STOPWORDS,
    _JD_STOP,
    _fold_accent,
    alternative_keys,
    jd_keyword_stats,
)
from skills import match_key

# Title overlap uses a small, dedicated stop set, never the full JD stop list:
# "full" and "stack" are functiony words to a JD tokenizer but are exactly the
# meaningful overlap of a developer title, so a title scorer needs its own.
_TITLE_STOP = {
    "a", "de", "da", "do", "das", "dos", "em", "para", "com", "ou", "e",
    "um", "uma", "o", "s", "pleno", "senior", "sênior", "junior", "júnior",
    "estagio", "estágio", "sao", "paulo", "sp", "remoto", "remota",
    "hibrido", "híbrido", "presencial", "desenvolvedor", "desenvolvedora",
}

# Common function words dropped from a free-text query, EN and PT. Role and
# domain words are kept: for a query, "full stack" is the signal, not noise.
_QUERY_STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "for", "of", "to", "in", "on", "at",
    "with", "by", "as", "de", "em", "para", "com", "da", "do", "das", "dos",
    "que", "e", "ou", "um", "uma", "na", "no", "nas", "nos", "vagas", "vaga",
}

# Generic Brazilian-portuguese role prose that carries no match signal.
_PT_BOILERPLATE = set(
    """
    vaga vagas empresa empresas estagio estagio pleno senior junior trainee
    remoto hibrido presencial trabalho trabalhar trabalhos experiencia anos
    desenvolvedor desenvolvedora
    requisitos responsabilidades beneficios salario contratacao contratacao clt pj
    time times produto produtos cliente clientes negocio negocios conhecimento
    habilidades equipe profissional profissionais procuramos buscamos pessoa
    pessoas projetos projeto atuar atuando desenvolver desenvolvimento desejavel
    obrigatorio diferencial desafios qualidade codigo testes automatizados
    producao escalavel aplicacoes aplicativos construir construcao integracao
    entrega entregar sustentacao suporte apoiar colaborar colaboracao aprender
    aprendizado crescimento autonomia impacto resultados resultados metodos
    metodologias agil agil lean scrumban kanban
    """.split()
)

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
    posted: str = ""


@dataclass
class Ranked:
    job: Job
    fit: int
    matched: list[str] = field(default_factory=list)


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


def _get_html(url: str, timeout: int = 20) -> str:
    """Fetch HTML with a browser-like UA; some boards block plain clients."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124 Safari/537.36"
            ),
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return resp.read().decode("utf-8", errors="replace")


def _matches(query: str, text: str) -> bool:
    hay = text.lower()
    terms = [t for t in re.findall(r"[a-z0-9+#.-]+", query.lower()) if len(t) >= 2]
    return all(t in hay for t in terms)


# ---- sources ----------------------------------------------

def _remotive(query: str, cap: int, **_) -> list[Job]:
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


def _remoteok(query: str, cap: int, **_) -> list[Job]:
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


LINKEDIN_SEARCH = (
    "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search")

# What --since maps to. LinkedIn ignores f_E and f_WT, so they are not offered:
# an option that silently does nothing is worse than no option.
SINCE = {"24h": "r86400", "week": "r604800", "month": "r2592000"}
LINKEDIN_PAGE = 25        # documented increment, though a page returns about 10
LINKEDIN_MAX_PAGES = 4    # bounds the requests a single search can make


def _linkedin(query: str, cap: int, since: str = "", location: str = "",
              remote: bool = False, **_) -> list[Job]:
    """Best-effort LinkedIn guest search. May be blocked; the extension path
    (--import) is the robust replacement.

    The card href is `/jobs/view/<slug>-<id>`, so the id comes from the card's
    own urn rather than from the href. A page holds about ten cards and `start`
    advances by 25, so the pages are walked until the cap is met, and the walk
    stops as soon as a page adds nothing new.
    """
    if since and since not in SINCE:
        raise ValueError(f"unknown --since '{since}'; use {', '.join(SINCE)}")

    jobs: list[Job] = []
    seen: set[str] = set()
    for page in range(LINKEDIN_MAX_PAGES):
        params = {"keywords": query, "start": str(page * LINKEDIN_PAGE)}
        if since:
            params["f_TPR"] = SINCE[since]
        if location:
            params["location"] = location
        if remote:
            params["f_WT"] = "2"
        html = _get_text(LINKEDIN_SEARCH + "?" + urllib.parse.urlencode(params))

        added = 0
        for card in re.split(r"(?=<li)", html):
            urn = re.search(r'data-entity-urn="urn:li:jobPosting:(\d+)"', card)
            href = re.search(r'href="(https://[^"?]*/jobs/view/[^"?]+)', card)
            if not urn and not href:
                continue
            job_id = urn.group(1) if urn else _linkedin_id(
                href.group(1) if href else "")
            if not job_id or job_id in seen:
                continue
            seen.add(job_id)
            added += 1

            def strip(s):
                return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s or "")).strip()

            def pick(pattern):
                match = re.search(pattern, card, re.S)
                return strip(match.group(1)) if match else ""

            match = re.search(r'job-search-card__listdate[^>]*datetime="([^"]+)"', card)
            posted = match.group(1) if match else ""
            jobs.append(
                Job(
                    title=pick(r"base-search-card__title[^>]*>(.*?)</h[34]>"),
                    company=pick(r"base-search-card__subtitle[^>]*>(.*?)</a>"),
                    location=pick(r"job-search-card__location[^>]*>(.*?)</span>"),
                    url=f"https://www.linkedin.com/jobs/view/{job_id}/",
                    description="",
                    source="linkedin",
                    posted=posted,
                )
            )
        if len(jobs) >= cap or added == 0:
            break
    return jobs[:cap]


def _linkedin_id(url: str) -> str:
    """The posting id from a LinkedIn job URL, which may carry a slug."""
    match = re.search(r"/jobs/view/(?:[^/]*?-)?(\d+)", str(url or ""))
    return match.group(1) if match else ""


# The description lives in one div, stable across the class renames around it.
_LINKEDIN_BODY_RE = re.compile(
    r'<div[^>]*class="[^"]*show-more-less-html__markup[^"]*"[^>]*>(.*?)</div>',
    re.S)

# What the JD body starts at and where the page's own chrome begins, shared with
# the other sources that fetch a detail page.
_DETAIL_START_RE = re.compile(
    r"(requisitos|descri.ão da vaga|sobre a vaga|responsabilidades)", re.I
)
_DETAIL_CUT_RE = re.compile(
    r"(candidatar|inscreva-se|enviar curr|como se candidatar|forma de pagamento)", re.I
)


def _clean_detail(html: str) -> str:
    """A description as text, with its block structure kept as blank lines."""
    text = re.sub(r"(?i)<br\s*/?>", "\n", html or "")
    text = re.sub(r"(?i)</(p|li|ul|ol|div|h[1-6])>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = _html.unescape(text)
    text = re.sub(r"[ \t\u00a0]+", " ", text)
    # An inline tag leaves a space before the punctuation that followed it.
    text = re.sub(r"\s+([.,;:!?)])", r"\1", text)
    text = "\n".join(line.strip() for line in text.splitlines())
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def _linkedin_detail(job: Job) -> str:
    """One posting's description from LinkedIn's guest detail endpoint."""
    job_id = _linkedin_id(job.url)
    if not job_id:
        return ""
    html = _get_text(
        "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/" + job_id)
    match = _LINKEDIN_BODY_RE.search(html)
    return _clean_detail(match.group(1) if match else "")


# Sources whose list response carries no description, and where to get one.
DETAILS = {"linkedin": _linkedin_detail}


def add_details(ranked: list[Ranked]) -> tuple[int, int]:
    """Fill in the description for the results shown, from their own source.

    Returns (filled, failed). Only the results already chosen are fetched, so the
    request count is bounded by what the caller asked to see.
    """
    filled = 0
    failed = 0
    for item in ranked:
        job = item.job
        if job.description:
            continue
        fetch = DETAILS.get(job.source)
        if not fetch:
            continue
        try:
            job.description = fetch(job)
        except Exception:  # noqa: BLE001 - a blocked fetch is a missing field
            failed += 1
            continue
        if job.description:
            filled += 1
        else:
            failed += 1
    return filled, failed


def _programathor_detail(url: str) -> str:
    """Best-effort fetch of a Programathor job page; returns the requirements
    section or an empty string when the page is blocked."""
    try:
        html = _get_html(url)
    except Exception:  # noqa: BLE001
        return ""
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    start_m = _DETAIL_START_RE.search(text)
    body = text[start_m.end():] if start_m else text
    cut_m = _DETAIL_CUT_RE.search(body)
    if cut_m:
        body = body[:cut_m.start()]
    return body.strip()[:2000]


def _programathor(query: str, cap: int, **_) -> list[Job]:
    """Programathor: server-rendered Brazilian dev job board. The listing card
    is used to filter cheaply; the detail page supplies the real requirements."""
    html = _get_html("https://programathor.com.br/jobs")
    jobs = []
    for card in re.split(r'(?=<a[^>]+href="/jobs/\d+)', html):
        href_m = re.search(r'href="(/jobs/\d+[^"]*)"', card)
        if not href_m:
            continue
        def strip(s):
            return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s or "")).strip()
        title_m = re.search(r'<h3 class="text-24 line-height-30">(.*?)</h3>', card, re.S)
        spans = re.findall(r"<span>(.*?)</span>", card, re.S)
        title = strip(title_m.group(1)) if title_m else ""
        company = strip(spans[0]) if spans else ""
        location = strip(spans[1]) if len(spans) > 1 else ""
        url = "https://programathor.com.br" + href_m.group(1)
        card_text = " ".join(x for x in (title, company, location) if x)
        if not title or (query and not _matches(query, card_text)):
            continue
        description = _programathor_detail(url) or card_text
        jobs.append(
            Job(
                title=title, company=company, location=location, url=url,
                description=description, source="programathor",
            )
        )
        if len(jobs) >= cap:
            break
    return jobs


def _gupy(query: str, cap: int, **_) -> list[Job]:
    """Best-effort Gupy. The public endpoint is frequently blocked or changed;
    when it is, this raises and the CLI reports the source as unreachable."""
    url = (
        "https://portal.api.gupy.io/api/job"
        "?limit=" + str(cap) + "&jobName=" + urllib.parse.quote(query)
    )
    data = _get_json(url)
    entries = data if isinstance(data, list) else data.get("data", [])
    jobs = []
    for entry in entries:
        jobs.append(
            Job(
                title=entry.get("name") or entry.get("title") or "",
                company=entry.get("company") or "",
                location=entry.get("workplace") or "",
                url=entry.get("careerPageUrl") or entry.get("url") or "",
                description=entry.get("description") or "",
                source="gupy",
            )
        )
    return jobs[:cap]


SOURCES = {
    "programathor": _programathor,
    "remotive": _remotive,
    "remoteok": _remoteok,
    "linkedin": _linkedin,
    "gupy": _gupy,
}


def known_sources() -> str:
    return ", ".join(sorted(SOURCES))


def from_file(path: Path) -> list[Job]:
    """Load jobs from a JSON file, e.g. a browser extension export.

    The file is an array of {title, company, location, url, description, tags?,
    posted?}.
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
                posted=entry.get("posted") or "",
            )
        )
    return jobs


# ---- ranking ----------------------------------------------

def _tokens(text: str) -> set[str]:
    # Fold diacritics before splitting, so "vivência" is one token and never
    # the viv/ncia fragments that destroyed JD matching for Portuguese text.
    return {t.lower() for t in re.findall(
        r"[A-Za-z][A-Za-z0-9+#.-]*", _fold_accent(text or ""))}


def _fold(text: str) -> str:
    """Strip diacritics so 'Sênior' folds to 'senior' for generic-word checks."""
    return "".join(
        c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn"
    )


def _is_generic(token: str) -> bool:
    return _fold(token) in JD_STOPWORDS or _fold(token) in _PT_BOILERPLATE


def _jd_terms(text: str) -> list[str]:
    """The JD's demands, from the one filter `ats` owns (spec 0016).

    search used to keep a second, looser rule of its own, which is why
    `cv inbox score` and `cv fit` read the same posting differently. The shared
    filter decides what a demand is (ADR 0012); all that is left here is
    emitting a slash-joined demand by its parts, so "ux/ui" meets "UX
    Principles" in the CV's own tokenizer.
    """
    out: list[str] = []
    seen: set[str] = set()
    for term in jd_keyword_stats(text)[0]:
        if "/" in term:
            for part in term.split("/"):
                if len(part) >= 2 and part not in seen and part not in _JD_STOP:
                    seen.add(part)
                    out.append(part)
            continue
        seen.add(term)
        out.append(term)
    return out


def _overlap_tokens(text: str) -> set[str]:
    """Token set for overlap, splitting hyphens so 'full-stack' matches
    'full stack' and vice versa."""
    out = _tokens(text)
    for token in list(out):
        if "-" in token:
            out.update(token.split("-"))
    return out


def _jd_terms_for(job: "Job") -> list[str]:
    """The JD's demands, minus the posting's own company name."""
    terms = _jd_terms(job.description)
    company = str(job.company or "")
    stops = {t for t in _tokens(company) if len(t) >= 2}
    compact = _fold_accent(company.lower().replace(" ", "").strip())
    if compact:
        stops.add(compact)
    return [k for k in terms if k not in stops]


def _cv_text(cv: dict) -> str:
    parts = [cv.get("summary", "")]
    for section in ("experience", "education"):
        for item in cv.get(section, []):
            parts.extend(item.get("bullets", []) or [])
    for group in cv.get("skills", []):
        parts.extend(group.get("tags", []) or [])
    return " ".join(parts)


def rank(jobs: list[Job], cv: dict, query: str = "") -> list[Ranked]:
    """Score each job 0-100, best first.

    A free-text query steers the rank (55% query relevance, 45% CV fit); with
    no query (--import) the CV fit alone decides.
    """
    cv_body = _cv_text(cv).lower()
    cv_tokens = _tokens(cv_body)
    cv_keys = {match_key(t) for t in cv_tokens}
    title_tokens = {t for t in _overlap_tokens(
        cv.get("personal", {}).get("title", ""))
        if len(t) >= 2 and t not in _TITLE_STOP}
    skill_tags = [t for g in cv.get("skills", []) for t in g.get("tags", [])]
    query_tokens = [t for t in _overlap_tokens(query) if len(t) >= 2 and t not in _QUERY_STOPWORDS]

    ranked = []
    for job in jobs:
        keywords = _jd_terms_for(job)
        alts = alternative_keys(job.description)
        jd_hits, jd_misses = _cover_demands(keywords, alts, cv_keys)
        jd_coverage = len(jd_hits) / (len(jd_hits) + len(jd_misses)) \
            if jd_hits or jd_misses else 0.0
        body = (job.title + " " + job.description).lower()
        body_keys = {match_key(t) for t in _tokens(body)}
        skill_coverage = (
            (sum(1 for t in skill_tags if any(
                match_key(tok) in body_keys for tok in _tokens(t.lower())))
             / len(skill_tags))
            if skill_tags
            else 0.0
        )
        job_tokens = {t for t in _overlap_tokens(job.title)
                      if len(t) >= 2 and t not in _TITLE_STOP}
        title_overlap = (
            len(job_tokens & title_tokens) / len(job_tokens)
            if job_tokens
            else 0.0
        )
        cv_fit = 0.5 * jd_coverage + 0.3 * skill_coverage + 0.2 * title_overlap
        if query_tokens:
            query_relevance = sum(1 for t in query_tokens if t in body) / len(query_tokens)
            # CV fit is the base; the query boosts within-stack matches but can
            # never lift an off-stack job (e.g. C#/Angular for a JS/TS CV).
            fit = round(100 * cv_fit * (1.0 + 0.5 * query_relevance))
        else:
            fit = round(100 * cv_fit)
        matched = [t for t in skill_tags
                    if any(match_key(tok) in body_keys
                           for tok in _tokens(t.lower()))][:6]
        ranked.append(Ranked(job=job, fit=fit, matched=matched))
    ranked.sort(key=lambda r: (-r.fit, r.job.title.lower()))
    return ranked


def _cover_demands(
    keywords: list[str],
    alts: dict[str, set[str]],
    cv_keys: set[str],
) -> tuple[list[str], list[str]]:
    """Split a JD's terms into covered and missing demands.

    A term the JD offered as an alternative to another ("pytest ou JEST")
    belongs to that other term's demand, so the demand is covered by any of
    its members and a missing demand is reported as one line naming the
    choice the posting left open.
    """
    hits: list[str] = []
    misses: list[str] = []
    claimed: set[str] = set()
    for keyword in keywords:
        if keyword in claimed:
            continue
        group = alts.get(keyword, {keyword}) & set(keywords) or {keyword}
        claimed.update(group)
        label = " or ".join(sorted(group)) if len(group) > 1 else keyword
        (hits if any(match_key(k) in cv_keys for k in group) else misses).append(label)
    return hits, misses


def explain(job: Job, cv: dict) -> dict:
    """The three components behind a fit percent, with counts and the terms
    that drive each one.

    A single score hides where it came from. This exposes the numerator and
    denominator of each part, and the terms that missed, so a low fit can be
    read as a fact rather than a mystery.
    """
    cv_body = _cv_text(cv).lower()
    cv_tokens = _tokens(cv_body)
    cv_keys = {match_key(t) for t in cv_tokens}
    title_tokens = {t for t in _overlap_tokens(
        cv.get("personal", {}).get("title", ""))
        if len(t) >= 2 and t not in _TITLE_STOP}
    skill_tags = [t for g in cv.get("skills", []) for t in g.get("tags", [])]

    keywords = _jd_terms_for(job)
    # "Vue.js ou React" is one demand: either side covers it, so a JD that
    # offers a choice must not read as several unmet requirements.
    alts = alternative_keys(job.description)
    jd_hits, jd_misses = _cover_demands(keywords, alts, cv_keys)
    jd_total = len(jd_hits) + len(jd_misses)

    body = (job.title + " " + job.description).lower()
    body_keys = {match_key(t) for t in _tokens(body)}
    matched = [t for t in skill_tags if any(
        match_key(tok) in body_keys for tok in _tokens(t.lower()))]

    job_tokens = {t for t in _overlap_tokens(job.title)
                  if len(t) >= 2 and t not in _TITLE_STOP}
    overlapped = sorted(set(job_tokens) & set(title_tokens))
    missed_title = sorted(set(job_tokens) - set(title_tokens))

    jd_ratio = len(jd_hits) / jd_total if jd_total else 0.0
    skill_ratio = len(matched) / len(skill_tags) if skill_tags else 0.0
    title_ratio = len(overlapped) / len(job_tokens) if job_tokens else 0.0
    return {
        "jd_covered": len(jd_hits), "jd_total": jd_total,
        "jd_misses": jd_misses,
        "skills_matched": len(matched), "skills_total": len(skill_tags),
        "skills_list": matched,
        "title_overlapped": len(overlapped), "title_total": len(job_tokens),
        "title_missed": missed_title,
        "ratios": {"jd": jd_ratio, "skill": skill_ratio, "title": title_ratio},
        "fit": round(100 * (0.5 * jd_ratio + 0.3 * skill_ratio
                            + 0.2 * title_ratio)),
    }


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