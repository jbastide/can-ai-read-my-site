"""Command line: `can-ai-read https://yoursite.com` or `can-ai-read serve`."""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__, check, report
from .fetch import Blocked, Policy


def _check_main(argv) -> int:
    p = argparse.ArgumentParser(
        prog="can-ai-read",
        description="Check if AI crawlers can get into a website and read its pages.",
        epilog="Start the web page instead with: can-ai-read serve",
    )
    p.add_argument("urls", nargs="+", help="one or more web addresses to check")
    p.add_argument("--runs", type=int, default=3, help="rounds of requests per page (default 3)")
    p.add_argument("--delay", type=float, default=15, help="seconds to wait between rounds (default 15)")
    p.add_argument("--quick", action="store_true", help="one round, no waiting")
    p.add_argument("--json", action="store_true", help="print the results as JSON")
    p.add_argument("--html", metavar="FILE", help="also save a report you can open in a browser")
    p.add_argument("--prompt", metavar="FILE", help="also save an AI prompt to review the page's facts")
    p.add_argument("--allow-private", action="store_true", help="allow private and internal addresses")
    p.add_argument("--no-color", action="store_true", help="plain text output")
    p.add_argument("--version", action="version", version=f"can-ai-read {__version__}")
    a = p.parse_args(argv)
    runs, delay = (1, 0) if a.quick else (max(1, min(10, a.runs)), max(0.0, a.delay))
    policy = Policy(allow_private=a.allow_private)
    color = sys.stdout.isatty() and not a.no_color and not a.json

    def progress(done, total, msg):
        if sys.stderr.isatty() and not a.json:
            sys.stderr.write(f"\r  {int(100 * done / total):3d}%  {msg[:70]:<70}")
            sys.stderr.flush()

    results = []
    for url in a.urls:
        try:
            res = check.run(url, runs=runs, delay=delay, policy=policy, progress=progress)
        except (ValueError, Blocked) as err:
            print(f"Can't check {url}: {err}", file=sys.stderr)
            return 2
        if sys.stderr.isatty() and not a.json:
            sys.stderr.write("\r" + " " * 80 + "\r")
        results.append(res)
        if not a.json:
            print(report.text(res, color=color))

    if a.json:
        out = []
        for r in results:
            r = dict(r)
            if r.get("page"):
                r["page"] = {k: v for k, v in r["page"].items() if k != "text"}
            out.append(r)
        print(json.dumps(out if len(out) > 1 else out[0], indent=2))
    if a.html:
        with open(a.html, "w", encoding="utf-8") as fh:
            fh.write(report.standalone(results[0]) if len(results) == 1 else
                     "<!doctype html><meta charset=utf-8><style>" + report.REPORT_CSS + "</style>"
                     + "".join(report.fragment(r) for r in results))
        print(f"Saved the report to {a.html}", file=sys.stderr)
    if a.prompt:
        with open(a.prompt, "w", encoding="utf-8") as fh:
            fh.write("\n\n=====\n\n".join(check.build_prompt(r) for r in results))
        print(f"Saved the AI prompt to {a.prompt}. Paste it into ChatGPT, Claude or Gemini.", file=sys.stderr)
    return 1 if any(r["summary"]["fix"] for r in results) else 0


def _serve_main(argv) -> int:
    from .server import env_settings, serve

    env = env_settings()
    p = argparse.ArgumentParser(prog="can-ai-read serve", description="Start the web page for the checker.")
    p.add_argument("--host", default="127.0.0.1", help="address to listen on (default 127.0.0.1, this computer only)")
    p.add_argument("--port", type=int, default=8080, help="port (default 8080)")
    p.add_argument("--open", action="store_true", help="open the page in your browser")
    p.add_argument("--allowed-domains", default=",".join(env["allowed_domains"]),
                   help="only allow these domains, comma-separated (also CAN_AI_READ_ALLOWED_DOMAINS)")
    p.add_argument("--allow-private", action="store_true", default=env["allow_private"],
                   help="allow private and internal addresses (also CAN_AI_READ_ALLOW_PRIVATE=1)")
    p.add_argument("--max-jobs", type=int, default=env["max_jobs"], help="checks that can run at once (default 2)")
    p.add_argument("--location", default=env["where"],
                   help="where requests come from, shown in reports (also CAN_AI_READ_LOCATION)")
    a = p.parse_args(argv)
    domains = [d.strip().lower().lstrip(".") for d in a.allowed_domains.split(",") if d.strip()]
    where = a.location or ("this computer" if a.host in ("127.0.0.1", "localhost", "::1") else "this server")
    serve(host=a.host, port=a.port, policy=Policy(allow_private=a.allow_private, allowed_domains=domains),
          max_jobs=max(1, a.max_jobs), where=where, open_browser=a.open, user=env["user"], password=env["password"])
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "serve":
        return _serve_main(argv[1:])
    if not argv:
        print("Usage: can-ai-read https://yoursite.com     (check from the command line)\n"
              "       can-ai-read serve --open             (open the web page)\n"
              "Run 'can-ai-read --help' for all options.")
        return 2
    return _check_main(argv)


if __name__ == "__main__":
    sys.exit(main())
