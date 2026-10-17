"""A small web interface for the checker.

Run it on your own computer, or let IT run it on an internal server (see DEPLOY.md). It uses only
the Python standard library, keeps results in memory for an hour, writes nothing to disk, and
sends no data anywhere except the requests to the sites being checked.
"""

from __future__ import annotations

import base64
import hmac
import json
import os
import secrets
import threading
import time
import traceback
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from . import __version__, check, report
from .fetch import Blocked, Policy

JOB_TTL = 3600
MAX_URLS = 5
MAX_BODY = 10_000

UI_CSS = report.REPORT_CSS + """
.wrap{max-width:900px;margin:0 auto;padding:28px 16px 12px}
.brand{font-size:clamp(30px,5vw,44px);line-height:1.05;font-weight:800;letter-spacing:-.01em;margin:0 0 8px}
.brand span{color:var(--accent)}
.lede{color:var(--muted);margin:0 0 20px;font-size:18px}
form{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:18px}
label{display:block;font-weight:600;margin:0 0 6px}
textarea{width:100%;min-height:92px;font:16px/1.4 ui-monospace,Menlo,monospace;padding:10px;border:1px solid var(--line);
border-radius:6px;background:var(--paper);color:var(--ink)}
.row{display:flex;flex-wrap:wrap;gap:16px;align-items:flex-end;margin-top:14px}
select{font-size:16px;padding:8px;border-radius:6px;border:1px solid var(--line);background:var(--paper);color:var(--ink)}
.consent{display:flex;gap:8px;align-items:flex-start;font-weight:400;margin-top:14px}
.consent input{margin-top:5px}
button{font:700 16px/1 system-ui,sans-serif;padding:12px 20px;border:0;border-radius:6px;background:var(--accent);color:#fff;cursor:pointer}
button:disabled{opacity:.5;cursor:default}
.hint{color:var(--muted);font-size:14px;margin:6px 0 0}
.status{margin:18px 0 0}
progress{width:100%;height:14px}
.error{background:var(--fix-bg);color:var(--fix);padding:10px 14px;border-radius:6px}
.downloads{display:flex;flex-wrap:wrap;gap:10px;max-width:900px;margin:18px auto 0;padding:0 16px}
.downloads a{display:inline-block;padding:8px 14px;border:1px solid var(--line);border-radius:6px;color:var(--ink);
text-decoration:none;background:var(--panel)}
.how{margin:28px 0 0;color:var(--muted);font-size:15px}
.how li{margin-bottom:4px}
footer{max-width:900px;margin:0 auto;padding:12px 16px 40px;color:var(--muted);font-size:14px}
"""

UI_JS = r"""
(function(){
  var form=document.getElementById('f'), out=document.getElementById('out'),
      btn=document.getElementById('go'), stat=document.getElementById('status');
  function show(msg,cls){stat.innerHTML='';var p=document.createElement('p');p.className=cls||'';p.textContent=msg;stat.appendChild(p);}
  form.addEventListener('submit',function(e){
    e.preventDefault();
    var urls=document.getElementById('urls').value.split(/\s+/).filter(Boolean);
    var runs=parseInt(document.getElementById('runs').value,10);
    if(!urls.length){show('Enter at least one web address.','error');return;}
    if(!document.getElementById('ok').checked){show('Please confirm you may test these sites.','error');return;}
    btn.disabled=true; out.innerHTML='';
    stat.innerHTML='<p id="msg">Starting…</p><progress id="bar" max="100" value="0"></progress>';
    fetch('api/check',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({urls:urls,runs:runs})})
    .then(function(r){return r.json().then(function(j){if(!r.ok)throw new Error(j.error||'Something went wrong.');return j;});})
    .then(function(j){poll(j.id);})
    .catch(function(err){btn.disabled=false;show(err.message,'error');});
  });
  function poll(id){
    fetch('api/job/'+encodeURIComponent(id)).then(function(r){return r.json();}).then(function(j){
      var bar=document.getElementById('bar'), msg=document.getElementById('msg');
      if(bar&&j.total){bar.value=Math.round(100*j.done/j.total);}
      if(msg){msg.textContent=j.message||'Working…';}
      if(j.state==='done'){
        btn.disabled=false; stat.innerHTML='';
        out.innerHTML=j.html;
        var d=document.createElement('div');d.className='downloads';
        [['report.html','Download the report'],['report.json','Download the data (JSON)'],['prompt.txt','Get an AI prompt to review the page facts']]
        .forEach(function(x){var a=document.createElement('a');a.href='job/'+encodeURIComponent(id)+'/'+x[0];a.textContent=x[1];a.setAttribute('download','');d.appendChild(a);});
        out.insertBefore(d,out.firstChild);
        out.scrollIntoView({behavior:'smooth'});
      } else if(j.state==='error'){btn.disabled=false;show(j.message,'error');}
      else {setTimeout(function(){poll(id);},1500);}
    }).catch(function(){setTimeout(function(){poll(id);},3000);});
  }
})();
"""


