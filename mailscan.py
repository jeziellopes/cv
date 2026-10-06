"""Read application confirmations from Gmail and record the captures they match.

The ledger recorded that a CV was written, never that an application went out.
LinkedIn's own Applied list covers what LinkedIn carried; a confirmation in the
mailbox covers the rest.

The search is by what a confirmation looks like, in the languages these arrive
in, rather than by the senders the ledger already knows. Searching by sender
meant a confirmation from any other address was never fetched, which excluded a
recruiter's own domain and every capture with no apply link. What decides a
match is that the message names the capture's role, so the sender is reported as
evidence and never trusted as the reason.

Dry by default. Nothing is written without --apply.
"""

from __future__ import annotations

import json
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

import typer

import inbox

ROOT = Path(__file__).resolve().parent
CLIENT_FILE = ROOT / ".cv-gmail-client.json"
TOKEN_FILE = ROOT / ".cv-gmail-token.json"
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
API = "https://gmail.googleapis.com/gmail/v1/users/me"
MAX_MESSAGES = 100

# What a confirmation is called, in the languages these arrive in. The search
# uses these; the match does not, because a subject in a third language should
# still match once the reader sees it.
CONFIRMATION_SUBJECTS = (
    "sua candidatura",
    "candidatura recebida",
    "recebemos sua candidatura",
    "candidatura para",
    "thank you for applying",
    "your application",
    "application received",
    "we received your application",
)

# Machine-readable identities. Callers branch on these, never on the message.
E_MAIL_NO_CLIENT = "E_MAIL_NO_CLIENT"
E_MAIL_NO_TOKEN = "E_MAIL_NO_TOKEN"
E_MAIL_API = "E_MAIL_API"


class MailError(Exception):
    """A failure with a stable identity, so a caller never matches on prose."""

    def __init__(self, identity: str, detail: str = "") -> None:
        super().__init__(detail or identity)
        self.identity = identity
        self.detail = detail


