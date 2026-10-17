"""Run every test on one address and turn the results into plain-language findings."""

from __future__ import annotations

import datetime as _dt
import random
import time
import urllib.parse
from typing import Callable, Optional

from . import __version__, page, robots
from .crawlers import AGENTS, KIND_LABEL, ROBOTS_ONLY, BROWSER_UA
from .fetch import Policy, fetch

FIX, CHECK, OK = "fix", "check", "ok"

Progress = Callable[[int, int, str], None]


def _normalize(url: str) -> str:
    url = url.strip()
    if not url:
        raise ValueError("Enter a web address.")
    if "://" not in url:
        url = "https://" + url
    parts = urllib.parse.urlsplit(url)
    if not parts.netloc:
        raise ValueError(f"'{url}' is not a web address.")
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path or "/", parts.query, ""))


def _outcome(resp) -> str:
    if resp.error:
        return "error"
    if resp.challenge:
        return "challenge"
    if resp.status is not None and 200 <= resp.status < 300:
        return "served"
    return "refused"


def _verdict(outcomes: list) -> str:
    s = set(outcomes)
    if s == {"served"}:
        return "served"
    if s and s <= {"refused", "challenge"}:
        return "refused"
    if s == {"error"}:
        return "error"
    return "mixed"


def run(
    url: str,
    runs: int = 3,
    delay: float = 15,
    pause: float = 1.5,
    policy: Optional[Policy] = None,
    progress: Optional[Progress] = None,
    where: str = "this computer",
) -> dict:
    policy = policy or Policy()
    url = _normalize(url)
    parts = urllib.parse.urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    path = parts.path + (("?" + parts.query) if parts.query else "")
    total = 2 + runs * len(AGENTS)
    done = 0

    def tick(msg):
        nonlocal done
        done += 1
        if progress:
            progress(done, total, msg)

    # 1. robots.txt
    rresp = fetch(origin + "/robots.txt", BROWSER_UA, policy)
    tick("Read robots.txt")
    robots_info = {"url": origin + "/robots.txt", "status": rresp.status, "error": rresp.error}
    parsed = {"groups": [], "sitemaps": []}
    is_text = "html" not in rresp.headers.get("content-type", "")
    if rresp.status == 200 and is_text:
        parsed = robots.parse(rresp.text)
        robots_info["found"] = True
    else:
        robots_info["found"] = False
    robots_info["sitemaps"] = parsed["sitemaps"]
    robots_info["agents"] = []
    for a in AGENTS[1:] + ROBOTS_ONLY:
        decision = robots.allowed(parsed, a["name"], path)
        robots_info["agents"].append({
            "name": a["name"], "company": a["company"], "kind": a["kind"], "use": a["use"],
            "named": robots.names(parsed, a["name"]),
            "allowed": decision["allowed"], "rule": decision["rule"], "group": decision["group"],
        })

    # 2. the server test: each name, several runs, shuffled order, spaced out
    outcomes = {a["name"]: [] for a in AGENTS}
    statuses = {a["name"]: [] for a in AGENTS}
    sizes = {a["name"]: [] for a in AGENTS}
    browser_html = ""
    for r in range(runs):
        order = AGENTS[:]
        random.shuffle(order)
        for i, a in enumerate(order):
            resp = fetch(url, a["ua"], policy)
            o = _outcome(resp)
            outcomes[a["name"]].append(o)
            statuses[a["name"]].append(resp.error and "error" or resp.status)
            sizes[a["name"]].append(len(resp.body))
            if a["name"] == "Browser" and o == "served" and not browser_html:
                browser_html = resp.text
            tick(f"Run {r + 1} of {runs}: asked as {a['name']}")
            if pause and i < len(order) - 1:
                time.sleep(pause)
        if r < runs - 1 and delay:
            time.sleep(delay)
    server = {
        "runs": runs,
        "agents": [
            {
                "name": a["name"], "company": a["company"], "kind": a["kind"],
                "kind_label": KIND_LABEL[a["kind"]], "use": a["use"],
                "statuses": statuses[a["name"]], "outcomes": outcomes[a["name"]],
                "verdict": _verdict(outcomes[a["name"]]),
                "bytes": max(sizes[a["name"]] or [0]),
            }
            for a in AGENTS
        ],
    }

    # 3. the page itself, as the normal visitor received it
    page_info = page.read(browser_html) if browser_html else None

    # 4. llms.txt (for information only)
    lresp = fetch(origin + "/llms.txt", BROWSER_UA, policy)
    tick("Read llms.txt")
    ltext = lresp.text.lstrip()[:200].lower() if lresp.status == 200 else ""
    if lresp.status != 200 or "<html" in ltext or "<!doctype" in ltext:
        llms_kind = "none"
    elif ltext.startswith("user-agent") or "\nuser-agent" in ltext:
        llms_kind = "robots-syntax"
    elif ltext.startswith("#"):
        llms_kind = "markdown"
    else:
        llms_kind = "other"

    result = {
        "tool": "can-ai-read-my-site",
        "version": __version__,
        "url": url,
        "checked_at": _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat(),
        "where": where,
        "robots": robots_info,
        "server": server,
        "page": page_info,
        "llms_txt": {"status": lresp.status, "kind": llms_kind},
    }
    result["findings"] = findings(result)
    counts = {lvl: sum(1 for f in result["findings"] if f["level"] == lvl) for lvl in (FIX, CHECK, OK)}
    result["summary"] = counts
    if counts[FIX]:
        result["headline"] = (
            f"AI tools may not be able to read this page. "
            f"{counts[FIX]} thing{'s' if counts[FIX] != 1 else ''} to fix."
        )
    elif counts[CHECK]:
        result["headline"] = "AI tools can probably read this page. A few things are worth a look."
    else:
        result["headline"] = "AI tools can read this page."
    return result


