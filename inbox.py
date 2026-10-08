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
import os
import re
import secrets
import shutil
import unicodedata
import urllib.parse
import urllib.request
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
# A capture below this CV fit is triaged into triage/ instead of the pipeline.
MIN_MATCH = int(os.environ.get("CV_MIN_MATCH", "60"))

# What a capture must carry for a tailored CV to be possible at all.
REQUIRED = ("company", "title")
MAX_BODY = 2_000_000# A DOM sample is legitimate here and large: it is how a broken selector gets
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
    # Set by the capture handler: the CV fit for the JD, and whether it went to
    # triage because it was below the minimum.
    match: Optional[int] = None
    triage: bool = False

    @property
    def path(self) -> str:
        root = "triage" if self.triage else "companies"
        return f"{root}/{self.slug}/description.md"


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


def score_payload(payload: dict, base_dir: Optional[Path] = None) -> Optional[int]:
    """The base CV's fit for a JD, 0-100, or None when it cannot be scored.

    The scoring is reused from search.py; the base cv.json is the target. A None
    result means the gate could not run, and the capture is promoted instead of
    being triaged, so a scoring failure never silently hides a job.
    """
    try:
        import search
    except ImportError:
        return None
    base_dir = base_dir or BASE_DIR
    if not (base_dir / "cv.json").is_file():
        return None
    job = search.Job(
        title=str(payload.get("title") or ""),
        company=str(payload.get("company") or ""),
        location=str(payload.get("location") or ""),
        url=str(payload.get("url") or ""),
        description=str(payload.get("description") or ""),
        source="capture",
    )
    try:
        cv = json.loads((base_dir / "cv.json").read_text(encoding="utf-8"))
        ranked = search.rank([job], cv)
    except Exception:  # noqa: BLE001 - a scoring failure must not hide the job
        return None
    return ranked[0].fit if ranked else None


def save_capture(payload: dict, base_dir: Optional[Path] = None,
                 match: Optional[int] = None) -> Capture:
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
            while slug in taken or (base_dir / "companies" / slug).exists() \
                    or (base_dir / "triage" / slug).exists():
                slug = f"{company_slug}/{role}-{n}"
                n += 1

    header = [title, company, location, url]
    if apply_url:
        header.append(f"apply: {apply_url}")

    # A capture always enters the pipeline. The fit is a separate check
    # (`cv triage add`, the panel's Match button), never a gate at capture:
    # grabbing a job and judging its fit are two different actions.
    root = "companies"
    out = base_dir / root / slug / "description.md"
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
        match=match,
        triage=False,
        status="new",
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


# Which captured "titles" are actually locations: the residue of the extraction
# bug that spec 0010 fixed for new captures. `cv inbox repair` fixes the residue.
LOCATION_WORDS = {
    "remote", "remoto", "remota", "remotely", "100% remoto", "hibrido",
    "híbrido", "hibrida", "híbrida", "presencial", "presential", "onsite",
    "on-site", "on site", "home office", "homeoffice", "são paulo", "sao paulo",
    "são paulo, brasil", "sao paulo, brasil", "brasil", "brazil",
    "guarulhos", "belo horizonte", "rio de janeiro",
}
# The job title element of LinkedIn's guest detail page, stable across the
# class renames that broke the extension's selectors.
_TITLE_TAG_RE = re.compile(r'class="top-card-layout__title[^"]*"[^>]*>(.*?)</', re.S)
_TITLE_HINT_RE = re.compile(
    r"(engineer|developer|develop|dev\b|engenheiro|programador|analista|analyst|"
    r"desenvolvedor|software|front-?end|back-?end|full-?stack|senior|sênior|pleno|"
    r"junior|júnior|estagi|arquiteto|architect|designer|product manager|pm|"
    r"react|node|backend|frontend)", re.I)


def _norm_for_repair(value: str) -> str:
    return " ".join(str(value or "").lower().split())


def title_is_damaged(entry: dict) -> bool:
    """Whether a capture's title is really its location, stored by the bug."""
    title = str(entry.get("title", "")).strip()
    if not title:
        return True
    low = _norm_for_repair(title)
    if low in LOCATION_WORDS:
        return True
    location = str(entry.get("location", "")).strip()
    return bool(location) and _norm_for_repair(location) == low


def _linkedin_title(job_id: str) -> str:
    """The posting's real title from LinkedIn's guest detail page."""
    if not re.fullmatch(r"\d+", str(job_id or "")):
        return ""
    try:
        html = urllib.request.urlopen(
            urllib.request.Request(
                "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/"
                + str(job_id),
                headers={"User-Agent": "Mozilla/5.0"}), timeout=25
        ).read().decode("utf-8", "replace")
    except Exception:  # noqa: BLE001 - a blocked fetch is a missing title
        return ""
    match = _TITLE_TAG_RE.search(html)
    if not match:
        return ""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", match.group(1))).strip()


