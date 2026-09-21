#!/usr/bin/env python3
# ============================================================
# cv: CLI
# Install:  pip install -e .
# Usage:
#   cv generate                                  → index.html (cv.json, classic)
#   cv generate --pdf                            → index.html + resume-en.pdf
#   cv generate --company <name> --pdf           → companies/<name>/JezielLopesCarvalho-en.pdf
#   cv generate --lang pt --theme modern --pdf
#   cv new acme                                  → scaffold companies/acme/cv-en.json
#
# Available themes: classic (default), modern, minimal
# Available languages: en (default), pt
# ============================================================

import json
import re
import sys
import html as _html
import shutil
from pathlib import Path
from typing import Optional

import typer
from typing_extensions import Annotated

import ats
import search as searchmod

BASE_DIR = Path(__file__).resolve().parent

app = typer.Typer(help="cv: edit cv.json, run one command, get a PDF.")

# ---- helpers ------------------------------------------------

# Variants ATS parsers choke on; normalised to ASCII at the output boundary.
_GLYPHS = str.maketrans({
    "\u2013": "-",   # en dash
    "\u2014": "-",   # em dash
    "\u2212": "-",   # minus sign
    "\u2011": "-",   # non-breaking hyphen
    "\u00a0": " ",   # non-breaking space
    "\u200b": "",    # zero-width space
    "\u200c": "",    # zero-width non-joiner
    "\u200d": "",    # zero-width joiner
    "\u2315": "",    # option key glyph
})

def esc(s=""):
    return _html.escape(str(s or "").translate(_GLYPHS), quote=True)

def date_range(start, end):
    return f"{esc(start)} - {esc(end)}"

def bullets(items):
    return "\n".join(
        f'      <li>{esc(b)}</li>'
        for b in (items or [])
    )

def experience_item(e):
    return f"""
    <article class="item">
      <h3 class="item-org">{esc(e["org"])}</h3>
      <p class="item-role">{esc(e["role"])}</p>
      <p class="item-meta">{esc(e["location"])} | {date_range(e["start"], e["end"])}</p>
      <ul class="bullet-list">
{bullets(e.get("bullets", []))}
      </ul>
    </article>"""

def education_item(e):
    return f"""
    <article class="item">
      <h3 class="item-org">{esc(e["institution"])}</h3>
      <p class="item-role">{esc(e["degree"])}</p>
      <p class="item-meta">{esc(e["location"])} | {date_range(e["start"], e["end"])}</p>
      <ul class="bullet-list">
{bullets(e.get("bullets", []))}
      </ul>
    </article>"""

def course_item(c):
    return f"""
    <p class="course-item">{esc(c["title"])} | {esc(c["institution"])}</p>"""

def skill_group(s):
    tags = ", ".join(esc(t) for t in s["tags"])
    return f"""
    <p class="skill-group"><span class="skill-label">{esc(s["group"])}:</span> {tags}</p>"""

def dot(filled):
    cls = "dot-filled" if filled else "dot-empty"
    return f'<span class="dot {cls}"></span>'

def language_item(lang):
    dots = "".join(dot(i < lang["dots"]) for i in range(5))
    return f"""
    <p class="language-item"><span class="language-name">{esc(lang["name"])}</span> <span class="language-level">{esc(lang["level"])}</span> <span class="language-dots">{dots}</span></p>"""

def contact_item(text, href=None):
    if href:
        return f'<a class="contact-item" href="{esc(href)}" target="_blank">{esc(text)}</a>'
    return f'<span class="contact-item">{esc(text)}</span>'

SEP = ' <span class="contact-separator">|</span> '

# ---- themes -------------------------------------------------
# Each theme provides:
#   fonts_url  – Google Fonts <link> href  (or "" for system fonts)
#   css_vars   – :root variable block (controls colors / fonts)
#   extra_css  – any additional CSS unique to the theme

PAGE_MARGIN = 50  # px, shared by all themes

