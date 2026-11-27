"""
Google sign-in and the session cookie (E1.3). Design: docs/e1-identity.md §3.

Design rationale:
    The console gets a Google ID token from Google Identity Services and posts
    it to `/auth/google`. That token is a JWT signed by Google; it is trusted
    only after its signature checks against Google's published certificates,
    its audience is Atlas's own client id (a token minted for another site is
    refused), its issuer is Google, it has not expired, and its email is
    verified. Atlas never sees a password and never uses the client secret.

    The session is a cookie holding the user id and an expiry, signed with
    HMAC-SHA256 under SESSION_SECRET. It carries no roles: the principal is
    read from the store on every request, so removing a member or changing a
    role takes effect on their next request, and an 8-hour cookie cannot keep
    access the store has taken away. HttpOnly (no script can read it), Secure,
    SameSite=Lax (another site's form post does not carry it).

    Certificates are fetched with httpx and kept until the max-age Google
    sends; a token signed by a key not in the cache triggers one refetch,
    which is how Google's key rotation is followed. Tests pass their own
    certificates and sign tokens with their own key.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

import httpx
import structlog

logger = structlog.get_logger(__name__)

COOKIE = "atlas_session"
SESSION_SECONDS = 8 * 3600
# The console sends this on every request; a cookie-carrying write without it
# is refused. A cross-site page cannot set it without a CORS preflight, and
# the API's CORS policy does not allow credentials.
CSRF_HEADER = "X-Requested-With"
CSRF_VALUE = "atlas"

GOOGLE_CERTS_URL = "https://www.googleapis.com/oauth2/v1/certs"
GOOGLE_ISSUERS = frozenset({"accounts.google.com", "https://accounts.google.com"})


class InvalidToken(ValueError):
    """The Google token was not one Atlas may accept. The message says why."""


class SignInUnavailable(RuntimeError):
    """Atlas cannot check any token right now: not configured, or Google's
    keys could not be read. Not the caller's fault, so not a 401."""


@dataclass(frozen=True)
class GoogleIdentity:
    subject: str
    email: str
    name: str
    hosted_domain: str  # the `hd` claim: set only for Google Workspace accounts


CertFetcher = Callable[[], Awaitable[tuple[dict[str, str], float]]]


async def _fetch_google_certs() -> tuple[dict[str, str], float]:
    async with httpx.AsyncClient(timeout=5.0) as client:
        r = await client.get(GOOGLE_CERTS_URL)
        r.raise_for_status()
    m = re.search(r"max-age=(\d+)", r.headers.get("cache-control", ""))
    ttl = float(m.group(1)) if m else 3600.0
    certs: dict[str, str] = r.json()
    return certs, ttl


def _kid(token: str) -> str:
    try:
        header = token.split(".", 1)[0]
        padded = header + "=" * (-len(header) % 4)
        return str(json.loads(base64.urlsafe_b64decode(padded)).get("kid", ""))
    except (ValueError, IndexError) as exc:
        raise InvalidToken("not a signed token") from exc


class GoogleVerifier:
    def __init__(self, client_id: str, *, certs: Mapping[str, str] | None = None,
                 fetch: CertFetcher | None = None) -> None:
        self.client_id = client_id
        self._certs: dict[str, str] = dict(certs or {})
        # Certificates handed in by a test are fixed: never expired, never refetched.
        self._fixed = certs is not None
        self._expires = 0.0
        self._fetched_at = 0.0
        self._fetch = fetch or _fetch_google_certs

    def _due(self, kid: str) -> bool:
        if self._fixed:
            return False
        now = time.time()
        # An unknown key id refetches at most once a minute, so a stream of
        # made-up tokens cannot turn into a stream of requests to Google.
        return now >= self._expires or (kid not in self._certs and now - self._fetched_at > 60)

    async def _load(self) -> None:
        self._fetched_at = time.time()
        try:
            self._certs, ttl = await self._fetch()
        except Exception as exc:
            logger.warning("google_certs_unavailable", error=str(exc))
            raise SignInUnavailable("Google's signing keys could not be read") from exc
        self._expires = time.time() + ttl

    async def verify(self, token: str) -> GoogleIdentity:
        from google.auth import jwt  # noqa: PLC0415 — heavy import, only on sign-in

        if not self.client_id:
            raise SignInUnavailable("sign-in is not configured")
        kid = _kid(token)
        if self._due(kid):
            await self._load()
        if kid not in self._certs:
            raise InvalidToken("signed by a key Google does not publish")
        try:
            claims: dict[str, object] = jwt.decode(  # type: ignore[no-untyped-call]
                token, certs=self._certs, audience=self.client_id, clock_skew_in_seconds=30)
        except ValueError as exc:
            # Wrong audience, expired, bad signature: google-auth raises
            # ValueError (or a subclass) for each.
            raise InvalidToken(str(exc)) from exc
        if claims.get("iss") not in GOOGLE_ISSUERS:
            raise InvalidToken("not issued by Google")
        email = str(claims.get("email", ""))
        if not email or claims.get("email_verified") not in (True, "true"):
            raise InvalidToken("the account's email address is not verified")
        return GoogleIdentity(subject=str(claims.get("sub", "")), email=email,
                              name=str(claims.get("name", "")),
                              hosted_domain=str(claims.get("hd", "")).lower())


