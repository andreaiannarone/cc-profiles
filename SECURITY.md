# Security policy

cc-profiles runs a local web server that can read and write your Claude Code profiles, so security reports are taken seriously.

## Reporting a vulnerability

Please **do not open a public issue** for security problems. Use GitHub's private reporting instead: go to the repository's **Security** tab and choose **Report a vulnerability**.

Include what you found, how to reproduce it, and what an attacker could do with it. You will get an answer within a week.

## Scope

Things that matter most:

- ways for a website, or another user on the same machine, to call the local API
- path traversal: reading or writing outside the profile folders and the app's data folder
- operations that lose data without a restorable backup
- credentials leaking between profiles

## How the app protects itself

- It listens on `127.0.0.1` only.
- It accepts only requests whose `Host` header is `127.0.0.1:<port>` or `localhost:<port>`, which blocks DNS rebinding.
- Every API call requires a random token generated at startup and embedded in the page.
- No CORS headers are sent, so other origins cannot read responses.
- File and folder names coming from the browser are validated before use.
