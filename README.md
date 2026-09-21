# cv

> Your resume. Your code. Always up to date.

A free, open-source resume generator. Edit `cv.json`, run one command, get a pixel-perfect HTML file and a print-ready PDF - no third-party login, no subscription, no watermark.

## Project structure

```
cv/
├── cv.json             ← base resume data in English (edit this)
├── cv-pt.json          ← base resume data in Portuguese-BR
├── generate.py         ← template engine + PDF exporter
├── requirements.txt    ← Python dependencies
├── messages/           ← recruiter messages (one .md per opportunity)
├── resume-en.pdf       ← generated base PDF (English)
├── resume-pt.pdf       ← generated base PDF (Portuguese-BR)
└── companies/
    └── {company}/
        ├── cv-en.json  ← tailored resume data for this company
        └── JezielLopesCarvalho-en.pdf  ← generated tailored PDF
```

> `index.html` is a build artifact and is intentionally git-ignored.

## Quick start

### For new candidates

1. **Copy the template:**
   ```bash
   cp cv.example.json cv.json       # English resume template
   cp cv-pt.example.json cv-pt.json  # Portuguese resume template
   ```

2. **Edit your data:**
   Fill in your personal info, experiences, education, skills, and languages in both JSON files.

3. **Generate PDFs:**
   ```bash
   ./install.sh
   cv generate --pdf --lang en      # Generate English resume
   cv generate --pdf --lang pt      # Generate Portuguese resume
   ```

Your generated PDFs will be `resume-en.pdf` and `resume-pt.pdf` in the root directory.

`./install.sh` installs the package (and re-registers new modules on re-run) and Playwright chromium. The browser directory is resolved from `PLAYWRIGHT_BROWSERS_PATH`, else a previous install's `.cv-env`, else Playwright's default, and is persisted to `.cv-env` so `cv generate --pdf` needs no export. On a machine where the system disk is full, keep browsers on another volume by running `PLAYWRIGHT_BROWSERS_PATH=/path/to/ms-playwright ./install.sh` once. `./install.sh --check` verifies the install without changing anything.

### For existing candidates

The `cv.json` and `cv-pt.json` files are gitignored - they contain your personal data. If you've already been using this tool, your existing files will continue to work.

## Commands

```bash
cv generate                             # render cv.json → index.html (classic, English)
cv generate --pdf                       # + export resume-en.pdf
cv generate --lang pt --pdf             # Portuguese version
cv generate --theme modern --pdf        # different theme
cv generate --company owlish --pdf      # tailored: companies/owlish/JezielLopesCarvalho-en.pdf
cv new acme                             # scaffold companies/acme/cv-en.json from base cv.json
cv translate --text "Your text here" --from en --to pt  # translate with keyword preservation
cv ats-check --company owlish           # verify the PDF parses in ATS and score it
cv search "react senior remote"         # search job sources and rank the best matches
```

| Option | Default | Description |
|---|---|---|
| `--company / -c` | - | Company ID - reads/writes under `companies/{id}/` |
| `--lang / -l` | `en` | Language code (`en`, `pt`) |
| `--theme / -t` | `classic` | Theme: `classic`, `modern`, `minimal` |
| `--pdf` | off | Export PDF after rendering HTML |

## ATS checking

Generated PDFs are verified against how applicant tracking systems parse them with `cv ats-check`. It enforces nine format gates (text layer, single column, reading order, semantic sections, date format, character set, contact info, content completeness, file size) and prints a 0-100 scorecard mirroring the categories used by third-party checkers.

```bash
cv ats-check --company owlish            # gates + scorecard for a company CV
cv ats-check --company owlish --jd companies/owlish/description.md  # add JD keyword coverage
cv ats-check --pdf resume-en.pdf --strict  # exit 1 on any gate failure or a score under 90
cv ats-check --company owlish --judge    # append an optional LLM judge pass (never gates)
```

Any gate failure exits 1. With `--strict`, the command also exits 1 when the overall score is below `--min-score` (default 90) or JD coverage is below `--min-coverage` (default 0.60). `--json` emits a machine-readable report. When `--company` is set and no `--jd` is given, the JD is auto-discovered from `companies/{id}/description.md` if present.

The CLI flags, exit codes, and `--json` output are the tool's API: a major version bump may change them, and gates exiting 1 on a failed check is the stable contract.

## Job search

`cv search` queries remote job boards with a free-text query and ranks the results by how well the CV covers each posting.

```bash
cv search "react senior remote"                # remotive, ranked by fit
cv search "typescript frontend" --source remoteok
cv search --import linkedin-export.json        # rank a LinkedIn extension export
cv search "react" --ingest 1                   # write the top match's JD to companies/<slug>/description.md
```

The fit score is a ranking signal, not a match rate: with a query it blends 55% query relevance with 45% CV fit (distinctive JD terms, CV skills found in the posting, title overlap). Generic prose in English and Portuguese is ignored and diacritics are folded, so `Sênior` and `experiência` don't dilute. Around 45-65% is a strong match for a generalist CV; low-signal sources compress everything toward 15-25%. Rank against a tailored CV with `--cv companies/<slug>/cv-en.json` for a sharper signal.

