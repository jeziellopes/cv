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
import unicodedata
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
    engineer engineers engineering software era either clt brl usd salary
    salaries compensation contract hiring hire senior junior midlevel lead
    hotmart fullstack full-stack remote
    agency agencies adexchanger adweek artificial award awards brazil
    breakthrough business cannes contender creative digital excellence
    forrester fwas gartner global google group human-machine intelligence
    interaction lions magic manager marketing microsoft monks pioneer players
    power programmatic quadranttm solution top linkedin
    """.split()
) | set(
    """
    ou para com sem sob sobre sua suas seu seus nossa nosso nossas nossos você
    vocês estamos estão está está buscando busca buscar buscamos buscam
    contratando contratamos procuramos candidato candidata candidatos candidatas
    candidatar profissional profissionais vaga vagas integrar integração gosto
    gosta gostamos goste interessado interessada interesse interesses precisa
    precisamos precisar deve devem pode podem ter temos trabalhar trabalhamos
    trabalhará atuar atuando responsável responsáveis desenvolvimento desenvolver
    desenvolvedor desenvolvedora desenvolvedores desenvolvedoras equipe times
    desafios desafio oferecemos oferecer fazer vamos vai dia dias time
    conhecendo conhecemos pessoa pessoas são sao paulo pleno frontend backend
    de em da das do dos uma um uma uma vivência vivências também ainda mesmo
    mesma através entre dentro fora além muito muita todo toda todos todas ser
    sendo foi seja dentro partir assim bem menos mais já hoje coisa coisas
    boa bom criar criando criar participar participantes modelo modelos
    tecnologia tecnologias principal principais estacao estação brooklin berrini
    sp eou vivencia vivencias e/ou paulo/sp hibrido hibrida híbrido híbrida
    remoto remota presencial utilizar utilizando venha quer essa parte ao na
    que se
    """.split()
)


def _fold_accent(text: str) -> str:
    """Strip diacritics so 'vivência' matches 'vivencia' and never splits."""
    return "".join(
        c for c in unicodedata.normalize("NFKD", text or "")
        if unicodedata.category(c) != "Mn"
    )


# Membership is decided on the folded form: the raw list carries accented
# spellings ("vivência"), the folded JD tokens never do.
_JD_STOP = frozenset(_fold_accent(w) for w in JD_STOPWORDS)


def _looks_like_domain(token: str) -> bool:
    """Whether a token mentions a domain, however it is written in prose.

    A bare "monks.com/careers" in the JD body must read as the shop's website,
    not as a demanded term. "node.js" survives: no segment is a registered
    top-level domain.
    """
    if "." not in token:
        return False
    segments = re.split(r"[./]", token)
    return any(segment in DOMAIN_TLDS for segment in segments)


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

# "c#", "c++", "node.js", "ci/cd", "es6+", ".net": punctuation only a technical
# term carries.
_TECH_PUNCT_RE = re.compile(r"[.#+/]")
_ACRONYM_RE = re.compile(r"[A-Z]{2,}")

# A requirement phrased with "ou" ("or") is one requirement with more than one
# acceptable answer. "Vue.js ou React" asks for a component framework; answering
# with React satisfies it, so the alternative must not read as a second, unmet
# demand (the operator's rule, spec 0015).
_ALT_TERM_RE = re.compile(r"[A-Za-z][A-Za-z0-9+#.-]*")
_ALT_RUN_RE = re.compile(
    rf"(?:{_ALT_TERM_RE.pattern}\s*,\s*)?{_ALT_TERM_RE.pattern}"
    rf"(?:\s*,?\s*(?:ou|or)\s*{_ALT_TERM_RE.pattern})+",
    re.IGNORECASE)
_ALT_SPLIT_RE = re.compile(r"\s*,\s*|\s*,?\s*(?:ou|or)\s*", re.IGNORECASE)
_E_OU_RE = re.compile(r"\b(?:e|and)\s*/\s*(?:ou|or)\b", re.IGNORECASE)

# A token boundary that ends a sentence, a clause or a list item. A colon is
# deliberately absent: "Conhecimento: Python" labels a demand, it does not start
# a sentence, so the capital after it still reads as a proper noun.
_SENTENCE_END_CHARS = frozenset(".!?;\n•-*–—")
_JD_TERM_RE = re.compile(r"[A-Za-z][A-Za-z0-9+#./-]*")


def _names_something(raw: str, is_name: bool) -> bool:
    """Whether a JD token names a technology rather than prose."""
    # Trailing sentence punctuation is not tech punctuation: "pagamento." ends a
    # sentence, "node.js" names one.
    bare = raw.rstrip(".-/")
    if _TECH_PUNCT_RE.search(bare):
        return True
    if _ACRONYM_RE.fullmatch(bare):
        return True
    return is_name


def _opens_sentence(text: str, start: int) -> bool:
    """Whether the token at `start` opens a sentence, list item or bullet.

    Whitespace is skipped when looking back for the character that ended the
    previous thought, but a newline is itself the break: a JD written as one
    item per line gives every line its own first word.
    """
    index = start - 1
    while index >= 0 and text[index] in " \t\r":
        index -= 1
    return index < 0 or text[index] in _SENTENCE_END_CHARS


def _jd_tokens(text: str) -> list[tuple[str, bool]]:
    """The JD's tokens with original case, each flagged as a probable name.

    Case is what separates a proper noun from a capitalised first word, so the
    tokenizer keeps it and hands the filter both facts. A capitalised word is a
    name when it sits inside a sentence: every language capitalises the first
    word, and reading that as a proper noun is what let "Em", "Vivência" and
    "Desired Skills" through as demands. A word that owns the colon is a label
    ("Requisitos:", "Desired Skills:"), never a demand either. The slash belongs
    in the term so "ci/cd" stays one token instead of two meaningless halves.
    """
    folded = _fold_accent(text or "")
    out: list[tuple[str, bool]] = []
    for match in _JD_TERM_RE.finditer(folded):
        raw = match.group(0)
        capitalised = raw[:1].isupper()
        labels = folded[match.end():].lstrip().startswith(":")
        name = capitalised and not _opens_sentence(folded, match.start()) \
            and not labels
        out.append((raw, name))
    return out


def _run_terms(text: str) -> set[str]:
    """The terms of every either/or run, folded to lower case.

    "pytest ou JEST" names two technologies even though the posting wrote one
    in lower case, and shape alone would drop it. A sibling the filter already
    reads as a name is what says the run is technologies (ADR 0012).
    """
    out: set[str] = set()
    for terms in _alt_runs(text):
        if any(_names_something(t, t[:1].isupper()) for t in terms):
            out.update(t.lower() for t in terms)
    return out


def jd_keyword_stats(text: str) -> tuple[list[str], int]:
    """The JD's kept keywords and the pre-filter token count.

    The pre-filter count counts distinct content tokens after the trivial drops
    (length, duplicates, digits, domains) and before the keyword filter, so the
    filter's own effect is visible. One implementation backs jd_keywords,
    ats coverage, cv fit and search, so they cannot disagree on what a keyword
    is (spec 0016).

    A kept keyword is a demand: it names something buildable (ADR 0012). It
    qualifies by tech punctuation ("node.js", "c#", "ci/cd", "es6+"), by being
    written as a proper noun or acronym away from the start of a sentence
    ("Python", "Kubernetes", "API"), or by sitting in an either/or run beside
    such a name ("pytest ou JEST"). Capitalisation only counts in that second
    position, because every language capitalises a sentence's first word and
    reading that as a proper noun is what let "Vivência" and "Conhecimento"
    through as demands.
    """
    text = "\n".join(
        line for line in (text or "").splitlines()
        if not re.match(r"^\s*(?:apply[: ]*)?https?://", line.strip())
    )
    text = re.sub(r"https?://\S+", " ", text)
    named_by_run = _run_terms(text)
    seen: set[str] = set()
    kept: list[str] = []
    kept_seen: set[str] = set()
    total = 0
    for raw, is_name in _jd_tokens(text):
        low = _fold_accent(raw.lower()).strip(".-/")
        if len(low) < 2 or low in seen:
            continue
        if any(ch.isdigit() for ch in low) or _looks_like_domain(low):
            continue
        seen.add(low)
        total += 1
        if low in _JD_STOP or low in kept_seen:
            continue
        if not (_names_something(raw, is_name) or low in named_by_run):
            continue
        kept_seen.add(low)
        kept.append(low)
    return kept, total


def jd_keywords(text: str) -> list[str]:
    return jd_keyword_stats(text)[0]


def _alt_runs(text: str) -> list[list[str]]:
    """Every either/or run in the JD, split into its terms as written."""
    cleaned = re.sub(r"https?://\S+", " ", "\n".join(
        line for line in (text or "").splitlines()
        if not re.match(r"^\s*(?:apply[: ]*)?https?://", line.strip())))
    cleaned = _E_OU_RE.sub(" ou ", _fold_accent(cleaned))
    return [[t.strip(".-/") for t in _ALT_SPLIT_RE.split(match.group(0))]
            for match in _ALT_RUN_RE.finditer(cleaned)]


def jd_alternatives(text: str) -> list[list[str]]:
    """Groups of kept keywords a JD offers as alternatives to one another.

    A requirement phrased with "ou" ("or") is one requirement with more than
    one acceptable answer: "Vue.js ou React" asks for a component framework,
    and answering with React satisfies it, so the alternative must not read as
    a second, unmet demand (spec 0015).

    Returns each run as the keywords the JD kept, in the order it wrote them. A
    run is returned only when every member survives the keyword filter: a run
    with a stopword inside it ("Node ou , Typescript", "Vivência com Node ou ;
    Typescript") is prose rather than an either/or demand, and treating it as
    optional would silently drop a real requirement.

    Recognised connectors are the ones a posting uses for alternatives:
    "X ou Y", "X ou Y ou Z", "X, Y ou Z", "X e/ou Y", "X, Y and/or Z".
    """
    kept, _ = jd_keyword_stats(text)
    kept_set = set(kept)
    groups: list[list[str]] = []
    for run in _alt_runs(text):
        terms = [term.lower() for term in run]
        if len(terms) < 2 or any(term not in kept_set for term in terms):
            continue
        groups.append(terms)
    return _merge_alternatives(groups)


def _merge_alternatives(groups: list[list[str]]) -> list[list[str]]:
    """Fuse runs that share a keyword, so "A ou B ou C" stays one requirement."""
    merged: list[set[str]] = []
    for group in groups:
        members = set(group)
        pool = [g for g in merged if g & members]
        for other in pool:
            members |= other
        merged = [g for g in merged if not (g & members)]
        merged.append(members)
    return [sorted(g) for g in merged]


def alternative_keys(text: str) -> dict[str, set[str]]:
    """Map each keyword to the alternatives the JD allows in its place.

    A member maps to the whole group including itself, so one lookup answers
    "is this demanded term satisfiable by what the CV already claims?".
    """
    out: dict[str, set[str]] = {}
    for group in jd_alternatives(text):
        for term in group:
            out.setdefault(term, set()).update(group)
    return out


def jd_demands(text: str) -> list[list[str]]:
    """The JD's kept keywords as demands, with either/or runs kept together.

    One list entry is one thing the posting asks for. A single alternative in
    an entry means the JD named no alternative for it.
    """
    kept, _ = jd_keyword_stats(text)
    alts = alternative_keys(text)
    units: list[list[str]] = []
    claimed: set[str] = set()
    for keyword in kept:
        if keyword in claimed:
            continue
        group = sorted(alts.get(keyword, {keyword}))
        claimed.update(group)
        units.append(group)
    return units


def score_tailoring(text: str, jd_text: str) -> tuple[Check, list[str]]:
    body = _fold_accent(norm(text).lower())
    keywords = jd_keywords(jd_text)
    if not keywords:
        # A JD the filter cannot read a single demand from is not a free pass:
        # reporting 100 would claim coverage nobody measured.
        total = jd_keyword_stats(jd_text)[1]
        if total:
            return Check("tailoring.keywords", "Tailoring", "Keyword coverage",
                         0, f"no demand found in {total} JD words"), []
        return Check("tailoring.keywords", "Tailoring", "Keyword coverage", 100, "empty JD"), []
    # Alternatives collapse to one demand: the JD asked for one of them, so
    # holding any one covers the requirement, and only a wholly unmet group is
    # a miss.
    demanded = jd_demands(jd_text)
    missing = [g for g in demanded if not any(k in body for k in g)]
    coverage = (len(demanded) - len(missing)) / len(demanded)
    return (
        Check(
            "tailoring.keywords", "Tailoring", "Keyword coverage",
            round(100 * coverage),
            f"{len(demanded) - len(missing)}/{len(demanded)} JD demands present",
        ),
        [" or ".join(g) if len(g) > 1 else g[0] for g in missing],
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
