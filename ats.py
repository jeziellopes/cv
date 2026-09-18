"""Deterministic ATS checks for generated CV PDFs.

Two layers:

- Gates: structural conditions real parsers depend on. Any failure is fatal.
- Scorecard: deterministic approximation of third-party checker categories
  (Enhancv-style). Informational unless the caller opts into strict mode.

An optional LLM judge (`--judge`) appends non-deterministic commentary and is
never part of the gates or the deterministic score.
"""

from __future__ import annotations

import re
import subprocess
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from pdfminer.high_level import extract_pages, extract_text
from pdfminer.layout import LAParams, LTTextLine

# ---- constants ----------------------------------------------

REQUIRED_SECTIONS = ["Summary", "Experience", "Education", "Skills", "Languages"]

MIN_TEXT_CHARS = 300
MAX_FILE_BYTES = 2 * 1024 * 1024
COLUMN_GAP_FRACTION = 0.12

# Characters that break parsers or date normalisation.
BANNED_CHARS = {
    "\u2013": "en dash",
    "\u2014": "em dash",
    "\u2011": "non-breaking hyphen",
    "\u2315": "option key glyph",
    "\u200b": "zero-width space",
    "\u200c": "zero-width non-joiner",
    "\u200d": "zero-width joiner",
    "\u00a0": "non-breaking space",
}

DATE_FIELD_RE = re.compile(r"^\d{2}/\d{4}$")
DATE_RANGE_RE = re.compile(r"\d{2}/\d{4}\s*-\s*(?:\d{2}/\d{4}|Present)")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"\+?\d[\d\s().-]{7,}\d")
LINKEDIN_RE = re.compile(r"(?:https?://)?(?:www\.)?linkedin\.com/in/[\w-]+", re.I)
FILENAME_RE = re.compile(r"^[A-Z][a-z]+(?:[A-Z][a-z]+)+.*\.pdf$")
TECH_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[./+#][A-Za-z0-9]+)+")
WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9+#.-]*")
BIAS_RE = re.compile(
    r"\b(date of birth|d\.?o\.?b\.?|marital status|nationality|gender|photo)\b",
    re.I,
)
LEADERSHIP_WORDS = [
    "lead", "led", "managed", "manager", "hired", "mentor", "mentored",
    "budget", "owned", "owner", "drove", "strategy", "roadmap", "head of",
]

# Portuguese equivalents. Without these, every PT CV scores 0 on leadership
# even when it carries real signals, because \bmentor\b never matches "mentorei".
LEADERSHIP_WORDS_PT = [
    "liderei", "lider", "liderança", "liderou", "coordenei", "conduzi",
    "gerenciei", "dono", "propriedade", "mentorei", "mentoria", "contratei",
    "orçamento", "estratégia", "roadmap", "diretor",
]

STOPWORDS = set(
    """
    a an the and or but if then than that this these those to of in on for with
    without from by as at into over under between across during within is are was
    were be been being will would can could should may might must do does did
    have has had not no your you our we they their them he she his her its it
    about above after again against all also am any because before below both
    each few more most other some such only own same so too very s t just don
    now will work working works role roles job jobs candidate candidates
    experience experienced years year strong plus etc using use used help helps
    team teams company companies ability able across including include includes
    required require requirements preferred nice must plus new new build builds
    building develop developing development design designing senior junior mid
    level full stack end to end well good great excellent opportunity position
    please apply application successful ideal you your we us our who what when
    where why how which while will you will need want looking join us
    """.split()
)

DATE_RE = re.compile(r"^\d{2}/(\d{4})$")

DOMAIN_TLDS = {"com", "org", "net", "io", "dev", "ai", "co", "br", "sh", "app", "cloud"}

JD_STOPWORDS = STOPWORDS | set(
    """
    providers provider leading provides provide route routes models save lower token
    tokens spend avoid vendor vendors supported support offer offers fast pace
    environment environments customers customer product products platform platforms
    scalable scale large modern best practice practices tools tooling stack stacks
    deep strong excellent ability skills skill knowledge understanding familiar
    familiarity bonus nice must want looking join team teams role roles build
    builds building write writes writing deliver delivers delivery ship shipping
    ensure ensures ensuring maintain maintains maintaining improve improves
    improving drive drives driving help helps helping create creates creating
    across within using use used plus etc including include includes
    """.split()
)


def _looks_like_domain(token: str) -> bool:
    return "." in token and token.rsplit(".", 1)[1] in DOMAIN_TLDS


# ---- extraction ---------------------------------------------

@dataclass
class Line:
    text: str
    x0: float
    x1: float
    y0: float
    y1: float
    page: int
    index: int


def _iter_lines(el):
    if isinstance(el, LTTextLine):
        yield el
        return
    for child in getattr(el, "_objs", []):
        yield from _iter_lines(child)


def extract_lines(pdf_path: Path) -> list[Line]:
    """Return text lines in pdfminer reading order with their geometry."""
    lines: list[Line] = []
    index = 0
    for pageno, layout in enumerate(extract_pages(str(pdf_path), laparams=LAParams())):
        for el in _iter_lines(layout):
            text = el.get_text().strip()
            if not text:
                continue
            lines.append(
                Line(
                    text=text,
                    x0=round(el.x0, 2),
                    x1=round(el.x1, 2),
                    y0=round(el.y0, 2),
                    y1=round(el.y1, 2),
                    page=pageno,
                    index=index,
                )
            )
            index += 1
    return lines


def extract_pdf_text(pdf_path: Path) -> str:
    return extract_text(str(pdf_path))


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


# ---- date helpers -------------------------------------------

def parse_month(value: str) -> Optional[tuple[int, int]]:
    """Parse MM/YYYY to (year, month); None for Present or unparseable."""
    if not value or value.strip().lower() in {"present", "current", "now"}:
        return None
    m = DATE_RE.match(value.strip())
    if not m:
        return None
    year = int(m.group(1))
    month = int(value.strip().split("/")[0])
    return (year, month)


def month_index(year: int, month: int) -> int:
    return year * 12 + (month - 1)


# ---- check model --------------------------------------------

@dataclass
class Check:
    key: str
    category: str
    title: str
    score: int
    detail: str = ""
    gate: bool = False

    @property
    def passed(self) -> bool:
        return self.score >= 100

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "category": self.category,
            "title": self.title,
            "gate": self.gate,
            "passed": self.passed,
            "score": self.score,
            "detail": self.detail,
        }