def _page(cfg) -> str:
    scope = (
        "This server only checks these domains: " + ", ".join(cfg["allowed_domains"]) + "."
        if cfg["allowed_domains"]
        else "This server checks public websites. It will not check private or internal addresses."
    )
    if cfg["allow_private"]:
        scope = "This server can also check private and internal addresses."
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark"><title>Can AI read my site?</title>
<link rel="stylesheet" href="static/style.css"></head><body>
<main class="wrap">
  <h1 class="brand">Can AI read <span>my site?</span></h1>
  <p class="lede">Check if ChatGPT, Claude and Perplexity can read the facts on your pages, and if your server lets their
  crawlers in. It takes about a minute per page.</p>
  <form id="f" novalidate>
    <label for="urls">Web addresses to check (one per line, up to {MAX_URLS})</label>
    <textarea id="urls" name="urls" placeholder="https://yoursite.com/&#10;https://yoursite.com/pricing" spellcheck="false" autocomplete="off"></textarea>
    <p class="hint">Start with your home page and the page that shows your prices.</p>
    <div class="row">
      <div><label for="runs">How careful?</label>
      <select id="runs" name="runs">
        <option value="1">Quick: 1 round (about 20 seconds)</option>
        <option value="3" selected>Standard: 3 rounds (about 1 minute)</option>
        <option value="5">Careful: 5 rounds (about 2 minutes)</option>
      </select></div>
      <button id="go" type="submit">Check now</button>
    </div>
    <label class="consent"><input type="checkbox" id="ok"> I own these sites or have permission to test them.</label>
  </form>
  <div id="status" class="status" aria-live="polite"></div>
</main>
<div id="out"></div>
<main class="wrap">
  <ol class="how">
    <li>It reads your robots.txt and checks what each AI crawler is allowed to see.</li>
    <li>It asks for your page several times, using the names of AI crawlers, Google, Bing and a normal browser. Then it compares the answers.</li>
    <li>It reads the page the way most AI crawlers do, without running JavaScript, and looks for prices, dates and hidden text.</li>
  </ol>