def normalize(value: str) -> str:
    """Lowercase, unaccented, so a Portuguese subject still matches a title."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text).strip().lower()


def default_query() -> str:
    """A Gmail search for what a confirmation looks like."""
    return "subject:(" + " OR ".join(
        f'"{phrase}"' for phrase in CONFIRMATION_SUBJECTS) + ")"


def _names_title(subject: str, title: str) -> bool:
    if not title:
        return False
    if title in subject:
        return True
    # A subject may shorten the role: require most of its longer words.
    words = [w for w in re.split(r"[^a-z0-9]+", title) if len(w) > 3]
    return bool(words) and sum(1 for w in words if w in subject) >= max(2, len(words) // 2)


def _names_title(subject: str, title: str) -> bool:
    """Whether the subject names this role, as a whole phrase.

    Phrase matching only. Substring matching on words made "full" and "stack"
    match inside "Fullstack", and a word-overlap fallback read "Senior Fullstack
    Engineer" as "Fullstack Engineer II", the two sharing most of their words.
    Both attributed a confirmation to the wrong role, which is worse than
    leaving it unmatched for the operator to place.
    """
    return bool(title) and title in subject


def names_one(message: dict, entry: dict, company_alone: bool = False) -> bool:
    """Whether the message identifies this capture, which is a company and a role.

    The pair is the identity the pipeline already uses, in
    `companies/<company>/<role>/`. A role alone is not a signal here: role
    titles repeat across companies, and their words repeat more often still, so
    it would attribute a confirmation to the wrong capture. The company alone is
    accepted only where that company has a single capture.
    """
    subject = normalize(message.get("subject", ""))
    company = normalize(entry.get("company", ""))
    has_company = bool(company) and company in subject
    if has_company and _names_title(subject, normalize(entry.get("title", ""))):
        return True
    return bool(has_company and company_alone)


def find_matches(entries: Optional[list[dict]] = None,
                 messages: Optional[list[dict]] = None
                 ) -> tuple[list[dict], list[dict], list[dict]]:
    """What each confirmation identifies.

    Returns (matches, already, unmatched). A match is
    {slug, company, title, message_id, from, subject, date}. A confirmation that
    identifies a capture already applied is reported as already; one that
    identifies none is unmatched, so a real confirmation the ledger cannot place
    is visible rather than dropped.
    """
    entries = entries if entries is not None else inbox.load_ledger()
    messages = messages or []

    companies: dict[str, int] = {}
    for entry in entries:
        key = normalize(entry.get("company", ""))
        companies[key] = companies.get(key, 0) + 1

    matches: list[dict] = []
    already: list[dict] = []
    unmatched: list[dict] = []

    for message in messages:
        found = None
        settled = None
        for entry in entries:
            company_alone = companies.get(normalize(entry.get("company", "")), 0) == 1
            if not names_one(message, entry, company_alone=company_alone):
                continue
            if inbox.step_of(str(entry.get("slug", "")), entry) == "applied":
                if settled is None:
                    settled = entry
                continue
            found = entry
            break
        if found is not None:
            matches.append({
                "slug": found.get("slug", ""),
                "company": found.get("company", ""),
                "title": found.get("title", ""),
                "message_id": message.get("id", ""),
                "from": message.get("from", ""),
                "subject": message.get("subject", ""),
                "date": message.get("date", ""),
            })
        elif settled is not None:
            already.append({"slug": settled.get("slug", ""),
                            "subject": message.get("subject", "")})
        else:
            unmatched.append(message)
    return matches, already, unmatched


# ---- Gmail ----------------------------------------------------------------

def _authorize(flow):
    """Run the consent flow, mapping a refused or failed consent to an identity.

    Google reports a denied consent as one of several exception types depending
    on where it fails, so they are collapsed here rather than at each caller.
    """
    try:
        return flow.run_local_server(port=0)
    except Exception as exc:  # noqa: BLE001 - the type is not part of the contract
        raise MailError(
            E_MAIL_NO_TOKEN,
            f"consent did not complete: {exc}. If the browser said access_denied, "
            "add the signing-in account as a test user on the OAuth consent screen.",
        ) from exc


def credentials():
    """Authorised credentials, running the consent flow when there is no token."""
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:  # the mailbox is optional tooling
        raise MailError(E_MAIL_NO_CLIENT,
                        f"google-auth-oauthlib is not installed: {exc}") from exc

    if not CLIENT_FILE.exists():
        raise MailError(E_MAIL_NO_CLIENT,
                        f"no OAuth client at {CLIENT_FILE}")

    creds = None
    if TOKEN_FILE.exists():
        try:
            creds = Credentials.from_authorized_user_info(
                json.loads(TOKEN_FILE.read_text()), SCOPES)
        except (ValueError, KeyError):
            creds = None
    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception as exc:  # noqa: BLE001
            raise MailError(
                E_MAIL_NO_TOKEN,
                f"the saved token could not be refreshed: {exc}") from exc
    else:
        try:
            flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_FILE), SCOPES)
        except (ValueError, OSError) as exc:
            raise MailError(E_MAIL_NO_CLIENT,
                            f"{CLIENT_FILE} is not a usable client: {exc}") from exc
        creds = _authorize(flow)

    TOKEN_FILE.write_text(creds.to_json())
    try:
        TOKEN_FILE.chmod(0o600)
    except OSError:
        pass
    return creds


def _get(url: str, token: str) -> dict:
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise MailError(E_MAIL_API, f"HTTP {exc.code} for {url}") from exc
    except (urllib.error.URLError, ValueError) as exc:
        raise MailError(E_MAIL_API, str(exc)) from exc


def _header(payload: dict, name: str) -> str:
    for header in payload.get("headers", []):
        if header.get("name", "").lower() == name.lower():
            return header.get("value", "")
    return ""


def fetch(query: str, limit: int = 50) -> list[dict]:
    """Search the mailbox and return the headers needed to match."""
    creds = credentials()
    if not creds.token:
        raise MailError(E_MAIL_NO_TOKEN, "the token has no access token; re-authorise")
    listing = _get(f"{API}/messages?" + urllib.parse.urlencode(
        {"q": query, "maxResults": min(limit, MAX_MESSAGES)}), creds.token)
    messages = []
    for item in listing.get("messages", []):
        params = [("format", "metadata"), ("metadataHeaders", "From"),
                  ("metadataHeaders", "Subject"), ("metadataHeaders", "Date")]
        full = _get(f"{API}/messages/{item['id']}?" + urllib.parse.urlencode(params),
                    creds.token)
        payload = full.get("payload", {})
        messages.append({
            "id": full.get("id", item["id"]),
            "from": _header(payload, "From"),
            "subject": _header(payload, "Subject"),
            "date": _header(payload, "Date"),
        })
    return messages


def run(query: Optional[str] = None, apply: bool = False, limit: int = 50,
        show_all: bool = False) -> None:
    """Read the mailbox, report the matches, and write them only when asked."""
    entries = inbox.load_ledger()
    if not entries:
        typer.echo("The queue is empty.", err=True)
        raise typer.Exit(code=1)

    search = query or default_query()
    typer.echo(f"query: {search}")
    try:
        messages = fetch(search, limit)
    except MailError as exc:
        typer.echo(f"{exc.identity}: {exc.detail}", err=True)
        raise typer.Exit(code=1) from exc

    matches, already, unmatched = find_matches(entries, messages)
    typer.echo(f"{len(messages)} message(s) read, {len(matches)} match(es)")
    for match in matches:
        typer.echo(f"  {match['slug']:28} {match['date'][:16]}  {match['from'][:40]}")
        typer.echo(f"      subject: {match['subject'][:70]}")

    # The matches are the reason to run this. The rest is reassurance that the
    # reader understood the mail, so it is one line unless it is asked for.
    if show_all:
        for item in already:
            typer.echo(f"  already applied: {item['slug']}  ({item['subject'][:60]})")
        for message in unmatched:
            typer.echo(f"  unmatched: {message.get('date', '')[:16]}  "
                       f"{message.get('from', '')[:40]}")
            typer.echo(f"      subject: {message.get('subject', '')[:70]}")
    elif already or unmatched:
        typer.echo(f"  ({len(already)} already applied, {len(unmatched)} unmatched; "
                   "pass --all to list them)")

    if not matches:
        return
    if not apply:
        typer.echo("\ndry run: nothing changed. Re-run with --apply to record these.")
        return
    applied = inbox.reconcile([m["slug"] for m in matches])
    typer.echo(f"\nrecorded applied: {', '.join(applied) if applied else 'none'}")