def _f(level, area, title, detail="", fix=""):
    return {"level": level, "area": area, "title": title, "detail": detail, "fix": fix}


def findings(res: dict) -> list:
    out = []
    agents = {a["name"]: a for a in res["server"]["agents"]}
    browser = agents["Browser"]
    robots_by_name = {a["name"]: a for a in res["robots"]["agents"]}
    runs = res["server"]["runs"]
    times = f"{runs} round{'s' if runs != 1 else ''}"

    # --- Server ---
    if browser["verdict"] == "error":
        out.append(_f(FIX, "Server", "The checker could not reach the page.",
                      f"Every try failed. The first error was: {browser['statuses'][0]}.",
                      "Check the address. If it opens in your browser, your site may be blocking this checker."))
    elif browser["verdict"] != "served":
        out.append(_f(CHECK, "Server", "Your site turned away the checker's normal browser test.",
                      "Bot protection often blocks scripts, even ones that look like a browser. "
                      "So the crawler tests below can't be compared fairly.",
                      "Run the checker from another network, or ask your IT team to check the server logs."))
    else:
        search_ok = all(agents[n]["verdict"] == "served" for n in ("Googlebot", "Bingbot"))
        for a in res["server"]["agents"]:
            if a["kind"] in ("browser", "search"):
                continue
            rb = robots_by_name.get(a["name"], {})
            if a["verdict"] == "refused":
                if a["kind"] == "ai-training":
                    out.append(_f(CHECK, "Server", f"Your server turns away {a['name']} ({a['company']}).",
                                  f"It refused this name every time ({times}). {a['name']} collects pages "
                                  "for AI training. Blocking it does not remove you from AI answers.",
                                  "That can be a fine choice. Just make sure someone chose it on purpose."))
                else:
                    extra = ""
                    if rb.get("named") and rb.get("allowed"):
                        extra = " Your robots.txt names it and lets it in, but your server still says no."
                    if not search_ok:
                        out.append(_f(CHECK, "Server", f"Your server turns away {a['name']} ({a['company']}), "
                                      "and Google's or Bing's name too.",
                                      "Your server may check whether a visitor is really who it says it is. "
                                      "If so, the real crawler may get in." + extra,
                                      "Ask your IT team or host for server logs with this name. "
                                      "A 200 means the real crawler got the page."))
                    else:
                        out.append(_f(FIX, "Server", f"Your server turns away {a['name']} ({a['company']}).",
                                      f"It refused this name every time ({times}), but let Google's and "
                                      f"Bing's names in. {a['use']}. If the real crawler gets the same answer, "
                                      "you can't appear there." + extra,
                                      "Ask whoever runs your hosting, Cloudflare or security plugin if a bot rule "
                                      f"blocks {a['name']}. Then check the server logs for its real visits."))
            elif a["verdict"] == "mixed":
                out.append(_f(CHECK, "Server", f"Your server sometimes turns away {a['name']}.",
                              f"Results: {', '.join(str(s) for s in a['statuses'])}. "
                              "This is often a rate limit.",
                              "Run the check again later. If it keeps happening, ask your host about bot rate limits."))
            elif a["verdict"] == "served" and browser["bytes"] > 5000 and a["bytes"] < 0.4 * browser["bytes"]:
                out.append(_f(CHECK, "Server", f"{a['name']} gets a much smaller page than a normal visitor.",
                              f"A normal visitor got about {browser['bytes'] // 1000} KB. "
                              f"{a['name']} got about {a['bytes'] // 1000} KB.",
                              "Open the page with this name and compare. Some sites send bots a short version."))
        if not any(f["area"] == "Server" for f in out):
            out.append(_f(OK, "Server", "Your server lets all the AI crawler names in.",
                          f"Every name got the page every time ({times})."))

    # --- robots.txt ---
    rb = res["robots"]
    if rb.get("error"):
        out.append(_f(CHECK, "robots.txt", "The checker could not read robots.txt.", rb["error"]))
    elif rb["status"] and rb["status"] >= 500:
        out.append(_f(FIX, "robots.txt", "Your robots.txt gives a server error.",
                      f"It answered with code {rb['status']}. Google treats that as 'stay out of everything' "
                      "until it works again.", "Ask your host to fix the robots.txt address."))
    elif not rb["found"]:
        out.append(_f(OK, "robots.txt", "You have no robots.txt.", "That means every crawler is allowed."))
    else:
        blocked_search = [a for a in rb["agents"] if not a["allowed"] and a["kind"] in ("ai-search", "ai-user", "search")]
        blocked_train = [a for a in rb["agents"] if not a["allowed"] and a["kind"] == "ai-training"]
        for a in blocked_search:
            out.append(_f(FIX, "robots.txt", f"Your robots.txt asks {a['name']} to stay out of this page.",
                          f"The rule is '{a['rule']}'. {a['use']}.",
                          f"Remove or change that rule if you want to appear in {a['company'] or 'its'} answers."))
        if blocked_train:
            names = ", ".join(a["name"] for a in blocked_train)
            out.append(_f(OK, "robots.txt", "You ask AI training crawlers to stay out.",
                          f"Blocked for training: {names}. This keeps your pages out of training. "
                          "It does not remove you from AI answers."))
        if not blocked_search:
            out.append(_f(OK, "robots.txt", "Your robots.txt lets AI search crawlers in."))
        if not rb["sitemaps"]:
            out.append(_f(CHECK, "robots.txt", "Your robots.txt doesn't list a sitemap.",
                          "A sitemap helps search engines find every page. Copilot answers from Bing's index.",
                          "Add a line like 'Sitemap: https://yoursite.com/sitemap.xml'. "
                          "Submit it to Google Search Console and Bing Webmaster Tools."))

    # --- The page ---
    p = res["page"]
    if p:
        if p["looks_like_js_app"]:
            out.append(_f(FIX, "Page", "Most of this page is built by JavaScript.",
                          f"Without running scripts, there are only about {p['words']} words. "
                          "AI crawlers from OpenAI, Anthropic and Perplexity don't run JavaScript.",
                          "Ask your developer to render the text on the server, or add a plain-text version."))
        elif p["words"] < 300:
            out.append(_f(CHECK, "Page", f"This page has only about {p['words']} words of readable text.",
                          "Short pages give an AI little to quote.",
                          "Add the facts a customer needs: price, what's included, who it's for, how long it takes."))
        else:
            out.append(_f(OK, "Page", f"The text is readable without JavaScript (about {p['words']} words)."))
        if p["hidden_words"] > 200 or (p["words"] and p["hidden_words"] > 0.2 * p["words"]):
            out.append(_f(CHECK, "Page", f"About {p['hidden_words']} words are hidden.",
                          "Text inside closed tabs, accordions or hidden boxes may be thrown away by AI tools.",
                          "Put your most important answers in plain view."))
        if p["prices_only_in_code"]:
            out.append(_f(FIX, "Page", "Some prices are only in hidden code.",
                          f"These prices are in the page's structured data but not in its text: "
                          f"{', '.join(p['prices_only_in_code'][:5])}. In one test, no AI tool found a price "
                          "that only lived there.",
                          "Show the price in the page text too."))
        elif not p["prices"]:
            out.append(_f(CHECK, "Page", "No prices found in the page text.",
                          "AI tools pick pages with clear prices more often.",
                          "If you sell something, show a price or a price range in plain text."))
        else:
            out.append(_f(OK, "Page", f"Prices are in the text ({len(p['prices'])} found)."))
        if not p["has_updated_label"] and not p["dates"]:
            out.append(_f(CHECK, "Page", "No visible date.",
                          "AI tools favor text that looks recent.",
                          "Show a real 'Last updated' date. Change it only when the content really changes."))
        if not p["h1"]:
            out.append(_f(CHECK, "Page", "The page has no main heading (H1).",
                          "", "Add one H1 that names what the page is about."))
        if len(p["h2"]) >= 3 and p["question_headings"] == 0:
            out.append(_f(CHECK, "Page", "None of the section headings is a question.",
                          "AI tools match sections to the questions people ask.",
                          "Write some headings the way a customer would ask, like 'How much does X cost?'"))

    # --- llms.txt ---
    kind = res["llms_txt"]["kind"]
    if kind == "robots-syntax":
        out.append(_f(CHECK, "llms.txt", "Your llms.txt is written like a robots.txt.",
                      "The llms.txt idea describes a short Markdown list of your pages. "
                      "Crawlers have no reason to follow rules written there.",
                      "Put crawler rules in robots.txt. llms.txt is optional."))
    elif kind == "none":
        out.append(_f(OK, "llms.txt", "You have no llms.txt.",
                      "That's fine. Studies have found no effect on AI citations."))
    else:
        out.append(_f(OK, "llms.txt", "You have an llms.txt.", "Fine to keep. Don't expect it to change much."))
    return out


def build_prompt(res: dict, max_words: int = 6000) -> str:
    """A prompt anyone can paste into an AI chat to review the page's facts."""
    p = res.get("page") or {}
    words = (p.get("text") or "").split()
    text = " ".join(words[:max_words])
    cut = " (cut short)" if len(words) > max_words else ""
    return f"""You are checking whether a web page gives an AI assistant clear facts it can quote.
Use only the page text below. Do not guess or add facts. Quote the page when you can.

Page: {res['url']}

Answer these questions in short bullet points:
1. What does the page sell or offer, in one sentence?
2. Does it state a price or a price range? Quote it, or say "missing".
3. Does it say what is included? Quote it, or say "missing".
4. Does it say who it is for, and who it is not for? Quote it, or say "missing".
5. Does it say how long it takes, or when it is available? Quote it, or say "missing".
6. Does it say what can go wrong or what the limits are? Quote it, or say "missing".
7. Does it show a date, like "Last updated"? Quote it, or say "missing".
8. Which claims are vague, like "best", "leading" or "high quality", with no number behind them?
9. Write five questions a customer might ask before buying that this page does not answer.
10. Suggest five section headings written as customer questions.

Page text{cut}:
---
{text}
---"""
