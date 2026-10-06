---
name: check-settings-schema
description: Check the Settings tab dropdowns (SETTING_FIELDS in settings.py) against the settings schema inside the installed Claude Code binary, report what changed and update them. Use after a Claude Code update, or when asked whether the settings options are still current.
---
# Check the settings schema

The dropdown options in `SETTING_FIELDS` (`src/cc_profiles/settings.py`) come from the settings schema compiled into the Claude Code binary. `SCHEMA_VERSION` records the version they were last checked against. Claude Code does not document this schema, so the only source is the binary itself.

## 0. Run the script first

```sh
.venv/bin/python scripts/check_settings_schema.py            # the claude on PATH
.venv/bin/python scripts/check_settings_schema.py <binary>   # or a given binary
```

It reads the binary directly and does steps 1 to 3 below for every field: enum values added or removed (inline lists, lists referenced by name, lists that spread other lists), type changes, missing keys, the `"file": "global"` fields against the `/config` panel, and `/config` items that are new or gone compared with its `CONFIG_IDS` mapping. It prints a Markdown report and exits with 0 (no differences), 1 (differences) or 2 (the binary's layout changed and the script needs updating). The same script runs every week in CI (`.github/workflows/claude-code-schema.yml`) and opens an issue when it exits with 1.

Use the manual steps below to confirm what it reports, to read the `.describe("…")` texts, when it exits with 2, or when it flags values *computed at runtime*. When you add or remove a field, or decide to leave a new `/config` item out, update `CONFIG_IDS` (and `LEFT_OUT` for schema values left out on purpose) in the script too.

## 1. Extract the strings

```sh
claude --version
B="$(readlink -f "$(which claude)")"
strings -n 6 "$B" > "$TMPDIR/claude-strings.txt"
```

If the version equals `SCHEMA_VERSION`, say so and stop, unless the user asked for a full check anyway.

## 2. Look up every field

Fields with `"file": "global"` live in `.claude.json`, not in the settings schema: check them against the `/config` panel instead (search the binary for `{id:"<id>",label:` and read its `options` and the `W(`/`B(` call that writes it). To see whether `/config` gained or lost items, list every `{id:"…",label:` after `Pe=[{id:"autoCompact"`.

For each entry in `SETTING_FIELDS`, find its schema with:

```sh
grep -o '<key>:()=>[^)]*' "$TMPDIR/claude-strings.txt" | sort -u
```

Read the result like this (the one-letter function names change between builds; the shape does not):

| In the binary | Meaning | What the field should be |
|---|---|---|
| `effortLevel:()=>j(["low","medium","high","xhigh"])` | enum, listed inline: extract it with `grep -o '<key>:()=>[A-Za-z_$]*(\[[^]]*\])'` | `select` with exactly these values |
| `editorMode:()=>j(tZr)` | enum, list defined elsewhere: find it with `grep -o '[^A-Za-z0-9_$]tZr=\[[^]]*\]'` | `select` |
| `ntt=["auto",...nZr]` | a list that includes another one: look up `nZr` the same way and join them | `select` |
| `language:()=>o().optional(` | any string | `text` (free field, optional `suggest`) |
| `prefersReducedMotion:()=>H().optional(` | boolean | `bool` |
| `cleanupPeriodDays:()=>C().int(` | number | `number` |
| `:()=>import(…)`, `model:()=>o.session.model()` | not the schema (a lazy chunk, unrelated code): ignore it and use the match that ends in `.optional(` or `.describe(` | |
| no match | the key was removed or renamed | report it; do not delete the field without asking |

The letters (`j`, `o`, `H`, `C`) are from 2.1.288 and change between builds. To learn the current ones, look up a key whose type you know, for example `language` for strings, `prefersReducedMotion` for booleans and `cleanupPeriodDays` for numbers.

Also note the `.describe("…")` text: it can tell when a key is deprecated (as happened with `includeCoAuthoredBy`).

## 3. Report

List, per field: unchanged, new values, removed values, changed type, or missing. Then ask before editing, unless the user asked you to update.

## 4. Update

- Edit `options` in `SETTING_FIELDS`. Give new values a short label in sentence case (see DESIGN.md). Never drop the user's current value: `field_options()` already keeps a current value that is not in the list, so removing an option from the list is safe.
- Set `SCHEMA_VERSION` to the checked version, and update the same version in README.md (section *Limitations*).
- Run `.venv/bin/python -m pytest`.
- If a dropdown changed, look at it on the `/sandbox` skill's fake home before calling it done.
