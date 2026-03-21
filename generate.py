#!/usr/bin/env python3
# ============================================================
# Open-CV — CLI
# Install:  pip install -e .
# Usage:
#   cv generate                                  → index.html (cv.json, classic)
#   cv generate --pdf                            → index.html + resume-en.pdf
#   cv generate --company owlish --pdf           → companies/owlish/JezielLopesCarvalho-en.pdf
#   cv generate --lang pt --theme modern --pdf
#   cv new acme                                  → scaffold companies/acme/cv-en.json
#
# Available themes: classic (default), modern, minimal
# Available languages: en (default), pt
# ============================================================

import json
import sys
import html as _html
import shutil
from pathlib import Path
from typing import Optional

import typer
from typing_extensions import Annotated

BASE_DIR = Path(__file__).resolve().parent

app = typer.Typer(help="cv — edit cv.json, run one command, get a PDF.")

# ---- helpers ------------------------------------------------

def esc(s=""):
    return _html.escape(str(s or ""), quote=True)

def bullets(items):
    return "\n".join(
        f'<li><span class="bullet-dot">•</span><span>{esc(b)}</span></li>'
        for b in (items or [])
    )

def experience_item(e):
    return f"""
<div class="item">
  <div class="item-header">
    <span class="item-org">{esc(e["org"])}</span>
    <span class="item-location">{esc(e["location"])}</span>
  </div>
  <div class="item-row">
    <span class="item-position">{esc(e["role"])}</span>
    <span class="item-date">{esc(e["start"])} – {esc(e["end"])}</span>
  </div>
  <ul class="bullet-list">
    {bullets(e.get("bullets", []))}
  </ul>
</div>"""

def education_item(e):
    return f"""
<div class="item">
  <div class="item-header">
    <span class="item-org">{esc(e["institution"])}</span>
    <span class="item-location">{esc(e["location"])}</span>
  </div>
  <div class="item-row">
    <span class="item-position">{esc(e["degree"])}</span>
    <span class="item-date">{esc(e["start"])} – {esc(e["end"])}</span>
  </div>
  <ul class="bullet-list">
    {bullets(e.get("bullets", []))}
  </ul>
</div>"""

def course_item(c):
    return f"""
<div class="course-item">
  <span class="course-title">{esc(c["title"])}</span>
  <span class="course-separator"></span>
  <span class="course-institution">{esc(c["institution"])}</span>
</div>"""

def skill_group(s):
    tags = "\n    ".join(
        f'<span class="skill-tag">{esc(t)}</span>' for t in s["tags"]
    )
    return f"""
<div class="skill-group">
  <span class="skill-label">{esc(s["group"])}</span>
  <div class="skill-tags">
    {tags}
  </div>
</div>"""

def dot(filled):
    cls = "dot-filled" if filled else "dot-empty"
    return f'<div class="dot {cls}"></div>'

def language_item(lang):
    dots = "\n    ".join(dot(i < lang["dots"]) for i in range(5))
    return f"""
<div class="language-item">
  <div class="language-name">{esc(lang["name"])}</div>
  <div class="language-level">{esc(lang["level"])}</div>
  <div class="language-dots">
    {dots}
  </div>
</div>"""

def portfolio_item(p):
    return f"""
<div class="portfolio-item">
  <div class="portfolio-icon">⌥</div>
  <div>
    <div class="portfolio-title">{esc(p["label"])}</div>
    <div class="portfolio-link"><a href="{esc(p["url"])}" target="_blank">{esc(p["display"])}</a></div>
  </div>
</div>"""

def contact_item(text, href=None):
    if href:
        return f'<span class="contact-item"><a href="{esc(href)}" target="_blank">{esc(text)}</a></span>'
    return f'<span class="contact-item">{esc(text)}</span>'

SEP = '<span class="contact-separator">·</span>'

# ---- themes -------------------------------------------------
# Each theme provides:
#   fonts_url  – Google Fonts <link> href  (or "" for system fonts)
#   css_vars   – :root variable block (controls colors / fonts)
#   extra_css  – any additional CSS unique to the theme

PAGE_MARGIN = 50  # px — shared by all themes

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