@dataclass
class AtsReport:
    gates: list[Check] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)
    judge: str = ""
    missing_keywords: list[str] = field(default_factory=list)

    @property
    def categories(self) -> dict[str, int]:
        buckets: dict[str, list[int]] = {}
        for c in self.checks:
            buckets.setdefault(c.category, []).append(c.score)
        return {k: round(sum(v) / len(v)) for k, v in buckets.items()}

    @property
    def overall(self) -> int:
        cats = list(self.categories.values())
        if not cats:
            return 0
        return round(sum(cats) / len(cats))

    @property
    def gates_passed(self) -> bool:
        return all(g.passed for g in self.gates)

    def to_dict(self) -> dict:
        return {
            "gates_passed": self.gates_passed,
            "gates": [g.to_dict() for g in self.gates],
            "categories": self.categories,
            "overall": self.overall,
            "missing_keywords": self.missing_keywords,
            "judge": self.judge,
            "checks": [c.to_dict() for c in self.checks],
        }


# ---- gates --------------------------------------------------

def gate_lines(text: str, lines: list[Line]) -> Check:
    count = len(text.strip())
    ok = count >= MIN_TEXT_CHARS
    return Check(
        key="G1", category="ATS Essentials", title="Text layer present",
        score=100 if ok else 0,
        detail=f"{count} extractable chars",
        gate=True,
    )


