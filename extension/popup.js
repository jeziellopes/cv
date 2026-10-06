// The panel: recent captures and the step each has reached. Steps are derived
// by the local server from the files on disk, so this view cannot drift from
// the ledger the way a second copy of the state would.

const DEFAULTS = { port: 8787, token: "" };

const $ = (id) => document.getElementById(id);

const STEP_LABEL = {
  captured: "captured",
  "cv-ready": "CV ready",
  applied: "applied",
  skipped: "skipped",
};

function setStatus(message, kind) {
  const el = $("status");
  el.textContent = message || "";
  el.className = kind || "";
}

async function send(message) {
  try {
    return await chrome.runtime.sendMessage(message);
  } catch {
    return { ok: false, error: "The extension was reloaded. Reopen the panel." };
  }
}

async function loadConfig() {
  const cfg = await chrome.storage.local.get(DEFAULTS);
  $("port").value = cfg.port;
  $("token").value = cfg.token;
}

async function saveConfig() {
  const port = Number($("port").value) || DEFAULTS.port;
  const token = $("token").value.trim();
  await chrome.storage.local.set({ port, token });
  setStatus("Saved.", "ok");
  renderJobs();
}

async function test() {
  setStatus("Checking...");
  const res = await send({ type: "ping" });
  setStatus(res && res.ok ? "Local server is reachable."
    : "No server. Run `cv inbox serve` and try again.",
  res && res.ok ? "ok" : "err");
}

function link(href, text, className) {
  const a = document.createElement("a");
  a.href = href;
  a.target = "_blank";
  a.rel = "noopener";
  a.textContent = text;
  if (className) a.className = className;
  return a;
}

async function markApplied(slug) {
  const res = await send({ type: "markApplied", payload: { slug } });
  if (!res || !res.ok) {
    setStatus((res && res.error) || "Could not mark applied.", "err");
    return;
  }
  setStatus(`${slug} marked applied.`, "ok");
  renderJobs();
}

// A decline carries a justification the operator writes, and it is reversible:
// a judgement made in a hurry is one you can take back.
async function decline(slug, reason) {
  const res = await send({ type: "skip", payload: { slug, reason: (reason || "").trim() } });
  if (!res || !res.ok) {
    setStatus((res && res.error) || "Could not decline.", "err");
    return;
  }
  setStatus(`${slug} declined.`, "ok");
  renderJobs();
}

async function reconsider(slug) {
  const res = await send({ type: "reconsider", payload: { slug } });
  if (!res || !res.ok) {
    setStatus((res && res.error) || "Could not reconsider.", "err");
    return;
  }
  setStatus(`${slug} reconsidered.`, "ok");
  renderJobs();
}

function jobRow(job) {
  const row = document.createElement("div");
  row.className = "job";

  const head = document.createElement("div");
  head.className = "head";
  const badge = document.createElement("span");
  badge.className = `badge ${job.step}`;
  badge.textContent = STEP_LABEL[job.step] || job.step;
  const name = document.createElement("span");
  name.className = "name";
  name.textContent = `${job.company} - ${job.title}`;
  head.append(badge, name);

  const slug = document.createElement("code");
  slug.textContent = job.slug;

  const actions = document.createElement("div");
  actions.className = "actions";
  if (job.url) actions.append(link(job.url, "Job"));
  if (job.apply_url) actions.append(link(job.apply_url, "Apply"));
  if (job.step !== "applied" && job.step !== "skipped") {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "mark";
    button.textContent = "Mark applied";
    button.addEventListener("click", () => markApplied(job.slug));
    actions.append(button);
  }

  row.append(head, slug, actions);

  if (job.step === "skipped") {
    const reason = document.createElement("p");
    reason.className = "reason";
    reason.textContent = job.reason
      ? `Declined: ${job.reason}`
      : "Declined, no reason given";
    const back = document.createElement("button");
    back.type = "button";
    back.className = "reconsider";
    back.textContent = "Reconsider";
    back.addEventListener("click", () => reconsider(job.slug));
    row.append(reason, back);
  } else {
    const form = document.createElement("div");
    form.className = "decline";
    const input = document.createElement("input");
    input.type = "text";
    input.className = "reason-input";
    input.placeholder = "Why not? (your words)";
    input.spellcheck = true;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "decline-button";
    button.textContent = "Decline";
    button.addEventListener("click", () => decline(job.slug, input.value));
    form.append(input, button);
    row.append(form);
  }

  return row;
}

async function renderJobs() {
  const list = $("list");
  list.textContent = "";
  const res = await send({ type: "jobs", limit: 25 });
  if (!res || !res.ok) {
    const empty = document.createElement("p");
    empty.className = "muted";
    empty.textContent = (res && res.error)
      || "Run `cv inbox serve` to see recent jobs.";
    list.append(empty);
    return;
  }
  const jobs = res.jobs || [];
  if (!jobs.length) {
    const empty = document.createElement("p");
    empty.className = "muted";
    empty.textContent = "Nothing captured yet.";
    list.append(empty);
    return;
  }
  for (const job of jobs) list.append(jobRow(job));
}

document.addEventListener("DOMContentLoaded", () => {
  loadConfig();
  renderJobs();
  $("save").addEventListener("click", saveConfig);
  $("test").addEventListener("click", test);
});