def _first_title_from_body(body: str) -> str:
    """A short standalone line that reads like a job title, or empty."""
    for line in (body or "").splitlines():
        title = line.strip()
        if not title or len(title) > 90:
            continue
        low = _norm_for_repair(title)
        if re.match(r"^(sobre a vaga|descri.ão da vaga|responsabilidades|"
                    r"requisitos|a empresa|sobre nós|benefícios)", low):
            continue
        if title[0].isupper() and _TITLE_HINT_RE.search(low):
            return title
    return ""


def _capture_body(entry: dict, base_dir: Optional[Path] = None) -> str:
    """The JD body of a capture, wherever its file sits."""
    base_dir = base_dir or BASE_DIR
    root = "triage" if (entry.get("triage")
                        or str(entry.get("status", "")).lower() in _TRIAGE) \
        else "companies"
    jd = base_dir / root / str(entry.get("slug", "")) / "description.md"
    if not jd.is_file():
        return str(entry.get("description", ""))
    return _jd_parts(jd.read_text(encoding="utf-8"))[1]


def _jd_parts(text: str) -> tuple[list[str], str]:
    """The header lines and the body of a captured JD file.

    The header is title, company, location, url, plus an optional apply line.
    Location may be empty, which puts a blank line inside the header, so the
    body is the content after the first blank that sits past the url field.
    """
    lines = text.splitlines()
    body_start = None
    for index, line in enumerate(lines):
        if line == "" and index >= 4:
            body_start = index
            break
    if body_start is None:
        return lines, ""
    return lines[:body_start], "\n".join(lines[body_start + 1:])


