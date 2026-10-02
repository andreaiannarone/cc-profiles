# Showing the profile in the status line

Claude Code can run a script to draw a [status line](https://code.claude.com/docs/en/statusline) at the bottom of the terminal. With several profiles, it is useful to see which one you are in.

## The `label` command

```sh
cc-profiles label
```

prints the name of the profile in use. It reads `CLAUDE_CONFIG_DIR` (or `~/.claude` when it is not set), looks for the profile with that folder in `~/.cc-profiles/config.json`, and prints its label. If the folder is not a known profile, it prints the suffix of the folder name (`~/.claude-test` → `test`), or `default`. It does not start the server and returns immediately.

## A minimal status line

`~/.claude/statusline.sh`:

```sh
#!/bin/sh
input=$(cat)                                   # JSON that Claude Code sends on stdin
model=$(printf '%s' "$input" | jq -r '.model.display_name // empty')
profile=$(cc-profiles label 2>/dev/null)
printf '(%s) %s' "$profile" "$model"
```

and in the profile's `settings.json`:

```json
{
  "statusLine": { "type": "command", "command": "sh ~/.claude/statusline.sh" }
}
```

To use the same script in every profile, [share](guides/profiles.md#share-items) `settings.json`, or point each profile's `statusLine` to the same script. The script finds the right profile by itself, because Claude Code passes `CLAUDE_CONFIG_DIR` down to it.

## Without calling cc-profiles

The status line runs often. If you prefer not to start Python each time, read the label straight from the config with `jq`:

```sh
dir=$(cd "${CLAUDE_CONFIG_DIR:-$HOME/.claude}" && pwd -P)
profile=$(jq -r --arg d "$dir" --arg h "$HOME" \
  '.profiles[] | select((.dir | sub("^~"; $h)) == $d) | .label' \
  "$HOME/.cc-profiles/config.json" 2>/dev/null | head -1)
```
