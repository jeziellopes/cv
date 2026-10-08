# cv

> Your resume. Your code. Always up to date.

A pipeline for job applications that only claims what code proves. A Chrome
extension captures a posting's JD from LinkedIn, and everything after that
runs through the `cv` CLI: the search that finds postings, the inbox that
holds each capture, the evidence ledgers that skillscan and gaps keep, the
tailored and ATS-checked CV render, and the record of the application.
`cv.json` is the base resume every tailored CV starts from. Nothing is
claimed on a CV that a repository cannot prove.

## The loop

Every application moves through the same steps, and the tool shows where it stands at each one.

```
capture   the extension saves a job from the browser into the queue
tailor    answers which projects to include and which may be named
build     cv generate writes the tailored CV and the PDF
gate      ats-check and the skill gate refuse anything unproven
decide    applied, skipped, or profile-only, recorded in the ledger
```

`cv inbox status` is the one screen: it counts each step, dates every JD, and reports any CV that claims a skill nothing proves.

The first step lives in your browser, not in a command. A small Chrome
extension puts an **Apply with CV** button on LinkedIn's job pages: it shows
where that job already stands in the queue, and one click hands the JD to it.
An application runs the whole path:

```bash
cv search "react senior remote"       # find postings, ranked by fit
(click capture in the browser)         # the extension saves the job
cv inbox next                          # oldest capture that still needs a CV
cv tailor <slug>                       # the questions this posting asks
cv generate --company <slug> --pdf     # the gated, tailored CV
cv inbox applied <slug>                # the application is recorded
```

