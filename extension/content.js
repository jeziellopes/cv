// Inject one capture button on the LinkedIn job detail page.
//
// LinkedIn is a single-page app and uses history.pushState, which fires no
// navigation event, so the script loads on any LinkedIn page and watches three
// ways: a MutationObserver, popstate, and a low-frequency URL poll.
//
// Extraction is layered, because LinkedIn renames classes and varies the DOM
// between accounts and experiments: known selectors, then JSON-LD JobPosting,
// then document metadata. When all of that fails it dumps what it did find, so
// the failure can be diagnosed from the console rather than guessed at.

const TAG = "[cv-capture]";

const SELECTORS = {
  title: [
    ".job-details-jobs-unified-top-card__job-title",
    "[class*='job-details-jobs-unified-top-card__job-title']",
    "[class*='jobs-unified-top-card__job-title']",
    ".jobs-unified-top-card__job-title",
    "h1.t-24",
    "h1",
  ],
  company: [
    ".job-details-jobs-unified-top-card__company-name",
    "[class*='job-details-jobs-unified-top-card__company-name']",
    "[class*='unified-top-card__company-name']",
    "[class*='company-name']",
    ".job-details-jobs-unified-top-card__primary-description-container a",
    ".jobs-unified-top-card__subtitle-primary-grouping a",
  ],
  location: [
    ".job-details-jobs-unified-top-card__primary-description-container",
    "[class*='unified-top-card__primary-description']",
    "[class*='unified-top-card__bullet']",
    ".jobs-unified-top-card__bullet",
  ],
  description: [
    ".jobs-description__content",
    "[class*='jobs-description__content']",
    ".jobs-box__html-content",
    "[class*='jobs-description']",
    "#job-details",
  ],
};

const BUTTON_ID = "cv-capture-button";
const TOAST_ID = "cv-capture-toast";

function log(...args) {
  console.log(TAG, ...args);
}

function textOf(el) {
  if (!el) return "";
  return (el.innerText || el.textContent || "").replace(/\s+/g, " ").trim();
}

function firstText(selectors) {
  for (const sel of selectors) {
    let el;
    try {
      el = document.querySelector(sel);
    } catch {
      continue;
    }
    const text = textOf(el);
    if (text) return text;
  }
  return "";
}

function descriptionText() {
  // Legacy semantic classes first, in case an account still serves them.
  for (const sel of SELECTORS.description) {
    let el;
    try {
      el = document.querySelector(sel);
    } catch {
      continue;
    }
    if (!el) continue;
    const text = (el.innerText || el.textContent || "").trim();
    if (text.length > 40) return text;
  }

  // Otherwise the job details screen, whose container is a stable data
  // attribute even though every class name is now hashed.
  let pane = null;
  for (const sel of ["[data-sdui-screen*='JobDetails']", "#workspace", "main"]) {
    try {
      pane = document.querySelector(sel);
    } catch {
      pane = null;
    }
    if (pane) break;
  }
  if (!pane) return "";

  const text = (pane.innerText || pane.textContent || "").replace(/\r/g, "");
  if (text.length < 40) return "";

  // Slice from the description heading, and stop at the apply/alert chrome.
  // Bare "apply" is not a stop word: it appears inside real descriptions.
  const start = text.match(
    /(sobre a vaga|descri[çc][ãa]o da vaga|requisitos|responsabilidades|atividades|about the job)/i
  );
  let body = start ? text.slice(start.index + start[0].length) : text;
  const stop = body.search(
    /(candidate-se|candidatar-se|inscreva-se|enviar curr|easy apply|set alert|alerta de vaga|reportar|denunciar|see how you compare|candidates who clicked apply|about the company|candidate seniority level)/i
  );
  if (stop > 0) {
    const cut = body.slice(0, stop).trim();
    if (cut.length >= 40) body = cut;
  }
  return body.trim();
}

