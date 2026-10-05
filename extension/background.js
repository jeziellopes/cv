// Every call to the local endpoint happens here, in the service worker, so the
// request is not subject to the LinkedIn page's own origin policy and the token
// stays out of page context.

async function config() {
  const cfg = await chrome.storage.local.get({ port: 8787, token: "" });
  return cfg;
}

async function request(method, path, payload) {
  const { port, token } = await config();
  const init = {
    method,
    headers: { "X-CV-Token": token },
  };
  if (payload !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(payload);
  }
  let res;
  try {
    res = await fetch(`http://127.0.0.1:${port}${path}`, init);
  } catch {
    return { ok: false, error: "No response from the local server. Is `cv inbox serve` running?" };
  }
  const body = await res.json().catch(() => ({}));
  if (!res.ok || !body.ok) {
    return { ok: false, error: body.error || `HTTP ${res.status}` };
  }
  return { ok: true, ...body };
}

const post = (path, payload) => request("POST", path, payload);

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (!msg || msg.type === "ping") {
    (async () => {
      const { port } = await config();
      try {
        const res = await fetch(`http://127.0.0.1:${port}/health`);
        sendResponse({ ok: res.ok });
      } catch {
        sendResponse({ ok: false });
      }
    })();
    return true;
  }
  if (msg.type === "capture") {
    post("/capture", msg.payload).then(sendResponse);
    return true;
  }
  if (msg.type === "diagnose") {
    post("/diagnose", msg.payload).then(sendResponse);
    return true;
  }
  if (msg.type === "jobs") {
    request("GET", `/jobs?limit=${Number(msg.limit) || 20}`).then(sendResponse);
    return true;
  }
  if (msg.type === "jobState") {
    request("GET", `/jobs?id=${encodeURIComponent(msg.id)}`)
      .then(sendResponse);
    return true;
  }
  if (msg.type === "markApplied") {
    post("/applied", msg.payload).then(sendResponse);
    return true;
  }
  if (msg.type === "reconcile") {
    post("/reconcile", { ids: msg.ids }).then(sendResponse);
    return true;
  }
  return false;
});
