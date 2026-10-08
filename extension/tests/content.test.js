// Behavioural tests for the content script, run in a stubbed DOM.
//
// The extension cannot be driven in a real browser from a test suite, so
// content.js runs in a vm context against a DOM shaped like the one LinkedIn
// actually serves: hashed class names, stable data-* anchors, and a
// document.title of "Job Title | Company | LinkedIn".
//
// Run: node extension/tests/content.test.js

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const SRC = fs.readFileSync(path.join(__dirname, "..", "content.js"), "utf8");

function makeEl(tag, attrs = {}, text = "") {
  const el = {
    tagName: tag.toUpperCase(),
    attrs,
    textContent: text,
    innerText: text,
    style: {},
    dataset: {},
    children: [],
    parentElement: null,
    _listeners: {},
    appendChild(child) {
      child.parentElement = this;
      this.children.push(child);
      return child;
    },
    insertBefore(child, ref) {
      child.parentElement = this;
      const at = this.children.indexOf(ref);
      if (at === -1) this.children.push(child);
      else this.children.splice(at, 0, child);
      return child;
    },
    remove() {
      this.removed = true;
      if (this.parentElement) {
        const at = this.parentElement.children.indexOf(this);
        if (at !== -1) this.parentElement.children.splice(at, 1);
      }
    },
    addEventListener(name, fn) {
      this._listeners[name] = fn;
    },
    setAttribute(key, value) {
      this.attrs[key] = value;
    },
    getAttribute(key) {
      return Object.prototype.hasOwnProperty.call(this.attrs, key)
        ? this.attrs[key]
        : null;
    },
  };
  Object.defineProperty(el, "href", {
    get() {
      return this.attrs.href || "";
    },
  });
  Object.defineProperty(el, "className", {
    get() {
      return this.attrs.class || "";
    },
  });
  // The content script inserts relative to the anchor, so siblings matter.
  Object.defineProperty(el, "nextSibling", {
    get() {
      if (!this.parentElement) return null;
      const at = this.parentElement.children.indexOf(this);
      if (at === -1) return null;
      return this.parentElement.children[at + 1] || null;
    },
  });
  // content.js assigns `button.id = ...`, so id must be a property, not only
  // an attribute, for getElementById-style lookups to see it.
  Object.defineProperty(el, "id", {
    get() {
      return this.attrs.id || "";
    },
    set(value) {
      this.attrs.id = value;
    },
  });
  Object.defineProperty(el, "type", {
    get() {
      return this.attrs.type || "";
    },
    set(value) {
      this.attrs.type = value;
    },
  });
  Object.defineProperty(el, "outerHTML", {
    get() {
      return `<${tag} ${JSON.stringify(this.attrs)}>${this.textContent}</${tag}>`;
    },
  });
  return el;
}