// LinkedIn job pages often carry schema.org JobPosting, which is stable across
// the class renames that break selector-based extraction.
function fromJsonLd() {
  let scripts;
  try {
    scripts = document.querySelectorAll('script[type="application/ld+json"]');
  } catch {
    return null;
  }
  for (const script of scripts) {
    let parsed;
    try {
      parsed = JSON.parse(script.textContent);
    } catch {
      continue;
    }
    const roots = Array.isArray(parsed) ? parsed : [parsed];
    for (const root of roots) {
      const nodes = root && root["@graph"] ? root["@graph"] : [root];
      for (const node of nodes) {
        if (!node || node["@type"] !== "JobPosting") continue;
        const org = node.hiringOrganization || {};
        const places = [].concat(node.jobLocation || []).map((loc) => {
          const addr = (loc && loc.address) || {};
          return [addr.addressLocality, addr.addressRegion]
            .filter(Boolean)
            .join(", ");
        });
        return {
          title: node.title || "",
          company: org.name || "",
          location: places.filter(Boolean).join(" | "),
          description: (node.description || "").replace(/<[^>]+>/g, " ").trim(),
        };
      }
    }
  }
  return null;
}

function fromMeta(name) {
  const el =
    document.querySelector(`meta[property="${name}"]`) ||
    document.querySelector(`meta[name="${name}"]`);
  return el ? (el.getAttribute("content") || "").trim() : "";
}

function currentJobId() {
  const fromPath = location.pathname.match(/\/jobs\/view\/(\d+)/);
  if (fromPath) return fromPath[1];
  const fromQuery = location.search.match(/currentJobId=(\d+)/);
  return fromQuery ? fromQuery[1] : "";
}

// An external application is an anchor whose target LinkedIn hides behind a
// redirect. Easy Apply has no external URL at all: its control is a button, so
// this returns nothing, which is the correct answer for those jobs.
const APPLY_SELECTORS = [
  'a[aria-label*="apply on company" i]',
  'a[aria-label*="candidat" i]',
  'a[aria-label*="apply" i]',
  'a[href*="/safety/go"]',
];

function unwrapApplyHref(href) {
  if (!href) return "";
  let url;
  try {
    url = new URL(href, location.href);
  } catch {
    return "";
  }
  const isLinkedIn = /(^|\.)linkedin\.com$/i.test(url.hostname);
  if (isLinkedIn && url.pathname.startsWith("/safety/go")) {
    // The searchParams getter already decodes once; decoding again would
    // corrupt a URL that legitimately contains percent escapes.
    const target = url.searchParams.get("url");
    return target && /^https?:\/\//i.test(target) ? target : "";
  }
  return /^https?:\/\//i.test(url.href) ? url.href : "";
}

function applyUrl() {
  for (const sel of APPLY_SELECTORS) {
    let el;
    try {
      el = document.querySelector(sel);
    } catch {
      continue;
    }
    if (!el) continue;
    const url = unwrapApplyHref(el.href || el.getAttribute("href") || "");
    if (url) return url;
  }
  return "";
}

// A job page is one where the URL names a job, or a description pane exists.
function isJobPage() {
  if (currentJobId()) return true;
  return SELECTORS.description.some((sel) => {
    try {
      return Boolean(document.querySelector(sel));
    } catch {
      return false;
    }
  });
}

// document.title is "Job Title | Company | LinkedIn" on a job page, and it
// survived the class-name change that broke every selector.
function titleParts() {
  const parts = String(document.title || "")
    .split(/\s+[|\u2013\u2014-]\s+/)
    .map((s) => s.trim())
    .filter(Boolean);
  if (parts.length && /linkedin/i.test(parts[parts.length - 1])) parts.pop();
  return parts;
}

function cleanTitle(text) {
  return String(text || "").replace(/^(selected|selecionado)[,\s]+/i, "").trim();
}