.header-contacts {{
  display: flex; flex-wrap: wrap;
  justify-content: center; align-items: center;
  gap: 0; margin-top: 4px;
}}

.contact-item {{ font-family: var(--font-body); font-size: 13px; line-height: 16px; padding-bottom: 2px; white-space: nowrap; }}
.contact-item a {{ color: inherit; text-decoration: none; }}
.contact-separator {{ margin: 0 6px; color: var(--color-muted); font-size: 13px; }}

.section {{ margin-bottom: 12px; }}

.section-title {{
  font-family: var(--font-heading);
  font-size: 18px; line-height: 23px; color: var(--color-accent);
  border-bottom: 1px solid var(--color-border);
  padding: 6px 12px 0; margin-bottom: 0;
}}

.item {{ padding: 6px 12px; break-inside: avoid; }}
.section-title {{ break-after: avoid; }}

.item-header {{ display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: nowrap; }}
.item-org {{ font-family: var(--font-body); font-weight: 400; font-size: 18px; line-height: 22px; color: var(--color-muted); }}
.item-location {{ font-family: var(--font-body); font-size: 15px; line-height: 18px; color: var(--color-text); text-align: right; white-space: nowrap; }}
.item-row {{ display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: nowrap; margin-top: 1px; }}
.item-position {{ font-family: var(--font-body); font-weight: 400; font-size: 15px; line-height: 18px; color: var(--color-text); }}
.item-date {{ font-family: var(--font-body); font-weight: 400; font-size: 15px; line-height: 18px; color: var(--color-text); white-space: nowrap; text-align: right; flex-shrink: 0; }}

.bullet-list {{ list-style: none; margin-top: 4px; }}
.bullet-list li {{ display: flex; align-items: flex-start; font-family: var(--font-body); font-size: 13px; line-height: 18px; gap: 4px; }}
.bullet-dot {{ flex-shrink: 0; line-height: 18px; }}

.summary-text {{ font-family: var(--font-body); font-size: 13px; line-height: 18px; text-align: left; white-space: pre-wrap; }}

.skill-group {{ display: flex; flex-wrap: wrap; align-items: baseline; gap: 0; padding: 6px 12px; }}
.skill-label {{ font-family: var(--font-body); font-size: 15px; line-height: 18px; color: var(--color-muted); white-space: nowrap; flex-shrink: 0; }}
.skill-label::after {{ content: ': '; }}
.skill-tags {{ display: flex; flex-wrap: wrap; align-items: center; gap: 0; }}
.skill-tag {{ font-family: var(--font-body); font-size: 13px; line-height: 18px; color: var(--color-text); }}
.skill-tag:not(:last-child)::after {{ content: '\\00B7'; font-weight: 700; margin: 0 5px; color: var(--color-text); }}

.languages-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); }}
.language-item {{ padding: 6px 12px; }}
.language-name {{ font-family: var(--font-body); font-size: 15px; line-height: 18px; color: var(--color-text); }}
.language-level {{ font-family: var(--font-body); font-size: 13px; line-height: 16px; color: var(--color-text); }}
.language-dots {{ display: flex; gap: 4px; margin-top: 3px; }}
.dot {{ width: 8px; height: 8px; border-radius: 50%; }}
.dot-filled {{ background: var(--color-accent); }}
.dot-empty  {{ background: #e4e4e4; }}

.portfolio-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); }}
.portfolio-item {{ display: flex; align-items: flex-start; gap: 8px; padding: 6px 12px; }}
.portfolio-icon {{ font-size: 20px; color: var(--color-muted); line-height: 1; margin-top: 2px; }}
.portfolio-title {{ font-family: var(--font-body); font-size: 15px; line-height: 18px; color: var(--color-text); font-weight: 400; }}
.portfolio-link {{ font-family: var(--font-body); font-size: 13px; line-height: 16px; color: var(--color-text); word-break: break-all; }}
.portfolio-link a {{ color: inherit; text-decoration: none; }}

