# CV Job Capture (browser extension)

Loads a **Salvar no CV** button on the LinkedIn job detail page. Clicking it
sends the job description to a local endpoint, which writes
`companies/<slug>/description.md` and queues it. Tailoring still happens
afterwards, because it needs the operator's answers.

## Install

1. `cv inbox serve` in the cv repo, and copy the token it prints.
2. Chrome, `chrome://extensions`, enable **Developer mode**.
3. **Load unpacked**, and pick this `extension/` directory.
4. Click the extension icon, paste the token, **Save**, then **Test**.
   It should say the local server is reachable.

## Use

Open a LinkedIn job. The button in the job header shows where that job already
is in the pipeline, so a job you have already handled is never captured twice:

| Button | Meaning | Click |
| --- | --- | --- |
| **Apply with CV** | not captured yet | captures the JD |
| **CV pending** | captured, no CV yet | re-captures, syncing the JD |
| **CV ready** | a tailored CV exists | opens the company apply link, and a **Mark applied** control appears next to it |
| **Applied** | the application went out | nothing |

Then, in the repo:

```
cv inbox list --all    # every capture with its step
cv inbox next          # the path of the oldest capture with no CV
cv inbox applied acme  # record that this one was sent
```

The toolbar popup is the panel: the 25 most recent captures, newest first, each
with its step and its Job and Apply links, and a **Mark applied** control.

Each row also has a **Decline** field: type why you are passing on a posting, in
your own words, and it is recorded with the step. A declined posting shows the
reason and a **Reconsider** control, so a judgement made in a hurry can be taken
back. The reason is yours to write; the CLI accepts one too,
`cv inbox skip <slug> -r "why"`, and `cv inbox reconsider <slug>` reverses it.

Steps are derived by the local server rather than stored: `captured` until a
`cv-*.json` exists (`cv-ready`), then `applied` once recorded. Nothing has to be
kept in sync, so regenerating or deleting a CV moves the step on its own.

## Reconciling with LinkedIn's Applied list

The ledger records that a CV was written, never that an application was sent.
LinkedIn does know, on **My Jobs -> Applied**, so that page gets a **Reconcile
with the CV ledger** button. It reads the job ids the page already shows and
marks each matching capture applied. Open the Applied list, click it once.

## Why a button and not a scraper

The operator browses and chooses. Nothing here reads LinkedIn in the
background, follows links, or pages through results, so the extension is a
one-click hand-off rather than automation. The Applied list is read only when
the operator clicks reconcile on it.

## When it says it could not read the job

LinkedIn renames its CSS classes and sometimes collapses the description.

- If the description is collapsed, expand it and click again.
- If a field is wrong, the selectors in `content.js` need updating. They are
  tried in order, so add the new class name to the front of the relevant list.