// "Remote", "São Paulo" and the company each live on the location line for
// some layouts. A locator that lands on that line is reading the wrong thing,
// so a title that equals the location is treated as the failed extraction the
// spec pins rather than accepted as the role.
function sameAsLocation(candidate, location) {
  if (!candidate || !location) return false;
  const norm = (text) =>
    String(text)
      .toLowerCase()
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/[^a-z0-9\s]/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  return norm(candidate) === norm(location);
}

function fromAriaLabel() {
  let el = null;
  try {
    el = document.querySelector('[aria-label^="Company logo for"]');
  } catch {
    el = null;
  }
  if (!el) return "";
  return String(el.getAttribute("aria-label") || "")
    .replace(/^Company logo for[,:]?\s*/i, "")
    .replace(/\.$/, "")
    .trim();
}

function extract() {
  const jsonLd = fromJsonLd() || {};
  const parts = titleParts();
  const id = currentJobId();

  // The location is resolved before the title so a title that merely repeats
  // the location line can be detected and rejected.
  const location = firstText(SELECTORS.location) || jsonLd.location || "";

  // The title link for this job carries the clean title; the list wrapper adds
  // a "Selected, " prefix that the anchor itself does not.
  const candidates = [];
  if (id) {
    try {
      candidates.push(textOf(document.querySelector(`a[href*="/jobs/view/${id}"]`)));
    } catch {
      candidates.push("");
    }
  }
  candidates.push(firstText(SELECTORS.title), parts[0], jsonLd.title,
                  fromMeta("og:title"));

  let title = "";
  for (const candidate of candidates) {
    const cleaned = cleanTitle(candidate);
    if (!cleaned) continue;
    if (sameAsLocation(cleaned, location)) continue;
    title = cleaned;
    break;
  }

  // The company logo's aria-label names the company, and it is stable.
  const company =
    fromAriaLabel() ||
    textOf(document.querySelector('a[href*="/company/"]')) ||
    firstText(SELECTORS.company) ||
    parts[1] ||
    jsonLd.company ||
    "";

  return {
    title,
    company,
    location,
    url: id ? `https://www.linkedin.com/jobs/view/${id}/` : location.href,
    apply_url: applyUrl(),
    description: descriptionText() || jsonLd.description || "",
    source: "linkedin-extension",
  };
}

// The job panel's markup, so exact selectors can be written from the repo.
// LinkedIn inlines large SVG icons, which spent the whole budget and truncated
// the sample before the description; those are stripped, and the job pane is
// preferred over the whole body.
function domSample() {
  let container = null;
  for (const sel of ["[data-sdui-screen*='JobDetails']", "#workspace", "main"]) {
    try {
      container = document.querySelector(sel);
    } catch {
      container = null;
    }
    if (container) break;
  }
  const target = container || document.body;
  if (!target || !target.outerHTML) return "";

  const stripped = target.outerHTML
    .replace(/<script[\s\S]*?<\/script>/gi, "")
    .replace(/<style[\s\S]*?<\/style>/gi, "")
    .replace(/<svg[\s\S]*?<\/svg>/gi, "")
    .replace(/<path[^>]*>/gi, "");
  return stripped.slice(0, 400000);
}