@dataclass
class SignIn:
    """What the sign-in routes need, held on app.state so a test can swap it."""

    client_id: str
    secret: str
    verifier: GoogleVerifier

    @property
    def enabled(self) -> bool:
        return bool(self.client_id and self.secret)

    @classmethod
    def from_settings(cls, client_id: str, secret: str) -> SignIn:
        return cls(client_id=client_id, secret=secret, verifier=GoogleVerifier(client_id))


# ── Session cookie ────────────────────────────────────────────────────────────

_VERSION = "v2"
# v1 cookies (user id only) are still read until they expire, at most 8 h
# after the v2 deploy; they simply carry no email or domain.
_V1 = "v1"


@dataclass(frozen=True)
class Session:
    """What a signed cookie says: who, and what Google verified about them.

    `email` and `hosted_domain` come from the verified Google sign-in, so the
    access tokens built from them (`email:`, `domain:`, E3) are as good as
    the sign-in itself. They ride in the cookie, not the store, because a
    domain is only known at sign-in and costs nothing to carry.
    """

    user_id: str
    email: str = ""
    hosted_domain: str = ""


def _mac(secret: str, payload: str) -> str:
    digest = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).rstrip(b"=").decode()


def _unb64(text: str) -> str:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4)).decode()


def sign_session(user_id: str, secret: str, *, email: str = "", hosted_domain: str = "",
                 now: float | None = None, seconds: int = SESSION_SECONDS) -> str:
    if not secret:
        raise ValueError("SESSION_SECRET is not set")
    if "." in user_id:
        raise ValueError("user ids never contain '.'")
    expires = int((now if now is not None else time.time()) + seconds)
    payload = (f"{_VERSION}.{user_id}.{_b64(email.lower())}.{_b64(hosted_domain.lower())}"
               f".{expires}")
    return f"{payload}.{_mac(secret, payload)}"


def read_session_identity(value: str, secret: str, *,
                          now: float | None = None) -> Session | None:
    """The session in a cookie Atlas signed and that has not expired, else None."""
    if not secret or not value:
        return None
    parts = value.split(".")
    if parts[0] == _V1 and len(parts) == 4:
        fields, mac = parts[:3], parts[3]
    elif parts[0] == _VERSION and len(parts) == 6:
        fields, mac = parts[:5], parts[5]
    else:
        return None
    if not hmac.compare_digest(mac, _mac(secret, ".".join(fields))):
        return None
    try:
        expires = int(fields[-1])
        email = _unb64(fields[2]) if len(fields) == 5 else ""
        domain = _unb64(fields[3]) if len(fields) == 5 else ""
    except (ValueError, UnicodeDecodeError):
        return None
    if expires <= (now if now is not None else time.time()) or not fields[1]:
        return None
    return Session(user_id=fields[1], email=email, hosted_domain=domain)


def read_session(value: str, secret: str, *, now: float | None = None) -> str | None:
    """The user id in a cookie Atlas signed and that has not expired, else None."""
    session = read_session_identity(value, secret, now=now)
    return session.user_id if session else None
