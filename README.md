# Open-CV

> Your resume. Your code. Always up to date.

Open-CV is a free, open-source resume generator. Edit `cv.json`, run one command, get a pixel-perfect HTML file and a print-ready PDF - no third-party login, no subscription, no watermark.

## Project structure

```
open-cv/
├── cv.json           ← YOUR resume data (edit this)
├── generate.py       ← template engine + PDF exporter
├── requirements.txt  ← Python dependencies
└── resume.pdf        ← generated demo (tracked in git)
```

> `index.html` is a build artifact and is intentionally git-ignored.

## Quick start

```bash
pip install -r requirements.txt
playwright install chromium
```

## Commands

| Command | Description |
|---|---|
| `python3 generate.py` | Render `cv.json` → `index.html` (classic theme) |
| `python3 generate.py --pdf` | Render `cv.json` → `index.html` + `resume.pdf` |
| `python3 generate.py --theme NAME` | Use a specific theme |
| `python3 generate.py --pdf --theme NAME` | Export PDF with a specific theme |
| `python3 -m http.server 5500` | Preview locally at http://localhost:5500 |

## Themes

| Theme | Font | Accent |
|---|---|---|
| `classic` *(default)* | Volkhov + PT Sans | Black - original style |
| `modern` | Inter | Blue `#2563eb` on name, titles & dots |
| `minimal` | IBM Plex Sans | Dark grey, uppercase section labels, light borders |

```bash
python3 generate.py --theme modern
python3 generate.py --pdf --theme minimal
```

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
  "location": "City, Country"
}
```

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
