# Deploying "Can AI read my site?" for your team

This page is for IT teams. It explains what the app does, what it needs and how to run it safely.

## The short version

- **What it is:** a small web app. People type in a web address, and it checks whether AI crawlers can reach and read that page.
- **What it needs:** one container (or Python 3.9+), very little memory (the Compose file caps it at 256 MB), no database, no disk and no secrets.
- **Network:** inbound on one port (8080 by default). Outbound HTTP and HTTPS to the websites being checked.
- **Data:** results stay in memory for one hour. Nothing is written to disk. No analytics, no tracking, no calls home.
- **Code:** Python standard library only. No third-party packages.

## Run it

With Docker Compose, from a copy of this project:

```bash
git clone https://github.com/jbastide/can-ai-read-my-site.git
cd can-ai-read-my-site
docker compose up -d --build
```

The `compose.yaml` file already runs it read-only, with all Linux capabilities dropped and a memory limit.

Or with plain Docker:

```bash
docker build -t can-ai-read .
docker run -d --name can-ai-read -p 8080:8080 \
  --read-only --cap-drop ALL --security-opt no-new-privileges:true \
  -e CAN_AI_READ_LOCATION="our company's server" \
  can-ai-read
```

Without Docker (any server with Python 3.9 or newer):

```bash
python3 -m pip install git+https://github.com/jbastide/can-ai-read-my-site
can-ai-read serve --host 0.0.0.0 --port 8080
```

Then open `http://your-server:8080/`.

## Settings

All settings are environment variables. You don't need to set any of them.

| Variable | What it does | Default |
| --- | --- | --- |
| `CAN_AI_READ_ALLOWED_DOMAINS` | Only allow checks on these domains, comma-separated. Subdomains count. Example: `example.com,example.se` | Any public website |
| `CAN_AI_READ_MAX_JOBS` | How many checks can run at the same time. Extra requests get a "busy" message. | `2` |
| `CAN_AI_READ_LOCATION` | Shown in every report, so readers know where the test requests came from. | `this server` |
| `CAN_AI_READ_USERNAME` and `CAN_AI_READ_PASSWORD` | Turn on a simple sign-in (HTTP Basic). Use only behind HTTPS. | Off |
| `CAN_AI_READ_ALLOW_PRIVATE` | Set to `1` to allow private and internal addresses. **Leave this off** unless you need to test an internal site. | Off |

Command-line flags do the same things: `can-ai-read serve --help`.

## Security

The app fetches web pages that users ask for. Any tool like that can be misused to reach things it shouldn't (this is called server-side request forgery). These guards are on by default:

- **No internal addresses.** Before every request, and again after every redirect, the app looks up the host name. It refuses private, loopback, link-local, multicast and reserved addresses. That covers `10.x`, `172.16–31.x`, `192.168.x`, `127.x`, `169.254.x` (including cloud metadata) and their IPv6 versions.
- **Web addresses only.** Only `http` and `https`.
- **Limits.** Up to 5 addresses per check, up to 5 rounds, up to 5 redirects, and a 20-second timeout. Each answer is cut off after 5 MB.
- **Allow list.** Set `CAN_AI_READ_ALLOWED_DOMAINS` to limit checks to your own domains. This is the safest setting for a shared server.
- **Busy limit.** Only `CAN_AI_READ_MAX_JOBS` checks run at once.
- **Strict page rules.** The web page sends a strict Content-Security-Policy (no inline scripts, no outside resources), `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer` and `Cache-Control: no-store`. Everything shown in a report is escaped.
- **Small container.** The image runs as a non-root user and works with a read-only file system and all Linux capabilities dropped.

One limit to know about: a host name could resolve to a public address when checked and a private one a moment later (DNS rebinding). If that matters on your network, use the allow list, or block the container from reaching internal networks with your firewall.

## Sign-in

The app has no user accounts. Choose one of these:

1. **Best:** put it behind your company's single sign-on proxy (for example Cloudflare Access, Google IAP, Azure App Proxy, oauth2-proxy or your load balancer's built-in sign-in).
2. **Simple:** set `CAN_AI_READ_USERNAME` and `CAN_AI_READ_PASSWORD`. Use HTTPS in front of it, because Basic sign-in sends the password with every request.
3. **Internal only:** keep it on a private network or VPN.

Always put HTTPS in front of it (a reverse proxy or load balancer). The app itself serves plain HTTP.

## Where to run it

The checker sees the website the way a visitor from your server's network sees it. This matters:

- **Run it outside your own network if you can**, for example on a small cloud server. If your company's firewall trusts its own office or data center, a check from inside will say "let in" when outside crawlers are turned away.
- **Set `CAN_AI_READ_LOCATION`** to describe where it runs, for example "AWS eu-north-1". Every report prints it.

## Health check and logs

- `GET /healthz` returns `ok` with no sign-in. Use it for your load balancer or orchestrator.
- Logs go to standard output, one line per request: client address, method, path and status. The web addresses people check are sent in the request body, so they are not logged.

## Updating

```bash
git pull
docker compose up -d --build
```

Crawler names and user agents change now and then. They live in `can_ai_read/crawlers.py`.

## What it sends to the sites it checks

For each address: one request for `robots.txt`, one for `llms.txt`, and 11 requests for the page per round (a browser, nine AI crawler names, Googlebot and Bingbot). Three rounds by default, so about 35 requests over a minute or two. The requests are spaced out and in a random order. No cookies are sent.

Only check sites you own or have permission to test.
