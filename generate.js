#!/usr/bin/env node
// ============================================================
// Open-CV - generator
// Usage:
//   node generate.js           → writes index.html
//   node generate.js --pdf     → writes index.html + resume.pdf
// ============================================================

import { readFileSync, writeFileSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const cv = JSON.parse(readFileSync(resolve(__dirname, 'cv.json'), 'utf8'));
const exportPdf = process.argv.includes('--pdf');

// ---- helpers ------------------------------------------------

const esc = (s = '') =>
  String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');

const bullets = (list = []) =>
  list
    .map(b => `<li><span class="bullet-dot">•</span><span>${esc(b)}</span></li>`)
    .join('\n');

const experienceItem = ({ org, location, role, start, end, bullets: bl }) => `
<div class="item">
  <div class="item-header">
    <span class="item-org">${esc(org)}</span>
    <span class="item-location">${esc(location)}</span>
  </div>
  <div class="item-row">
    <span class="item-position">${esc(role)}</span>
    <span class="item-date">${esc(start)} – ${esc(end)}</span>
  </div>
  <ul class="bullet-list">
    ${bullets(bl)}
  </ul>
</div>`;

const educationItem = ({ institution, location, degree, start, end, bullets: bl }) => `
<div class="item">
  <div class="item-header">
    <span class="item-org">${esc(institution)}</span>
    <span class="item-location">${esc(location)}</span>
  </div>
  <div class="item-row">
    <span class="item-position">${esc(degree)}</span>
    <span class="item-date">${esc(start)} – ${esc(end)}</span>
  </div>
  <ul class="bullet-list">
    ${bullets(bl)}
  </ul>
</div>`;

const courseItem = ({ title, institution }) => `
<div class="course-item">
  <span class="course-title">${esc(title)}</span>
  <span class="course-separator"></span>
  <span class="course-institution">${esc(institution)}</span>
</div>`;

const skillGroup = ({ group, tags }) => `
<div class="skill-group">
  <span class="skill-label">${esc(group)}</span>
  <div class="skill-tags">
    ${tags.map(t => `<span class="skill-tag">${esc(t)}</span>`).join('\n    ')}
  </div>
</div>`;

const dot = (filled) =>
  `<div class="dot ${filled ? 'dot-filled' : 'dot-empty'}"></div>`;

const languageItem = ({ name, level, dots }) => `
<div class="language-item">
  <div class="language-name">${esc(name)}</div>
  <div class="language-level">${esc(level)}</div>
  <div class="language-dots">
    ${Array.from({ length: 5 }, (_, i) => dot(i < dots)).join('\n    ')}
  </div>
</div>`;

const portfolioItem = ({ label, url, display }) => `
<div class="portfolio-item">
  <div class="portfolio-icon">⌥</div>
  <div>
    <div class="portfolio-title">${esc(label)}</div>
    <div class="portfolio-link"><a href="${esc(url)}" target="_blank">${esc(display)}</a></div>
  </div>
</div>`;

const contactItem = (text, href) =>
  href
    ? `<span class="contact-item"><a href="${esc(href)}" target="_blank">${esc(text)}</a></span>`
    : `<span class="contact-item">${esc(text)}</span>`;

const sep = `<span class="contact-separator">·</span>`;

// ---- page break helper --------------------------------------

// Simple heuristic: split experience at index SPLIT_AT for page 2
const SPLIT_AT = 4; // first 4 roles on page 1, rest on page 2
const exp1 = cv.experience.slice(0, SPLIT_AT);
const exp2 = cv.experience.slice(SPLIT_AT);

// ---- CSS ----------------------------------------------------

const CSS = `
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --font-heading: 'Volkhov', Arial, Helvetica, sans-serif;
  --font-body:    'PT Sans', Arial, Helvetica, sans-serif;
  --color-text:   #000000;
  --color-muted:  #6f7878;
  --color-border: #000000;
  --page-padding: 50px;
}

body {
  font-family: var(--font-body);
  color: var(--color-text);
  background: #e8e8e8;
}

.page {
  width: 794px;
  min-height: 1122px;
  background: #ffffff;
  margin: 40px auto;
  padding: var(--page-padding) var(--page-padding) 0;
  box-shadow: 0 2px 8px rgba(0,0,0,.18);
}

.resume-header { text-align: center; margin-bottom: 6px; padding: 6px 12px; }

.header-name {
  font-family: var(--font-heading);
  font-weight: 700; font-size: 22px; line-height: 28px;
  text-transform: uppercase; color: var(--color-text);
}

.header-title {
  font-family: var(--font-body);
  font-weight: 400; font-size: 18px; line-height: 22px;
  color: var(--color-muted); margin-top: 2px;
}

.header-contacts {
  display: flex; flex-wrap: wrap;
  justify-content: center; align-items: center;
  gap: 0; margin-top: 4px;
}

.contact-item { font-family: var(--font-body); font-size: 13px; line-height: 16px; padding-bottom: 2px; white-space: nowrap; }
.contact-item a { color: inherit; text-decoration: none; }
.contact-separator { margin: 0 6px; color: var(--color-muted); font-size: 13px; }

.section { margin-bottom: 12px; }

.section-title {
  font-family: var(--font-heading);
  font-size: 18px; line-height: 23px; color: var(--color-text);
  border-bottom: 1px solid var(--color-border);
  padding: 6px 12px 0; margin-bottom: 0;
}

.item { padding: 6px 12px; }

.item-header { display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: nowrap; }
.item-org { font-family: var(--font-body); font-weight: 400; font-size: 18px; line-height: 22px; color: var(--color-muted); }
.item-location { font-family: var(--font-body); font-size: 15px; line-height: 18px; color: var(--color-text); text-align: right; white-space: nowrap; }
.item-row { display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: nowrap; margin-top: 1px; }
.item-position { font-family: var(--font-body); font-weight: 400; font-size: 15px; line-height: 18px; color: var(--color-text); }
.item-date { font-family: var(--font-body); font-weight: 400; font-size: 15px; line-height: 18px; color: var(--color-text); white-space: nowrap; text-align: right; flex-shrink: 0; }

.bullet-list { list-style: none; margin-top: 4px; }
.bullet-list li { display: flex; align-items: flex-start; font-family: var(--font-body); font-size: 13px; line-height: 18px; gap: 4px; }
.bullet-dot { flex-shrink: 0; line-height: 18px; }

.summary-text { font-family: var(--font-body); font-size: 13px; line-height: 18px; text-align: left; white-space: pre-wrap; }

.skill-group { display: flex; flex-wrap: wrap; align-items: baseline; gap: 0; padding: 6px 12px; }
.skill-label { font-family: var(--font-body); font-size: 15px; line-height: 18px; color: var(--color-muted); white-space: nowrap; flex-shrink: 0; }
.skill-label::after { content: ': '; }
.skill-tags { display: flex; flex-wrap: wrap; gap: 0; }
.skill-tag { font-family: var(--font-body); font-size: 13px; line-height: 16px; color: var(--color-text); }
.skill-tag:not(:last-child)::after { content: ', '; }

.languages-grid { display: grid; grid-template-columns: repeat(3, 1fr); }
.language-item { padding: 6px 12px; }
.language-name { font-family: var(--font-body); font-size: 15px; line-height: 18px; color: var(--color-text); }
.language-level { font-family: var(--font-body); font-size: 13px; line-height: 16px; color: var(--color-text); }
.language-dots { display: flex; gap: 4px; margin-top: 3px; }
.dot { width: 8px; height: 8px; border-radius: 50%; }
.dot-filled { background: var(--color-text); }
.dot-empty  { background: #e4e4e4; }

.portfolio-grid { display: grid; grid-template-columns: repeat(3, 1fr); }
.portfolio-item { display: flex; align-items: flex-start; gap: 8px; padding: 6px 12px; }
.portfolio-icon { font-size: 20px; color: var(--color-muted); line-height: 1; margin-top: 2px; }
.portfolio-title { font-family: var(--font-body); font-size: 15px; line-height: 18px; color: var(--color-text); font-weight: 400; }
.portfolio-link { font-family: var(--font-body); font-size: 13px; line-height: 16px; color: var(--color-text); word-break: break-all; }
.portfolio-link a { color: inherit; text-decoration: none; }

.page-footer { position: relative; height: 50px; }

.course-item { display: flex; align-items: baseline; flex-wrap: nowrap; padding: 6px 12px; gap: 0; }
.course-title { font-family: var(--font-body); font-weight: 400; font-size: 15px; line-height: 18px; color: var(--color-muted); flex-shrink: 1; white-space: nowrap; }
.course-separator { flex: 1; border-bottom: 1px dotted #ccc; margin: 0 8px; position: relative; top: -3px; min-width: 12px; }
.course-institution { font-family: var(--font-body); font-size: 13px; line-height: 16px; color: var(--color-text); white-space: nowrap; }

@media print {
  body { background: none; }
  .page { width: 100%; margin: 0; box-shadow: none; min-height: unset; }
  .page-break { page-break-after: always; }
}

@page { size: A4; margin: 0; }
`;

// ---- HTML template ------------------------------------------

const html = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>${esc(cv.personal.name)} - Resume</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Volkhov:wght@400;700&family=PT+Sans:wght@400;700&display=swap" rel="stylesheet" />
  <!-- Generated by Open-CV - edit cv.json, not this file -->
  <style>${CSS}</style>
</head>
<body>

<!-- PAGE 1 -->
<div class="page">

  <header class="resume-header">
    <div class="header-name">${esc(cv.personal.name)}</div>
    <div class="header-title">${esc(cv.personal.title)}</div>
    <div class="header-contacts">
      ${contactItem(cv.personal.phone)}
      ${sep}
      ${contactItem(cv.personal.email, `mailto:${cv.personal.email}`)}
      ${sep}
      ${contactItem(cv.personal.linkedin, cv.personal.linkedin)}
      ${sep}
      ${contactItem(cv.personal.location)}
    </div>
  </header>

  <section class="section">
    <div class="section-title">Summary</div>
    <div class="item">
      <p class="summary-text">${esc(cv.summary)}</p>
    </div>
  </section>

  <section class="section">
    <div class="section-title">Experience</div>
    ${exp1.map(experienceItem).join('\n')}
  </section>

  <div class="page-footer"></div>
</div>

<!-- PAGE 2 -->
<div class="page">

  <section class="section">
    <div class="section-title">Experience</div>
    ${exp2.map(experienceItem).join('\n')}
  </section>

  <section class="section">
    <div class="section-title">Education</div>
    ${cv.education.map(educationItem).join('\n')}
  </section>

  <section class="section">
    <div class="section-title">Training / Courses</div>
    ${cv.courses.map(courseItem).join('\n')}
  </section>

  <section class="section">
    <div class="section-title">Skills</div>
    ${cv.skills.map(skillGroup).join('\n')}
  </section>

  <div class="page-footer"></div>
</div>

<!-- PAGE 3 -->
<div class="page">

  <section class="section">
    <div class="section-title">Languages</div>
    <div class="languages-grid">
      ${cv.languages.map(languageItem).join('\n')}
    </div>
  </section>

  <section class="section">
    <div class="section-title">Portfolio</div>
    <div class="portfolio-grid">
      ${cv.portfolio.map(portfolioItem).join('\n')}
    </div>
  </section>

  <div class="page-footer"></div>
</div>

</body>
</html>`;

// ---- write HTML ---------------------------------------------

const htmlOut = resolve(__dirname, 'index.html');
writeFileSync(htmlOut, html, 'utf8');
console.log(`✔ index.html written`);

// ---- export PDF ---------------------------------------------

if (exportPdf) {
  const puppeteer = await import('puppeteer');
  const browser = await puppeteer.default.launch({ args: ['--no-sandbox'] });
  const page = await browser.newPage();

  await page.goto(`file://${htmlOut}`, { waitUntil: 'networkidle0' });
  await new Promise(r => setTimeout(r, 800)); // let Google Fonts render

  const pdfOut = resolve(__dirname, 'resume.pdf');
  await page.pdf({
    path: pdfOut,
    format: 'A4',
    printBackground: true,
    margin: { top: 0, right: 0, bottom: 0, left: 0 },
  });

  await browser.close();
  console.log(`✔ resume.pdf written`);
}
