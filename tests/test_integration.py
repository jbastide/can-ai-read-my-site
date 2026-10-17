"""End to end: a fake site that turns away GPTBot and OAI-SearchBot, checked by the CLI engine and the web UI."""

import json
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from can_ai_read import check, report, server
from can_ai_read.fetch import Policy

PAGE = (b"<html><head><title>Fake clinic</title></head><body><h1>Fake clinic</h1>"
        + b"<p>Cleaning costs $120. Last updated October 1, 2026.</p>" + b"<p>Words here. </p>" * 120
        + b"</body></html>")
ROBOTS = b"User-agent: *\nAllow: /\n\nUser-agent: OAI-SearchBot\nAllow: /\n"


class FakeSite(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        ua = self.headers.get("User-Agent", "")
        if self.path == "/robots.txt":
            body, ctype, code = ROBOTS, "text/plain", 200
        elif self.path == "/llms.txt":
            body, ctype, code = b"not found", "text/plain", 404
        elif "GPTBot" in ua or "OAI-SearchBot" in ua:
            body, ctype, code = b"Forbidden", "text/plain", 403
        else:
            body, ctype, code = PAGE, "text/html; charset=utf-8", 200
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def start(handler):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


class IntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.site = start(FakeSite)
        cls.url = f"http://127.0.0.1:{cls.site.server_address[1]}/"

    @classmethod
    def tearDownClass(cls):
        cls.site.shutdown()

    def test_engine(self):
        res = check.run(self.url, runs=2, delay=0, pause=0, policy=Policy(allow_private=True))
        verdicts = {a["name"]: a["verdict"] for a in res["server"]["agents"]}
        self.assertEqual(verdicts["GPTBot"], "refused")
        self.assertEqual(verdicts["OAI-SearchBot"], "refused")
        self.assertEqual(verdicts["Googlebot"], "served")
        titles = [f["title"] for f in res["findings"] if f["level"] == "fix"]
        self.assertTrue(any("OAI-SearchBot" in t for t in titles), titles)
        # GPTBot is a training crawler: a "check", not a "fix"
        self.assertFalse(any("GPTBot" in t for t in titles), titles)
        fix = [f for f in res["findings"] if "OAI-SearchBot" in f["title"]][0]
        self.assertIn("robots.txt names it", fix["detail"])
        self.assertIn("$120", res["page"]["prices"])
        self.assertIn("OAI-SearchBot", report.text(res))
        self.assertIn("<table>", report.standalone(res))
        self.assertIn("Page text", check.build_prompt(res))

    def test_web_ui(self):
        ui = start(server.make_handler(server.App(Policy(allow_private=True), 2, "test", delay=0, pause=0),
                                       {"allowed_domains": [], "allow_private": True}))
        base = f"http://127.0.0.1:{ui.server_address[1]}/"
        try:
            home = urllib.request.urlopen(base).read().decode()
            self.assertIn("Can AI read", home)
            csp = urllib.request.urlopen(base).headers["Content-Security-Policy"]
            self.assertIn("script-src 'self'", csp)
            req = urllib.request.Request(base + "api/check", data=json.dumps({"urls": [self.url], "runs": 1}).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
            job = json.loads(urllib.request.urlopen(req).read())["id"]
            for _ in range(100):
                st = json.loads(urllib.request.urlopen(base + "api/job/" + job).read())
                if st["state"] != "running":
                    break
                time.sleep(0.2)
            self.assertEqual(st["state"], "done", st)
            self.assertIn("OAI-SearchBot", st["html"])
            self.assertNotIn("<script", st["html"])
            data = json.loads(urllib.request.urlopen(base + f"job/{job}/report.json").read())
            self.assertNotIn("text", data[0]["page"])
            self.assertIn("Page text", urllib.request.urlopen(base + f"job/{job}/prompt.txt").read().decode())
        finally:
            ui.shutdown()

    def test_web_ui_refuses_private_by_default(self):
        ui = start(server.make_handler(server.App(Policy(), 2, "test"), {"allowed_domains": [], "allow_private": False}))
        base = f"http://127.0.0.1:{ui.server_address[1]}/"
        try:
            req = urllib.request.Request(base + "api/check", data=json.dumps({"urls": [self.url]}).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)
            self.assertEqual(ctx.exception.code, 400)
            self.assertIn("private", json.loads(ctx.exception.read())["error"])
        finally:
            ui.shutdown()

    def test_basic_auth(self):
        ui = start(server.make_handler(server.App(Policy(), 2, "test", user="it", password="s3cret"),
                                       {"allowed_domains": [], "allow_private": False}))
        base = f"http://127.0.0.1:{ui.server_address[1]}/"
        try:
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(base)
            self.assertEqual(ctx.exception.code, 401)
            self.assertEqual(urllib.request.urlopen(base + "healthz").read(), b"ok")
        finally:
            ui.shutdown()


if __name__ == "__main__":
    unittest.main()
