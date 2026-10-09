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
6. **A requirement phrased with "ou" is one requirement.** Read the JD's list
   literally: "fintech, bancos, meios de pagamento ou sistemas financeiros"
   is satisfied the moment any one of them is evidenced. Stripe evidence is
   payments evidence. Never add a project, a bullet, or a tag to close the
   other alternatives of an "ou" list, and never report the unmatched words
   as a gap. A keyword score that misses them is a measurement artifact, not
   a missing requirement.
7. **A build is done only when its fit reads honestly and its debrief is
   written.** "The PDF exists" is not done, and neither is "the gates pass".
   A fit score that still carries noise, or two tools that disagree on the
   same posting, means the measurement is unfinished and the generation is
   not done. A run that ends without a cv-debrief record of what it surfaced
   repeats the finding next time. The two checks are the completion gate, not
   suggestions.
8. **Every demanded term the CV does not cover routes to the evidence ledger.
   This is the core operation of the flow.** `cv fit` lists each term the
   posting demands that the CV has not claimed, with its status. Soft names
   claim without proof; allowed names claim with the recorded reason;
   evidenced names claim after `cv gaps refresh`; anything else is a question
   for the operator (`cv gaps answer`), never a silent drop and never a
   padding of the score. The flow converts a missing list into evidence
   work, and coverage is gained by resolving evidence. Skill mentions are
   matched broadly: "ui", "ux" and "ux/ui" are one claim, because a company's
   ATS will not spell-check the variants.
9. **Never invent data.** Summary, bullets, figures and tags come from the
   JSON. If a claim is not reproducible from a repository, it does not go on
   the CV, whatever the posting asked for.

## Method

The flow is six steps, each backed by the CLI. Only the middle four need the
posting; the gate and the render frame them.

1. **Read the JD.**
   ```bash
   cv tailor <slug>               # what this posting asks, and what is open
   ```
   The JD lives at `companies/<slug>/description.md`. Read it as facts, not
   vibes: the requirements, the level (`pleno`, `sênior`), the "ou" lists.
2. **Extract the JD's keywords.**
   ```bash
   cv fit <slug>                  # the posting's terms, pre-filter
   ```
   Every content token the JD actually uses, before any opinion is applied.
3. **Filter out non-skill words.**
   ```bash
   cv fit <slug>                  # the same command reports the kept set
   ```
   URL lines, Portuguese function words, level and location words and
   accent-split fragments leave the keyword set; what remains is the posting's
   real skill and tech vocabulary.
4. **Match the kept set against the curated skills.**
   ```bash
   cv fit <slug>                  # matched and unmatched, per curated CV tag
   ```
   Compare the keep list to this CV's skill tags. An "ou" list is one
   requirement: matched the moment any alternative is evidenced. A seniority
   frame conflict surfaces here and stops for your decision.
5. **Check the evidence.**
   ```bash
   cv gaps check                  # nothing a CV claims stays unproven
   ```
   Every tag the CV will carry is evidenced, soft, or allowed. An unmatched
   alternative is never a reason to add a claim; it is either covered by
   evidence or a real absence to record.
6. **Write the CV.**
   ```bash
   cv generate --company <slug> --lang pt --pdf
   cv ats-check --company <slug> --lang pt --strict
   cv inbox score <slug>             # the base fit must read honestly before done
   cv fit <slug> --lang pt           # the tailored claims must match the ledger
   ```
   Generate, then the strict check decides done: gates green and the score at
   the floor. `cv inbox score <slug>` is the honest-fit check: when its terms
   still carry noise, or two tools disagree on the same posting, the build is
   not done. A score under the floor is content to iterate, never a renderer
   to force.

`cv fit <slug>` backs steps 2, 3 and 4 in one pass, so the posting's terms,
the filtered keep set, and the curated match are always the same numbers,
never three tools drifting apart.

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
[ ] no "ou" requirement is reported as a gap when one of its alternatives is evidenced
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