def _page_widths(lines: list[Line]) -> dict[int, float]:
    widths: dict[int, float] = {}
    for line in lines:
        widths.setdefault(line.page, max(widths.get(line.page, 0.0), line.x1))
    return widths


def gate_single_column(lines: list[Line]) -> Check:
    """Fail if any two text boxes sharing a visual row have a wide horizontal gap."""
    if not lines:
        return Check("G2", "ATS Essentials", "Single column", 0, "no text", gate=True)
    page_width = max((p for p in _page_widths(lines).values()), default=595.0)
    threshold = COLUMN_GAP_FRACTION * page_width

    offenders: list[str] = []
    pages: dict[int, list[Line]] = {}
    for line in lines:
        pages.setdefault(line.page, []).append(line)

    for pageno, page_lines in pages.items():
        for i, a in enumerate(page_lines):
            for b in page_lines[i + 1 :]:
                overlap = min(a.y1, b.y1) - max(a.y0, b.y0)
                shorter = min(a.y1 - a.y0, b.y1 - b.y0)
                if shorter <= 0 or overlap <= 0.5 * shorter:
                    continue
                if a.x1 < b.x0:
                    gap = b.x0 - a.x1
                elif b.x1 < a.x0:
                    gap = a.x0 - b.x1
                else:
                    continue
                if gap > threshold:
                    offenders.append(
                        f"page {pageno + 1}: {norm(' '.join([a.text, b.text]))[:60]} (gap {gap:.0f}pt)"
                    )

    ok = not offenders
    return Check(
        key="G2", category="ATS Essentials", title="Single column reading order",
        score=100 if ok else 0,
        detail="; ".join(offenders[:3]) if offenders else f"no row gap exceeds {threshold:.0f}pt",
        gate=True,
    )


def _find_index(lines: list[Line], needle: str, start: int = 0) -> Optional[int]:
    target = norm(needle)
    if not target:
        return None
    for line in lines:
        if line.index < start:
            continue
        if target in norm(line.text):
            return line.index
    return None


def gate_reading_order(lines: list[Line], cv: Optional[dict]) -> Check:
    if not cv:
        return Check("G3", "ATS Essentials", "Reading order", 100, "no cv.json supplied", gate=True)
    problems: list[str] = []
    cursor = 0
    for item in cv.get("experience", []):
        org = item.get("org", "")
        role = item.get("role", "")
        bullets = item.get("bullets", []) or []
        idx_org = _find_index(lines, org, cursor)
        if idx_org is None:
            problems.append(f"{org}: org not found after previous item")
            continue
        idx_role = _find_index(lines, role, idx_org + 1)
        if idx_role is None:
            problems.append(f"{org}: role not found after org")
            continue
        if bullets and bullets[0].split():
            first_word = bullets[0].split()[0]
            idx_bullet = _find_index(lines, first_word, idx_role + 1)
            if idx_bullet is None:
                problems.append(f"{org}: first bullet not found after role")
                continue
            cursor = idx_bullet + 1
        else:
            cursor = idx_role + 1
    ok = not problems
    return Check(
        key="G3", category="ATS Essentials", title="Reading order",
        score=100 if ok else 0,
        detail="; ".join(problems[:3]) if problems else "org then role then bullets",
        gate=True,
    )


def gate_sections(text: str) -> Check:
    present = [s for s in REQUIRED_SECTIONS if re.search(rf"^\s*{re.escape(s)}\s*$", text, re.M)]
    missing = [s for s in REQUIRED_SECTIONS if s not in present]
    ok = not missing
    return Check(
        key="G4", category="Sections", title="Semantic sections",
        score=100 if ok else 0,
        detail=f"missing: {', '.join(missing)}" if missing else ", ".join(present),
        gate=True,
    )


