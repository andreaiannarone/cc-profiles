---
description: Open the cc-profiles web UI to manage your Claude Code profiles
argument-hint: "[restart|stop]"
---
Run `cc-profiles open $ARGUMENTS` with the Bash tool, nothing else, and wait for it to finish.

Then tell the user, in one short line, what its output says: the URL where cc-profiles is open; that it was restarted, and that they should reload the page; that it was stopped or was not running; or why it did not start or stop.

If the output says the action is unknown, say that this command accepts nothing, `restart` or `stop`.

If the command was not found, the cc-profiles app is not installed, or not in the PATH Claude Code was started with. Say that this command only opens the app, and that one of these installs it (then restart Claude Code):

```sh
pipx install cc-profiles
uv tool install cc-profiles
brew install andreaiannarone/cc-profiles/cc-profiles
```