// Only the selector forms the content script uses are implemented.
function matches(el, sel) {
  let m;
  // Attribute selectors may carry a case-insensitive flag, e.g. [x*="y" i].
  if ((m = sel.match(/^\[([\w-]+)\*=['"]([^'"]*)['"]\s*(i?)\]$/))) {
    const v = el.attrs[m[1]];
    if (typeof v !== "string") return false;
    return m[3]
      ? v.toLowerCase().includes(m[2].toLowerCase())
      : v.includes(m[2]);
  }
  if ((m = sel.match(/^([a-z0-9]+)\[([\w-]+)\*=['"]([^'"]*)['"]\s*(i?)\]$/))) {
    const v = el.attrs[m[2]];
    if (el.tagName !== m[1].toUpperCase() || typeof v !== "string") return false;
    return m[4]
      ? v.toLowerCase().includes(m[3].toLowerCase())
      : v.includes(m[3]);
  }
  if ((m = sel.match(/^\[([\w-]+)\^="([^"]*)"\]$/))) {
    const v = el.attrs[m[1]];
    return typeof v === "string" && v.startsWith(m[2]);
  }
  if ((m = sel.match(/^([a-z0-9]+)\[([\w-]+)="([^"]*)"\]$/))) {
    return el.tagName === m[1].toUpperCase() && el.attrs[m[2]] === m[3];
  }
  if ((m = sel.match(/^\[([\w-]+)="([^"]*)"\]$/))) {
    return el.attrs[m[1]] === m[2];
  }
  if ((m = sel.match(/^meta\[(?:property|name)="([^"]+)"\]$/))) {
    return el.tagName === "META" && el.attrs._meta === m[1];
  }
  if (sel.startsWith("#")) return el.attrs.id === sel.slice(1);
  if (sel.startsWith(".")) {
    return String(el.attrs.class || "").split(/\s+/).includes(sel.slice(1));
  }
  return el.tagName === sel.toUpperCase();
}

function run({ url, title = "", nodes = [], metas = {}, scripts = [], responses = {} }) {
  const body = makeEl("body");
  const pool = [...nodes];
  const created = [];
  for (const [key, value] of Object.entries(metas)) {
    pool.push(makeEl("meta", { _meta: key, content: value }));
  }

  const document = {
    body,
    documentElement: makeEl("html"),
    title,
    createElement: (tag) => {
      const el = makeEl(tag);
      created.push(el);
      return el;
    },
    querySelector(sel) {
      return pool.find((el) => matches(el, sel)) || null;
    },
    querySelectorAll(sel) {
      if (sel.includes("ld+json")) return scripts.map((s) => makeEl("script", {}, s));
      return pool.filter((el) => matches(el, sel));
    },
    getElementById: (id) =>
      body.children.find((c) => c.attrs.id === id) ||
      created.find((c) => c.attrs.id === id) ||
      null,
  };

  const location = {
    href: url,
    pathname: url.replace(/^https?:\/\/[^/]+/, "").split("?")[0],
    search: url.includes("?") ? "?" + url.split("?")[1] : "",
  };

  const sent = [];
  const logs = [];
  const sandbox = {
    document,
    location,
    // A vm context has no web globals; the content script relies on URL.
    URL,
    URLSearchParams,
    console: {
      log: (...a) => logs.push(a.map(String).join(" ")),
      error: () => {},
    },
    setTimeout: (fn) => fn(),
    clearTimeout: () => {},
    setInterval: () => 0,
    MutationObserver: class {
      observe() {}
    },
    chrome: {
      runtime: {
        sendMessage: async (msg) => {
          sent.push(msg);
          const custom = responses[msg.type];
          if (custom) return custom;
          return { ok: true, path: "companies/rotik/description.md" };
        },
      },
    },
    window: { addEventListener() {} },
  };

  vm.createContext(sandbox);
  vm.runInContext(SRC, sandbox);
  // The button may be nested in the action bar rather than appended to body.
  const button = created.find((c) => c.attrs.id === "cv-capture-button") || null;
  return { button, created, logs, sent };
}

const JOB_URL =
  "https://www.linkedin.com/jobs/search-results/?currentJobId=4385917440";
const FEED_URL = "https://www.linkedin.com/feed/";

// The job header's own controls, exactly as the captured page had them: an
// outer action bar holding one wrapper per control, which is why the button
// must be a sibling of the wrappers rather than of the button itself.
const actionBar = makeEl("div", { class: "ckya1x ckyipj ckyjp7" });
const applyWrapper = actionBar.appendChild(
  makeEl("div", { class: "ckya49 ckyguo ckyhqg ckymt4" })
);
// The Apply control for a non-Easy-Apply job: an anchor whose target LinkedIn
// wraps in its own redirect.
const EXTERNAL_APPLY = "https://rotik.inhire.app/vagas/28ca3bb0/pessoa-desenvolvedora-full-stack?source=linkedin";
const safetyHref =
  "https://www.linkedin.com/safety/go?url=" +
  encodeURIComponent(EXTERNAL_APPLY) +
  "&urlhash=7QcK&mt=abc&isSdui=true";
const applyAnchor = applyWrapper.appendChild(
  makeEl("a", { "aria-label": "Apply on company website", href: safetyHref }, "Apply")
);
const saveWrapper = actionBar.appendChild(
  makeEl("div", { class: "ckya49 ckyguo ckyhqg ckymt4" })
);
const saveControl = saveWrapper.appendChild(
  makeEl("button", { type: "button", "aria-label": "Unsave the job" }, "Saved")
);

// The shape captured from the real page: hashed classes, no semantic names.
const REAL_PAGE = {
  url: JOB_URL,
  title: "Pessoa Desenvolvedora Full Stack | Rotik | LinkedIn",
  nodes: [
    makeEl("a",
      { href: "https://www.linkedin.com/jobs/view/4385917440/?trackingId=x" },
      "Pessoa Desenvolvedora Full Stack"),
    makeEl("a", { href: "https://www.linkedin.com/company/rotik/life/" }, "Rotik"),
    makeEl("img", { "aria-label": "Company logo for, Rotik." }),
    makeEl("div", { "data-sdui-screen": "com.linkedin.sdui.flagshipnav.jobs.SemanticJobDetails" },
      "Pessoa Desenvolvedora Full Stack Rotik Remote Easy Apply Sobre a vaga " +
      "Buscamos pessoa desenvolvedora com React, NestJS e Node.js. " +
      "Requisitos: TypeScript e testes automatizados. Candidate-se"),
    actionBar,
    applyWrapper,
    applyAnchor,
    saveWrapper,
    saveControl,
  ],
};

const results = [];
function check(label, condition, detail) {
  results.push({ label, ok: Boolean(condition), detail });
}

async function clickCapture(button) {
  if (!button) return;
  await button._listeners.click();
  await new Promise((resolve) => setImmediate(resolve));
}

(async () => {
  // The real page that failed: hashed classes, title in document.title.
  let r = run(REAL_PAGE);
  check("injects on the real job page", r.button, "no button");
  check("places the button in the job action row, not floating",
    r.button && r.button.dataset.mode === "inline",
    r.button && r.button.dataset.mode);
  check("labels the button as the primary action",
    r.button && r.button.textContent === "Apply with CV" &&
      r.button.attrs["aria-label"] === "Apply with CV",
    r.button && `${JSON.stringify(r.button.textContent)}`);
  check("goes in the outer action bar, not inside a control's wrapper",
    r.button && r.button.parentElement === actionBar,
    r.button && r.button.parentElement && r.button.parentElement.attrs.class);
  check("sits immediately after the Save control's wrapper",
    r.button && actionBar.children.indexOf(r.button) ===
      actionBar.children.indexOf(saveWrapper) + 1,
    "not adjacent to the Save wrapper");
  check("is not sharing a wrapper with another button",
    r.button && r.button.parentElement.children.filter(
      (c) => c.tagName === "BUTTON"
    ).length === 1,
    "two buttons in one wrapper");

  await clickCapture(r.button);
  const cap = r.sent.find((m) => m.type === "capture");
  const payload = cap ? cap.payload : {};
  check("reads the title from the job link", payload.title === "Pessoa Desenvolvedora Full Stack",
    JSON.stringify(payload.title));
  check("reads the company from the logo aria-label", payload.company === "Rotik",
    JSON.stringify(payload.company));
  check("reads the description from the job pane",
    typeof payload.description === "string" &&
      payload.description.startsWith("Buscamos pessoa desenvolvedora") &&
      !payload.description.includes("Candidate-se"),
    JSON.stringify((payload.description || "").slice(0, 70)));
  check("builds the canonical job url",
    payload.url === "https://www.linkedin.com/jobs/view/4385917440/",
    payload.url);
  check("captures the company apply link behind LinkedIn's redirect",
    payload.apply_url === EXTERNAL_APPLY,
    JSON.stringify(payload.apply_url));

  // Easy Apply has no external link, so there must be no apply_url.
  r = run({
    url: JOB_URL,
    title: "Pessoa Desenvolvedora Full Stack | Rotik | LinkedIn",
    nodes: [
      makeEl("button", { "aria-label": "Easy Apply" }, "Easy Apply"),
      makeEl("div", { "data-sdui-screen": "x.jobs.SemanticJobDetails" },
        "Sobre a vaga " + "Requisitos: Laravel, React. ".repeat(4)),
      makeEl("a", { href: "https://www.linkedin.com/jobs/view/4385917440/" },
        "Pessoa Desenvolvedora Full Stack"),
      makeEl("img", { "aria-label": "Company logo for, Rotik." }),
    ],
  });
  await clickCapture(r.button);
  const easy = (r.sent.find((m) => m.type === "capture") || {}).payload || {};
  check("leaves apply_url empty for Easy Apply",
    easy.apply_url === "", JSON.stringify(easy.apply_url));

  // The location line must never stand in for the role (spec 0010). A page
  // whose title element reads "Remote" must fall through to a real source.
  r = run({
    url: JOB_URL,
    title: "Engenheiro de Software | Acme | LinkedIn",
    nodes: [
      makeEl("img", { "aria-label": "Company logo for, Acme." }),
      makeEl("div", { class: "jobs-unified-top-card__job-title" }, "Remote"),
      makeEl("div", { class: "jobs-unified-top-card__bullet" }, "Remote"),
      makeEl("button", { "aria-label": "Easy Apply" }, "Easy Apply"),
      makeEl("div", { "data-sdui-screen": "x.jobs.SemanticJobDetails" },
        "Sobre a vaga " + "Requisitos: React, TypeScript e testes. ".repeat(4)),
    ],
  });
  await clickCapture(r.button);
  const loc = (r.sent.find((m) => m.type === "capture") || {}).payload || {};
  check("never lets the location line stand in for the title",
    loc.title === "Engenheiro de Software" && loc.location === "Remote",
    JSON.stringify([loc.title, loc.location]));

  // LinkedIn appends page chrome after the JD; it must not leak into the JD.
  r = run({
    url: JOB_URL,
    title: "Pessoa Desenvolvedora Full Stack | Rotik | LinkedIn",
    nodes: [
      makeEl("img", { "aria-label": "Company logo for, Rotik." }),
      makeEl("a", { href: "https://www.linkedin.com/jobs/view/4385917440/" },
        "Pessoa Desenvolvedora Full Stack"),
      makeEl("div", { "data-sdui-screen": "x.jobs.SemanticJobDetails" },
        "Sobre a vaga " + "Requisitos: Laravel, React, TypeScript. ".repeat(5) +
        " See how you compare to others who clicked apply Candidates who clicked apply 5360 total"),
    ],
  });
  await clickCapture(r.button);
  const p3 = (r.sent.find((m) => m.type === "capture") || {}).payload || {};
  check("stops the description before LinkedIn's page chrome",
    Boolean(p3.description) && !p3.description.includes("See how you compare") &&
      !p3.description.includes("Candidates who clicked"),
    JSON.stringify((p3.description || "").slice(-70)));

  // No action bar: the button must still be reachable, floating.
  r = run({
    url: JOB_URL,
    title: "Pessoa Desenvolvedora Full Stack | Rotik | LinkedIn",
    nodes: [makeEl("div", { "data-sdui-screen": "x.jobs.SemanticJobDetails" },
      "x".repeat(80))],
  });
  check("falls back to an in-flow button with no action bar",
    r.button && r.button.dataset.mode === "fallback",
    r.button && r.button.dataset.mode);
  check("the button is never a fixed overlay",
    !/position:\s*fixed/.test(
      fs.readFileSync(path.join(__dirname, "..", "content.css"), "utf8")
        .split("#cv-capture-toast")[0]
    ),
    "a fixed position rule is present in the button styles");
  await clickCapture(r.button);
  const p2 = (r.sent.find((m) => m.type === "capture") || {}).payload || {};
  check("falls back to document.title for title and company",
    p2.title === "Pessoa Desenvolvedora Full Stack" && p2.company === "Rotik",
    JSON.stringify([p2.title, p2.company]));

  // Injection: no readable job at all.
  r = run({ url: FEED_URL });
  check("does not inject on the feed", !r.button, "button present");

  // No placement target at all: show nothing rather than a fixed overlay.
  r = run({ url: JOB_URL });
  check("shows no button when there is no place to put it in flow",
    !r.button, "a button was injected anyway");

  // Failure path, with a real container so the button can be clicked.
  r = run({ url: JOB_URL, nodes: [makeEl("div", { id: "workspace" })] });
  check("uses the job container as an in-flow fallback",
    r.button && r.button.dataset.mode === "fallback",
    r.button && r.button.dataset.mode);
  await clickCapture(r.button);
  check("sends no capture when nothing is readable",
    r.sent.filter((m) => m.type === "capture").length === 0, "a capture was sent");
  const diag = r.sent.find((m) => m.type === "diagnose");
  check("sends a diagnosis instead", Boolean(diag), "no diagnose sent");
  check("the diagnosis is small enough to keep",
    diag && typeof diag.payload.domSample === "string", "no domSample");

  // ---- step awareness ------------------------------------------------------

  // The server answers a jobState lookup a moment after the button is drawn, so
  // these flush the microtask queue before asserting.
  const flush = async () => {
    await new Promise((resolve) => setImmediate(resolve));
  };
  const jobNodes = [
    makeEl("img", { "aria-label": "Company logo for, Rotik." }),
    makeEl("a", { href: "https://www.linkedin.com/jobs/view/4385917440/" },
      "Pessoa Desenvolvedora Full Stack"),
    makeEl("div", { "data-sdui-screen": "x.jobs.SemanticJobDetails" },
      "Sobre a vaga " + "Requisitos: React e NestJS. ".repeat(4)),
  ];
  const jobPage = (job) => run({
    url: JOB_URL,
    title: "Pessoa Desenvolvedora Full Stack | Rotik | LinkedIn",
    nodes: jobNodes,
    responses: { jobState: { ok: true, job } },
  });

  r = jobPage({ slug: "rotik", step: "cv-ready", apply_url: "https://rotik.example/apply" });
  await flush();
  await flush();
  check("shows the step the capture has reached",
    r.button && r.button.textContent === "CV ready",
    r.button && r.button.textContent);
  check("offers to record the application once a CV exists",
    Boolean(r.created.find((c) => c.attrs.id === "cv-applied-button")),
    "no mark-applied control");

  r = jobPage({ slug: "rotik", step: "applied" });
  await flush();
  await flush();
  check("shows an applied posting as applied",
    r.button && r.button.textContent === "Applied",
    r.button && r.button.textContent);
  check("disables the button once applied",
    r.button && r.button.disabled === true, "button still enabled");

  r = jobPage(null);
  await flush();
  await flush();
  check("keeps the capture action for a job the ledger does not know",
    r.button && r.button.textContent === "Apply with CV",
    r.button && r.button.textContent);

  r = jobPage({ slug: "rotik", step: "skipped" });
  await flush();
  await flush();
  check("shows a posting passed over on purpose",
    r.button && r.button.textContent === "Skipped",
    r.button && r.button.textContent);
  check("offers no mark-applied control on a skipped posting",
    !r.created.find((c) => c.attrs.id === "cv-applied-button"),
    "a mark-applied control appeared");

  // ---- reconciling with LinkedIn's Applied list ---------------------------

  const appliedPage = () => run({
    url: "https://www.linkedin.com/my-items/saved-jobs/?cardType=APPLIED",
    nodes: [
      makeEl("a", { href: "https://www.linkedin.com/jobs/view/111/" }, "Applied one"),
      makeEl("a", { href: "https://www.linkedin.com/jobs/view/222/" }, "Applied two"),
    ],
    responses: { reconcile: { ok: true, count: 1, applied: ["rotik"] } },
  });

  r = appliedPage();
  const reconcile = r.created.find((c) => c.attrs.id === "cv-reconcile-button");
  check("offers a reconcile control on the applied list",
    Boolean(reconcile), "no reconcile control");
  if (reconcile) {
    await reconcile._listeners.click();
    await flush();
  }
  const rec = r.sent.find((m) => m.type === "reconcile");
  check("sends the job ids it found on the applied list",
    Boolean(rec) && rec.ids.includes("111") && rec.ids.includes("222"),
    JSON.stringify(rec && rec.ids));

  r = run({
    url: FEED_URL,
    nodes: [makeEl("a", { href: "https://www.linkedin.com/jobs/view/111/" }, "x")],
  });
  check("does not reconcile off the applied list",
    !r.created.find((c) => c.attrs.id === "cv-reconcile-button"),
    "reconcile control injected on the feed");

  for (const { label, ok, detail } of results) {
    console.log(`${ok ? "ok  " : "FAIL"}  ${label}${ok ? "" : `  <- ${detail}`}`);
  }
  const failed = results.filter((x) => !x.ok).length;
  console.log(failed === 0 ? "\nALL CONTENT-SCRIPT TESTS PASS" : `\n${failed} FAILED`);
  process.exit(failed === 0 ? 0 : 1);
})();
