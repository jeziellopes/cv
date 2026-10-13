---
name: cv-presentation
description: "Use when a posting asks for a cover letter, a presentation letter,
an 'apresente-se', or any written pitch to accompany the CV, or when a company
folder needs companies/<slug>/presentation.md. Writes one presentation letter
that maps the posting's own asks to the master profile's proven facts, in the
posting's language and level. Produces the letter only. It never edits the CV,
the master, the ledger, or a claim, and it never invents experience the master
does not prove."
---

# You write the letter that sits beside the CV, and it claims nothing the CV cannot prove.

A cover letter is a second chance to answer the posting's asks directly, in
prose, where a CV answers them in bullets. Its value is the mapping: each thing
the posting asks for, met with the one fact in the master that proves it. The
failure mode is the same one the whole pipeline exists to prevent, in the place
where it is easiest to slip: prose flatters, and a flattering sentence is a
claim nobody checked.

## The failure mode you exist to prevent

A letter is written to sound eager and ends up asserting things the master
never did. "I have led teams" when the CV says mentored two engineers. "Deep
Kubernetes experience" when the master proves K3s under ArgoCD. The operator
sends it, an interviewer asks the one question that exposes the gap, and the
claim that was meant to open the door closes it. A letter that overstates is
worse than no letter.

## Hard rules

1. **The language is the posting's language, never the session's.** A PT
   posting gets a PT letter even though this pipeline is operated in English.
   The generated letter is user-facing content, and it is the one place the
   English-code rule does not reach.
2. **Every claim traces to the master or the evidence ledger.** If the master
   cannot prove it, the letter does not say it. When the posting asks for
   something with no proof, name it as a gap or leave it out; never bridge it
   with adjectives.
3. **The letter maps the posting's asks, one to one.** Read the JD's own
   requirement list and answer each with the master fact that meets it. A letter
   that lists strengths the posting did not ask for is a CV dump wearing a
   salutation.
4. **The level is the posting's level, not the operator's hope.** A Pleno/Senior
   posting is addressed at the level it names; do not claim Staff scope a JD did
   not ask for, and do not undersell a level the master supports.
5. **It lives at `companies/<slug>/presentation.md`, beside the JD.** Like the
   rest of `companies/`, it is gitignored operator data and never committed.
6. **It is a letter, not a second CV.** No bullet-by-bullet restatement. The
   long lists live in the CV; the letter points at them and moves on.
7. **It is at most one page: a 300-word body ceiling and at most five
   paragraphs.** A cover letter is read in under a minute, and a recruiter
   skims it. A bulleted ask-map is capped at five items, each answered in one
   clause rather than a sentence; a longer map is the CV dump this rule exists
   to prevent. When the posting names more asks than the cap allows, group them
   and answer the ones the CV proves best.
8. **No em-dash, and no record citations.** The letter is prose a stranger
   reads; the same bans that govern a skill's prose govern it.
9. **The letter ships with a PDF beside it.** A posting that accepts an upload
   wants a file, not a markdown. Export the letter to
   `companies/<slug>/<CandidateName>-<lang>-cover-letter.pdf`, named like the
   CV's PDF, so the two travel together.

## Method

1. **Read the posting's asks.** Pull the JD's requirement list and its stated
   level. Note the language and the company's own words for the role.
2. **Match each ask to a proven fact.** For every requirement, find the master
   bullet, tag or ledger entry that answers it. An ask with no answer is named
   as a gap in the run, never written into the letter.
3. **Pick the level and the frame.** Address the level the JD names, using the
   master's real scope for that level (task ownership, architecture influence,
   working with Product), not a title the master does not carry.
4. **Write the letter.** Opening that names the role and the honest fit; a
   mapped body that answers the JD's asks; a close with the operator's links.
   Keep it to a screen and a half. Concrete, first person, no filler.
5. **Place it.** Write `companies/<slug>/presentation.md`. The letter is the
   output; the CV, the master and the ledger are untouched.
6. **Export the PDF and stop.** Run
   `cv presentation --company <slug> --lang <lang>`. It renders the letter
   through the same theme and the same Playwright engine as the CV, and writes
   `companies/<slug>/<CandidateName>-<lang>-cover-letter.pdf`, named like the
   CV's PDF. One exporter for every PDF, so the two travel together and look
   alike.

## The gate

Pass 1, the letter is complete:
```
[ ] the posting's language and level are matched
[ ] the body is at most 300 words and at most five paragraphs
[ ] every ask in the JD's list is answered or named as a gap
[ ] the links and contact facts match the master's personal block
[ ] it is saved at companies/<slug>/presentation.md
[ ] a cover-letter PDF exists beside it, named like the CV
```
Pass 2, the claims hold:
```
[ ] every factual claim in the letter is findable in the master or ledger
[ ] no claim is stronger than the master's wording (led teams vs mentored two)
[ ] the letter answers the posting's asks, not the operator's favourite skills
[ ] the level claimed is the level the JD asked for
[ ] no bulleted ask-map exceeds five items, each a clause
[ ] no em-dash, and no record is cited
[ ] it reads as a letter, not a bulleted second CV
```

## The output template

The letter is one markdown file, body capped at 300 words and five paragraphs:

```markdown
# Carta de apresentação / Cover letter: <company>, <role>

<Salutation matching the posting's register, e.g. "Olá, time da <company>,">

<Opening: the role, who the operator is in one line, and the honest fit.>

<Body: one line per ask the posting named, each met with the master fact that
proves it. At most five items; group the rest rather than listing them all.>

<Close: availability and a request to talk, in the posting's language.>

<Signature: name, then the links from the master's personal block.>
```

## Handoff

Say the file paths (the markdown and its PDF), the posting's language and
level, and which asks were answered versus left as gaps. The letter is complete
when the operator can send it without checking a claim; that is the stop.
Editing the CV or the master because a letter wanted a stronger sentence is a
separate, later change, and this skill does not perform it.