Sources: `programathor` (default, Brazilian dev board; serves a ~15-job recent feed), `remotive`, `remoteok`, `linkedin` (guest endpoint, best-effort and often blocked), and `gupy` (best-effort, frequently unreachable). Client-rendered boards (vagas.com.br, GeekHunter, inhire) aren't scrapable and belong on the `--import` path. `--json` emits a machine-readable list. `--ingest N` writes `companies/<slug>/description.md` and prints the next pipeline commands.

## Themes

| Theme | Font | Accent |
|---|---|---|
| `classic` *(default)* | Volkhov + PT Sans | Black - original style |
| `modern` | Inter | Blue `#2563eb` on name, titles & dots |
| `minimal` | IBM Plex Sans | Dark grey, uppercase section labels, light borders |

```bash
cv generate --theme modern
cv generate --pdf --theme minimal
```

## Languages

| Language | Code | CV File |
|---|---|---|
| English *(default)* | `en` | `cv.json` |
| Portuguese-BR | `pt` | `cv-pt.json` |

```bash
cv generate --lang pt
cv generate --lang pt --pdf --theme modern
```

> **Note:** To add support for more languages, create a new `cv-{lang}.json` file and use `--lang {lang}`.

## How to update your resume

**Only edit `cv.json`** - `index.html` is auto-generated and will be overwritten on the next build.

### Personal info

```json
"personal": {
  "name": "Your Name",
  "title": "Your Title",
  "phone": "+1...",
  "email": "you@example.com",
  "linkedin": "https://linkedin.com/in/you",
  "portfolio": "https://yourportfolio.dev",
  "github": "https://github.com/yourhandle",
  "location": "City, Country"
}
```

The header renders on **two lines**:
- **Line 1:** phone | email | linkedin
- **Line 2:** portfolio | github | location

`portfolio` and `github` are optional. All other fields are required.

### Add an experience entry

```json
{
  "org": "Company Name",
  "location": "City, Country",
  "role": "Your Role",
  "start": "MM/YYYY",
  "end": "MM/YYYY",
  "bullets": [
    "What you did.",
    "Another achievement."
  ]
}
```

### Add a skill tag

```json
"tags": ["...", "New Skill"]
```

### Add a language

```json
{ "name": "French", "level": "Intermediate", "dots": 3 }
```

`dots` is a number from 1 to 5.

### Add a salary expectation (company CVs)

Optional field - renders as an extra line in the CV header when present. Omit it for the base CV.

```json
"salary_expectation": {
  "amount": "R$ 6.500/mês",
  "contract": "CLT",
  "note": "negotiable"
}
```

`contract` and `note` are optional. `amount` is required if the key is present.

## Translation with keyword preservation

When translating your CV to multiple languages, technical terms (React, Design Systems, etc.) should remain in English for consistency. Use the built-in `translate` command:

```bash
cv translate --text "Your summary here" --from en --to pt
```

The command automatically:
1. Replaces English keywords with placeholders (e.g., React → {TECH_0})
2. Translates the text to your target language
3. Restores the keywords

Supported keywords include: React, TypeScript, Design Systems, TDD, AWS, etc.

> **Note:** Requires `google-translate-api`. Install with: `pip install google-translate-api`

## Page layout & margins

Content flows naturally across pages - no manual page splitting.
Playwright paginates automatically, respecting `break-inside: avoid` on every
entry so items are never split mid-bullet.

To change the margin on all four sides, edit one constant in `generate.py`:

```python
PAGE_MARGIN = 50  # px - applies to screen padding, @page, and Playwright
```

## Typography (classic theme)

| Element | Font | Size |
|---|---|---|
| Name | Volkhov Bold | 22px |
| Section titles | Volkhov Regular | 18px |
| Company / Org | PT Sans Regular | 18px |
| Role / Position | PT Sans Regular | 15px |
| Body / Bullets | PT Sans Regular | 13px |

Fonts are loaded from Google Fonts. For fully offline use, download and self-host **Volkhov** and **PT Sans**.

## License

MIT - use, fork, share freely.

## Roadmap

> Vision: evolve cv into a personal CV automation pipeline - one command from a recruiter message to a tailored PDF.

### Phase 1 - Manual message drop *(now)*
Drop LinkedIn recruiter messages as `.md` files into `./messages/`.
For each message, create a tailored `companies/{company}/cv-en.json` and generate the PDF.

```
messages/
└── recruiter-name.md       ← paste the message here

companies/
└── recruiter-name/
    ├── cv-en.json           ← tailored resume data
    └── JezielLopesCarvalho-en.pdf
```

Then:
```bash
cv generate --company recruiter-name --lang en --pdf
```

### Phase 2 - Automated generation *(planned)*
Parse `./messages/*.md` to extract role requirements automatically, then generate a tailored `cv-{company}-en.json` using an AI-assisted pipeline - no manual editing required.

### Phase 3 - LinkedIn integration *(future)*
Fetch recruiter messages directly from LinkedIn via API or browser automation, triggering the full pipeline end-to-end.

---

> **Project rename:** As scope expands beyond a static CV generator, a rename may better reflect the automation-first direction. TBD.

