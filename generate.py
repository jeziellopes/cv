#!/usr/bin/env python3
# ============================================================
# cv: CLI
# Install:  pip install -e .
# Usage:
#   cv generate                                  → index.html (cv.json, classic)
#   cv generate --pdf                            → index.html + resume-en.pdf
#   cv generate --company <name> --pdf           → companies/<name>/<CandidateName>-en.pdf
#   cv generate --lang pt --theme modern --pdf
#   cv new acme                                  → scaffold companies/acme/cv-en.json
#
# Available themes: classic (default), modern, minimal
# Available languages: en (default), pt
# ============================================================

import json
import os
import re
import sys
import html as _html
import shutil
import unicodedata
from pathlib import Path
from typing import Optional

import typer
from typing_extensions import Annotated

import ats
import evidence
import guards
import inbox
import search as searchmod

BASE_DIR = Path(__file__).resolve().parent
BANNER_FONT = "slant"
BANNER_TEXT = "cv"
BANNER_HEADLINE = "A free, open-source resume generator"


def _version() -> str:
    try:
        text = (BASE_DIR / "pyproject.toml").read_text()
    except OSError:
        return "0.0.0"
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
    return match.group(1) if match else "0.0.0"


def _show_banner(compact: bool = False) -> None:
    """Print the ASCII banner unless compact mode is on or pyfiglet is missing."""
    if compact:
        return
    try:
        import pyfiglet
    except ImportError:
        return
    try:
        banner = pyfiglet.figlet_format(BANNER_TEXT, font=BANNER_FONT)
    except Exception:
        return
    lines = [line for line in banner.splitlines() if line.strip()]
    width = max(len(line) for line in lines)
    mid = len(lines) // 2
    version = f"v{_version()}"
    for i, line in enumerate(lines):
        right = version if i == mid - 1 else BANNER_HEADLINE if i == mid else ""
        print(f"  {line.ljust(width)}   {right}".rstrip() if right else f"  {line}")
    print()


app = typer.Typer(
    help="cv: edit cv.json, run one command, get a PDF.",
    invoke_without_command=True,
)

# Captures from the browser extension land in a queue the operator works
# through, so the tailoring step never starts from a pasted file.
app.add_typer(inbox.app, name="inbox")

# Evidence scanning and the project/naming view are their own concern.
app.add_typer(evidence.app)

# The honesty guards: reproducible figures, and publishable names.
app.add_typer(guards.claims_app, name="claims")
app.add_typer(guards.names_app, name="names")


@app.callback(invoke_without_command=True)
def root(
    ctx: typer.Context,
    compact: Annotated[
        bool,
        typer.Option("--compact", help="Hide the banner and print less."),
    ] = False,
) -> None:
    if ctx.invoked_subcommand is None:
        if not compact:
            _show_banner()
        typer.echo(ctx.get_help())
        raise typer.Exit()

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
.section.keep-together {{ break-inside: avoid; }}

.section-title {{
  font-family: var(--font-heading);
  font-size: 18px; line-height: 23px; color: var(--color-accent);
  border-bottom: 1px solid var(--color-border);
  padding: 6px 12px 0; margin-bottom: 0;
  break-after: avoid;
}}

.item {{ padding: 6px 12px; break-inside: avoid; }}
.item-org {{ font-family: var(--font-body); font-weight: 700; font-size: 18px; line-height: 22px; color: var(--color-muted); break-after: avoid; }}
.item-role {{ font-family: var(--font-body); font-weight: 400; font-size: 15px; line-height: 18px; color: var(--color-text); break-after: avoid; }}
.item-meta {{ font-family: var(--font-body); font-size: 15px; line-height: 18px; color: var(--color-text); break-after: avoid; }}

.bullet-list {{ list-style: disc outside; margin: 4px 0 0 18px; }}
.bullet-list li {{ font-family: var(--font-body); font-size: 13px; line-height: 18px; break-inside: avoid; }}

.summary-text {{ font-family: var(--font-body); font-size: 13px; line-height: 18px; white-space: pre-wrap; }}

.skill-group {{ font-family: var(--font-body); font-size: 13px; line-height: 18px; padding: 6px 12px; break-inside: avoid; }}
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

  <section class="section keep-together">
    <h2 class="section-title">Education</h2>
    {"".join(education_item(e) for e in cv["education"])}
  </section>

  <section class="section keep-together">
    <h2 class="section-title">Training / Courses</h2>
    {"".join(course_item(c) for c in cv["courses"])}
  </section>

  <section class="section keep-together">
    <h2 class="section-title">Skills</h2>
    {"".join(skill_group(s) for s in cv["skills"])}
  </section>

  <section class="section keep-together">
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

def candidate_filename_stem(cv_path: Path) -> str:
    """The PDF filename stem, taken from the CV rather than hardcoded.

    A tailored PDF is named for the candidate it describes, so the name is
    data in cv.json and never a literal in this module.
    """
    try:
        cv = json.loads(cv_path.read_text())
        name = cv["personal"]["name"]
    except (OSError, ValueError, KeyError, TypeError):
        return "cv"
    ascii_name = unicodedata.normalize("NFKD", name)
    ascii_name = "".join(c for c in ascii_name if not unicodedata.combining(c))
    return "".join(ascii_name.split()) or "cv"


