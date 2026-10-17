"""A small robots.txt reader that follows RFC 9309.

- Groups start with one or more User-agent lines.
- A crawler uses the groups that name its product token (case-insensitive), or "*" if none do.
- The longest matching rule wins. If an Allow and a Disallow rule are equally long, Allow wins.
- "*" matches any characters and "$" anchors the end of the path.
"""

from __future__ import annotations

import re
from typing import Optional


def parse(text: str) -> dict:
    groups: list = []
    sitemaps: list = []
    current = None
    last_was_agent = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()
        if key == "user-agent":
            if current is None or not last_was_agent:
                current = {"agents": [], "rules": []}
                groups.append(current)
            current["agents"].append(value)
            last_was_agent = True
            continue
        last_was_agent = False
        if key in ("allow", "disallow"):
            if current is None:
                continue
            if key == "disallow" and value == "":
                continue  # "Disallow:" with nothing after it allows everything
            current["rules"].append((key == "allow", value))
        elif key == "sitemap":
            sitemaps.append(value)
    return {"groups": groups, "sitemaps": sitemaps}


def _token(agent_value: str) -> str:
    return agent_value.split("/", 1)[0].strip().lower()


def names(parsed: dict, token: str) -> bool:
    t = token.lower()
    return any(_token(a) == t for g in parsed["groups"] for a in g["agents"])


def _rules_for(parsed: dict, token: str):
    t = token.lower()
    specific = [g for g in parsed["groups"] if any(_token(a) == t for a in g["agents"])]
    if specific:
        return [r for g in specific for r in g["rules"]], token
    star = [g for g in parsed["groups"] if any(a.strip() == "*" for a in g["agents"])]
    if star:
        return [r for g in star for r in g["rules"]], "*"
    return [], None


def _compile(pattern: str):
    anchored = pattern.endswith("$")
    body = pattern[:-1] if anchored else pattern
    regex = "".join(".*" if ch == "*" else re.escape(ch) for ch in body)
    return re.compile(regex + ("$" if anchored else ""))


def allowed(parsed: dict, token: str, path: str = "/") -> dict:
    """Return {"allowed": bool, "rule": str or None, "group": token, "*" or None}."""
    if path.startswith("/robots.txt"):
        return {"allowed": True, "rule": None, "group": None}
    rules, group = _rules_for(parsed, token)
    best: Optional[tuple] = None
    for is_allow, pattern in rules:
        if not pattern.startswith("/") and not pattern.startswith("*"):
            continue
        if _compile(pattern).match(path):
            length = len(pattern)
            if best is None or length > best[0] or (length == best[0] and is_allow and not best[1]):
                best = (length, is_allow, pattern)
    if best is None:
        return {"allowed": True, "rule": None, "group": group}
    return {
        "allowed": best[1],
        "rule": ("Allow: " if best[1] else "Disallow: ") + best[2],
        "group": group,
    }