def gate_dates(text: str, cv: Optional[dict]) -> Check:
    problems: list[str] = []
    if cv:
        for section in ("experience", "education"):
            for item in cv.get(section, []):
                start = str(item.get("start", ""))
                end = str(item.get("end", ""))
                if not (DATE_FIELD_RE.match(start) or start.lower() in {"present", ""}):
                    problems.append(f"bad start '{start}'")
                if not (DATE_FIELD_RE.match(end) or end.lower() in {"present", ""}):
                    problems.append(f"bad end '{end}'")
                if start and end and f"{start} - {end}" not in norm(text):
                    problems.append(f"range '{start} - {end}' not rendered")
    ok = not problems
    return Check(
        key="G5", category="ATS Essentials", title="Date format",
        score=100 if ok else 0,
        detail="; ".join(problems[:3]) if problems else "MM/YYYY - MM/YYYY or Present",
        gate=True,
    )


def gate_characters(text: str) -> Check:
    found = [f"{name} ({ch!r})" for ch, name in BANNED_CHARS.items() if ch in text]
    ok = not found
    return Check(
        key="G6", category="ATS Essentials", title="Character set",
        score=100 if ok else 0,
        detail="; ".join(found[:4]) if found else "no banned glyphs",
        gate=True,
    )


def gate_contact(text: str, cv: Optional[dict]) -> Check:
    problems: list[str] = []
    if not EMAIL_RE.search(text):
        problems.append("no email")
    if not PHONE_RE.search(text):
        problems.append("no phone")
    if not LINKEDIN_RE.search(text):
        problems.append("no linkedin")
    if cv:
        name = cv.get("personal", {}).get("name", "")
        if name and norm(name).lower() not in norm(text).lower():
            problems.append("name missing")
    ok = not problems
    return Check(
        key="G7", category="Sections", title="Contact information",
        score=100 if ok else 0,
        detail="; ".join(problems) if problems else "email, phone, linkedin, name",
        gate=True,
    )


def _cv_values(cv: dict) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for item in cv.get("experience", []):
        out.append(("experience.org", item.get("org", "")))
        out.append(("experience.role", item.get("role", "")))
    for item in cv.get("education", []):
        out.append(("education.institution", item.get("institution", "")))
        out.append(("education.degree", item.get("degree", "")))
    for item in cv.get("courses", []):
        out.append(("courses.title", item.get("title", "")))
    for group in cv.get("skills", []):
        for tag in group.get("tags", []):
            out.append(("skills.tag", tag))
    for lang in cv.get("languages", []):
        out.append(("languages.name", lang.get("name", "")))
    return out


def gate_completeness(text: str, cv: Optional[dict]) -> Check:
    if not cv:
        return Check("G8", "Sections", "Content completeness", 100, "no cv.json supplied", gate=True)
    full = norm(text).lower()
    missing = [f"{key}:{value}" for key, value in _cv_values(cv) if value and norm(value).lower() not in full]
    ok = not missing
    return Check(
        key="G8", category="Sections", title="Content completeness",
        score=100 if ok else 0,
        detail=f"{len(missing)} missing: {', '.join(missing[:4])}" if missing else "all cv.json values found",
        gate=True,
    )


def gate_file(pdf_path: Path) -> Check:
    problems: list[str] = []
    if pdf_path.suffix.lower() != ".pdf":
        problems.append("not a PDF")
    size = pdf_path.stat().st_size if pdf_path.exists() else 0
    if size >= MAX_FILE_BYTES:
        problems.append(f"{size} bytes >= 2MB")
    ok = not problems
    return Check(
        key="G9", category="ATS Essentials", title="File format and size",
        score=100 if ok else 0,
        detail="; ".join(problems) if problems else f"PDF, {size // 1024} KB",
        gate=True,
    )


# ---- scorecard ----------------------------------------------

def _all_bullets(cv: Optional[dict]) -> list[str]:
    if not cv:
        return []
    out: list[str] = []
    for section in ("experience", "education"):
        for item in cv.get(section, []):
            out.extend(item.get("bullets", []) or [])
    return out