def repair_capture(entry: dict, base_dir: Optional[Path] = None,
                   fetch=None, dry_run: bool = False) -> dict:
    """Re-derive a damaged capture's title, location and score (spec 0011).

    The title comes from LinkedIn's guest page by posting id, falling back to
    the first title-looking line in the JD. Nothing is written in a dry run.
    """
    base_dir = base_dir or BASE_DIR
    fetch = fetch or _linkedin_title
    slug = str(entry.get("slug", ""))
    root = ("triage" if (entry.get("triage")
                         or str(entry.get("status", "")).lower() in _TRIAGE)
            else "companies")
    jd = base_dir / root / slug / "description.md"
    if not jd.is_file():
        return {"slug": slug, "ok": False, "reason": "no JD file"}

    head, body = _jd_parts(jd.read_text(encoding="utf-8"))
    url = str(entry.get("url", ""))
    job_id_m = re.search(r"/jobs/view/(\d+)", url)
    title = fetch(job_id_m.group(1)) if job_id_m else ""
    if not title:
        title = _first_title_from_body(body)
    if not title:
        return {"slug": slug, "ok": False, "reason": "no title source"}

    old_title = str(entry.get("title", "")).strip()
    location = str(entry.get("location", "")).strip()
    if not location and _norm_for_repair(old_title) in LOCATION_WORDS:
        location = old_title

    match = score_payload({
        "title": title,
        "company": str(entry.get("company", "")),
        "location": location,
        "url": url,
        "description": body.strip(),
    }, base_dir)

    report = {"slug": slug, "ok": True, "title": title, "location": location,
              "match": match, "dry": dry_run}
    if match is None:
        report["triage"] = bool(entry.get("triage"))
    else:
        report["triage"] = match < MIN_MATCH
    if dry_run:
        return report

    entries = load_ledger()
    for candidate in entries:
        if candidate.get("slug") != slug:
            continue
        candidate["title"] = title
        candidate["location"] = location
        if match is not None:
            candidate["match"] = match
            candidate["triage"] = report["triage"]
            candidate["status"] = "triaged" if report["triage"] else "new"

    lines = list(head)
    if len(lines) >= 4:
        lines[0] = title
        lines[2] = location
    if root == "triage" and not report["triage"]:
        moved = base_dir / "companies" / slug / "description.md"
        moved.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(jd), str(moved))
        try:
            (base_dir / "triage" / slug).rmdir()
        except OSError:
            pass
        jd = moved
    jd.write_text("\n".join(lines) + "\n\n" + body, encoding="utf-8")
    save_ledger(entries)
    return report


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

        def _authorized(self) -> bool:
            return secrets.compare_digest(self.headers.get("X-CV-Token", ""), token)

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/health":
                self._send(200, {"ok": True})
                return
            if self.path.split("?")[0] == "/jobs":
                if not self._authorized():
                    self._send(401, {"ok": False, "error": "bad token"})
                    return
                query = urllib.parse.urlparse(self.path).query
                params = urllib.parse.parse_qs(query)
                if "id" in params or "slug" in params:
                    key = (params.get("id") or params.get("slug"))[0]
                    entry = job_for(key, base_dir)
                    self._send(200, {"ok": True,
                                     "job": job_view(entry, base_dir) if entry else None})
                    return
                limit = params.get("limit", ["20"])[0]
                try:
                    count = max(1, min(200, int(limit)))
                except ValueError:
                    count = 20
                self._send(200, {"ok": True, "jobs": jobs(base_dir, count)})
                return
            if self.path.split("?")[0] == "/score":
                if not self._authorized():
                    self._send(401, {"ok": False, "error": "bad token"})
                    return
                params = urllib.parse.parse_qs(
                    urllib.parse.urlparse(self.path).query)
                if params.get("slug"):
                    payload = _stored_payload(params["slug"][0], base_dir)
                    if payload is None:
                        self._send(404, {"ok": False, "error": "no such capture"})
                        return
                else:
                    payload = {
                        "title": (params.get("title") or [""])[0],
                        "company": (params.get("company") or [""])[0],
                        "location": "",
                        "url": "",
                        "description": (params.get("description") or [""])[0],
                    }
                match = score_payload(payload, base_dir)
                self._send(200, {"ok": True, "match": match,
                                 "min": MIN_MATCH})
                return
            self._send(404, {"ok": False, "error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            if self.path not in ("/capture", "/diagnose", "/applied", "/reconcile",
                                 "/skip", "/reconsider", "/profile", "/unprofile"):
                self._send(404, {"ok": False, "error": "not found"})
                return
            if not self._authorized():
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

            if self.path == "/applied":
                slug = mark_applied(
                    payload.get("slug") or payload.get("url") or "", base_dir)
                if not slug:
                    self._send(404, {"ok": False, "error": "no such capture"})
                    return
                self._send(200, {"ok": True, "slug": slug})
                return

            if self.path == "/reconcile":
                ids = payload.get("ids")
                if not isinstance(ids, list):
                    self._send(422, {"ok": False, "error": "expected ids: []"})
                    return
                applied = reconcile(ids, base_dir)
                self._send(200, {"ok": True, "applied": applied,
                                 "count": len(applied)})
                return

            if self.path in ("/skip", "/reconsider", "/profile", "/unprofile"):
                identifier = (payload.get("slug") or payload.get("url") or "")
                try:
                    if self.path == "/skip":
                        slug = mark_skipped(identifier,
                                            str(payload.get("reason") or ""),
                                            base_dir)
                        step = "skipped"
                    elif self.path == "/reconsider":
                        slug = mark_reconsidered(identifier, base_dir)
                        step = "captured"
                    elif self.path == "/profile":
                        slug = mark_profile(identifier, base_dir)
                        step = "profile"
                    else:
                        slug = mark_captured(identifier, base_dir)
                        step = "captured"
                except StepTransitionError as exc:
                    self._send(409, {"ok": False, "code": exc.identity,
                                     "error": exc.detail})
                    return
                if not slug:
                    self._send(404, {"ok": False, "code": E_NO_CAPTURE,
                                     "error": "no such capture"})
                    return
                self._send(200, {"ok": True, "slug": slug, "step": step})
                return

            try:
                match = score_payload(payload, base_dir)
                capture = save_capture(payload, base_dir, match=match)
            except ValueError as exc:
                self._send(422, {"ok": False, "error": str(exc)})
                return
            self._send(200, {"ok": True, "slug": capture.slug, "path": capture.path,
                             "match": match})

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


def cv_gaps(slug: str, base_dir: Optional[Path] = None) -> Optional[dict[str, list[str]]]:
    """Skill tags a capture's CVs claim that no repository proves.

    None means the ledger is absent, which is different from a CV with no gaps:
    one is unknown, the other is clean. Imported lazily so the listener stays
    stdlib only and cannot fail on the heavier evidence module.
    """
    import skills

    ledger = skills.load_gaps()
    if not ledger:
        return None
    folder = (base_dir or BASE_DIR) / "companies" / slug
    if not folder.is_dir():
        return {}
    found: dict[str, list[str]] = {}
    for cv_file in sorted(folder.glob("cv-*.json")):
        try:
            cv = json.loads(cv_file.read_text())
        except ValueError:
            continue
        problems = skills.unproven_in(cv, ledger)
        if problems:
            found[cv_file.name] = problems
    return found


def mark_profile(identifier: str, base_dir: Optional[Path] = None) -> Optional[str]:
    """Record that an application uses only the LinkedIn profile, so no CV.

    A refusal only for a declined capture. An applied capture may still be
    flagged as profile-only: the point is which roles want a tailored CV, and an
    email confirmation does not change that, so the applied step is kept and the
    profile marker is added next to it.
    """
    entry = job_for(identifier, base_dir)
    if not entry:
        return None
    status = str(entry.get("status", "new")).lower()
    if status in _SKIPPED:
        raise StepTransitionError(E_NOT_CAPTURED,
                                  "a declined posting must be reconsidered first")
    entries = load_ledger()
    for candidate in entries:
        if candidate.get("slug") == entry.get("slug"):
            candidate["profile_only"] = True
            candidate["profile_at"] = datetime.now(timezone.utc).isoformat(
                timespec="seconds")
            if status not in _APPLIED:
                candidate["status"] = "profile"
    save_ledger(entries)
    return entry.get("slug")


def mark_captured(identifier: str, base_dir: Optional[Path] = None) -> Optional[str]:
    """Return a profile-only posting to the queue, so a CV is wanted again."""
    entry = job_for(identifier, base_dir)
    if not entry:
        return None
    if str(entry.get("status", "new")).lower() not in _PROFILE:
        raise StepTransitionError(E_NOT_PROFILE,
                                  "only a profile-only posting can rejoin the queue")
    entries = load_ledger()
    for candidate in entries:
        if candidate.get("slug") == entry.get("slug"):
            candidate["status"] = "new"
            candidate.pop("profile_at", None)
    save_ledger(entries)
    return entry.get("slug")


def jd_date(slug: str, base_dir: Optional[Path] = None) -> str:
    """The date the capture's JD file was last written, or empty."""
    base_dir = base_dir or BASE_DIR
    jd = base_dir / "companies" / slug / "description.md"
    if not jd.is_file():
        return ""
    return datetime.fromtimestamp(jd.stat().st_mtime).date().isoformat()


# The capture lifecycle: captured -> cv-ready -> applied, a posting passed over
# is skipped, one applied straight from the LinkedIn profile is profile-only,
# and one below the match minimum is triaged until promoted or dropped. Only
# applied, skipped, profile and triaged are stored; "cv-ready" is read from the
# files on disk, so regenerating or deleting a CV moves the step without
# anything needing to be kept in sync.
STEPS = ("captured", "cv-ready", "applied", "skipped", "profile", "triaged")
_APPLIED = {"applied"}
_SKIPPED = {"skipped", "rejected", "declined"}
_PROFILE = {"profile", "profile-only"}
_TRIAGE = {"triaged"}

# Returned in `code` so a caller branches on the identity, never on the message.
E_NO_CAPTURE = "E_NO_CAPTURE"
E_ALREADY_APPLIED = "E_ALREADY_APPLIED"
E_NOT_SKIPPED = "E_NOT_SKIPPED"
E_NOT_PROFILE = "E_NOT_PROFILE"
E_NOT_CAPTURED = "E_NOT_CAPTURED"


class StepTransitionError(Exception):
    """A step change that the capture's own step forbids.

    A declining option shown on an applied capture, or a reconsider shown on one
    that was never declined, would otherwise write an impossible transition.
    """

    def __init__(self, identity: str, detail: str = "") -> None:
        super().__init__(detail or identity)
        self.identity = identity
        self.detail = detail


def step_of(slug: str, entry: dict, base_dir: Optional[Path] = None) -> str:
    """Which step a capture has reached.

    The stored steps are checked before the derived one, so a posting that has a
    CV next to it does not read as pending again when it was skipped, applied or
    confined to the LinkedIn profile.
    """
    status = str(entry.get("status", "new")).lower()
    if status in _APPLIED:
        return "applied"
    if status in _SKIPPED:
        return "skipped"
    if status in _PROFILE:
        return "profile"
    if status in _TRIAGE:
        return "triaged"
    return "cv-ready" if has_cv(slug, base_dir) else "captured"


def job_for(identifier: str, base_dir: Optional[Path] = None) -> Optional[dict]:
    """A ledger entry by slug, by posting URL, or by LinkedIn job id."""
    key = str(identifier or "").strip()
    if not key:
        return None
    for entry in load_ledger():
        url = str(entry.get("url", ""))
        if entry.get("slug") == key or url == key:
            return entry
        match = re.search(r"/jobs/view/(\d+)", url)
        if match and match.group(1) == key:
            return entry
    return None


def job_view(entry: dict, base_dir: Optional[Path] = None) -> dict:
    slug = str(entry.get("slug", ""))
    return {
        "slug": slug,
        "company": entry.get("company", ""),
        "title": entry.get("title", ""),
        "url": entry.get("url", ""),
        "apply_url": entry.get("apply_url", ""),
        "captured_at": entry.get("captured_at", ""),
        "step": step_of(slug, entry, base_dir),
        "reason": entry.get("skip_reason", ""),
        "profile_only": bool(entry.get("profile_only")),
        "match": entry.get("match"),
        "triage": bool(entry.get("triage")),
    }


def jobs(base_dir: Optional[Path] = None, limit: Optional[int] = None) -> list[dict]:
    """Every capture as a step view, most recently captured first."""
    view = [job_view(entry, base_dir) for entry in load_ledger()]
    view.sort(key=lambda job: job.get("captured_at", ""), reverse=True)
    return view[:limit] if limit else view


def mark_applied(identifier: str, base_dir: Optional[Path] = None) -> Optional[str]:
    """Record that an application was submitted, by slug or posting.

    Returns the slug on success, None when nothing matched.
    """
    entry = job_for(identifier, base_dir)
    if not entry:
        return None
    entries = load_ledger()
    for candidate in entries:
        if candidate.get("slug") == entry.get("slug"):
            candidate["status"] = "applied"
    save_ledger(entries)
    return entry.get("slug")


def reconcile(identifiers, base_dir: Optional[Path] = None) -> list[str]:
    """Mark every capture that matches one of these job ids or URLs applied.

    LinkedIn's own Applied list is the only reliable record of what was sent,
    so the extension reads it and hands the ids over in one call.
    """
    wanted = {str(i).strip() for i in identifiers or [] if str(i).strip()}
    if not wanted:
        return []
    entries = load_ledger()
    applied: list[str] = []
    for entry in entries:
        url = str(entry.get("url", ""))
        match = re.search(r"/jobs/view/(\d+)", url)
        job_id = match.group(1) if match else ""
        if (entry.get("slug") in wanted or url in wanted
                or (job_id and job_id in wanted)):
            entry["status"] = "applied"
            applied.append(str(entry.get("slug", "")))
    if applied:
        save_ledger(entries)
    return applied


def mark_skipped(identifier: str, reason: str = "",
                 base_dir: Optional[Path] = None) -> Optional[str]:
    """Record that a posting was passed over on purpose, and why.

    Refuses a capture already recorded as applied: an application that was sent
    cannot be declined after the fact.
    """
    entry = job_for(identifier, base_dir)
    if not entry:
        return None
    if str(entry.get("status", "new")).lower() in _APPLIED:
        raise StepTransitionError(E_ALREADY_APPLIED,
                                  "the application was already sent")
    entries = load_ledger()
    for candidate in entries:
        if candidate.get("slug") == entry.get("slug"):
            candidate["status"] = "skipped"
            candidate["skipped_at"] = datetime.now(timezone.utc).isoformat(
                timespec="seconds")
            if reason:
                candidate["skip_reason"] = reason
    save_ledger(entries)
    return entry.get("slug")


def mark_reconsidered(identifier: str, base_dir: Optional[Path] = None
                      ) -> Optional[str]:
    """Return a declined posting to captured, dropping the reason with it.

    Refuses a capture that was not declined: reconsidering exists to take a
    decline back, not to move any other step.
    """
    entry = job_for(identifier, base_dir)
    if not entry:
        return None
    if str(entry.get("status", "new")).lower() not in _SKIPPED:
        raise StepTransitionError(E_NOT_SKIPPED,
                                  "only a declined posting can be reconsidered")
    entries = load_ledger()
    for candidate in entries:
        if candidate.get("slug") == entry.get("slug"):
            candidate["status"] = "new"
            candidate.pop("skip_reason", None)
            candidate.pop("skipped_at", None)
    save_ledger(entries)
    return entry.get("slug")


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
        entries = [e for e in entries
                   if step_of(e.get("slug", ""), e) == "captured"]

    if not entries:
        typer.echo("Queue is empty.")
        return

    needs = 0
    for e in entries:
        slug = e.get("slug", "")
        step = step_of(slug, e)
        if step == "captured":
            needs += 1
        typer.echo(
            f"  [{step:8}] {slug:22} {e.get('company', '')} - {e.get('title', '')}"
        )
        # The apply link is the reason the capture exists; show it here rather
        # than leaving it buried in the JD file.
        if e.get("apply_url"):
            typer.echo(f"             apply: {e['apply_url']}")
    typer.echo(f"\n{len(entries)} captur(es), {needs} still need a CV.")


@app.command("next")
def next_command() -> None:
    """Print the path of the oldest capture that still needs a CV."""
    for e in load_ledger():
        if step_of(e.get("slug", ""), e) == "captured":
            typer.echo(f"companies/{e['slug']}/description.md")
            return
    typer.echo("Nothing waiting on a CV.")


@app.command("applied")
def applied_command(identifier: str) -> None:
    """Record that an application was submitted, by slug or posting URL."""
    entry = job_for(identifier)
    if not entry:
        typer.echo(f"No capture matching {identifier}.", err=True)
        raise typer.Exit(code=1)
    before = step_of(entry["slug"], entry)
    mark_applied(identifier)
    after = step_of(entry["slug"], find_entry(entry["slug"]))
    typer.echo(f"{entry['slug']}: {before} -> {after}")


@app.command("mail")
def mail_command(
    query: Optional[str] = typer.Option(None, "--query", "-q",
                                        help="Gmail search; defaults to confirmation subjects"),
    apply: bool = typer.Option(False, "--apply",
                               help="write the matches; dry run otherwise"),
    limit: int = typer.Option(50, "--limit", help="maximum messages to read"),
    all_: bool = typer.Option(False, "--all", "-a",
                              help="also list already-applied and unmatched confirmations"),
) -> None:
    """Record applied from application confirmations in Gmail."""
    import mailscan

    mailscan.run(query=query, apply=apply, limit=limit, show_all=all_)


@app.command("skip")
def skip_command(
    identifier: str,
    reason: str = typer.Option("", "--reason", "-r",
                               help="why this posting was passed over"),
) -> None:
    """Record that a posting was passed over on purpose."""
    entry = job_for(identifier)
    if not entry:
        typer.echo(f"No capture matching {identifier}.", err=True)
        raise typer.Exit(code=1)
    before = step_of(entry["slug"], entry)
    try:
        mark_skipped(identifier, reason)
    except StepTransitionError as exc:
        typer.echo(f"{exc.identity}: {exc.detail}", err=True)
        raise typer.Exit(code=1)
    after = step_of(entry["slug"], find_entry(entry["slug"]))
    typer.echo(f"{entry['slug']}: {before} -> {after}"
               + (f"  ({reason})" if reason else ""))


@app.command("reconsider")
def reconsider_command(identifier: str) -> None:
    """Return a declined posting to captured, dropping the reason."""
    entry = job_for(identifier)
    if not entry:
        typer.echo(f"No capture matching {identifier}.", err=True)
        raise typer.Exit(code=1)
    before = step_of(entry["slug"], entry)
    try:
        mark_reconsidered(identifier)
    except StepTransitionError as exc:
        typer.echo(f"{exc.identity}: {exc.detail}", err=True)
        raise typer.Exit(code=1)
    after = step_of(entry["slug"], find_entry(entry["slug"]))
    typer.echo(f"{entry['slug']}: {before} -> {after}")


@app.command("profile")
def profile_command(identifier: str) -> None:
    """Record that an application uses only the LinkedIn profile, no CV."""
    entry = job_for(identifier)
    if not entry:
        typer.echo(f"No capture matching {identifier}.", err=True)
        raise typer.Exit(code=1)
    before = step_of(entry["slug"], entry)
    try:
        mark_profile(identifier)
    except StepTransitionError as exc:
        typer.echo(f"{exc.identity}: {exc.detail}", err=True)
        raise typer.Exit(code=1)
    after = step_of(entry["slug"], find_entry(entry["slug"]))
    typer.echo(f"{entry['slug']}: {before} -> {after}")


@app.command("requeue")
def requeue_command(identifier: str) -> None:
    """Return a profile-only posting to the queue, so a CV is wanted again."""
    entry = job_for(identifier)
    if not entry:
        typer.echo(f"No capture matching {identifier}.", err=True)
        raise typer.Exit(code=1)
    before = step_of(entry["slug"], entry)
    try:
        mark_captured(identifier)
    except StepTransitionError as exc:
        typer.echo(f"{exc.identity}: {exc.detail}", err=True)
        raise typer.Exit(code=1)
    after = step_of(entry["slug"], find_entry(entry["slug"]))
    typer.echo(f"{entry['slug']}: {before} -> {after}")


triage_app = typer.Typer(help="Postings captured below the match minimum.")


def move_to_triage(slug: str, base_dir: Optional[Path] = None) -> bool:
    """Move a queued capture into triage/, by explicit request.

    Captures never get there on their own: the operator asks, after checking
    the fit, and this is the ask. Refuses when the queued JD is not on disk.
    """
    base_dir = base_dir or BASE_DIR
    src = base_dir / "companies" / slug / "description.md"
    if not src.is_file():
        return False
    dst = base_dir / "triage" / slug / "description.md"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    entries = load_ledger()
    for candidate in entries:
        if candidate.get("slug") == slug:
            candidate["triage"] = True
            candidate["status"] = "triaged"
    save_ledger(entries)
    return True


def _stored_payload(slug: str, base_dir: Optional[Path] = None) -> Optional[dict]:
    """A capture's scoring payload, rebuilt from its ledger entry and JD."""
    base_dir = base_dir or BASE_DIR
    entry = find_entry(slug)
    if not entry:
        return None
    return {
        "title": str(entry.get("title", "")),
        "company": str(entry.get("company", "")),
        "location": str(entry.get("location", "")),
        "url": str(entry.get("url", "")),
        "description": _capture_body(entry, base_dir),
    }


def triaged_entries() -> list[dict]:
    """Every capture that went to triage, with its recorded match."""
    return [e for e in load_ledger()
            if e.get("triage") or str(e.get("status", "")).lower() in _TRIAGE]


@triage_app.command("list")
def triage_list() -> None:
    """List the postings below the match minimum."""
    entries = sorted(triaged_entries(), key=lambda e: e.get("match") or 0)
    if not entries:
        typer.echo(f"Nothing triaged. Minimum match is {MIN_MATCH}%.")
        return
    typer.echo(f"minimum match {MIN_MATCH}%")
    for e in entries:
        typer.echo(f"  {str(e.get('match', '?')):>3}%  {e.get('slug', '')}")
        typer.echo(f"      {e.get('company', '')} - {e.get('title', '')}")
    typer.echo("\nnext: cv triage promote <slug>   cv triage drop <slug> --yes")


@triage_app.command("promote")
def triage_promote(slug: str) -> None:
    """Move a triaged JD into the queue so a CV can be tailored from it."""
    entry = next((e for e in load_ledger()
                  if e.get("slug") == slug and e.get("triage")), None)
    if not entry:
        typer.echo(f"No triaged capture {slug}.", err=True)
        raise typer.Exit(code=1)
    src = BASE_DIR / "triage" / slug / "description.md"
    dst = BASE_DIR / "companies" / slug / "description.md"
    if not src.is_file():
        typer.echo(f"No JD at {src.relative_to(BASE_DIR)}", err=True)
        raise typer.Exit(code=1)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    try:
        (BASE_DIR / "triage" / slug).rmdir()
    except OSError:
        pass
    entries = load_ledger()
    for candidate in entries:
        if candidate.get("slug") == slug and candidate.get("triage"):
            candidate["status"] = "new"
            candidate["triage"] = False
    save_ledger(entries)
    typer.echo(f"{slug} ({entry.get('match')}%) promoted to the queue.")
    typer.echo(f"Next: cv tailor {slug}")


@triage_app.command("drop")
def triage_drop(
    slug: str,
    yes: bool = typer.Option(False, "--yes",
                             help="confirm the triaged posting is discarded"),
) -> None:
    """Remove a triaged posting and its JD."""
    if not yes:
        typer.echo("This removes the triaged JD and its ledger entry. "
                   "Pass --yes to confirm.", err=True)
        raise typer.Exit(code=1)
    entries = load_ledger()
    window = triaged_entries()
    if not any(e.get("slug") == slug for e in window):
        typer.echo(f"No triaged capture {slug}.", err=True)
        raise typer.Exit(code=1)
    entries[:] = [e for e in entries
                  if not (e.get("slug") == slug and e.get("triage"))]
    shutil.rmtree(BASE_DIR / "triage" / slug, ignore_errors=True)
    save_ledger(entries)
    typer.echo(f"{slug} dropped.")


@triage_app.command("add")
def triage_add(slug: str) -> None:
    """Score a queued capture and move it to triage below the minimum.

    The match check that was once the capture's own step is now this command:
    grabbing a job never sends it to triage; asking to check the fit does.
    """
    entry = find_entry(slug)
    if not entry:
        typer.echo(f"No capture {slug}.", err=True)
        raise typer.Exit(code=1)
    if entry.get("triage"):
        typer.echo(f"{slug} is already triaged.")
        return
    payload = _stored_payload(slug)
    if not payload:
        typer.echo(f"No JD at companies/{slug}/description.md", err=True)
        raise typer.Exit(code=1)
    match = score_payload(payload)
    if match is None:
        typer.echo(f"{slug}: could not score (no cv.json).", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"{slug}: CV fit {match}% (minimum {MIN_MATCH}%)")
    if match >= MIN_MATCH:
        typer.echo("at or above the minimum: stays in the queue.")
        return
    if move_to_triage(slug):
        typer.echo(f"{slug} moved to triage.")
    else:
        typer.echo(f"No JD at companies/{slug}/description.md", err=True)
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
    step = step_of(slug, entry)
    if entry.get("profile_only"):
        cv_note = "not required (profile only)"
    else:
        cv_note = "ready" if ready else "pending"
    typer.echo(f"  company   {entry.get('company', '')}")
    typer.echo(f"  title     {entry.get('title', '')}")
    typer.echo(f"  location  {entry.get('location') or '-'}")
    typer.echo(f"  linkedin  {entry.get('url', '')}")
    typer.echo(f"  apply     {entry.get('apply_url') or '(none: Easy Apply)'}")
    typer.echo(f"  step      {step}, CV {cv_note}")
    if entry.get("skip_reason"):
        typer.echo(f"  skipped   {entry['skip_reason']}")
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


@app.command("score")
def score_command(slug: str) -> None:
    """Show what drives a capture's fit percent, piece by piece."""
    entry = find_entry(slug)
    if not entry:
        typer.echo(f"No capture with slug {slug}.", err=True)
        raise typer.Exit(code=1)
    import search

    base_dir = BASE_DIR
    cv_path = base_dir / "cv.json"
    if not cv_path.is_file():
        typer.echo("No cv.json to score against.", err=True)
        raise typer.Exit(code=1)
    try:
        cv = json.loads(cv_path.read_text(encoding="utf-8"))
    except ValueError:
        typer.echo("cv.json is not valid JSON.", err=True)
        raise typer.Exit(code=1)

    job = search.Job(
        title=str(entry.get("title", "")),
        company=str(entry.get("company", "")),
        location=str(entry.get("location", "")),
        url=str(entry.get("url", "")),
        description=_capture_body(entry, base_dir),
        source="capture",
    )
    exp = search.explain(job, cv)
    r = exp["ratios"]
    typer.echo(f"{slug}: fit {exp['fit']}% = 0.5*jd({r['jd']:.2f}) + "
               f"0.3*skill({r['skill']:.2f}) + 0.2*title({r['title']:.2f})")

    typer.echo(f"\n  jd coverage    {exp['jd_covered']}/{exp['jd_total']} "
               f"distinct JD terms in the CV narrative")
    for missed in exp["jd_misses"][:20]:
        typer.echo(f"      miss  {missed}")
    if len(exp["jd_misses"]) > 20:
        typer.echo(f"      ... and {len(exp['jd_misses']) - 20} more")

    typer.echo(f"\n  skill coverage {exp['skills_matched']}/{exp['skills_total']} "
               f"CV tags mentioned in the JD")
    for skill in exp["skills_list"][:10]:
        typer.echo(f"      hit   {skill}")
    if len(exp["skills_list"]) > 10:
        typer.echo(f"      ... and {len(exp['skills_list']) - 10} more")

    typer.echo(f"\n  title overlap  {exp['title_overlapped']}/"
               f"{exp['title_total']} title tokens in the CV title "
               f"({cv.get('personal', {}).get('title', '')!r})")
    for token in exp["title_missed"][:10]:
        typer.echo(f"      miss  {token}")


@app.command("repair")
def repair_command(
    slug: Optional[str] = typer.Option(None, "--slug",
                                       help="one capture; default is every damaged one"),
    apply: bool = typer.Option(False, "--apply",
                               help="write the repairs; a dry run by default"),
) -> None:
    """Re-derive damaged capture titles from LinkedIn and re-score them."""
    if slug:
        entries = [e for e in load_ledger() if e.get("slug") == slug]
        if not entries:
            typer.echo(f"No capture {slug}.", err=True)
            raise typer.Exit(code=1)
    else:
        entries = [e for e in load_ledger() if title_is_damaged(e)]
    if not entries:
        typer.echo("Nothing to repair.")
        return

    touched = 0
    for entry in entries:
        report = repair_capture(entry, BASE_DIR, dry_run=not apply)
        name = str(entry.get("slug", ""))
        if not report.get("ok"):
            typer.echo(f"  {name:26} left alone ({report.get('reason', 'no title')})")
            continue
        touched += 1
        where = "triaged" if report.get("triage") else "in the queue"
        verb = "would be" if report.get("dry") else "is now"
        score = "unscored" if report.get("match") is None \
            else f"{report.get('match')}%"
        typer.echo(f"  {name:26} {report.get('title')!r} {verb} {where} ({score})")
    if not apply and touched:
        typer.echo("\ndry run: nothing was written. Pass --apply to repair.")


@app.command("status")
def status_command() -> None:
    """Summarise the queue: what is waiting and what is done."""
    entries = load_ledger()
    if not entries:
        typer.echo("Queue is empty.")
        return
    step = {e.get("slug", ""): step_of(e.get("slug", ""), e) for e in entries}
    pending = [e for e in entries if step[e.get("slug", "")] == "captured"]
    pending = [e for e in entries if step[e.get("slug", "")] == "captured"]
    with_cv = [e for e in entries if has_cv(e.get("slug", ""))]
    ready = [e for e in entries if step[e.get("slug", "")] == "cv-ready"]
    applied = [e for e in entries if step[e.get("slug", "")] == "applied"]
    skipped = [e for e in entries if step[e.get("slug", "")] == "skipped"]
    profile = [e for e in entries if step[e.get("slug", "")] == "profile"]
    pending_apply = [e for e in entries
                     if step[e.get("slug", "")] in ("captured", "cv-ready", "profile")]
    with_link = [e for e in entries if e.get("apply_url")]

    typer.echo(f"  captures         {len(entries)}")
    typer.echo(f"  pending apply    {len(pending_apply)}")
    typer.echo(f"  CV ready         {len(ready)}")
    typer.echo(f"  pending CV       {len(pending)}")
    typer.echo(f"  applied          {len(applied)}")
    typer.echo(f"  skipped          {len(skipped)}")
    typer.echo(f"  profile only     {len(profile)}")
    typer.echo(f"  with apply link  {len(with_link)}")

    # Which CVs carry a claim nothing proves. The ledger may be absent, which is
    # not the same as clean, so it is reported rather than assumed.
    gapped: list[tuple[str, dict[str, list[str]]]] = []
    unknown = False
    for entry in with_cv:
        gaps = cv_gaps(entry.get("slug", ""))
        if gaps is None:
            unknown = True
            break
        if gaps:
            gapped.append((entry.get("slug", ""), gaps))
    if unknown:
        typer.echo("  CVs with gaps    unknown (run `cv gaps refresh`)")
    else:
        typer.echo(f"  CVs with gaps    {len(gapped)}")

    if gapped:
        typer.echo("\n  CVs claiming a skill no repository proves:")
        for slug, gaps in gapped:
            for cv_file, tags in gaps.items():
                typer.echo(f"    {slug:22} {cv_file}  <- {', '.join(tags)}")

    dated = []
    for e in entries:
        date = jd_date(e.get("slug", ""))
        if date:
            dated.append((date, e.get("slug", "")))
    if dated:
        typer.echo("\n  JD generated:")
        for date, slug in dated:
            typer.echo(f"    {date}  {slug}")

    if pending:
        typer.echo("\n  waiting on a CV:")
        for e in pending:
            typer.echo(f"    {e.get('slug', ''):24} {e.get('company', '')} - "
                       f"{e.get('title', '')}")


if __name__ == "__main__":
    app()
