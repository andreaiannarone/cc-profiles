# Profile by folder

With **profile by folder** on, typing `claude` in a terminal starts Claude Code in the profile of the folder you are in: `claude` in `~/code/work/api` opens your Work profile, in `~/code/personal/blog` the default one. You no longer need to remember `claude-work`.

The profile comes from the same [rules](../concepts.md#rules) the Projects tab uses to say which profile a project belongs to, so the two always agree.

## Turn it on

In the **Profiles** tab, the **Profile by folder** section has a switch: **Pick the profile from the folder when I run claude**. The confirmation shows the exact line and file:

```sh
command -v cc-profiles >/dev/null 2>&1 && eval "$(cc-profiles shell-init zsh)"  # cc-profiles: profile by folder
```

- With zsh, the line goes at the end of `~/.zshrc` (created if it does not exist).
- With bash, it goes at the end of `~/.bashrc` and `~/.bash_profile`, the ones that exist (with neither, `~/.bash_profile` on macOS and `~/.bashrc` on Linux).
- Other shells are not supported: the switch says so.

The files are backed up first, so the change shows up in the [Backups](backups.md) tab and **Restore** undoes it. Turning it on twice adds nothing. Open a new terminal to use it.

Turning the switch off removes only the lines ending in `# cc-profiles: profile by folder`, and nothing else in the file.

You can also add the line yourself, in any startup file you like: the switch then shows it as on.

## Which profile `claude` picks

| The folder you are in | `claude` starts in |
|---|---|
| matches a rule for a profile, e.g. `code/work` → Work | that profile (`CLAUDE_CONFIG_DIR=~/.claude-work`) |
| matches a rule for the default profile (`~/.claude`) | the default profile, with `CLAUDE_CONFIG_DIR` left unset |
| matches a `shared` rule (your home folder, temporary folders) | the default profile |
| matches no rule | the default profile |

Subfolders count: a rule `code/work` covers `~/code/work/api/src` too, because rules match any path that contains their text. Rules are checked in the same order as in the Projects tab: exact rules first, then the first matching rule wins. Rules you add with **Assign…** go to the top, so to give `code/work/client` its own profile while `code/work` stays Work, add the `code/work/client` rule after the other one.

`claude` keeps working as before when:

- you set `CLAUDE_CONFIG_DIR` yourself (`CLAUDE_CONFIG_DIR=~/.claude-x claude`): your value always wins;
- you use a profile's own command, such as `claude-work`;
- cc-profiles is not installed or not in `PATH`: the function runs plain `claude`.

The section also lists your rules as *folder → profile*, and **Try a folder** shows which profile `claude` would pick for any path, without changing anything.

## From the terminal

```sh
cc-profiles which                 # the profile for the current folder: Work
cc-profiles which ~/code/blog     # for another folder
cc-profiles which --dir           # its config folder: /Users/you/.claude-work
cc-profiles shell-init zsh        # the claude function the line loads
```

`cc-profiles which` prints nothing and exits with status 1 when no rule matches or the rule says `shared`. It only reads `~/.cc-profiles/config.json`, never writes, and starts in about 50 ms because it does not load the server: it runs every time you start `claude`.

The function `shell-init` prints is short:

```sh
function claude {
  if [ -z "${CLAUDE_CONFIG_DIR:-}" ] && command -v cc-profiles >/dev/null 2>&1; then
    local __ccp_dir
    __ccp_dir="$(cc-profiles which --dir 2>/dev/null)"
    if [ -n "$__ccp_dir" ] && [ "$__ccp_dir" != "${HOME%/}/.claude" ]; then
      CLAUDE_CONFIG_DIR="$__ccp_dir" command claude "$@"
      return
    fi
  fi
  command claude "$@"
}
```

The default profile keeps `CLAUDE_CONFIG_DIR` unset on purpose: when it is set, Claude Code reads its settings from `<folder>/.claude.json` instead of `~/.claude.json`.

To stop using it in the current terminal without turning it off: `unset -f claude`.
