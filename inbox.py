"""Local capture endpoint: a hand-picked JD becomes a queued CV request.

The operator browses LinkedIn themselves, logged in, and clicks a button on a
job they want. This receives that job, writes it where the tailoring pipeline
already looks, and records it in a ledger so the queue is visible.

Deliberately stdlib only. The repository has no web framework and this needs no
dependency: a single POST on loopback with a token.

Threat model, since this writes files from a browser:
  - a page other than ours could POST to localhost, so a token is required
  - a payload could try to escape companies/ via the slug, so the slug is
    reduced to [a-z0-9-] before it becomes a path
  - the listener is bound to 127.0.0.1, never 0.0.0.0
"""

from __future__ import annotations

import json
import re
import secrets
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

import typer

BASE_DIR = Path(__file__).resolve().parent
LEDGER = BASE_DIR / "inbox.json"
TOKEN_FILE = BASE_DIR / ".cv-inbox-token"
DIAGNOSE_FILE = BASE_DIR / "inbox-diagnose.json"
DEFAULT_PORT = 8787

# What a capture must carry for a tailored CV to be possible at all.
REQUIRED = ("company", "title")
MAX_BODY = 2_000_000
# A DOM sample is legitimate here and large: it is how a broken selector gets
# fixed without another round trip through the browser.
MAX_DIAGNOSE = 6_000_000


def slugify(name: str) -> str:
    """Reduce a company name to a safe directory name.

    Accents fold first, so "Árvore & Cia." becomes "arvore-cia" rather than
    losing the letter. Everything outside [a-z0-9] then collapses to a hyphen,
    so "/", "." and ".." cannot survive into a path.
    """
    folded = "".join(
        c for c in unicodedata.normalize("NFKD", name or "")
        if not unicodedata.combining(c)
    )
    slug = re.sub(r"[^a-z0-9]+", "-", folded.lower()).strip("-")
    return slug or "job"


@dataclass
class Capture:
    slug: str
    company: str
    title: str
    location: str
    url: str
    description: str
    captured_at: str
    status: str = "new"
    # The company's own application link, when the job is not Easy Apply.
    apply_url: str = ""

    @property
    def path(self) -> str:
        return f"companies/{self.slug}/description.md"


def load_ledger(path: Optional[Path] = None) -> list[dict]:
    path = path or LEDGER
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return []
    return data if isinstance(data, list) else []


def save_ledger(entries: list[dict], path: Optional[Path] = None) -> None:
    path = path or LEDGER
    path.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def _role_slug(title: str) -> str:
    """A short folder name for a role, from its job title."""
    return slugify(title)[:40].strip("-") or "role"


def save_capture(payload: dict, base_dir: Optional[Path] = None) -> Capture:
    """Write the JD to companies/<slug>/description.md and queue it.

    The file layout matches search.ingest() so the existing pipeline reads it
    unchanged.
    """
    base_dir = base_dir or BASE_DIR
    missing = [f for f in REQUIRED if not str(payload.get(f, "")).strip()]
    if missing:
        raise ValueError(f"missing required field(s): {', '.join(missing)}")

    company = str(payload["company"]).strip()

    title = str(payload.get("title", "")).strip()
    location = str(payload.get("location", "")).strip()
    url = str(payload.get("url", "")).strip()
    description = str(payload.get("description", "")).strip()

    # Only a real link is kept, so a stray string cannot land in the JD file.
    apply_url = str(payload.get("apply_url", "")).strip()
    if not re.match(r"^https?://", apply_url, re.I):
        apply_url = ""

    # A job already in the ledger keeps its folder and its row, so re-clicking
    # a posting syncs it instead of minting a second entry.
    #
    # Identity is the posting URL, falling back to company and title when a
    # capture carries no link.
    entries = load_ledger()

    def is_same_job(entry: dict) -> bool:
        if url:
            return entry.get("url") == url
        return (entry.get("company"), entry.get("title")) == (company, title)

    same_job = next((e for e in entries if is_same_job(e)), None)

    company_slug = slugify(company)
    if same_job:
        slug = same_job["slug"]
    else:
        # The first role sits at the company folder. A second, different role
        # nests under it, matching companies/<company>/<role>/ used for CVs.
        first_segments = {e.get("slug", "").split("/")[0] for e in entries}
        taken = {e.get("slug", "") for e in entries}
        if company_slug not in first_segments:
            slug = company_slug
        else:
            role = _role_slug(title)
            slug = f"{company_slug}/{role}"
            n = 2
            while slug in taken or (base_dir / "companies" / slug).exists():
                slug = f"{company_slug}/{role}-{n}"
                n += 1

    header = [title, company, location, url]
    if apply_url:
        header.append(f"apply: {apply_url}")

    out = base_dir / "companies" / slug / "description.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(header) + f"\n\n{description}\n", encoding="utf-8")

    capture = Capture(
        slug=slug,
        company=company,
        title=title,
        location=location,
        url=url,
        description=description,
        captured_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        apply_url=apply_url,
    )

    # The JD lives in companies/<slug>/description.md. Keeping a second copy in
    # the ledger duplicated it and went stale the moment the file was edited.
    entry = asdict(capture)
    entry.pop("description", None)

    if same_job:
        # Syncing refreshes the JD and the link; it does not undo the fact that
        # a CV was already produced for this position.
        keep_status = same_job.get("status", "new")
        same_job.update(entry)
        same_job["status"] = keep_status
    else:
        entries.append(entry)
    save_ledger(entries)
    return capture


