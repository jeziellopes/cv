const DEFAULTS = { port: 8787, token: "" };

const $ = (id) => document.getElementById(id);

function status(message, kind) {
  const el = $("status");
  el.textContent = message;
  el.className = kind || "";
}

async function load() {
  const cfg = await chrome.storage.local.get(DEFAULTS);
  $("port").value = cfg.port;
  $("token").value = cfg.token;
}

async function save() {
  const port = Number($("port").value) || DEFAULTS.port;
  const token = $("token").value.trim();
  await chrome.storage.local.set({ port, token });
  status("Saved.", "ok");
}

async function test() {
  status("Checking...");
  const res = await chrome.runtime.sendMessage({ type: "ping" });
  if (res && res.ok) {
    status("Local server is reachable.", "ok");
  } else {
    status("No server. Run `cv inbox serve` and try again.", "err");
  }
}

document.addEventListener("DOMContentLoaded", () => {
  load();
  $("save").addEventListener("click", save);
  $("test").addEventListener("click", test);
});
