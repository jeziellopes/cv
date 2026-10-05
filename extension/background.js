// Send a job to the local endpoint. Done in the service worker so the request
// is not subject to the LinkedIn page's own origin policy.

async function config() {
  const cfg = await chrome.storage.local.get({ port: 8787, token: "" });
  return cfg;
}

async function post(path, payload) {
  const { port, token } = await config();
  try {
    const res = await fetch(`http://127.0.0.1:${port}${path}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CV-Token": token,
      },
      body: JSON.stringify(payload),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok || !body.ok) {
      return { ok: false, error: body.error || `HTTP ${res.status}` };
    }
    return { ok: true, slug: body.slug, path: body.path };
  } catch (err) {
    return {
      ok: false,
      error:
        "No response from the local server. Is `cv inbox serve` running?",
    };
  }
}

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
  return false;
});
