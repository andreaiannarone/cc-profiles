# Product
<!-- impeccable:product-schema 1 -->

Drafted from the repository (README, DESIGN.md, CLAUDE.md, the docs) and from the maintainer's requests while building it, without an interview: lines marked *(inferred)* are hypotheses to confirm or correct.

## Platform

web

A local page served by the app on `127.0.0.1`, opened in a browser or in the Mac app's window (a WKWebView around the same page, with a menu bar icon and macOS notifications). It must also work at phone width.

## Users

Developers who use Claude Code with more than one account or setup on the same computer: typically a personal and a work claude.ai account, sometimes a client's, each in its own profile folder (`~/.claude`, `~/.claude-<id>`) selected with `CLAUDE_CONFIG_DIR`. They open cc-profiles when something needs fixing or checking: a project that ended up in the wrong profile, a folder that moved, a setting that differs between profiles, how much of the plan is left. *(inferred)* Most sessions are short and task-driven; few people keep it open all day, though the Mac app's menu bar icon is there for those who do.

The maintainer is one of these users and decides by using it daily, in Italian, while the product's interface stays in English.

## Product Purpose

Keep several Claude Code profiles in order without editing Claude Code's undocumented files by hand: move projects, memories and conversations between profiles, relink projects whose folder moved, edit memories, settings, skills, agents and MCP servers, share items across profiles, create, import and delete profiles, and see each account's plan limits and usage. Success is a change made in a few clicks that Claude Code picks up at its next session, and that can always be undone.

## Positioning

It edits Claude Code's own files, possibly while a session uses them, and every change is reversible: each operation journals its steps in a backup that one **Restore** undoes. It reads Claude Code's formats as they are on disk, follows Claude Code's schema for settings, and never copies or refreshes login credentials between profiles.

## Operating Context

- Runs locally: the server listens only on `127.0.0.1`, checks the `Host` header and a per-page token, and sends nothing anywhere except the update check (PyPI), the plan limits (claude.ai, with the profile's own sign-in, read-only) and GitHub's public API for commit identities.
- Installed with pipx, uv or Homebrew; the Mac app is optional. Works on macOS and Linux.
- Also reachable from Claude Code itself through the `/cc-profiles` command and a plugin.
- People switch between it and a terminal: paths, commands and file names are what they copy and search.

## Capabilities and Constraints

- Python standard library only, Python 3.9 compatible; the UI is vanilla JS with no build step and system fonts only, so it works offline.
- Every write is atomic and goes through a backup journal; operations run one at a time.
- Claude Code's on-disk formats are undocumented and change between versions; the settings options are checked against the installed Claude Code (`SCHEMA_VERSION`).
- Login tokens are read only by the plan limits check, never stored, sent to the page or refreshed.
- Releases happen only when the maintainer asks; versions move one step at a time.

## Brand Commitments

- Name: **cc-profiles**, lowercase. Mascot: two pixel creatures in Claude Code's orange (`docs/assets/logo.svg`), next to the title and in loading states.
- Voice: plain English, sentence case, buttons named after their action, concrete numbers, errors that say what happened and what to do (DESIGN.md, *Writing*).
- GPL-3.0-or-later, open source on GitHub, documentation at cc-profiles.andreaia.com.

## Evidence on Hand

- Screenshots and demo GIFs generated from the real app on a sandbox home (`scripts/make_screenshots.py` → `docs/assets/`), never by hand.
- The documentation site (`docs/`), the changelog and in-app release notes.
- No testimonials, user counts, benchmarks or press: future work must not invent any.

## Product Principles

1. **Undo is the safety net.** Any change to Claude Code's files can be restored, and the interface says where the backup is.
2. **Friction grows with the stakes.** One click to assign, a confirmation to move, typing the name to delete a profile; confirmations give concrete numbers.
3. **Problems before lists.** What needs attention comes first, each with the one action that fixes it.
4. **Local and quiet.** Nothing leaves the machine unless a feature needs it and says so; nothing runs on its own that the user did not turn on.
5. **Follow Claude Code, do not reinvent it.** Its names, formats and options are the vocabulary; cc-profiles adds the overview and the safety, not new concepts.

## Accessibility & Inclusion

WCAG 2.1 AA in both themes: every tab is checked with axe in the tests, light and dark. State is never told by color alone, motion respects `prefers-reduced-motion`, and the whole UI works by keyboard (shortcuts with `?`).
