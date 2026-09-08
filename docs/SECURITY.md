# Security Policy

English | [中文](SECURITY.zh.md)

## Reporting a vulnerability

Use GitHub's private vulnerability reporting: open the repository's **Security** tab and choose **Report a vulnerability**. A report opens a private draft advisory visible only to the maintainer. Never file a public issue and never discuss an unfixed vulnerability in public spaces.

## What to include

- The affected gate or command (for example `hdsh pairing verify`, `hdsh policy lifecycle`).
- A reproduction: the configuration file, a minimal payload, and the environment (operating system, Python, prek, and uv versions).
- The impact you assess — what an attacker achieves, such as command execution, token disclosure, or corrupted pairing records.

## What to expect

A sole maintainer on a best-effort basis: acknowledgment within 7 days, a fix timeline that follows severity, and coordinated disclosure — the fix ships with a published GitHub Security Advisory (a CVE can be assigned), which propagates to downstream consumers through Dependabot. Reporters are credited in the advisory.

## Scope and trust boundary

The policy engine processes issue and pull-request titles, bodies, and labels inside GitHub Actions while holding `GITHUB_TOKEN` and a project-scoped token: that content is untrusted input, and the engine treats it as data only — crafted content that causes command execution or token exfiltration in those workflows is in scope. Gates running inside a consuming repository read that repository's own files as configuration; those files are the consumer's trust domain, not part of this project's threat model. Secrets exist only as repository CI secrets, and the engine never echoes token values.

## Supported versions

| Version | Supported |
|---|---|
| main branch | ✅ best-effort |

No release has been cut yet, so `main` is the only supported surface; version rows appear here when the first release is tagged.