_STRUCTURAL_CSS = f"""
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

body {{
  font-family: var(--font-body);
  color: var(--color-text);
  background: #e8e8e8;
}}

.resume {{
  width: 794px;
  background: #ffffff;
  margin: 40px auto 40px;
  padding: var(--page-margin);
  box-shadow: 0 2px 8px rgba(0,0,0,.18);
}}

.resume-header {{ text-align: center; margin-bottom: 6px; padding: 6px 12px; }}

.header-name {{
  font-family: var(--font-heading);
  font-weight: 700; font-size: 22px; line-height: 28px;
  text-transform: uppercase; color: var(--color-accent);
}}

.header-title {{
  font-family: var(--font-body);
  font-weight: 400; font-size: 18px; line-height: 22px;
  color: var(--color-muted); margin-top: 2px;
}}

.contact-line {{ margin-top: 4px; font-family: var(--font-body); font-size: 13px; line-height: 18px; }}
.contact-item {{ color: inherit; text-decoration: none; }}
.contact-separator {{ margin: 0 6px; color: var(--color-muted); }}

.section {{ margin-bottom: 12px; }}

.section-title {{
  font-family: var(--font-heading);
  font-size: 18px; line-height: 23px; color: var(--color-accent);
  border-bottom: 1px solid var(--color-border);
  padding: 6px 12px 0; margin-bottom: 0;
  break-after: avoid;
}}

.item {{ padding: 6px 12px; break-inside: avoid; }}
.item-org {{ font-family: var(--font-body); font-weight: 700; font-size: 18px; line-height: 22px; color: var(--color-muted); }}
.item-role {{ font-family: var(--font-body); font-weight: 400; font-size: 15px; line-height: 18px; color: var(--color-text); }}
.item-meta {{ font-family: var(--font-body); font-size: 15px; line-height: 18px; color: var(--color-text); }}

.bullet-list {{ list-style: disc outside; margin: 4px 0 0 18px; }}
.bullet-list li {{ font-family: var(--font-body); font-size: 13px; line-height: 18px; }}

.summary-text {{ font-family: var(--font-body); font-size: 13px; line-height: 18px; white-space: pre-wrap; }}

.skill-group {{ font-family: var(--font-body); font-size: 13px; line-height: 18px; padding: 6px 12px; }}
.skill-label {{ font-weight: 700; color: var(--color-muted); }}

.language-item {{ font-family: var(--font-body); font-size: 15px; line-height: 18px; padding: 6px 12px; }}
.language-level {{ font-size: 13px; color: var(--color-muted); }}
.language-dots {{ display: inline-flex; gap: 4px; margin-left: 4px; vertical-align: middle; }}
.dot {{ width: 8px; height: 8px; border-radius: 50%; display: inline-block; }}
.dot-filled {{ background: var(--color-accent); }}
.dot-empty  {{ background: #e4e4e4; }}

.course-item {{ font-family: var(--font-body); font-size: 15px; line-height: 18px; padding: 6px 12px; break-inside: avoid; }}

@media print {{
  body  {{ background: none; }}
  .resume {{ width: 100%; margin: 0; padding: 0; box-shadow: none; }}
}}

@page {{ size: A4; margin: {PAGE_MARGIN}px; }}
"""

