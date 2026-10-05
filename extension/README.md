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

Open a LinkedIn job. A blue button appears bottom-right. Click it. The toast
reports the path that was written, for example `companies/acme/description.md`.

Then, in the repo:

```
cv inbox list     # what is queued
cv inbox next     # the path of the oldest unprocessed capture
cv inbox done acme
```

## Why a button and not a scraper

The operator browses and chooses. Nothing here reads LinkedIn in the
background, follows links, or pages through results, so the extension is a
one-click hand-off rather than automation.

## When it says it could not read the job

LinkedIn renames its CSS classes and sometimes collapses the description.

- If the description is collapsed, expand it and click again.
- If a field is wrong, the selectors in `content.js` need updating. They are
  tried in order, so add the new class name to the front of the relevant list.
