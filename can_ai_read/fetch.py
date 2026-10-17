"""Fetching with guard rails.

The checker requests web pages on the user's behalf. When it runs as a shared server, that is a
risk: someone could point it at an internal address. So by default it refuses any address that
resolves to a private, loopback, link-local, multicast or reserved IP, checks every redirect the
same way, can be limited to a list of domains, and never reads more than a fixed number of bytes.
"""

from __future__ import annotations

import ipaddress
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Optional

MAX_BYTES = 5_000_000
TIMEOUT = 20


class Blocked(Exception):
    """The address is not allowed by the fetch policy."""


@dataclass
class Policy:
    allow_private: bool = False
    allowed_domains: list = field(default_factory=list)  # empty = any public domain

    def check_url(self, url: str) -> None:
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in ("http", "https"):
            raise Blocked("Only http and https addresses can be checked.")
        host = (parts.hostname or "").lower().rstrip(".")
        if not host:
            raise Blocked("The address has no host name.")
        if self.allowed_domains and not any(
            host == d or host.endswith("." + d) for d in self.allowed_domains
        ):
            raise Blocked(f"{host} is not on this server's list of allowed domains.")
        if self.allow_private:
            return
        try:
            infos = socket.getaddrinfo(host, parts.port or (443 if parts.scheme == "https" else 80))
        except socket.gaierror:
            raise Blocked(f"Could not find the address {host}.")
        for info in infos:
            ip = ipaddress.ip_address(info[4][0].split("%", 1)[0])
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_multicast
                or ip.is_reserved
                or ip.is_unspecified
            ):
                raise Blocked(f"{host} points to a private or internal address, which is not allowed.")


@dataclass
class Response:
    url: str
    status: Optional[int] = None
    final_url: str = ""
    headers: dict = field(default_factory=dict)
    body: bytes = b""
    error: str = ""
    seconds: float = 0.0

    @property
    def text(self) -> str:
        ctype = self.headers.get("content-type", "")
        charset = "utf-8"
        if "charset=" in ctype:
            charset = ctype.split("charset=", 1)[1].split(";", 1)[0].strip().strip('"') or "utf-8"
        try:
            return self.body.decode(charset, errors="replace")
        except LookupError:
            return self.body.decode("utf-8", errors="replace")

    @property
    def challenge(self) -> bool:
        """True when the answer looks like a bot challenge page rather than the real page."""
        if self.headers.get("cf-mitigated", "").lower() == "challenge":
            return True
        sample = self.body[:20000].lower()
        markers = (b"challenge-platform", b"cf-chl-", b"just a moment...", b"_incapsula_resource", b"px-captcha")
        return any(m in sample for m in markers) and len(sample) < 20000


class _GuardedRedirect(urllib.request.HTTPRedirectHandler):
    max_redirections = 5

    def __init__(self, policy: Policy):
        super().__init__()
        self.policy = policy

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.policy.check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url: str, user_agent: str, policy: Policy, timeout: int = TIMEOUT) -> Response:
    out = Response(url=url)
    start = time.monotonic()
    try:
        policy.check_url(url)
        opener = urllib.request.build_opener(
            _GuardedRedirect(policy),
            urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        )
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9,sv;q=0.8",
            },
        )
        try:
            resp = opener.open(req, timeout=timeout)
        except urllib.error.HTTPError as err:
            resp = err
        out.status = resp.status if hasattr(resp, "status") else resp.code
        out.final_url = resp.geturl()
        out.headers = {k.lower(): v for k, v in resp.headers.items()}
        out.body = resp.read(MAX_BYTES)
        resp.close()
    except Blocked as err:
        out.error = str(err)
    except urllib.error.URLError as err:
        reason = getattr(err, "reason", err)
        out.error = f"Could not connect: {reason}"
    except (socket.timeout, TimeoutError):
        out.error = "The site took too long to answer."
    except Exception as err:  # noqa: BLE001 - report any network failure as text
        out.error = f"{type(err).__name__}: {err}"
    out.seconds = round(time.monotonic() - start, 2)
    return out