def resolve_paths(company, lang):
    if company:
        company_dir = BASE_DIR / "companies" / company
        cv_path = company_dir / f"cv-{lang}.json"
        pdf_out = company_dir / f"{candidate_filename_stem(cv_path)}-{lang}.pdf"
    else:
        cv_filename = "cv.json" if lang == "en" else f"cv-{lang}.json"
        cv_path = BASE_DIR / cv_filename
        pdf_out = BASE_DIR / f"{candidate_filename_stem(cv_path)}-{lang}.pdf"
    return cv_path, pdf_out, BASE_DIR / "index.html"


def resolve_browsers_path():
    """Resolve the Playwright browser directory: env var, then .cv-env, else default."""
    env = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if env:
        return env
    cv_env = BASE_DIR / ".cv-env"
    if cv_env.exists():
        for line in cv_env.read_text(encoding="utf-8").splitlines():
            if line.startswith("PLAYWRIGHT_BROWSERS_PATH="):
                return line.split("=", 1)[1].strip().strip('"')
    return ""


@app.command()
def generate(
    company: Annotated[Optional[str], typer.Option("--company", "-c", help="Company ID (reads companies/{id}/cv-{lang}.json, writes companies/{id}/<CandidateName>-{lang}.pdf)")] = None,
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
        browsers = resolve_browsers_path()
        if browsers:
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = browsers
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


def _company_label(cv_path: Path) -> str:
    """A stable name for a tailored CV, nested or flat."""
    folder = cv_path.parent
    if folder.parent.name == "companies":
        return folder.name
    return f"{folder.parent.name}/{folder.name}"


def _ats_check_every(lang: str) -> None:
    """Score every tailored CV and report, so one can be compared to the rest."""
    root = BASE_DIR / "companies"
    rows: list[tuple[str, Optional[int], bool, str]] = []
    worst = 0

    for cv_path in sorted(root.rglob(f"cv-{lang}.json")):
        folder = cv_path.parent
        # Pick the PDF for this language, not merely the first one present: a
        # folder can hold both cv-en and cv-pt, and scoring one against the
        # other's CV reports a failure that is not real.
        candidates = sorted(folder.glob(f"*-{lang}.pdf"))
        pdfs = candidates or sorted(folder.glob("*.pdf"))
        if not pdfs:
            rows.append((_company_label(cv_path), None, False, "no PDF"))
            continue
        try:
            cv = json.loads(cv_path.read_text(encoding="utf-8"))
        except ValueError:
            rows.append((_company_label(cv_path), None, False, "bad JSON"))
            continue
        jd = folder / "description.md"
        jd_text = jd.read_text(encoding="utf-8") if jd.exists() else ""
        report = ats.run_checks(pdfs[0], cv=cv, jd_text=jd_text)
        rows.append((_company_label(cv_path), report.overall,
                     report.gates_passed, ""))

    failed = [r for r in rows if not r[2]]
    typer.echo(f"{'application':28} {'score':>6}  gates")
    typer.echo("-" * 48)
    for name, score, passed, note in rows:
        shown = "-" if score is None else str(score)
        state = "ok" if passed else (note or "FAIL")
        typer.echo(f"{name:28} {shown:>6}  {state}")
        if score is not None:
            worst = worst or score

    scored = [r for r in rows if r[1] is not None]
    if scored:
        low = min(r[1] for r in scored)
        typer.echo(f"\n{len(scored)} scored, lowest {low}.")
    if failed:
        typer.echo(f"✖ {len(failed)} not passing gates.", err=True)
        raise typer.Exit(1)


@app.command()
def status() -> None:
    """One screen: the capture queue, the CVs on disk, and the naming rules."""
    entries = inbox.load_ledger()
    pending = [e for e in entries if not inbox.has_cv(e.get("slug", ""))]
    ready = [e for e in entries if inbox.has_cv(e.get("slug", ""))]
    # Exact language files only: this excludes cv-pt.backup.<stamp>.json, which
    # would otherwise read as a language called "pt.backup.20260328_161326".
    cvs = sorted(p for p in (BASE_DIR / "companies").rglob("cv-*.json")
                 if re.fullmatch(r"cv-[a-z]{2}\.json", p.name))

    typer.echo("queue")
    typer.echo(f"  captures        {len(entries)}")
    typer.echo(f"  CV ready        {len(ready)}")
    typer.echo(f"  pending CV      {len(pending)}")
    if pending:
        for e in pending:
            link = "  apply" if e.get("apply_url") else ""
            typer.echo(f"    {e.get('slug', ''):24} {e.get('company', '')}"
                       f" - {e.get('title', '')}{link}")

    typer.echo("\nportfolio")
    typer.echo(f"  tailored CVs    {len(cvs)}")
    langs = {}
    for cv in cvs:
        key = cv.stem.split("-")[-1]
        langs[key] = langs.get(key, 0) + 1
    typer.echo("  by language     " +
               ", ".join(f"{k}={v}" for k, v in sorted(langs.items())))

    typer.echo("\nnext")
    if pending:
        typer.echo(f"  cv tailor {pending[0].get('slug')}")
    else:
        typer.echo("  nothing queued; capture a job from the extension")


@app.command()
def tailor(
    slug: Annotated[str, typer.Argument(help="capture slug, e.g. from cv inbox list")],
) -> None:
    """Prepare a tailoring session for one captured job.

    Tailoring cannot be automatic: it needs the operator's answers about which
    projects to include and which may be named. This gathers what those
    answers depend on, so the session starts informed.
    """
    entry = inbox.find_entry(slug)
    if not entry:
        typer.echo(f"No capture with slug {slug}.", err=True)
        raise typer.Exit(1)

    typer.echo(f"{entry.get('company')} - {entry.get('title')}")
    typer.echo(f"  linkedin  {entry.get('url', '')}")
    typer.echo(f"  apply     {entry.get('apply_url') or '(none: Easy Apply)'}")
    typer.echo(f"  jd        companies/{slug}/description.md")
    typer.echo(f"  CV        {'already built' if inbox.has_cv(slug) else 'not built'}")

    jd = BASE_DIR / "companies" / slug / "description.md"
    if jd.exists():
        lines = [line.strip() for line in jd.read_text(encoding="utf-8").splitlines()
                 if line.strip() and not line.strip().startswith(("http", "apply:"))]
        # Start at the section that states what the role wants, not the
        # company's own introduction.
        start = next(
            (i for i, line in enumerate(lines)
             if re.match(r"(requisitos|qualifica|o que esperamos|responsabilidades|"
                         r"diferenciais|para isso|voc[êe] vai precisar|precisar ter|"
                         r"experi[êe]ncia|conhecimento|habilidades|requirements|"
                         r"what you|your day)", line, re.I)),
            None,
        )
        if start is not None:
            typer.echo("\nwhat the JD asks for:")
            for line in lines[start:start + 14]:
                typer.echo(f"  - {line[:88]}")
        else:
            typer.echo("\nfirst lines of the JD:")
            for line in lines[:8]:
                typer.echo(f"  - {line[:88]}")

    company = slug.split("/")[0]
    config = guards.load_names()
    approved = sorted(config.get("approved_by_company", {}).get(company, []))
    typer.echo(f"\nnames already approved for {company}: "
               f"{', '.join(approved) if approved else 'none'}")
    typer.echo("  approve more with: cv names approve "
               f"{company} <project>")

    typer.echo("\nthe two questions to answer before bullets:")
    typer.echo("  1. which projects should this CV include?")
    typer.echo("  2. which of them may be named, for this application only?")
    typer.echo("\nsee candidates with: cv projects --company " + company)


@app.command()
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
    every: Annotated[bool, typer.Option("--all", help="Score every tailored CV.")] = False,
):
    """Check a generated CV PDF for ATS safety and score it."""
    if every:
        _ats_check_every(lang)
        return

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
    source: Annotated[str, typer.Option("--source", "-s", help="Job source: programathor, remotive, remoteok, linkedin, gupy")] = "programathor",
    limit: Annotated[int, typer.Option("--limit", "-n", help="Max results to show")] = 10,
    import_file: Annotated[Optional[Path], typer.Option("--import", help="Rank jobs from a JSON file (e.g. a LinkedIn extension export)")] = None,
    cv_file: Annotated[Optional[Path], typer.Option("--cv", help="Rank against a tailored cv.json instead of the base cv.json")] = None,
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

    cv_path = cv_file if cv_file else BASE_DIR / "cv.json"
    cv = json.loads(cv_path.read_text(encoding="utf-8"))
    ranked = searchmod.rank(jobs, cv, query=query or "")[:limit]
    if not ranked:
        typer.echo("✖ no jobs found for the query", err=True)
        raise typer.Exit(1)

    if as_json:
        typer.echo(json.dumps([
            {"rank": i, "fit": r.fit, "title": r.job.title, "company": r.job.company,
             "location": r.job.location, "url": r.job.url, "source": r.job.source,
             "matched": r.matched}
            for i, r in enumerate(ranked, 1)
        ], indent=2))
        return

    typer.echo(f"Best matches for '{query or import_file}' (fit = query relevance + how well the CV covers the JD)")
    for i, r in enumerate(ranked, 1):
        mark = " *" if ingest == i else ""
        typer.echo(f"  {i:>2}. {r.fit:>3}%  {r.job.title} @ {r.job.company} ({r.job.location}){mark}")
        typer.echo(f"        {r.job.url}")
        if r.matched:
            typer.echo(f"        matches: {', '.join(r.matched)}")

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


def main() -> None:
    if "--help" in sys.argv or "-h" in sys.argv:
        _show_banner(compact="--compact" in sys.argv)
    app()


if __name__ == "__main__":
    main()