.course-item {{ display: flex; align-items: baseline; flex-wrap: nowrap; padding: 6px 12px; gap: 0; break-inside: avoid; }}
.course-title {{ font-family: var(--font-body); font-weight: 400; font-size: 15px; line-height: 18px; color: var(--color-muted); flex-shrink: 1; white-space: nowrap; }}
.course-separator {{ flex: 1; border-bottom: 1px dotted #ccc; margin: 0 8px; position: relative; top: -3px; min-width: 12px; }}
.course-institution {{ font-family: var(--font-body); font-size: 13px; line-height: 16px; color: var(--color-text); white-space: nowrap; }}

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
    # IBM Plex Sans; very light grey palette; no bold contrast —
    # clean, understated, ATS-friendly.
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
    line2_html = f""" <span class="contact-separator">·</span>""".join(line2_items)
    
    salary_row = ""
    if sal:
        parts = [esc(sal["amount"])]
        if sal.get("contract"):
            parts.append(esc(sal["contract"]))
        if sal.get("note"):
            parts.append(esc(sal["note"]))
        salary_row = f"""
    <div class="header-contacts" style="margin-top:2px;">
      {contact_item("Salary expectation: " + " · ".join(parts))}
    </div>"""
    
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{esc(p["name"])} — Resume</title>
  {build_fonts_link(theme_name)}
  <!-- Generated by cv — edit cv.json, not this file -->
  <style>{build_css(theme_name)}</style>
</head>
<body>

<div class="resume">

  <header class="resume-header">
    <div class="header-name">{esc(p["name"])}</div>
    <div class="header-title">{esc(p["title"])}</div>
    <div class="header-contacts">
      {contact_item(p["phone"])}
      {SEP}
      {contact_item(p["email"], f'mailto:{p["email"]}')}
      {SEP}
      {contact_item(p["linkedin"], p["linkedin"])}
    </div>
    <div class="header-contacts" style="margin-top:2px;">
      {line2_html}
    </div>{salary_row}
  </header>

  <section class="section">
    <div class="section-title">Summary</div>
    <div class="item">
      <p class="summary-text">{esc(cv["summary"])}</p>
    </div>
  </section>

  <section class="section">
    <div class="section-title">Experience</div>
    {"".join(experience_item(e) for e in cv["experience"])}
  </section>

  <section class="section">
    <div class="section-title">Education</div>
    {"".join(education_item(e) for e in cv["education"])}
  </section>

  <section class="section">
    <div class="section-title">Training / Courses</div>
    {"".join(course_item(c) for c in cv["courses"])}
  </section>

  <section class="section">
    <div class="section-title">Skills</div>
    {"".join(skill_group(s) for s in cv["skills"])}
  </section>

  <section class="section">
    <div class="section-title">Languages</div>
    <div class="languages-grid">
      {"".join(language_item(l) for l in cv["languages"])}
    </div>
  </section>

</div>

</body>
</html>"""

# ---- CLI commands -------------------------------------------

@app.command()
def generate(
    company: Annotated[Optional[str], typer.Option("--company", "-c", help="Company ID (reads companies/{id}/cv-{lang}.json, outputs companies/{id}/JezielLopesCarvalho-{lang}.pdf)")] = None,
    lang: Annotated[str, typer.Option("--lang", "-l", help="Language code (en, pt)")] = "en",
    theme: Annotated[str, typer.Option("--theme", "-t", help="Theme: classic, modern, minimal")] = "classic",
    pdf: Annotated[bool, typer.Option("--pdf", help="Export PDF after rendering HTML")] = False,
):
    """Render cv.json to index.html and optionally export a PDF."""
    if company:
        company_dir = BASE_DIR / "companies" / company
        cv_path = company_dir / f"cv-{lang}.json"
        pdf_out = company_dir / f"JezielLopesCarvalho-{lang}.pdf"
    else:
        cv_filename = "cv.json" if lang == "en" else f"cv-{lang}.json"
        cv_path = BASE_DIR / cv_filename
        pdf_out = BASE_DIR / f"resume-{lang}.pdf"

    html_out = BASE_DIR / "index.html"

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
    typer.echo(f"  Next: edit the file, then run:")
    typer.echo(f"    cv generate --company {company_id} --pdf")


if __name__ == "__main__":
    app()

