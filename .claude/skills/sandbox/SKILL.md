---
name: sandbox
description: Start cc-profiles on a fake home with sample profiles, projects and memories, to try the UI or a change without touching the real Claude Code profiles. Use when asked to run, try, demo or check the app by hand.
---
# Run cc-profiles on a sandbox

The app writes into Claude Code's own files, so it never runs on the real home folder (see CLAUDE.md; the `sandbox_guard.py` hook enforces it). This skill builds a fake home and starts the app on it.

1. Build the fake home. It prints its path:

   ```sh
   .venv/bin/python .claude/skills/sandbox/make_home.py
   ```

   It holds three profiles (Default, Work, Client), skills and MCP servers, projects with conversations, memories and prompt history, one project in two profiles, and one whose folder was moved, so every tab has something to show. Pass a folder as argument to build it there instead of a new temporary one.

2. Start the app on it, in the background, on port 4799 (4777 is the user's real instance):

   ```sh
   HOME="<path from step 1>" .venv/bin/cc-profiles open --port 4799
   ```

   Add `--no-browser` when you only need the API, for example to check a change with `curl`. API calls need the token: read it from the page (`const TOKEN = "…"`) and send it as `X-Token`, with `Host: 127.0.0.1:4799`.

   Health shows *Not logged in* for every profile: expected, a sandbox has no credentials.

3. Tell the user the URL, the sandbox path and the `kill <pid>` command that `open` printed. When they are done, stop the server with it. The sandbox is a temporary folder: delete it, or keep it to try again later by repeating step 2 with the same path.

To start from a clean sandbox after a change to `server.py`, stop the server, build a new home and start again: the running server does not reload code.
