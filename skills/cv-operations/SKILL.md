---
name: cv-operations
description: "Use when working on the cv job-application pipeline, or reading a
capture, an evidence, a gap or a fit percent. The authority on how this pipeline
is operated: what captured data means, what proves a claim, what a score is, and
how changes and commits are made here. Produces nothing and writes nothing; it
is loaded so a session does not rediscover these rules."
---

# The authority on operating the cv pipeline

A free, open-source job-application pipeline whose defining property is that it
never claims what its code cannot prove. Everything below is a rule with the
reason it exists, learned the hard way in one working session.

## Evidence is the diff, never the file

A skill is claimable only where the lines the operator's commits added prove
it. A needle sitting in a teammate's line, or in a file the operator merely
touched, is not evidence. The scanner reads `git log --all --author=<author
set> -p` and keeps the `+` hunks, so a whole-file match reads as nothing.

The walk crosses every branch, not just the checked-out one. Work the operator
finished on a feature branch is theirs whether or not it was merged, and a
HEAD-only walk reads a whole branch of contribution, a Criteria builder or a
Strategy pattern, as if it never happened.

Author attribution is by identity, not display name. Commits carry different
names across employers but a stable email, so the author set in `skills.json`
matches both, and every repo checked resolves to exactly the operator's own
identities, never to a namesake.

The candidate finder `cv evidence` is advisory by design; the gate that decides
claims uses the diff corpus and nothing else. Do not weaken a gate to reach
green: a capture is refused when a claimed skill loses its diff evidence.

## Captures never decide their own fate

Capturing and judging are two actions. `Apply with CV`, or any capture, always
places the job in the pipeline with status `new`. A low fit is a note, never a
verdict. To set a capture aside, score it first and then move it: the panel's
Match button, or `cv triage add <slug>`, which reports the fit and moves the
job below the minimum only when asked.

The four postings already triaged were the residue of a former bug: their
titles had been captured as the location ("Remote"). They are handled with
`cv triage promote` and `cv triage drop --yes`.

## Reading a fit percent

A capture's percent is `100 * (0.5*jd + 0.3*skill + 0.2*title)`, where the jd
axis is the share of the posting's "distinctive" terms that appear in the CV
narrative, the skill axis is the share of the CV's tags mentioned verbatim in
the posting, and the title axis is the token overlap between the posting title
and the CV's `personal.title`.

The jd axis has a real bias: it counts nearly every capitalized word, and
Portuguese capitalizes sentence starts, so a Portuguese posting's terms are
mostly prose the English CV narrative misses, and the axis caps low no matter
how well the job fits. Before judging a percent, read the components: `cv
inbox score <slug>` names which terms missed, which tags hit, and the title
overlap point by point. A low percent for a Portuguese or mobile posting is
expected and is not, by itself, a reason to set the job aside.

After a capture's fields were corrupted by a title bug, `cv inbox repair`
re-derives title and location from LinkedIn's guest detail page by posting id,
falls back to the first title-looking line in the JD, re-scores, and re-runs
the triage gate. It is a dry run by default; `--apply` writes.

## The evidence and gaps flow

`cv gaps refresh` reads both probe patterns and the packages the same diff
lines import, and merges them into one ledger. The packages are bound to
skills through a hand-reviewed mapping in `skills.json`; standard library and
`@/` aliases carry no signal and are skipped; unmapped packages used across
two or more repos are written to gitignored `candidates.json` for the operator
to approve, never auto-approved.

`cv skillscan` reports, per repo, the authored imports with a mapped skill,
then the candidates. A demanded skill that the code cannot prove is never a
flat gap: the report asks the operator, and `cv gaps answer` records the
answer, with an engagement that moves the skill out, or `--could-not-place`
that keeps it there. The gaps are what remains after both the research and the
ask leave a skill unresolved.

## Records, and the shape of a change

Significant decisions get a record in the docs root before the implementation
lands. Patterns matter: numbered, kebab-cased, a status line, and a superseding
record links back instead of editing the old one. Code and records live in
separate repositories, and both are committed by scope.

Every change ships with its tests. A bug fix gets a test that reproduces it
first; a low fit is diagnosed, never silenced.

## This file's commit rules

The repo's own commit hook enforces these, so a message that violates them is
refused, and the refusal is the point, not an obstacle.

- Conventional Commits: `feat:`, `fix:`, `docs:`, and the subject names the
  change, never the record or the process that produced it.
- The subject is imperative, lowercase, no trailing period, at most 50 columns
  after the type's colon.
- The body runs at most three lines, each at most 72 columns.
- The subject must not join two changes with "and"; a second change is a
  second commit.
- No record may be cited; state the fact, never its source.
- Commit by scope as a standing default: one focused commit per concern,
  without stopping to ask. Push always needs a separate, explicit ask.
- A failed message carries the reason; reword to fix it, never bypass the hook.

Folding review noise is normal: `githooks review origin/main..HEAD` reports
violations that fixup, and unpushed violations are rewound with `git rebase -i`
(pick the first, squash the rest, provide the merged message through the
editor), so the violation never existed for others.

## Verification before "done"

`cv gaps check` passes, the full test suite is green, `ruff` and `node
--check` are clean, the extension's behavior tests pass, and the docs check
reports no em-dash. A change that touches the evidence or gate leaves those
numbers verifiable in the report, never asserted.