def save_diagnose(payload: dict, base_dir: Optional[Path] = None) -> Path:
    """Record what the page actually contained when extraction failed.

    Written to a gitignored file so a broken selector can be diagnosed from the
    repository instead of from the browser's console.
    """
    base_dir = base_dir or BASE_DIR
    out = base_dir / "inbox-diagnose.json"
    payload = dict(payload)
    payload["received_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    return out


def get_token(path: Optional[Path] = None) -> str:
    """The shared secret, created on first use and kept out of git."""
    path = path or TOKEN_FILE
    if path.exists():
        token = path.read_text(encoding="utf-8").strip()
        if token:
            return token
    token = secrets.token_urlsafe(24)
    path.write_text(token + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return token


def make_handler(token: str, base_dir: Path):
    """Build a request handler bound to one token and one output directory."""

    class Handler(BaseHTTPRequestHandler):
        server_version = "cv-inbox/1"

        def _send(self, code: int, body: dict) -> None:
            data = json.dumps(body).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            # The extension's own origin; no wildcard.
            origin = self.headers.get("Origin", "")
            if origin.startswith("chrome-extension://"):
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-CV-Token")
            self.end_headers()
            self.wfile.write(data)

        def do_OPTIONS(self) -> None:  # noqa: N802
            self._send(204, {})

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/health":
                self._send(200, {"ok": True})
            else:
                self._send(404, {"ok": False, "error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            if self.path not in ("/capture", "/diagnose"):
                self._send(404, {"ok": False, "error": "not found"})
                return
            if not secrets.compare_digest(self.headers.get("X-CV-Token", ""), token):
                self._send(401, {"ok": False, "error": "bad token"})
                return
            limit = MAX_DIAGNOSE if self.path == "/diagnose" else MAX_BODY
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                self._send(400, {"ok": False, "error": "bad length"})
                return
            if length <= 0 or length > limit:
                self._send(413, {"ok": False, "error": "bad body size"})
                return
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                self._send(400, {"ok": False, "error": "bad json"})
                return
            if not isinstance(payload, dict):
                self._send(400, {"ok": False, "error": "expected an object"})
                return

            if self.path == "/diagnose":
                out = save_diagnose(payload, base_dir)
                self._send(200, {"ok": True, "path": out.name})
                return

            try:
                capture = save_capture(payload, base_dir)
            except ValueError as exc:
                self._send(422, {"ok": False, "error": str(exc)})
                return
            self._send(200, {"ok": True, "slug": capture.slug, "path": capture.path})

        def log_message(self, fmt: str, *args) -> None:
            typer.echo(f"  inbox: {fmt % args}")

    return Handler


app = typer.Typer(help="Capture hand-picked job descriptions into the CV queue.")


@app.command("serve")
def serve(
    port: int = typer.Option(DEFAULT_PORT, "--port", "-p"),
    host: str = typer.Option("127.0.0.1", "--host"),
) -> None:
    """Listen for captures from the browser extension."""
    token = get_token()
    handler = make_handler(token, BASE_DIR)
    server = ThreadingHTTPServer((host, port), handler)
    typer.echo(f"Inbox listening on http://{host}:{port}")
    typer.echo(f"Token: {token}")
    typer.echo("Paste that token into the extension options once. Ctrl-C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        typer.echo("\nStopped.")
    finally:
        server.server_close()


@app.command("token")
def token_command() -> None:
    """Print the token the extension needs."""
    typer.echo(get_token())


def has_cv(slug: str, base_dir: Optional[Path] = None) -> bool:
    """Whether a tailored CV exists for a capture yet.

    The ledger records what was captured; this is what tells the queue which
    captures still need a CV, which is the question the operator actually asks.
    """
    base_dir = base_dir or BASE_DIR
    folder = base_dir / "companies" / slug
    return bool(list(folder.glob("cv-*.json"))) if folder.is_dir() else False


@app.command("list")
def list_command(
    all_: bool = typer.Option(False, "--all", help="include processed captures"),
    pending: bool = typer.Option(False, "--pending",
                                 help="only captures with no tailored CV yet"),
) -> None:
    """Show the capture queue and which entries still need a CV."""
    entries = load_ledger()
    if not all_ and not pending:
        entries = [e for e in entries if e.get("status") == "new"]
    if pending:
        entries = [e for e in entries if not has_cv(e.get("slug", ""))]

    if not entries:
        typer.echo("Queue is empty.")
        return

    needs = 0
    for e in entries:
        slug = e.get("slug", "")
        ready = has_cv(slug)
        if not ready:
            needs += 1
        typer.echo(
            f"  [{e.get('status', '?'):4}] {'CV ready' if ready else 'pending '} "
            f"{slug:22} {e.get('company', '')} - {e.get('title', '')}"
        )
        # The apply link is the reason the capture exists; show it here rather
        # than leaving it buried in the JD file.
        if e.get("apply_url"):
            typer.echo(f"         apply: {e['apply_url']}")
    typer.echo(f"\n{len(entries)} captur(es), {needs} still need a CV.")


@app.command("next")
def next_command() -> None:
    """Print the path of the oldest unprocessed capture."""
    for e in load_ledger():
        if e.get("status") == "new":
            typer.echo(f"companies/{e['slug']}/description.md")
            return
    typer.echo("Queue is empty.", err=True)
    raise typer.Exit(code=1)


@app.command("done")
def done_command(slug: str) -> None:
    """Mark a capture as processed."""
    entries = load_ledger()
    for e in entries:
        if e.get("slug") == slug:
            e["status"] = "done"
            save_ledger(entries)
            typer.echo(f"{slug} marked done.")
            return
    typer.echo(f"No capture with slug {slug}.", err=True)
    raise typer.Exit(code=1)


def find_entry(slug: str) -> Optional[dict]:
    for entry in load_ledger():
        if entry.get("slug") == slug:
            return entry
    return None


@app.command("show")
def show_command(slug: str) -> None:
    """Show one capture: its header, its apply link, and its CV state."""
    entry = find_entry(slug)
    if not entry:
        typer.echo(f"No capture with slug {slug}.", err=True)
        raise typer.Exit(code=1)
    ready = has_cv(slug)
    typer.echo(f"  company   {entry.get('company', '')}")
    typer.echo(f"  title     {entry.get('title', '')}")
    typer.echo(f"  location  {entry.get('location') or '-'}")
    typer.echo(f"  linkedin  {entry.get('url', '')}")
    typer.echo(f"  apply     {entry.get('apply_url') or '(none: Easy Apply)'}")
    typer.echo(f"  status    {entry.get('status', '?')}, CV "
               f"{'ready' if ready else 'pending'}")
    typer.echo(f"  captured  {entry.get('captured_at', '')}")
    typer.echo(f"  jd        companies/{slug}/description.md")


@app.command("apply")
def apply_command(
    slug: str,
    open_: bool = typer.Option(False, "--open", help="open it in a browser"),
) -> None:
    """Print the link to apply with, preferring the company's own page."""
    entry = find_entry(slug)
    if not entry:
        typer.echo(f"No capture with slug {slug}.", err=True)
        raise typer.Exit(code=1)
    url = entry.get("apply_url") or entry.get("url") or ""
    if not url:
        typer.echo("No link recorded for this capture.", err=True)
        raise typer.Exit(code=1)
    typer.echo(url)
    if open_:
        import webbrowser

        webbrowser.open(url)


@app.command("status")
def status_command() -> None:
    """Summarise the queue: what is waiting and what is done."""
    entries = load_ledger()
    if not entries:
        typer.echo("Queue is empty.")
        return
    pending = [e for e in entries if not has_cv(e.get("slug", ""))]
    ready = [e for e in entries if has_cv(e.get("slug", ""))]
    with_link = [e for e in entries if e.get("apply_url")]

    typer.echo(f"  captures         {len(entries)}")
    typer.echo(f"  CV ready         {len(ready)}")
    typer.echo(f"  pending CV       {len(pending)}")
    typer.echo(f"  with apply link  {len(with_link)}")
    if pending:
        typer.echo("\n  waiting on a CV:")
        for e in pending:
            typer.echo(f"    {e.get('slug', ''):24} {e.get('company', '')} - "
                       f"{e.get('title', '')}")


if __name__ == "__main__":
    app()
