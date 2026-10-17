"""Turn a result into text for the terminal or a standalone HTML report."""

from __future__ import annotations

import html
import textwrap

from .check import CHECK, FIX, OK

LABEL = {FIX: "FIX", CHECK: "CHECK", OK: "OK"}
CAVEAT = (
    "These tests ran from {where}, not from OpenAI's, Anthropic's or Perplexity's own servers. "
    "A site can treat the real crawlers differently. Only your server logs show what they really got."
)


def text(res: dict, color: bool = False) -> str:
    def c(code, s):
        return f"\033[{code}m{s}\033[0m" if color else s

    tint = {FIX: "31;1", CHECK: "33;1", OK: "32;1"}
    lines = [
        "",
        c("1", f"Can AI read {res['url']}?"),
        res["headline"],
        f"Fix: {res['summary'][FIX]}   Check: {res['summary'][CHECK]}   OK: {res['summary'][OK]}",
        "",
    ]
    order = {FIX: 0, CHECK: 1, OK: 2}
    for f in sorted(res["findings"], key=lambda f: order[f["level"]]):
        tag = c(tint[f["level"]], f"[{LABEL[f['level']]}]".ljust(8))
        lines.append(f"{tag}{f['area']}: {f['title']}")
        for part in (f.get("detail"), ("What to do: " + f["fix"]) if f.get("fix") else ""):
            if part:
                lines.extend(textwrap.wrap(part, 92, initial_indent=" " * 8, subsequent_indent=" " * 8))
        lines.append("")

    lines.append(c("1", "What each name got"))
    lines.append(f"  {'Name':<18}{'Kind':<26}{'Answers':<24}Result")
    for a in res["server"]["agents"]:
        codes = " ".join(str(s) for s in a["statuses"])
        lines.append(f"  {a['name']:<18}{a['kind_label']:<26}{codes:<24}{a['verdict']}")
    lines.append("")
    lines.extend(textwrap.wrap(CAVEAT.format(where=res["where"]), 100))
    lines.append("")
    return "\n".join(lines)


def _e(s) -> str:
    return html.escape(str(s if s is not None else ""), quote=True)


def fragment(res: dict) -> str:
    """The report body, used inside the web app and inside the standalone file."""
    order = {FIX: 0, CHECK: 1, OK: 2}
    s = res["summary"]
    out = [
        f'<section class="report" aria-labelledby="r-h">',
        f'<h2 id="r-h">Can AI read <span class="url">{_e(res["url"])}</span>?</h2>',
        f'<p class="headline">{_e(res["headline"])}</p>',
        '<ul class="tally">'
        f'<li class="fix"><b>{s[FIX]}</b> to fix</li>'
        f'<li class="check"><b>{s[CHECK]}</b> to check</li>'
        f'<li class="ok"><b>{s[OK]}</b> OK</li></ul>',
        '<h3>What we found</h3><ol class="findings">',
    ]
    for f in sorted(res["findings"], key=lambda f: order[f["level"]]):
        out.append(
            f'<li class="{f["level"]}"><span class="badge">{LABEL[f["level"]]}</span>'
            f'<div><p class="ftitle"><span class="area">{_e(f["area"])}</span> {_e(f["title"])}</p>'
            + (f'<p>{_e(f["detail"])}</p>' if f.get("detail") else "")
            + (f'<p class="todo"><b>What to do:</b> {_e(f["fix"])}</p>' if f.get("fix") else "")
            + "</div></li>"
        )
    out.append("</ol>")

    out.append('<h3>What each name got from your server</h3>')
    out.append('<div class="tablewrap"><table><thead><tr><th scope="col">Name</th><th scope="col">Company</th>'
               '<th scope="col">What it does</th><th scope="col">Answers</th><th scope="col">Result</th></tr></thead><tbody>')
    for a in res["server"]["agents"]:
        codes = " ".join(_e(x) for x in a["statuses"])
        out.append(f'<tr><th scope="row">{_e(a["name"])}</th><td>{_e(a["company"])}</td><td>{_e(a["use"])}</td>'
                   f'<td class="codes">{codes}</td><td class="v-{_e(a["verdict"])}">{_e(a["verdict"])}</td></tr>')
    out.append("</tbody></table></div>")
    out.append('<p class="note">200 means the page was sent. 403 means "forbidden". 429 means "too many requests". '
               '"challenge" means a bot check page was sent instead of the real page.</p>')

    rb = res["robots"]
    out.append("<h3>What your robots.txt says</h3>")
    if not rb.get("found"):
        out.append(f'<p>No robots.txt was found (answer: {_e(rb.get("status") or rb.get("error"))}). Every crawler is allowed.</p>')
    else:
        out.append('<div class="tablewrap"><table><thead><tr><th scope="col">Name</th><th scope="col">Named in the file?</th>'
                   '<th scope="col">Allowed on this page?</th><th scope="col">Rule that decides</th></tr></thead><tbody>')
        for a in rb["agents"]:
            out.append(f'<tr><th scope="row">{_e(a["name"])}</th><td>{"Yes" if a["named"] else "No"}</td>'
                       f'<td class="v-{"served" if a["allowed"] else "refused"}">{"Yes" if a["allowed"] else "No"}</td>'
                       f'<td><code>{_e(a["rule"] or "none")}</code></td></tr>')
        out.append("</tbody></table></div>")

    p = res.get("page")
    if p:
        out.append("<h3>What a crawler sees on the page</h3><dl class=\"facts\">")
        rows = [
            ("Title", p["title"] or "missing"),
            ("Main heading (H1)", "; ".join(p["h1"]) or "missing"),
            ("Words readable without JavaScript", p["words"]),
            ("Hidden words", p["hidden_words"]),
            ("Prices in the text", ", ".join(p["prices"][:8]) or "none found"),
            ("Dates in the text", ", ".join(p["dates"][:6]) or "none found"),
            ("Section headings that are questions", f'{p["question_headings"]} of {len(p["h2"])}'),
            ("Tables with header cells", f'{p["tables_with_headers"]} of {p["tables"]}'),
            ("Scripts on the page", p["scripts"]),
        ]
        for k, v in rows:
            out.append(f"<dt>{_e(k)}</dt><dd>{_e(v)}</dd>")
        out.append("</dl>")
    out.append(f'<p class="caveat">{_e(CAVEAT.format(where=res["where"]))}</p>')
    out.append(f'<p class="meta">Checked {_e(res["checked_at"])} with can-ai-read-my-site {_e(res["version"])}.</p>')
    out.append("</section>")
    return "\n".join(out)