def score_quantify(cv: Optional[dict]) -> Check:
    bullets = _all_bullets(cv)
    if not bullets:
        return Check("content.quantify", "Content", "Quantify impact", 100, "no bullets")
    with_number = sum(1 for b in bullets if re.search(r"\d", b))
    pct = with_number / len(bullets)
    score = min(100, round(100 * pct / 0.40))
    return Check(
        "content.quantify", "Content", "Quantify impact", score,
        f"{with_number}/{len(bullets)} bullets contain a number",
    )


def score_repetition(cv: Optional[dict]) -> Check:
    bullets = _all_bullets(cv)
    counts: dict[str, int] = {}
    for bullet in bullets:
        words = WORD_RE.findall(bullet)
        if not words:
            continue
        lead = words[0].lower()
        if len(lead) < 4 or lead in STOPWORDS:
            continue
        counts[lead] = counts.get(lead, 0) + 1
    flagged = sorted((w for w, c in counts.items() if c >= 3), key=lambda w: -counts[w])
    score = max(0, 100 - 10 * len(flagged))
    return Check(
        "content.repetition", "Content", "Repetition", score,
        f"{len(flagged)} repeated opening verbs: {', '.join(flagged[:5])}" if flagged else "no opening verb repeats 3+ times",
    )


def score_bullet_length(cv: Optional[dict]) -> Check:
    bullets = _all_bullets(cv)
    if not bullets:
        return Check("content.bullet_length", "Content", "Bullets consistency", 100, "no bullets")
    in_range = sum(1 for b in bullets if 10 <= len(b.split()) <= 35)
    score = round(100 * in_range / len(bullets))
    return Check(
        "content.bullet_length", "Content", "Bullets consistency", score,
        f"{in_range}/{len(bullets)} bullets are 10-35 words",
    )


def score_order(text: str) -> Check:
    body = norm(text)
    order = {s: body.find(s) for s in ("Summary", "Experience", "Education", "Skills")}
    ok = all(v >= 0 for v in order.values()) and order["Summary"] < order["Education"] and order["Experience"] < order["Skills"]
    return Check(
        "sections.order", "Sections", "Sections order", 100 if ok else 40,
        "impact-first" if ok else "summary/experience not before education/skills",
    )


def score_essential_sections(text: str) -> Check:
    required = ["Summary", "Experience", "Education", "Skills"]
    present = sum(1 for s in required if re.search(rf"^\s*{re.escape(s)}\s*$", text, re.M))
    score = round(100 * present / len(required))
    return Check(
        "sections.essential", "Sections", "Essential sections", score,
        f"{present}/{len(required)} sections present",
    )


def score_contact_information(text: str) -> Check:
    present = sum(1 for pattern in (EMAIL_RE, PHONE_RE, LINKEDIN_RE) if pattern.search(text))
    score = round(100 * present / 3)
    return Check(
        "sections.contact", "Sections", "Contact information", score,
        f"{present}/3 of email, phone, linkedin present",
    )


def score_filename(pdf_path: Path) -> Check:
    ok = bool(FILENAME_RE.match(pdf_path.name))
    return Check(
        "ats.filename", "ATS Essentials", "File name", 100 if ok else 50,
        pdf_path.name,
    )


def _timeline(cv: Optional[dict]):
    out = []
    for item in (cv or {}).get("experience", []):
        name = item.get("org", "")
        start = parse_month(item.get("start", ""))
        end = parse_month(item.get("end", ""))
        if start:
            out.append((name, start, end))
    return out


def score_gaps(cv: Optional[dict]) -> Check:
    items = _timeline(cv)
    gaps = []
    for (name_a, start_a, end_a), (name_b, start_b, end_b) in zip(items, items[1:]):
        if end_b is None or start_a is None:
            continue
        months = (start_a[0] - end_b[0]) * 12 + (start_a[1] - end_b[1])
        if months > 3:
            gaps.append(f"{name_b} -> {name_a}: {months} months")
    score = max(0, 100 - 25 * len(gaps))
    return Check(
        "hr.gaps", "HR Red Flags", "Employment gaps", score,
        "; ".join(gaps[:3]) if gaps else "no gap over 3 months",
    )