THEMES = {
    # ── Classic ─────────────────────────────────────────────
    # Exact port of the original JS design: Volkhov serif headings,
    # PT Sans body, black text, muted grey, no accent colour.
    "classic": {
        "fonts_url": (
            "https://fonts.googleapis.com/css2?"
            "family=Volkhov:wght@400;700&family=PT+Sans:wght@400;700&display=swap"
        ),
        "css_vars": f"""
:root {{
  --font-heading: 'Volkhov', Arial, Helvetica, sans-serif;
  --font-body:    'PT Sans', Arial, Helvetica, sans-serif;
  --color-text:   #000000;
  --color-muted:  #6f7878;
  --color-border: #000000;
  --color-accent: #000000;
  --page-margin:  {PAGE_MARGIN}px;
}}""",
        "extra_css": "",
    },

    # ── Modern ──────────────────────────────────────────────
    # Inter font throughout; blue accent on name, section titles,
    # and filled language dots; slightly softer border.
    "modern": {
        "fonts_url": (
            "https://fonts.googleapis.com/css2?"
            "family=Inter:wght@400;600;700&display=swap"
        ),
        "css_vars": f"""
:root {{
  --font-heading: 'Inter', system-ui, sans-serif;
  --font-body:    'Inter', system-ui, sans-serif;
  --color-text:   #111827;
  --color-muted:  #6b7280;
  --color-border: #2563eb;
  --color-accent: #2563eb;
  --page-margin:  {PAGE_MARGIN}px;
}}""",
        "extra_css": """
/* Modern: slightly bolder section titles */
.section-title { font-weight: 700; letter-spacing: 0.03em; }
.header-name   { letter-spacing: 0.06em; }
""",
    },

    # ── Minimal ─────────────────────────────────────────────
    # IBM Plex Sans; very light grey palette; no bold contrast; clean and understated.
    "minimal": {
        "fonts_url": (
            "https://fonts.googleapis.com/css2?"
            "family=IBM+Plex+Sans:wght@300;400;600&display=swap"
        ),
        "css_vars": f"""
:root {{
  --font-heading: 'IBM Plex Sans', system-ui, sans-serif;
  --font-body:    'IBM Plex Sans', system-ui, sans-serif;
  --color-text:   #1a1a1a;
  --color-muted:  #888888;
  --color-border: #cccccc;
  --color-accent: #1a1a1a;
  --page-margin:  {PAGE_MARGIN}px;
}}""",
        "extra_css": """
/* Minimal: lighter weight headings, subdued section divider */
.section-title  { font-weight: 600; font-size: 14px; letter-spacing: 0.12em;
                  text-transform: uppercase; border-bottom-width: 1px; }
.header-name    { font-weight: 600; letter-spacing: 0.08em; }
.item-org       { font-size: 15px; }
.dot-empty      { background: #e0e0e0; }
""",
    },
}

# ---- build CSS ----------------------------------------------

def build_css(theme_name):
    theme = THEMES.get(theme_name)
    if not theme:
        known = ", ".join(THEMES)
        sys.exit(f"Unknown theme '{theme_name}'. Available: {known}")
    return theme["css_vars"] + "\n" + _STRUCTURAL_CSS + "\n" + theme["extra_css"]

def build_fonts_link(theme_name):
    url = THEMES[theme_name]["fonts_url"]
    if not url:
        return ""
    return (
        '<link rel="preconnect" href="https://fonts.googleapis.com" />\n'
        '  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />\n'
        f'  <link href="{url}" rel="stylesheet" />'
    )

# ---- HTML builder -------------------------------------------

def build_html(cv: dict, theme_name: str) -> str:
    p = cv["personal"]
    sal = cv.get("salary_expectation")
    
    # Build line 2 items (portfolio, github, location)
    line2_items = []
    if p.get("portfolio"):
        line2_items.append(contact_item(p["portfolio"], p["portfolio"]))
    if p.get("github"):
        line2_items.append(contact_item(p["github"], p["github"]))
    line2_items.append(contact_item(p["location"]))
    line2_html = SEP.join(line2_items)
    
    salary_row = ""
    if sal:
        parts = [esc(sal["amount"])]
        if sal.get("contract"):
            parts.append(esc(sal["contract"]))
        if sal.get("note"):
            parts.append(esc(sal["note"]))
        salary_row = f"""
    <p class="contact-line">{contact_item("Salary expectation: " + " | ".join(parts))}</p>"""
    
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{esc(p["name"])} - Resume</title>
  {build_fonts_link(theme_name)}
  <!-- Generated by cv: edit cv.json, not this file -->
  <style>{build_css(theme_name)}</style>
</head>
<body>

