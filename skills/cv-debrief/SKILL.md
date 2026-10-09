---
name: cv-debrief
description: "Use after every CV is generated or scored with this pipeline, to
capture what the run taught and turn it into the pipeline's own skills.
Debriefs the generation, the score and the ATS verdict, names each finding,
and proposes the skill update or operator decision it earns. Produces the
debrief record and the proposal only; it never edits the CV, the data, or the
skills without the operator's approval."
---

# You debrief every CV generation, and whatever it taught becomes a skill.

A generation run is a small experiment. It either passed clean, or it showed
something the pipeline did not anticipate: a scorer artifact, an "ou"
requirement, a seniority frame conflict, a gate that cannot see the data. The
value of the run is the finding, and the finding belongs in the pipeline's own
skills, not in the session that happened to hit it.

## The failure mode you exist to prevent

A run shows a real finding and the session moves on. The next generation hits
the same artifact, the same frame conflict, the same scorer noise, and the
operator re-diagnoses it by hand. Findings that are not captured are
re-discovery, billed every time.

## Hard rules

1. **Every generation ends in a debrief, even a clean one.** A passing run is
   a finding too: it confirms the gate, the frame, and the score hold. Skip
   the debrief only when nothing was generated.
2. **A finding is a fact, not a fix.** Record what the run showed, with the
   command and the number: the score, the gate that fired, the artifact word.
   Do not edit the skill in the same breath; the proposal is the deliverable.
3. **Every finding names an owner:** an existing rule in `cv-operations`, a
   step or gate in `generate-cv`, a brand-new producer skill when the finding
   repeats enough to earn one, or the operator when it is a decision (which
   projects to include, which name to approve) rather than a defect.
4. **A produced skill is proposed, never written mid-run.** The debrief names
   the change and the file; writing it happens after approval, in the edit
   itself, so a finding that argues both sides cannot slip in.
5. **The debrief must not invent.** Everything cited is reproducible from the
   commands it names. No em-dash, English, and it never claims a number the
   run did not produce.

## Method

1. **Run the generation and its checks.** Generate the CV, run the strict ATS
   check, and read the fit components.
2. **Collect the findings.** What surprised the run: a score that does not
   read correctly, a gate that fired on real content, a frame or "ou"
   requirement the skill did not anticipate, a keyword list full of noise.
3. **Name each finding's owner** and the exact change it would justify: a rule
   added to `cv-operations`, a step or gate row in `generate-cv`, a new
   producer skill with its own description, or an operator decision.
4. **Write the record.** One markdown record per generation, in the project
   docs root `~/lab/docs/cv/debriefs/`, named for the slug and date. Records
   are docs: they never live inside `skills/`. List the run, the findings,
   and each proposed change.
5. **Stop.** The record is the output. Editing the CV, the data, or the skills
   happens after the operator approves each proposed change.

## The gate

Pass 1, the record is complete:
```
[ ] the generation and checks it ran are named
[ ] every finding carries the command and number that produced it
[ ] every finding names an owner and exactly one proposed change
```
Pass 2, the findings hold together:
```
[ ] each proposed change traces to the finding, not to a neighboring worry
[ ] no two proposals contradict each other or an existing rule
[ ] each finding is reproducible from the cited command
[ ] a passing run is recorded as such, never inflated into a finding
```

## The output template

A record is one markdown file per generation:

```markdown
# Debrief: <slug or base>, <lang>, <date>

## Run
- commands: cv generate ..., cv ats-check ..., cv inbox score ...
- verdict: <gates / strict score / fit components>

## Findings
- <symptom with the number and the command that produced it>

## Proposed changes
- <owner> | <skill file> | <the exact rule or step>
- <owner=operator> | <the decision being asked, with the options>

## Stopped at
- <what was not changed and why, awaiting approval>
```

## Handoff

Say the verdict, the findings, and the owners. The record is complete when the
operator can approve each proposed change without re-running anything; that is
the stop. Writing the approved changes is a separate, later edit, and this
debrief does not perform it.