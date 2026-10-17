import unittest

from can_ai_read import page, robots
from can_ai_read.fetch import Blocked, Policy


class RobotsTest(unittest.TestCase):
    def test_specific_group_beats_star(self):
        p = robots.parse("User-agent: *\nDisallow: /\n\nUser-agent: GPTBot\nAllow: /\n")
        self.assertTrue(robots.allowed(p, "GPTBot", "/x")["allowed"])
        self.assertFalse(robots.allowed(p, "ClaudeBot", "/x")["allowed"])

    def test_case_insensitive_and_version(self):
        p = robots.parse("User-agent: gptbot/1.2\nDisallow: /\n")
        self.assertFalse(robots.allowed(p, "GPTBot", "/")["allowed"])
        self.assertTrue(robots.names(p, "GPTBot"))

    def test_longest_match_and_tie(self):
        p = robots.parse("User-agent: *\nDisallow: /a\nAllow: /a/b\nDisallow: /c\nAllow: /c\n")
        self.assertTrue(robots.allowed(p, "X", "/a/b/1")["allowed"])
        self.assertFalse(robots.allowed(p, "X", "/a/z")["allowed"])
        self.assertTrue(robots.allowed(p, "X", "/c")["allowed"])

    def test_wildcards(self):
        p = robots.parse("User-agent: *\nDisallow: /*.pdf$\nDisallow: /private*/x\n")
        self.assertFalse(robots.allowed(p, "X", "/files/a.pdf")["allowed"])
        self.assertTrue(robots.allowed(p, "X", "/files/a.pdf?x=1")["allowed"])
        self.assertFalse(robots.allowed(p, "X", "/private-area/x")["allowed"])

    def test_empty_disallow_and_grouped_agents(self):
        p = robots.parse("User-agent: GPTBot\nUser-agent: ClaudeBot\nDisallow:\n\nSitemap: https://e.com/s.xml\n")
        self.assertTrue(robots.allowed(p, "ClaudeBot", "/")["allowed"])
        self.assertEqual(p["sitemaps"], ["https://e.com/s.xml"])

    def test_no_file_rules(self):
        self.assertTrue(robots.allowed(robots.parse(""), "GPTBot", "/")["allowed"])


class PageTest(unittest.TestCase):
    HTML = """<html lang="en"><head><title>Dental implants | Clinic</title>
    <meta name="description" content="Prices and steps.">
    <script type="application/ld+json">{"@type":"Product","dateModified":"2026-10-01",
      "offers":{"@type":"Offer","price":"4900","priceCurrency":"USD"}}</script>
    <script>var x = 1;</script><style>.a{}</style></head>
    <body><h1>Dental implants in Naperville</h1>
    <h2>How much do implants cost?</h2><p>A single implant costs $3,200 to $4,500. Last updated October 1, 2026.</p>
    <div hidden><p>secret words here that crawlers may drop</p></div>
    <div style="display: none">more hidden</div>
    <table><tr><th>Item</th><th>Price</th></tr><tr><td>Crown</td><td>1 200 kr</td></tr></table>
    <noscript>Enable JavaScript</noscript></body></html>"""

    def test_read(self):
        r = page.read(self.HTML)
        self.assertEqual(r["title"], "Dental implants | Clinic")
        self.assertEqual(r["h1"], ["Dental implants in Naperville"])
        self.assertEqual(r["question_headings"], 1)
        self.assertIn("$3,200", r["prices"])
        self.assertTrue(any("kr" in p for p in r["prices"]))
        self.assertTrue(r["has_updated_label"])
        self.assertEqual(r["tables_with_headers"], 1)
        self.assertGreaterEqual(r["hidden_words"], 8)
        self.assertNotIn("secret", r["text"])
        self.assertNotIn("var x", r["text"])
        self.assertEqual(r["prices_only_in_code"], ["4900"])
        self.assertFalse(r["looks_like_js_app"])

    def test_js_app(self):
        html = '<html><body><div id="root"></div>' + '<script src="/a.js"></script>' * 4 + "</body></html>"
        self.assertTrue(page.read(html)["looks_like_js_app"])

    def test_swedish_date(self):
        self.assertTrue(page.read("<p>Publicerad 17 oktober 2026</p>")["dates"])


class PolicyTest(unittest.TestCase):
    def test_blocks_private(self):
        for url in ("http://127.0.0.1/", "http://localhost:8080/", "http://10.0.0.5/", "http://169.254.169.254/latest"):
            with self.assertRaises(Blocked, msg=url):
                Policy().check_url(url)

    def test_scheme(self):
        with self.assertRaises(Blocked):
            Policy().check_url("file:///etc/passwd")

    def test_allowlist(self):
        pol = Policy(allow_private=True, allowed_domains=["example.com"])
        pol.check_url("https://www.example.com/")
        with self.assertRaises(Blocked):
            pol.check_url("https://example.com.evil.net/")

    def test_allow_private(self):
        Policy(allow_private=True).check_url("http://127.0.0.1:9/")


if __name__ == "__main__":
    unittest.main()