<div class="resume">

  <header class="resume-header">
    <h1 class="header-name">{esc(p["name"])}</h1>
    <p class="header-title">{esc(p["title"])}</p>
    <p class="contact-line">
      {contact_item(p["phone"])}{SEP}{contact_item(p["email"], f'mailto:{p["email"]}')}{SEP}{contact_item(p["linkedin"], p["linkedin"])}
    </p>
    <p class="contact-line">
      {line2_html}
    </p>{salary_row}
  </header>

  <section class="section">
    <h2 class="section-title">Summary</h2>
    <p class="summary-text">{esc(cv["summary"])}</p>
  </section>

  <section class="section">
    <h2 class="section-title">Experience</h2>
    {"".join(experience_item(e) for e in cv["experience"])}
  </section>

  <section class="section">
    <h2 class="section-title">Education</h2>
    {"".join(education_item(e) for e in cv["education"])}
  </section>

  <section class="section">
    <h2 class="section-title">Training / Courses</h2>
    {"".join(course_item(c) for c in cv["courses"])}
  </section>

  <section class="section">
    <h2 class="section-title">Skills</h2>
    {"".join(skill_group(s) for s in cv["skills"])}
  </section>

  <section class="section">
    <h2 class="section-title">Languages</h2>
    {"".join(language_item(lang_item) for lang_item in cv["languages"])}
  </section>

</div>