// Every class name on the page that looks job-related, which is the shortest
// path to a working selector.
function classHints() {
  const seen = new Set();
  const out = [];
  let nodes;
  try {
    nodes = document.querySelectorAll(
      '[class*="job"], [class*="top-card"], [class*="topcard"]'
    );
  } catch {
    return out;
  }
  for (const el of nodes) {
    const className = String(el.className || "");
    if (!className || typeof className !== "string") continue;
    const key = `${el.tagName}.${className}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(key.slice(0, 160));
    if (out.length >= 40) break;
  }
  return out;
}

// What the page actually contains, so a failure can be reported rather than
// guessed at.
function diagnose() {
  const samples = {};
  for (const key of ["title", "company", "description"]) {
    samples[key] = SELECTORS[key]
      .map((sel) => {
        let el;
        try {
          el = document.querySelector(sel);
        } catch {
          return null;
        }
        return el ? `${sel} -> "${textOf(el).slice(0, 60)}"` : null;
      })
      .filter(Boolean);
  }
  const headings = Array.from(document.querySelectorAll("h1, h2"))
    .slice(0, 6)
    .map((el) => `${el.tagName}.${el.className}`.slice(0, 90));

  return {
    url: location.href,
    documentTitle: document.title,
    ogTitle: fromMeta("og:title"),
    jobId: currentJobId() || null,
    jsonLd: Boolean(fromJsonLd()),
    matched: samples,
    headings,
    classHints: classHints(),
    domSample: domSample(),
  };
}

function toast(message, ok) {
  let el = document.getElementById(TOAST_ID);
  if (!el) {
    el = document.createElement("div");
    el.id = TOAST_ID;
    document.body.appendChild(el);
  }
  el.textContent = message;
  el.className = ok ? "cv-toast cv-toast-ok" : "cv-toast cv-toast-err";
  el.style.display = "block";
  clearTimeout(el._timer);
  el._timer = setTimeout(() => {
    el.style.display = "none";
  }, 5000);
}

async function onCapture(button) {
  const payload = extract();
  log("extracted", payload);

  if (!payload.company || !payload.title) {
    const diag = diagnose();
    log("diagnose", diag);
    // Best effort: let the repo record what the page looked like, so the
    // selector can be fixed without a round trip through DevTools.
    try {
      await chrome.runtime.sendMessage({ type: "diagnose", payload: diag });
    } catch {
      /* the server may not be running; the console log still has it */
    }
    toast(
      "Could not read the title or company. Diagnosis sent to the repo.",
      false
    );
    return;
  }
  if (payload.description.length < 40) {
    toast("The description looks collapsed. Expand it (See more), then retry.", false);
    return;
  }

  button.disabled = true;
  button.textContent = "Enviando...";
  let result;
  try {
    result = await chrome.runtime.sendMessage({ type: "capture", payload });
  } catch {
    result = { ok: false, error: "The extension was reloaded. Refresh the page." };
  }
  button.disabled = false;
  button.textContent = "Apply with CV";

  if (result && result.ok) {
    const rated = result.match == null ? "" : `  ${result.match}% match`;
    const went = result.triage
      ? `, triaged below ${result.min}%`
      : "";
    toast(`Saved to ${result.path}${rated}${went}`, true);
    log("saved", result);
  } else {
    toast(`Not saved: ${(result && result.error) || "unknown error"}`, false);
    log("failed", result);
  }
  await refreshJobState();
  refreshButtons();
}

// ---- step awareness --------------------------------------------------------
//
// A capture has three steps: captured (the JD is in the ledger), cv-ready (a
// tailored CV exists on disk), applied (the application went out). The page
// reads the step from the local server by job id, so a job already in the
// pipeline shows where it is instead of inviting a second capture.

const APPLIED_BUTTON_ID = "cv-applied-button";

const STEP_LABEL = {
  none: "Apply with CV",
  captured: "CV pending",
  "cv-ready": "CV ready",
  applied: "Applied",
  skipped: "Skipped",
  profile: "Profile",
};

let jobState = null;   // {found, slug, step, apply_url} when this job is known
let stateJobId = "";   // the job id the state belongs to

async function ask(message) {
  try {
    return await chrome.runtime.sendMessage(message);
  } catch {
    return { ok: false };
  }
}

async function refreshJobState() {
  const id = currentJobId();
  if (!id) return;
  const res = await ask({ type: "jobState", id });
  // A slow answer must not land on a job the operator has already left.
  if (currentJobId() !== id) return;
  stateJobId = id;
  jobState = res && res.ok ? res.job || null : null;
}

function currentStep() {
  if (!jobState || stateJobId !== currentJobId()) return "none";
  return jobState.step || "captured";
}

function openApply() {
  const url = jobState && jobState.apply_url;
  if (url) {
    window.open(url, "_blank", "noopener");
    return;
  }
  toast("This job uses Easy Apply. Use LinkedIn's own Apply button.", true);
}

async function markApplied(button) {
  if (!jobState || !jobState.slug) return;
  button.disabled = true;
  const res = await ask({ type: "markApplied", payload: { slug: jobState.slug } });
  if (res && res.ok) {
    jobState.step = "applied";
    toast("Marked applied.", true);
    refreshButtons();
  } else {
    button.disabled = false;
    toast(`Not marked: ${(res && res.error) || "unknown error"}`, false);
  }
}

async function onButtonClick(button) {
  const step = currentStep();
  if (step === "cv-ready" || step === "profile") return openApply();
  if (step === "applied" || step === "skipped") return;
  // none: first capture. captured: the JD is queued, re-clicking syncs it.
  return onCapture(button);
}

// The button doubles as a step badge, and a small second control appears once a
// CV exists, so an application can be recorded after it has been sent.
function refreshButtons() {
  const button = document.getElementById(BUTTON_ID);
  if (!button) return;
  const step = currentStep();
  button.textContent = STEP_LABEL[step] || STEP_LABEL.none;
  button.dataset.step = step;
  button.disabled = step === "applied";
  button.title = step === "none" ? "Apply with CV"
    : `CV pipeline: ${STEP_LABEL[step] || step}`;

  const mark = document.getElementById(APPLIED_BUTTON_ID);
  const want = step === "cv-ready" || step === "profile";
  if (want && !mark) {
    const created = document.createElement("button");
    created.id = APPLIED_BUTTON_ID;
    created.type = "button";
    created.className = "cv-applied";
    created.textContent = "Mark applied";
    created.addEventListener("click", () => markApplied(created));
    if (button.parentElement) {
      button.parentElement.insertBefore(created, button.nextSibling);
    }
  } else if (!want && mark) {
    mark.remove();
  }
}

// ---- reconciling with LinkedIn's own record --------------------------------
//
// The ledger recorded that a CV was finished, never that an application went
// out. LinkedIn does know, on its Applied list, so that page gets a control
// that reads the job ids it displays and hands them to the local server.

const RECONCILE_ID = "cv-reconcile-button";

function appliedIds() {
  const ids = new Set();
  let anchors;
  try {
    anchors = document.querySelectorAll('a[href*="/jobs/view/"]');
  } catch {
    return [];
  }
  for (const anchor of anchors) {
    const href = String(anchor.href || anchor.getAttribute("href") || "");
    const match = href.match(/\/jobs\/view\/(\d+)/);
    if (match) ids.add(match[1]);
  }
  return [...ids];
}

function isAppliedList() {
  return /cardType=APPLIED|applied/i.test(location.href) && appliedIds().length > 0;
}

async function onReconcile(button) {
  const ids = appliedIds();
  if (!ids.length) {
    toast("No applied jobs found on this page.", false);
    return;
  }
  button.disabled = true;
  const res = await ask({ type: "reconcile", ids });
  button.disabled = false;
  if (res && res.ok) {
    toast(`Marked ${res.count} capture(s) applied.`, true);
  } else {
    toast(`Not reconciled: ${(res && res.error) || "unknown error"}`, false);
  }
}

function injectReconcile() {
  const existing = document.getElementById(RECONCILE_ID);
  if (!isAppliedList()) {
    if (existing) existing.remove();
    return;
  }
  if (existing || !document.body) return;
  const host = document.querySelector("main") || document.body;
  if (!host) return;
  const button = document.createElement("button");
  button.id = RECONCILE_ID;
  button.type = "button";
  button.className = "cv-reconcile";
  button.textContent = "Reconcile with the CV ledger";
  button.title = "Mark each job on this list that the ledger knows as applied";
  button.addEventListener("click", () => onReconcile(button));
  host.insertBefore(button, host.firstChild);
}

// The job header's own controls. The aria-labels survive hashed class names,
// but LinkedIn localises them, so matching is case-insensitive and covers more
// than one language rather than the one string seen in a single capture.
const ACTION_ANCHORS = [
  'button[aria-label*="save the job" i]',
  'button[aria-label*="unsave the job" i]',
  'button[aria-label*="salvar" i]',
  'button[aria-label*="more options" i]',
  'button[aria-label*="mais op" i]',
];

// Where the button goes when the header anchor is absent. These are in-flow
// containers, never a fixed overlay: a fixed element lands on top of
// LinkedIn's own controls, which is what it did.
const FALLBACK_CONTAINERS = [
  "[data-sdui-screen*='JobDetails']",
  "#workspace",
  "main",
];

function findActionAnchor() {
  for (const sel of ACTION_ANCHORS) {
    let el;
    try {
      el = document.querySelector(sel);
    } catch {
      continue;
    }
    if (el && el.parentElement) return el;
  }
  return null;
}

function findFallbackContainer() {
  for (const sel of FALLBACK_CONTAINERS) {
    let el;
    try {
      el = document.querySelector(sel);
    } catch {
      continue;
    }
    if (el) return el;
  }
  return null;
}

function inject() {
  const shouldShow = isJobPage();
  const existing = document.getElementById(BUTTON_ID);

  if (!shouldShow) {
    if (existing) existing.remove();
    const stale = document.getElementById(APPLIED_BUTTON_ID);
    if (stale) stale.remove();
    return;
  }
  if (!document.body) return;

  const anchor = findActionAnchor();
  const parent = anchor ? anchor.parentElement : findFallbackContainer();
  if (!parent) {
    if (existing) existing.remove();
    return;
  }

  const mode = anchor ? "inline" : "fallback";

  // Leave it alone when it is already where it belongs; LinkedIn re-renders
  // the header often, and re-inserting would fight it.
  if (
    existing &&
    existing.parentElement === parent &&
    existing.dataset.mode === mode
  ) {
    return;
  }
  if (existing) existing.remove();

  const button = document.createElement("button");
  button.id = BUTTON_ID;
  button.type = "button";
  button.dataset.mode = mode;
  button.className = mode === "inline" ? "cv-inline" : "cv-fallback";
  button.textContent = "Apply with CV";
  button.title = "Apply with CV";
  button.setAttribute("aria-label", "Apply with CV");
  button.addEventListener("click", () => onButtonClick(button));

  if (anchor) {
    // The anchor sits in its own wrapper inside the action bar, and that
    // wrapper is sized for a single control: a second child overlaps it. The
    // button therefore goes into the bar itself, beside the wrappers.
    const wrapper = anchor.parentElement;
    const bar = wrapper && wrapper.parentElement;
    if (bar) {
      bar.insertBefore(button, wrapper.nextSibling);
    } else {
      wrapper.insertBefore(button, anchor.nextSibling);
    }
  } else {
    parent.insertBefore(button, parent.firstChild);
  }
  log("button injected", mode);

  // The label starts at the capture action and is corrected once the server
  // answers, so the page is usable immediately and accurate a moment later.
  button.dataset.step = "none";
  refreshJobState().then(refreshButtons);
}

let scheduled = false;
function schedule() {
  if (scheduled) return;
  scheduled = true;
  setTimeout(() => {
    scheduled = false;
    inject();
    injectReconcile();
  }, 400);
}

new MutationObserver(schedule).observe(document.documentElement, {
  childList: true,
  subtree: true,
});
window.addEventListener("popstate", schedule);

// pushState fires nothing, so poll for a URL change.
let lastUrl = location.href;
setInterval(() => {
  if (location.href !== lastUrl) {
    lastUrl = location.href;
    log("url changed", lastUrl);
    schedule();
  }
}, 1000);

log("content script loaded on", location.href);
schedule();
