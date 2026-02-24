# Open-CV

> Your resume. Your code. Always up to date.

Open-CV is a free, open-source resume generator. Edit `cv.json`, run one command, get a pixel-perfect HTML file and a print-ready PDF - no third-party login, no subscription, no watermark.

## Project structure

```
open-cv/
├── cv.json          ← YOUR resume data (edit this)
├── generate.js      ← template engine + PDF exporter
├── package.json
├── index.html       ← generated output (do not edit by hand)
└── resume.pdf       ← generated output
```

## Quick start

```bash
npm install
```

## Commands

| Command | Description |
|---|---|
| `npm run build` | Render `cv.json` → `index.html` |
| `npm run export` | Render `cv.json` → `index.html` + `resume.pdf` |
| `npm run preview` | Build and serve locally at http://localhost:5500 |

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
Puppeteer paginates automatically, respecting `break-inside: avoid` on every
entry so items are never split mid-bullet.

To change the margin on all four sides, edit one constant in `generate.js`:

```js
const PAGE_MARGIN = 50; // px - applies to screen padding, @page, and Puppeteer
```

## Typography

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