</body>
</html>"""

# ---- translation helpers ------------------------------------

def get_keywords_to_preserve():
    """Return a list of English keywords that should be preserved during translation."""
    return [
        # Technologies
        "React", "React Native", "React Hooks", "Context API", "Redux",
        "Node.js", "NestJS", "Express",
        "TypeScript", "JavaScript", "ES6+", "ES5",
        "HTML5", "CSS3",
        "API", "REST", "REST API", "REST APIs", "WebSockets",
        "SQL", "NoSQL",
        # Frameworks & Tools
        "Storybook", "Radix UI", "Styled-Components",
        "Vite", "Webpack", "Gatsby",
        "Jest", "Testing Library", "Cypress", "Vitest",
        "React Hook Form", "Zod",
        "TanStack Router",
        "Zustand",
        "Docker", "Kubernetes", "Lambda",
        # Architecture
        "microservices", "cloud-native", "design system", "design systems",
        "monolithic MVC", "Repository Pattern", "CI/CD",
        "observability", "SRE",
        # Practices
        "code quality", "code reviews", "performance optimization",
        "accessibility", "responsive design",
        "TDD", "SDD", "test-driven development", "spec-driven development",
        "mentorship", "technical excellence",
        "agile", "backlog refinement",
        # Roles & Companies
        "frontend", "backend", "full-stack",
        "Senior", "Developer", "Engineer",
        "ioasys", "BR Media Group", "Base Exchange", "Flowa", "Flowa Technologies",
        "AWS", "AWS S3", "LinkedIn",
    ]

def translate_text_with_keywords(text: str, source_lang: str = "en", target_lang: str = "pt") -> str:
    """
    Translate text while preserving English keywords.
    
    Args:
        text: Text to translate
        source_lang: Source language code
        target_lang: Target language code
    
    Returns:
        Translated text with keywords preserved
    """
    keywords = get_keywords_to_preserve()
    
    # Create placeholder map
    placeholder_map = {}
    placeholders_text = text
    
    # Replace keywords with placeholders (case-insensitive)
    for i, keyword in enumerate(keywords):
        pattern = r'\b' + re.escape(keyword) + r'\b'
        if re.search(pattern, placeholders_text, re.IGNORECASE):
            placeholder = f"{{TECH_{i}}}"
            placeholders_text = re.sub(pattern, placeholder, placeholders_text, flags=re.IGNORECASE)
            placeholder_map[placeholder] = keyword
    
    # Translate using google-translate-api
    try:
        from google_translate_api import translate
        translated = translate(placeholders_text, source_lang, target_lang)
    except ImportError:
        typer.echo("⚠ google-translate-api not installed. Install with: pip install google-translate-api")
        return text
    
    # Restore keywords
    for placeholder, keyword in placeholder_map.items():
        translated = translated.replace(placeholder, keyword)
    
    return translated

# ---- CLI commands -------------------------------------------

def resolve_paths(company, lang):
    if company:
        company_dir = BASE_DIR / "companies" / company
        cv_path = company_dir / f"cv-{lang}.json"
        pdf_out = company_dir / f"JezielLopesCarvalho-{lang}.pdf"
    else:
        cv_filename = "cv.json" if lang == "en" else f"cv-{lang}.json"
        cv_path = BASE_DIR / cv_filename
        pdf_out = BASE_DIR / f"resume-{lang}.pdf"
    return cv_path, pdf_out, BASE_DIR / "index.html"


@app.command()
def generate(
    company: Annotated[Optional[str], typer.Option("--company", "-c", help="Company ID (reads companies/{id}/cv-{lang}.json, outputs companies/{id}/JezielLopesCarvalho-{lang}.pdf)")] = None,
    lang: Annotated[str, typer.Option("--lang", "-l", help="Language code (en, pt)")] = "en",
    theme: Annotated[str, typer.Option("--theme", "-t", help="Theme: classic, modern, minimal")] = "classic",
    pdf: Annotated[bool, typer.Option("--pdf", help="Export PDF after rendering HTML")] = False,
):
    """Render cv.json to index.html and optionally export a PDF."""
    cv_path, pdf_out, html_out = resolve_paths(company, lang)

    if not cv_path.exists():
        typer.echo(f"✖ CV file not found: {cv_path.relative_to(BASE_DIR)}", err=True)
        raise typer.Exit(1)

    if theme not in THEMES:
        typer.echo(f"✖ Unknown theme '{theme}'. Available: {', '.join(THEMES)}", err=True)
        raise typer.Exit(1)

    with open(cv_path, encoding="utf-8") as f:
        cv = json.load(f)

    html_out.write_text(build_html(cv, theme), encoding="utf-8")
    company_info = f", company: {company}" if company else ""
    typer.echo(f"✔ index.html written  (lang: {lang}, theme: {theme}{company_info})")

    if pdf:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            typer.echo(
                "✖ Playwright is not installed.\n"
                "  Run: pip install playwright && playwright install chromium",
                err=True,
            )
            raise typer.Exit(1)

        pdf_out.parent.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(args=["--no-sandbox"])
            page = browser.new_page()
            page.goto(f"file://{html_out}", wait_until="networkidle")
            page.wait_for_timeout(800)   # let Google Fonts render
            page.pdf(
                path=str(pdf_out),
                format="A4",
                print_background=True,
                margin={
                    "top":    f"{PAGE_MARGIN}px",
                    "right":  f"{PAGE_MARGIN}px",
                    "bottom": f"{PAGE_MARGIN}px",
                    "left":   f"{PAGE_MARGIN}px",
                },
            )
            browser.close()

        typer.echo(f"✔ {pdf_out.relative_to(BASE_DIR)} written")


def _print_report(report, jd_text=""):
    typer.echo("\nATS format gates")
    for g in report.gates:
        mark = "✔" if g.passed else "✖"
        typer.echo(f"  {mark} {g.key} {g.title}: {g.detail}")
    typer.echo(f"\nScorecard ({report.overall}/100)")
    for category, score in report.categories.items():
        typer.echo(f"  {category}: {score}%")
    for check in report.checks:
        if check.key == "ats.gates":
            continue
        typer.echo(f"    - {check.title}: {check.score}% ({check.detail})")
    if jd_text.strip():
        keyword = next((c for c in report.checks if c.key == "tailoring.keywords"), None)
        if keyword:
            typer.echo(f"\nJD tailoring: {keyword.score}% coverage")
        if report.missing_keywords:
            typer.echo(f"  missing: {', '.join(report.missing_keywords[:20])}")
    if report.judge:
        typer.echo(f"\nLLM judge (non-deterministic)\n{report.judge}")
    if report.gates_passed:
        typer.echo("\n✔ All ATS gates passed")
    else:
        typer.echo("\n✖ ATS gates failed", err=True)


@app.command("ats-check")
def ats_check(
    company: Annotated[Optional[str], typer.Option("--company", "-c", help="Company ID")] = None,
    lang: Annotated[str, typer.Option("--lang", "-l", help="Language code")] = "en",
    pdf: Annotated[Optional[Path], typer.Option("--pdf", help="Explicit PDF path")] = None,
    cv_file: Annotated[Optional[Path], typer.Option("--cv", help="Explicit cv.json path")] = None,
    jd: Annotated[Optional[str], typer.Option("--jd", help="JD file path or http(s) URL")] = None,
    judge: Annotated[bool, typer.Option("--judge", help="Run the optional LLM judge")] = False,
    judge_cmd: Annotated[str, typer.Option("--judge-cmd", help="Judge command")] = "claude -p",
    strict: Annotated[bool, typer.Option("--strict", help="Also fail below score thresholds")] = False,
    min_score: Annotated[int, typer.Option("--min-score", help="Overall score floor in strict mode")] = 90,
    min_coverage: Annotated[float, typer.Option("--min-coverage", help="JD coverage floor in strict mode")] = 0.60,
    as_json: Annotated[bool, typer.Option("--json", help="Emit machine-readable JSON")] = False,
):
    """Check a generated CV PDF for ATS safety and score it."""
    cv_path, pdf_path, _ = resolve_paths(company, lang)
    if pdf:
        pdf_path = pdf
    if cv_file:
        cv_path = cv_file
    if not pdf_path.exists():
        typer.echo(f"✖ PDF not found: {pdf_path}", err=True)
        raise typer.Exit(1)

    cv = json.loads(cv_path.read_text(encoding="utf-8")) if cv_path.exists() else None

    jd_text = ""
    if jd:
        try:
            jd_text = ats.fetch_jd(jd)
        except Exception as exc:  # noqa: BLE001
            typer.echo(f"⚠ could not load JD: {exc}", err=True)
    elif company:
        auto = BASE_DIR / "companies" / company / "description.md"
        if auto.exists():
            jd_text = auto.read_text(encoding="utf-8")

    report = ats.run_checks(pdf_path, cv=cv, jd_text=jd_text)

    if judge:
        report.judge = ats.run_judge(judge_cmd, ats.extract_pdf_text(pdf_path), jd_text)

    if as_json:
        typer.echo(json.dumps(report.to_dict(), indent=2))
    else:
        _print_report(report, jd_text)

    if not report.gates_passed:
        raise typer.Exit(1)
    if strict:
        if report.overall < min_score:
            typer.echo(f"✖ overall score {report.overall} < {min_score}", err=True)
            raise typer.Exit(1)
        if jd_text.strip():
            keyword = next((c for c in report.checks if c.key == "tailoring.keywords"), None)
            if keyword and keyword.score < min_coverage * 100:
                typer.echo(f"✖ JD coverage {keyword.score}% < {min_coverage:.0%}", err=True)
                raise typer.Exit(1)


@app.command()
def search(
    query: Annotated[Optional[str], typer.Argument(help="Search query, e.g. 'react senior remote'. Ignored with --import")] = None,
    source: Annotated[str, typer.Option("--source", "-s", help="Job source: remotive, remoteok, linkedin")] = "remotive",
    limit: Annotated[int, typer.Option("--limit", "-n", help="Max results to show")] = 10,
    import_file: Annotated[Optional[Path], typer.Option("--import", help="Rank jobs from a JSON file (e.g. a LinkedIn extension export)")] = None,
    ingest: Annotated[Optional[int], typer.Option("--ingest", help="Write ranked result #N as a JD to companies/<slug>/description.md")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Emit machine-readable JSON")] = False,
):
    """Search job sources and rank the best matches for this CV."""
    if import_file:
        if not import_file.exists():
            typer.echo(f"✖ import file not found: {import_file}", err=True)
            raise typer.Exit(1)
        jobs = searchmod.from_file(import_file)
    else:
        if not query:
            typer.echo("✖ a query is required unless --import is used", err=True)
            raise typer.Exit(2)
        try:
            jobs = searchmod.SOURCES[source](query, limit * 5)
        except KeyError:
            typer.echo(f"✖ unknown source '{source}'. Available: {searchmod.known_sources()}", err=True)
            raise typer.Exit(2)
        except Exception as exc:  # noqa: BLE001
            typer.echo(f"✖ could not reach {source}: {exc}", err=True)
            raise typer.Exit(1)

    cv = json.loads((BASE_DIR / "cv.json").read_text(encoding="utf-8"))
    ranked = searchmod.rank(jobs, cv)[:limit]
    if not ranked:
        typer.echo("✖ no jobs found for the query", err=True)
        raise typer.Exit(1)

    if as_json:
        typer.echo(json.dumps([
            {"rank": i, "fit": r.fit, "title": r.job.title, "company": r.job.company,
             "location": r.job.location, "url": r.job.url, "source": r.job.source}
            for i, r in enumerate(ranked, 1)
        ], indent=2))
        return

    typer.echo(f"Best matches for '{query or import_file}' (fit = how well the CV covers the JD)")
    for i, r in enumerate(ranked, 1):
        mark = " *" if ingest == i else ""
        typer.echo(f"  {i:>2}. {r.fit:>3}%  {r.job.title} @ {r.job.company} ({r.job.location}){mark}")
        typer.echo(f"        {r.job.url}")

    if ingest:
        if not 1 <= ingest <= len(ranked):
            typer.echo(f"✖ --ingest {ingest} is out of range (1-{len(ranked)})", err=True)
            raise typer.Exit(1)
        target = ranked[ingest - 1].job
        path = searchmod.ingest(target, BASE_DIR)
        typer.echo(f"✔ JD written to {path.relative_to(BASE_DIR)}")
        typer.echo(f"  Next: cv generate --company {path.parent.name} --pdf && cv ats-check --company {path.parent.name}")


@app.command()
def new(
    company_id: Annotated[str, typer.Argument(help="Company ID to scaffold (e.g. acme)")],
    lang: Annotated[str, typer.Option("--lang", "-l", help="Language code")] = "en",
):
    """Scaffold a new company CV from the base cv.json."""
    company_dir = BASE_DIR / "companies" / company_id
    dest = company_dir / f"cv-{lang}.json"

    if dest.exists():
        typer.echo(f"✖ {dest.relative_to(BASE_DIR)} already exists.", err=True)
        raise typer.Exit(1)

    src = BASE_DIR / ("cv.json" if lang == "en" else f"cv-{lang}.json")
    if not src.exists():
        typer.echo(f"✖ Base CV not found: {src.name}", err=True)
        raise typer.Exit(1)

    company_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(src, dest)
    typer.echo(f"✔ Scaffolded {dest.relative_to(BASE_DIR)}")
    typer.echo("  Next: edit the file, then run:")
    typer.echo(f"    cv generate --company {company_id} --pdf")


@app.command()
def translate(
    text: Annotated[str, typer.Option("--text", "-t", help="Text to translate")] = "",
    source_lang: Annotated[str, typer.Option("--from", "-f", help="Source language")] = "en",
    target_lang: Annotated[str, typer.Option("--to", "-o", help="Target language")] = "pt",
):
    """Translate text while preserving English technical keywords."""
    if not text:
        typer.echo("Please provide text to translate using --text option.", err=True)
        raise typer.Exit(1)
    
    result = translate_text_with_keywords(text, source_lang, target_lang)
    typer.echo(f"\n{result}\n")


if __name__ == "__main__":
    app()