REPORT_CSS = """
:root{--ink:#16130f;--muted:#5f5850;--paper:#fbf8f2;--panel:#fff;--line:#d9d2c6;--accent:#e2571c;
--fix:#b3261e;--fix-bg:#fbe9e7;--check:#8a5a00;--check-bg:#fdf3dc;--ok:#2f6b3a;--ok-bg:#e6f2e6}
@media (prefers-color-scheme:dark){:root{--ink:#f1ece4;--muted:#b7aea2;--paper:#171411;--panel:#211d19;
--line:#3a342e;--fix:#ff8a80;--fix-bg:#3a1d1a;--check:#f2c35b;--check-bg:#352a12;--ok:#8fd19a;--ok-bg:#16301b}}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font:17px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}
.report{max-width:900px;margin:0 auto;padding:28px 16px 48px}
h2{font-size:clamp(24px,4vw,32px);line-height:1.15;margin:0 0 8px}
h2 .url{word-break:break-all;color:var(--accent)}
h3{margin:32px 0 10px;font-size:20px}
.headline{font-size:19px;margin:0 0 14px}
.tally{display:flex;flex-wrap:wrap;gap:10px;list-style:none;padding:0;margin:0}
.tally li{padding:8px 14px;border-radius:6px;font-weight:600}
.tally b{font-size:22px;margin-right:4px}
.tally .fix,.findings .fix .badge{background:var(--fix-bg);color:var(--fix)}
.tally .check,.findings .check .badge{background:var(--check-bg);color:var(--check)}
.tally .ok,.findings .ok .badge{background:var(--ok-bg);color:var(--ok)}
.findings{list-style:none;padding:0;margin:0;display:grid;gap:10px}
.findings li{display:flex;gap:12px;background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:12px 14px}
.findings p{margin:0 0 4px}
.badge{flex:0 0 auto;align-self:flex-start;font-weight:700;font-size:13px;letter-spacing:.06em;padding:3px 8px;border-radius:4px}
.ftitle{font-weight:600}
.area{color:var(--muted);font-weight:500}
.todo b{color:var(--ink)}
.tablewrap{overflow-x:auto;border:1px solid var(--line);border-radius:8px;background:var(--panel)}
table{border-collapse:collapse;width:100%;min-width:560px;font-size:15px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}
thead th{font-size:13px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted)}
.codes{font-family:ui-monospace,Menlo,monospace;white-space:nowrap}
.v-served{color:var(--ok);font-weight:600}.v-refused{color:var(--fix);font-weight:600}
.v-mixed,.v-error{color:var(--check);font-weight:600}
.facts{display:grid;grid-template-columns:minmax(160px,1fr) 2fr;gap:6px 16px;margin:0}
.facts dt{color:var(--muted)}.facts dd{margin:0;word-break:break-word}
@media (max-width:560px){.facts{grid-template-columns:1fr}.facts dd{margin-bottom:8px}}
.note,.caveat,.meta{color:var(--muted);font-size:15px}
.caveat{border-left:4px solid var(--accent);padding:8px 12px;background:var(--panel);margin-top:28px}
code{font-family:ui-monospace,Menlo,monospace;font-size:14px}
"""


def standalone(res: dict) -> str:
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<meta name=\"color-scheme\" content=\"light dark\">"
        f"<title>Can AI read {_e(res['url'])}?</title><style>{REPORT_CSS}</style></head><body>"
        f"{fragment(res)}</body></html>"
    )
