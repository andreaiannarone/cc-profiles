---
description: Open the cc-profiles web UI to manage your Claude Code profiles
argument-hint: "[restart|stop]"
allowed-tools: Bash(cc-profiles open:*)
---
!`cc-profiles open $ARGUMENTS`

Tell the user, in one short line, what the output above says: the URL where cc-profiles is open; that it was restarted, and that they should reload the page; that it was stopped or was not running; or why it did not start or stop.

If the output says the action is unknown, say that this command accepts nothing, `restart` or `stop`.

If the command was not found, cc-profiles was moved or uninstalled. Say that running `cc-profiles` once in a terminal fixes this command, and that if it is not installed, one of these installs it:

```sh
pipx install cc-profiles
uv tool install cc-profiles
brew install andreaiannarone/cc-profiles/cc-profiles
```