</main>
<footer>{scope} Results stay in this server's memory for one hour and are never saved. can-ai-read-my-site {__version__} ·
<a href="https://github.com/jbastide/can-ai-read-my-site">Source code</a></footer>
<script src="static/app.js"></script>
</body></html>"""


class App:
    def __init__(self, policy: Policy, max_jobs: int, where: str, user: str = "", password: str = "",
                 delay: float = 15, pause: float = 1.5):
        self.policy = policy
        self.max_jobs = max_jobs
        self.where = where
        self.user = user
        self.password = password
        self.delay = delay
        self.pause = pause
        self.jobs = {}
        self.lock = threading.Lock()

    def running(self) -> int:
        return sum(1 for j in self.jobs.values() if j["state"] == "running")

    def prune(self):
        cutoff = time.time() - JOB_TTL
        for k in [k for k, j in self.jobs.items() if j["created"] < cutoff and j["state"] != "running"]:
            del self.jobs[k]

    def start(self, urls: list, runs: int) -> str:
        job_id = secrets.token_urlsafe(16)
        job = {"state": "running", "created": time.time(), "done": 0, "total": 1, "message": "Starting…",
               "results": []}
        with self.lock:
            self.prune()
            self.jobs[job_id] = job
        threading.Thread(target=self._work, args=(job, urls, runs), daemon=True).start()
        return job_id

    def _work(self, job, urls, runs):
        try:
            per = 2 + runs * 11
            job["total"] = per * len(urls)
            for n, url in enumerate(urls):
                base = n * per

                def prog(done, total, msg, base=base, url=url):
                    job["done"] = base + done
                    job["message"] = f"{url}: {msg}"

                job["results"].append(check.run(url, runs=runs, delay=self.delay, pause=self.pause,
                                                 policy=self.policy, progress=prog, where=self.where))
            job["state"] = "done"
            job["message"] = "Done."
        except (ValueError, Blocked) as err:
            job["state"] = "error"
            job["message"] = str(err)
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            job["state"] = "error"
            job["message"] = "Something went wrong while checking. Try again, or check one address at a time."


def make_handler(app: App, cfg: dict):
    page = _page(cfg).encode()
    css = UI_CSS.encode()
    js = UI_JS.encode()
    csp = ("default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; "
           "form-action 'self'; base-uri 'none'; frame-ancestors 'none'")

    class Handler(BaseHTTPRequestHandler):
        server_version = "can-ai-read/" + __version__
        sys_version = ""

        def log_message(self, fmt, *args):  # keep logs short; never log request bodies
            print(f"{self.address_string()} {self.command} {urlsplit(self.path).path} {args[1] if len(args) > 1 else ''}")

        def _send(self, status, body: bytes, ctype: str, extra: dict = None):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Security-Policy", csp)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, status, obj):
            self._send(status, json.dumps(obj).encode(), "application/json; charset=utf-8")

        def _authorized(self) -> bool:
            if not app.user:
                return True
            header = self.headers.get("Authorization", "")
            if header.startswith("Basic "):
                try:
                    user, _, pw = base64.b64decode(header[6:]).decode().partition(":")
                except ValueError:
                    return False
                return hmac.compare_digest(user, app.user) and hmac.compare_digest(pw, app.password)
            return False

        def _deny(self):
            self._send(HTTPStatus.UNAUTHORIZED, b"Sign in to use this checker.", "text/plain; charset=utf-8",
                       {"WWW-Authenticate": 'Basic realm="Can AI read my site", charset="UTF-8"'})

        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            path = urlsplit(self.path).path
            if path == "/healthz":
                return self._send(200, b"ok", "text/plain; charset=utf-8")
            if not self._authorized():
                return self._deny()
            if path in ("/", "/index.html"):
                return self._send(200, page, "text/html; charset=utf-8")
            if path == "/static/style.css":
                return self._send(200, css, "text/css; charset=utf-8")
            if path == "/static/app.js":
                return self._send(200, js, "text/javascript; charset=utf-8")
            parts = path.strip("/").split("/")
            if len(parts) == 3 and parts[0] == "api" and parts[1] == "job":
                job = app.jobs.get(parts[2])
                if not job:
                    return self._json(404, {"state": "error", "message": "That check has expired. Run it again."})
                body = {k: job[k] for k in ("state", "done", "total", "message")}
                if job["state"] == "done":
                    body["html"] = "\n".join(report.fragment(r) for r in job["results"])
                return self._json(200, body)
            if len(parts) == 3 and parts[0] == "job":
                job = app.jobs.get(parts[1])
                if not job or job["state"] != "done":
                    return self._send(404, b"Not found or not finished.", "text/plain; charset=utf-8")
                name = parts[2]
                if name == "report.html":
                    body = "".join(report.standalone(r) for r in job["results"][:1])
                    if len(job["results"]) > 1:
                        body = ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" "
                                "content=\"width=device-width, initial-scale=1\"><title>Can AI read my site?</title>"
                                f"<style>{report.REPORT_CSS}</style></head><body>"
                                + "".join(report.fragment(r) for r in job["results"]) + "</body></html>")
                    return self._send(200, body.encode(), "text/html; charset=utf-8",
                                      {"Content-Disposition": 'attachment; filename="can-ai-read-report.html"'})
                if name == "report.json":
                    data = [{k: v for k, v in r.items()} for r in job["results"]]
                    for d in data:
                        if d.get("page"):
                            d["page"] = {k: v for k, v in d["page"].items() if k != "text"}
                    return self._send(200, json.dumps(data, indent=2).encode(), "application/json; charset=utf-8",
                                      {"Content-Disposition": 'attachment; filename="can-ai-read-report.json"'})
                if name == "prompt.txt":
                    body = "\n\n=====\n\n".join(check.build_prompt(r) for r in job["results"])
                    return self._send(200, body.encode(), "text/plain; charset=utf-8",
                                      {"Content-Disposition": 'attachment; filename="can-ai-read-prompt.txt"'})
            return self._send(404, b"Not found.", "text/plain; charset=utf-8")

        def do_POST(self):
            if not self._authorized():
                return self._deny()
            if urlsplit(self.path).path != "/api/check":
                return self._json(404, {"error": "Not found."})
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > MAX_BODY:
                return self._json(400, {"error": "The request was empty or too large."})
            try:
                data = json.loads(self.rfile.read(length))
                urls = [str(u) for u in data.get("urls", []) if str(u).strip()]
                runs = int(data.get("runs", 3))
            except (ValueError, TypeError, AttributeError):
                return self._json(400, {"error": "The request could not be read."})
            if not urls:
                return self._json(400, {"error": "Enter at least one web address."})
            if len(urls) > MAX_URLS:
                return self._json(400, {"error": f"Check up to {MAX_URLS} addresses at a time."})
            runs = max(1, min(5, runs))
            cleaned = []
            for u in urls:
                try:
                    norm = check._normalize(u)
                    app.policy.check_url(norm)
                except (ValueError, Blocked) as err:
                    return self._json(400, {"error": str(err)})
                cleaned.append(norm)
            with app.lock:
                if app.running() >= app.max_jobs:
                    return self._json(429, {"error": "The checker is busy with other checks. Try again in a minute."})
            return self._json(202, {"id": app.start(cleaned, runs)})

    return Handler


def serve(host: str = "127.0.0.1", port: int = 8080, policy: Policy = None, max_jobs: int = 2,
          where: str = "this computer", open_browser: bool = False, user: str = "", password: str = "",
          delay: float = 15, pause: float = 1.5) -> None:
    policy = policy or Policy()
    app = App(policy, max_jobs, where, user, password, delay, pause)
    cfg = {"allowed_domains": policy.allowed_domains, "allow_private": policy.allow_private}
    httpd = ThreadingHTTPServer((host, port), make_handler(app, cfg))
    httpd.daemon_threads = True
    shown = "localhost" if host in ("127.0.0.1", "0.0.0.0", "::") else host
    url = f"http://{shown}:{httpd.server_address[1]}/"
    print(f"Can AI read my site? is running at {url}")
    print("Press Ctrl+C to stop.")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        httpd.server_close()


def env_settings() -> dict:
    """Settings IT can set with environment variables (see DEPLOY.md)."""
    domains = [d.strip().lower().lstrip(".") for d in os.environ.get("CAN_AI_READ_ALLOWED_DOMAINS", "").split(",") if d.strip()]
    return {
        "allowed_domains": domains,
        "allow_private": os.environ.get("CAN_AI_READ_ALLOW_PRIVATE", "") in ("1", "true", "yes"),
        "max_jobs": int(os.environ.get("CAN_AI_READ_MAX_JOBS", "2")),
        "where": os.environ.get("CAN_AI_READ_LOCATION", ""),
        "user": os.environ.get("CAN_AI_READ_USERNAME", ""),
        "password": os.environ.get("CAN_AI_READ_PASSWORD", ""),
    }