def score_overlaps(cv: Optional[dict]) -> Check:
    items = _timeline(cv)
    overlaps = []
    for (name_a, start_a, end_a), (name_b, start_b, end_b) in zip(items, items[1:]):
        if start_a and end_b and month_index(*start_a) < month_index(*end_b):
            overlaps.append(f"{name_a} starts before {name_b} ends")
    score = max(0, 100 - 25 * len(overlaps))
    return Check(
        "hr.overlaps", "HR Red Flags", "Overlapping roles", score,
        "; ".join(overlaps[:3]) if overlaps else "no overlaps",
    )


def score_tight_transitions(cv: Optional[dict]) -> Check:
    short = []
    for name, start, end in _timeline(cv):
        if start is None:
            continue
        end_index = month_index(*end) if end else start[0] * 12 + 11
        if end_index - month_index(*start) < 24:
            short.append(name)
    score = max(0, 100 - 10 * len(short))
    return Check(
        "hr.transitions", "HR Red Flags", "Tight transitions", score,
        f"{len(short)} roles under 24 months" if short else "no short roles",
    )


def score_bias(text: str) -> Check:
    hits = BIAS_RE.findall(text)
    return Check(
        "discrimination.bias", "Discrimination", "Bias signals", 0 if hits else 100,
        f"found: {', '.join(sorted(set(hits)))}" if hits else "none",
    )


def score_skill_evidence(cv: Optional[dict]) -> Check:
    if not cv:
        return Check("seniority.skills", "Seniority", "Skill evidence", 100, "no cv.json supplied")
    bullets = " ".join(_all_bullets(cv)).lower()
    tags = [t for group in cv.get("skills", []) for t in group.get("tags", [])]
    orphans = [t for t in tags if t.lower() not in bullets]
    tag_lower = {t.lower() for t in tags}
    hidden = [
        tok for tok in set(TECH_TOKEN_RE.findall(" ".join(_all_bullets(cv))))
        if tok.lower() not in tag_lower
    ]
    orphan_ratio = len(orphans) / len(tags) if tags else 0
    score = max(0, round(100 - 100 * orphan_ratio - 2 * len(hidden)))
    return Check(
        "seniority.skills", "Seniority", "Skill evidence", score,
        f"{len(orphans)} orphan skills, {len(hidden)} hidden skills",
    )


def _is_portuguese(cv: Optional[dict]) -> bool:
    """Portuguese CVs are identified by declaring Português in their languages.

    The tailored JSON carries no explicit lang key, so the language list is the
    reliable signal.
    """
    for entry in (cv or {}).get("languages", []):
        name = (entry.get("name") or "").strip().lower()
        if name.startswith("portugu") or name.startswith("português"):
            return True
    return False


def score_leadership(cv: Optional[dict]) -> Check:
    body = " ".join(_all_bullets(cv)).lower() if cv else ""
    words = list(LEADERSHIP_WORDS)
    if _is_portuguese(cv):
        words += LEADERSHIP_WORDS_PT
    hits = sorted({w for w in words if re.search(rf"\b{re.escape(w)}\b", body)})
    score = min(100, round(100 * len(hits) / 5))
    return Check(
        "seniority.leadership", "Seniority", "Leadership signals", score,
        f"signals: {', '.join(hits)}" if hits else "none",
    )


# ---- tailoring ----------------------------------------------

def jd_keywords(text: str) -> list[str]:
    tokens = WORD_RE.findall(text or "")
    out: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        low = token.lower().strip(".-/")
        if len(low) < 2 or low in JD_STOPWORDS or low in seen:
            continue
        if any(ch.isdigit() for ch in low) or _looks_like_domain(low):
            continue
        seen.add(low)
        out.append(low)
    return out


