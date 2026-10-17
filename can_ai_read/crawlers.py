"""The visitors the checker pretends to be, and the crawler names it looks for in robots.txt.

Each crawler's user agent carries the crawler's name token (for example "GPTBot"). Firewalls and
security plugins usually match on that token. The full strings follow the patterns the companies
publish; check the links for the current versions.
"""

from __future__ import annotations

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
)

# kind:
#   "browser"     the control: a normal visitor
#   "ai-search"   builds an AI company's search index; blocking it removes you from that AI's answers
#   "ai-user"     fetches a page when a person asks the AI about it; blocking it has the same effect
#   "ai-training" collects pages to train AI models; blocking it does not remove you from AI answers
#   "search"      the control: Google's and Bing's search crawlers
AGENTS = [
    {
        "name": "Browser",
        "company": "",
        "kind": "browser",
        "use": "A normal visitor (the control)",
        "ua": BROWSER_UA,
    },
    {
        "name": "OAI-SearchBot",
        "company": "OpenAI",
        "kind": "ai-search",
        "use": "Finds pages for ChatGPT search answers",
        "ua": "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; OAI-SearchBot/1.3; +https://openai.com/searchbot",
        "docs": "https://developers.openai.com/api/docs/bots",
    },
    {
        "name": "ChatGPT-User",
        "company": "OpenAI",
        "kind": "ai-user",
        "use": "Opens a page when a ChatGPT user asks about it",
        "ua": "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; ChatGPT-User/1.0; +https://openai.com/bot",
        "docs": "https://developers.openai.com/api/docs/bots",
    },
    {
        "name": "GPTBot",
        "company": "OpenAI",
        "kind": "ai-training",
        "use": "Collects pages that may be used to train OpenAI models",
        "ua": "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; GPTBot/1.3; +https://openai.com/gptbot)",
        "docs": "https://developers.openai.com/api/docs/bots",
    },
    {
        "name": "Claude-SearchBot",
        "company": "Anthropic",
        "kind": "ai-search",
        "use": "Finds pages for Claude's search answers",
        "ua": "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; Claude-SearchBot/1.0; +https://www.anthropic.com)",
        "docs": "https://support.claude.com/",
    },
    {
        "name": "Claude-User",
        "company": "Anthropic",
        "kind": "ai-user",
        "use": "Opens a page when a Claude user asks about it",
        "ua": "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; Claude-User/1.0; +https://www.anthropic.com)",
        "docs": "https://support.claude.com/",
    },
    {
        "name": "ClaudeBot",
        "company": "Anthropic",
        "kind": "ai-training",
        "use": "Collects pages that may be used to train Claude",
        "ua": "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; ClaudeBot/1.0; +claudebot@anthropic.com)",
        "docs": "https://support.claude.com/",
    },
    {
        "name": "PerplexityBot",
        "company": "Perplexity",
        "kind": "ai-search",
        "use": "Finds pages for Perplexity answers",
        "ua": "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; PerplexityBot/1.0; +https://perplexity.ai/perplexitybot)",
        "docs": "https://docs.perplexity.ai/guides/bots",
    },
    {
        "name": "Perplexity-User",
        "company": "Perplexity",
        "kind": "ai-user",
        "use": "Opens a page when a Perplexity user asks about it",
        "ua": "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; Perplexity-User/1.0; +https://perplexity.ai/perplexity-user)",
        "docs": "https://docs.perplexity.ai/guides/bots",
    },
    {
        "name": "Googlebot",
        "company": "Google",
        "kind": "search",
        "use": "Google Search, AI Overviews and AI Mode (the control)",
        "ua": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    },
    {
        "name": "Bingbot",
        "company": "Microsoft",
        "kind": "search",
        "use": "Bing and Microsoft Copilot answers (the control)",
        "ua": "Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)",
    },
]

# Names that only matter in robots.txt: they never visit as themselves.
ROBOTS_ONLY = [
    {
        "name": "Google-Extended",
        "company": "Google",
        "kind": "ai-training",
        "use": "A robots.txt switch for Gemini training and grounding; not a separate visitor",
    },
    {
        "name": "Applebot-Extended",
        "company": "Apple",
        "kind": "ai-training",
        "use": "A robots.txt switch for Apple AI training; not a separate visitor",
    },
    {
        "name": "CCBot",
        "company": "Common Crawl",
        "kind": "ai-training",
        "use": "An open web archive many AI models are trained on",
    },
]

KIND_LABEL = {
    "browser": "Normal visitor",
    "ai-search": "AI search",
    "ai-user": "AI, on a user's request",
    "ai-training": "AI training",
    "search": "Search engine",
}


def agent(name: str) -> dict:
    for a in AGENTS:
        if a["name"] == name:
            return a
    raise KeyError(name)