The extension's one-time setup lives in
[The inbox and the extension](#the-inbox-and-the-extension). The base resume
and one-off PDFs come from the Quick start below.

## Project structure

```
cv/
├── cv.json             base resume in English (edit this)
├── cv-pt.json          base resume in Portuguese-BR
├── generate.py         renderer and PDF exporter
├── ats.py              deterministic ATS gates and scorecard
├── search.py           job search and fit ranking
├── inbox.py            capture queue, ledger, steps, local endpoint
├── evidence.py         scan repositories for real usage of a skill
├── skills.py           the skill-evidence gate and the gap ledger
├── guards.py           claim verification and name approval
├── mailscan.py         read application confirmations from Gmail
├── staleness.py        fingerprints so an outdated PDF is visible
├── extension/          Chrome extension: capture and the panel
├── install.sh          install the package and Playwright chromium
└── companies/          tailored CVs, one folder per application
    └── {company}/
        ├── description.md
        ├── cv-en.json
        └── <Name>-en.pdf
```

`companies/`, `inbox.json`, `project-names.json`, `gaps.json` and the Gmail
client and token are gitignored: they hold personal data and the identity of
proprietary work. `index.html` is a build artifact and is ignored too.

## Quick start

### For new candidates

1. **Copy the template:**
   ```bash
   cp cv.example.json cv.json       # English resume template
   cp cv-pt.example.json cv-pt.json # Portuguese resume template
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

The `cv.json` and `cv-pt.json` files are gitignored, because they contain your personal data. If you have been using this tool, your existing files keep working.

## Commands

```bash
cv generate --company <id> --lang pt --pdf      # build a tailored CV and PDF
cv status                                       # the queue, the CVs, the next step
cv stale [--fix]                                # PDFs older than what they are built from
cv ats-check --company <id> --jd companies/<id>/description.md
cv inbox list [--all|--pending]                 # the queue by step
cv inbox status                                 # counts, JD dates, unproven claims
cv inbox next                                   # the oldest capture that still needs a CV
cv inbox applied <slug>                         # record that it was sent
cv inbox skip <slug> -r "why"                   # decline it, with your own reason
cv inbox reconsider <slug>                      # take a decline back
cv inbox profile <slug>                         # no CV wanted, LinkedIn profile only
cv inbox requeue <slug>                         # bring a profile-only capture back
cv inbox mail [--apply] [--all]                 # record applied from Gmail confirmations
cv gaps [--soft]                                # skills postings ask for: answered, or needing your answer
cv gaps answer -s X -e ENG | --could-not-place  # your answer for a demanded, unevidenced skill
cv gaps refresh                                 # rescan repositories, rebuild the ledger
cv gaps check                                   # fail any CV that claims an unproven skill
cv skillscan                                    # discover skills from the imports you actually wrote
cv evidence --probe aws                         # where real usage exists
cv names check                                  # docs that name an unapproved project
cv claims verify                                # re-derive every quantified figure
cv search ...                                   # see Job search below
```

| Option | Default | Description |
|---|---|---|
| `--company / -c` | - | Company ID, reads and writes under `companies/{id}/` |
| `--lang / -l` | `en` | Language code (`en`, `pt`) |
| `--theme / -t` | `classic` | Theme: `classic`, `modern`, `minimal` |
| `--pdf` | off | Export PDF after rendering HTML |

## ATS checking

Generated PDFs are verified against how applicant tracking systems parse them with `cv ats-check`. It enforces nine format gates (text layer, single column, reading order, semantic sections, date format, character set, contact info, content completeness, file size) and prints a 0-100 scorecard mirroring the categories third-party checkers use.

```bash
cv ats-check --company <id>                      # gates + scorecard for a company CV
cv ats-check --company <id> --jd companies/<id>/description.md  # add JD keyword coverage
cv ats-check --pdf resume-en.pdf --strict        # exit 1 on any gate failure or a score under 90
cv ats-check --company <id> --judge              # append an optional LLM judge pass (never gates)
```

Any gate failure exits 1. With `--strict`, the command also exits 1 when the overall score is below `--min-score` (default 90) or JD coverage is below `--min-coverage` (default 0.60). `--json` emits a machine-readable report. When `--company` is set and no `--jd` is given, the JD is auto-discovered from `companies/{id}/description.md` if present.

The CLI flags, exit codes, and `--json` output are the tool's API: a major version bump may change them, and gates exiting 1 on a failed check is the stable contract.

## The honesty gates

Three gates decide what may appear on a CV instead of trusting the author, and each one exits non-zero rather than being a convention.

- **Claims.** Every quantified figure a CV asserts is re-derived from the repositories, so a number that cannot be reproduced is caught before it ships. `cv claims verify`.
- **Names.** A project name is publishable only where the operator approved it for that application, and never in prose that reaches a stranger. `cv names check`.
- **Skill evidence.** A skill is claimable only where the lines the operator's commits added prove it. `cv gaps refresh` scans the repositories and builds a ledger, matching both probe patterns and the packages those added lines import (`cv skillscan` reports what that discovers); `cv generate` refuses to render a CV that claims a skill neither evidenced, soft, nor allowed. A demanded, unevidenced skill is not declared a gap until the operator is asked: the report names it and `cv gaps answer` records the answer, with an engagement for affirmed skills or `--could-not-place` for ones that stay gaps. The gaps are what remains after both steps leave a skill unresolved.

The evidence scanner is deliberately a candidate finder. A hit is read before it becomes a claim, docs and manifests do not count as usage, bare words are matched whole (so `ecs` does not match `specs`), and the scanner's own probe files are excluded from their own evidence.

The gate that decides claims is stricter: evidence is matched against the lines the operator's commits added, not the current text of files they touched. A needle a teammate wrote inside a shared file no longer evidences a skill, so a contribution is the diff, never the file. One diff read feeds both the probe scan and the import scan, so a refresh does not pay `git log -p` twice.

The import lens binds the added lines to skills through a hand-reviewed package mapping in `skills.json`. Node and Python standard library and `@/` path aliases carry no signal and are skipped; packages that match no mapping are written to `candidates.json` (gitignored) for you to approve rather than becoming skills on their own.

## Job search

`cv search` queries remote job boards with a free-text query and ranks the results by how well the CV covers each posting.

```bash
cv search "react senior remote"                        # programathor, ranked by fit
cv search "typescript frontend" --source linkedin --since week --limit 10
cv search --import linkedin-export.json                # rank a browser export
cv search "react" --ingest 1                           # write the top match's JD to companies/<slug>/description.md
```

The fit score is a ranking signal, not a match rate: the CV fit is the base, and a query multiplies it (up to 1.5x), so a typed query boosts within-stack matches but never lifts an off-stack posting. Each result shows which of your skills the posting matches. Around 45-65% is a strong match for a generalist CV.

Sources: `programathor` (default), `remotive`, `remoteok`, `linkedin`, and `gupy`. The `linkedin` source reads LinkedIn's guest endpoints: listing cards, then a description per shown result (bounded by `--limit`), walkable past the ten-per-page cap. Of LinkedIn's search filters, `--since` (`24h`, `week`, `month`), `--location` and `--remote` are passed through, and the ones LinkedIn ignores server-side are deliberately not offered. `--json` emits a machine-readable list; `--no-detail` skips the description fetches; `--ingest N` writes `companies/<slug>/description.md` and prints the next commands.

## The inbox and the extension

Pick a job in your own browser and hand it to the pipeline without copy-paste.

1. Start the local endpoint. It binds loopback only and prints a token:

   ```bash
   cv inbox serve
   ```

2. Install the extension once. In Chrome, open `chrome://extensions`, enable
   **Developer mode**, choose **Load unpacked**, and select `extension/`.
   Click the extension icon, paste the token, **Save**, then **Test**.

3. Open a LinkedIn job. The button in the header shows where that job already
   is in the pipeline: **Apply with CV**, **CV pending**, **CV ready**, **Applied**,
   **Skipped**, or **Profile**. Clicking it captures the JD to
   `companies/<slug>/description.md`.

4. Tailor and build, one capture at a time:

   ```bash
   cv inbox next          # the oldest capture that still needs a CV
   cv tailor <slug>       # the questions to answer for this posting
   cv generate --company <slug> --lang pt --pdf
   cv inbox applied <slug>   # after the application goes out
   ```

The toolbar popup is the panel: tabs for **Captured** (captured, cv-ready and
profile-only), **Applied** and **Skipped**, each with its count. Every row has
its Job and Apply links and the actions that belong to that step: **Mark applied**,
**Decline** with a reason you write, and **Reconsider** for a decline. A step that
has no meaning on a capture is not offered there, and the same impossibility is
refused by the API.

A capture can be recorded as **applied** from four places, each a record that
the application was sent rather than an inference: the CLI, the panel, Gmail
confirmations, or LinkedIn's own Applied list via the **Reconcile with the CV
ledger** button on that page. A posting that needs no tailored CV, because the
apply uses only the LinkedIn profile, is marked **profile** and leaves the
pending list.

## Reading your mailbox

`cv inbox mail` reads application confirmations from Gmail and reports the
captures they match, then records them with `--apply`. Dry by default, so a
run that matches nothing writes nothing.

A confirmation identifies a capture by the pair the pipeline already uses, the
company and the role as a phrase. It must name the company and the role; a
confirmation naming only the company counts only where that company has one
capture, and the role alone never decides. The sender is reported as evidence,
never required. A confirmation that names no capture, or names one already
applied, is reported rather than dropped.

## Themes

| Theme | Font | Accent |
|---|---|---|
| `classic` *(default)* | Volkhov + PT Sans | Black |
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

To add more languages, create a `cv-{lang}.json` file and use `--lang {lang}`.

## How to update your resume

**Only edit `cv.json`.** `index.html` is auto-generated and is overwritten on the next build.

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

The header renders on two lines: phone, email, linkedin on the first, and
portfolio, github, location on the second. `portfolio` and `github` are
optional; all other fields are required.

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

A tag you add is checked against the skill-evidence ledger. If nothing proves it
you have a gap to close, a reason to record, or a tag to drop.

### Add a language

```json
{ "name": "French", "level": "Intermediate", "dots": 3 }
```

`dots` is a number from 1 to 5.

### Add a salary expectation (company CVs)

Optional field, for company CVs. Omit it for the base CV.

```json
"salary_expectation": {
  "amount": "R$ 6.500/mês",
  "contract": "CLT",
  "note": "negotiable"
}
```

`contract` and `note` are optional. `amount` is required if the key is present.

## Translation with keyword preservation

When translating your CV, technical terms (React, Design Systems, and so on)
should remain in English for consistency. Use the built-in `translate` command:

```bash
cv translate --text "Your summary here" --from en --to pt
```

The command replaces English keywords with placeholders, translates the text,
then restores the keywords. Supported keywords include React, TypeScript,
Design Systems, TDD, and AWS.

> **Note:** Requires `google-translate-api`. Install with `pip install google-translate-api`.

## Page layout & margins

Content flows naturally across pages, with no manual page splitting. Playwright
paginates automatically, respecting `break-inside: avoid` on every entry so
items are never split mid-bullet.

To change the margin on all four sides, edit one constant in `generate.py`:

```python
PAGE_MARGIN = 50  # px: screen padding, @page, and Playwright
```

## Typography (classic theme)

| Element | Font | Size |
|---|---|---|
| Name | Volkhov Bold | 22px |
| Section titles | Volkhov Regular | 18px |
| Company / Org | PT Sans Regular | 18px |
| Role / Position | PT Sans Regular | 15px |
| Body / Bullets | PT Sans Regular | 13px |

Fonts are loaded from Google Fonts. For fully offline use, download and
self-host **Volkhov** and **PT Sans**.

## License

MIT: use, fork, share freely.