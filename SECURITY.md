# Security

## Reporting a problem

If you find a security problem, please don't open a public issue. Use GitHub's private
[**Report a vulnerability**](https://github.com/jbastide/can-ai-read-my-site/security/advisories/new) form instead.
We'll reply within a week.

## What this app protects against

The web interface fetches pages that users ask for. The main risk for any app like that is server-side
request forgery: tricking the server into fetching something on an internal network. The guards, and the
one known limit, are described in [DEPLOY.md](DEPLOY.md#security).

## Supported versions

Only the latest version gets fixes.