def score_tailoring(text: str, jd_text: str) -> tuple[Check, list[str]]:
    body = norm(text).lower()
    keywords = jd_keywords(jd_text)
    if not keywords:
        return Check("tailoring.keywords", "Tailoring", "Keyword coverage", 100, "empty JD"), []
    missing = [k for k in keywords if k not in body]
    coverage = (len(keywords) - len(missing)) / len(keywords)
    return (
        Check(
            "tailoring.keywords", "Tailoring", "Keyword coverage",
            round(100 * coverage),
            f"{len(keywords) - len(missing)}/{len(keywords)} JD keywords present",
        ),
        missing,
    )


def fetch_jd(source: str) -> str:
    """Load a JD from a local path or an http(s) URL (HTML is stripped)."""
    if source.startswith("http://") or source.startswith("https://"):
        with urllib.request.urlopen(source, timeout=15) as resp:  # noqa: S310
            raw = resp.read().decode("utf-8", errors="replace")
        return re.sub(r"<[^>]+>", " ", raw)
    return Path(source).read_text(encoding="utf-8")


# ---- judge --------------------------------------------------

JUDGE_PROMPT = (
    "You are an ATS resume judge. Given the resume text and an optional job "
    "description, return concise scores (0-100) for credibility, leadership "
    "signals, interview risk (higher is safer), and spelling/grammar, each with "
    "one sentence of justification. Do not invent facts.\n\nRESUME:\n{resume}\n\n"
    "JOB DESCRIPTION:\n{jd}\n"
)


def build_judge_prompt(resume_text: str, jd_text: str = "") -> str:
    return JUDGE_PROMPT.format(resume=resume_text, jd=jd_text or "(none provided)")


def run_judge(judge_cmd: str, resume_text: str, jd_text: str = "") -> str:
    """Run the configured judge command, feeding the prompt on stdin."""
    proc = subprocess.run(  # noqa: S603
        judge_cmd.split(),
        input=build_judge_prompt(resume_text, jd_text),
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if proc.returncode != 0:
        return f"judge command failed ({proc.returncode}): {proc.stderr.strip()[:200]}"
    return proc.stdout.strip()


# ---- orchestration ------------------------------------------

def run_checks(
    pdf_path: Path,
    cv: Optional[dict] = None,
    jd_text: str = "",
) -> AtsReport:
    report = AtsReport()
    if not pdf_path.exists():
        report.gates.append(
            Check("G0", "ATS Essentials", "PDF exists", 0, f"not found: {pdf_path}", gate=True)
        )
        return report

    text = extract_pdf_text(pdf_path)
    lines = extract_lines(pdf_path)

    report.gates = [
        gate_lines(text, lines),
        gate_single_column(lines),
        gate_reading_order(lines, cv),
        gate_sections(text),
        gate_dates(text, cv),
        gate_characters(text),
        gate_contact(text, cv),
        gate_completeness(text, cv),
        gate_file(pdf_path),
    ]

    gate_scores = [g.score for g in report.gates if g.key != "G0"]
    report.checks = [
        score_quantify(cv),
        score_repetition(cv),
        score_bullet_length(cv),
        score_essential_sections(text),
        score_contact_information(text),
        score_order(text),
        score_filename(pdf_path),
        score_gaps(cv),
        score_overlaps(cv),
        score_tight_transitions(cv),
        score_bias(text),
        score_skill_evidence(cv),
        score_leadership(cv),
    ]
    report.checks.append(
        Check(
            "ats.gates", "ATS Essentials", "Format gates",
            round(sum(gate_scores) / len(gate_scores)) if gate_scores else 0,
            f"{sum(1 for g in report.gates if g.passed)}/{len(report.gates)} gates passed",
        )
    )

    if jd_text.strip():
        check, missing = score_tailoring(text, jd_text)
        report.checks.append(check)
        report.missing_keywords = missing

    return report
