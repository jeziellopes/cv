---
name: generate-cv
description: "Use when a resume has to be built or rebuilt with this pipeline,
for the base CVs or for one posting, or when a built CV has to be judged good
enough to send. Generates the tailored CV as HTML and PDF and runs the ATS
check that decides whether the build is done. Produces the PDF and its ATS
verdict only; it never edits cv.json, writes personal data, or applies to a job."
---

# You generate a CV; you do not declare one done.

The pipeline turns `cv.json` into a gated, ATS-checked PDF, and the definition
of done is a green gate, not an existing file. A PDF that exists proves only
that a render ran.

## The failure mode you exist to prevent

A CV is reported as built because the PDF appeared. No gate ran, no strict
score was read, and a posting-tailored CV went out carrying a claim the ledger
cannot prove, or an ATS reading order that split a role from its bullets. The
operator sees "generated" and the document is unusable to the ATS that is
going to parse it.

## Hard rules

1. **Nothing renders until the gate passes.** `cv gaps check` reports a clean
   count, and `cv generate` itself refuses to render a CV that claims a skill
   the ledger cannot evidence. Never render around the refusal.
2. **Only the JSON is edited.** `cv.json` and `cv-pt.json` are the data;
   `index.html` and the PDFs are artifacts and are overwritten on each build.
3. **A posting gets a tailored CV first.** Run `cv tailor <slug>` to answer
   which projects to include and which may be named, apply the answers into
   `companies/<slug>/cv-<lang>.json`, and only then generate it. The base CV
   and a tailored CV are different documents.
4. **Done means the ATS gates pass and the strict score clears.** A single
   `cv ats-check --pdf <pdf> --strict` decides it: gates all green and overall
   score at least the floor. A score under the floor is a build to fix, not a
   build to ship.
5. **The seniority frame is a tailoring decision, never assumed.** Read the
   posting's level from the title and JD (`pleno`, `sênior`, `júnior`, role
   words), read how the CV frames you (a founder or lead title, the org the
   experience section leads with), and when they disagree, ask the operator
   which frame this posting gets before any generate. A founder framing aimed
   at a Pleno role is not an error the moment it is written; it is an open
   question. For a Pleno posting the standing frame is: hands-on senior
   contributor. Founder and org-leading words leave the title, the summary,
   and the role line, while the org itself stays in the experience section
   unchanged.
6. **Never invent data.** Summary, bullets, figures and tags come from the
   JSON. If a claim is not reproducible from a repository, it does not go on
   the CV, whatever the posting asked for.

## Method

1. **Confirm the base data is current.** The text you render is whatever
   `cv.json` (English) and `cv-pt.json` (Portuguese) hold today. Do not edit a
   rendered file.
2. **Run the gate.**
   ```bash
   cv gaps check
   ```
   Any CV that claims an unproven skill is reported; fix the tag, the
   evidence, or the claim before rendering.
3. **For a posting, tailor first.**
   ```bash
   cv inbox next          # the oldest capture that still needs a CV
   cv tailor <slug>       # the questions this posting asks
   ```
   Read what the JD asks for, then compare the posting's seniority with how
   the CV frames you: if the JD wants `Pleno` and the CV leads with a founder
   or lead title, ask which frame this posting uses before writing the
   tailored JSON. Write the tailored JSON under `companies/<slug>/`.
4. **Generate.**
   ```bash
   cv generate --pdf --lang en                # base English resume
   cv generate --pdf --lang pt                # base Portuguese resume
   cv generate --company <slug> --lang pt --pdf   # a posting's tailored CV
   ```
   Thematic and margin choices are `--theme` and `PAGE_MARGIN`; they change
   the look, never the content.
5. **Verify, then decide.**
   ```bash
   cv ats-check --pdf <pdf> --strict
   ```
   Green gates and a qualifying score mean done. When a gate fails, read
   which one: a missed field like a course or a tag is a content problem in
   the JSON, and a reading-order break after a role is a section problem. Fix
   the source, regenerate, and re-check until the one command passes.
6. **Iterate on the data, never on the renderer.** A strict floor under the
   target is earned with content, not by toggling checks.

## The gate

Pass 1, the presence of a build:
```
[ ] the PDF exists at the expected path
[ ] cv gaps check is clean
[ ] ats-check --strict passes (gates green, score >= the floor, JD coverage >= 0.60 where a JD is given)
```
Pass 2, the build holding together:
```
[ ] the PDF has the same orgs, roles, dates and bullets as the JSON it was built from
[ ] nothing on the CV claims a skill the ledger cannot prove
[ ] no ATS gate flags a reading-order break or a missing field
[ ] the sender's name matches the personal data, not the file's old name
[ ] the posting's seniority and the CV framing agree, or the operator chose the frame
```

## The output template

The artifact is the PDF plus the scorecard it carries. A completed build reads:

```
cv generate --pdf --lang en
✔ index.html written  (lang: en, theme: classic)
✔ <Name>-en.pdf written
cv ats-check --pdf <Name>-en.pdf --strict
✔ All ATS gates passed
✔ overall score 90+ (or the configured floor)
```

## Handoff

Say which PDF was written, the gate count that let it render, and the strict
score once it passed. Stop there: the application happens elsewhere, and a
gate failure gets fixed in the JSON, in a session that reads it, not in this
one by editing the renderer.