# Frequently asked questions

Short answers to what people ask most about cc-profiles and Claude Code profiles.

## How do I use several Claude Code accounts on one computer?

Each account lives in its own Claude Code configuration folder, such as `~/.claude` and `~/.claude-work`, selected with the `CLAUDE_CONFIG_DIR` environment variable. cc-profiles finds these profiles, creates new ones with a `claude-<name>` command to start them, and shows which account each one is signed in with. See [Concepts](concepts.md) and [Profiles and sharing](guides/profiles.md).

## How do I start Claude Code in a different profile for each project?

Add folder rules in the Projects tab (for example `code/work` goes to the Work profile) and turn on Profile by folder in the Profiles tab. From then on, typing `claude` in a terminal starts Claude Code in the profile of the folder you are in. See [Profile by folder](guides/profile-by-folder.md).

## How do I move a project from one Claude Code profile to another?

In the Projects tab, pick Move on the project. cc-profiles moves its conversations, memories, file snapshots, prompt history and per-project settings, shows every file it touches first, and keeps a backup you can restore. See [Projects](guides/projects.md).

## Does cc-profiles copy my login or API keys between profiles?

No. Login credentials (`.credentials.json` and the account stored in `.claude.json`) are never copied, shared, exported or put into templates, because a copied token can stop working when the original profile refreshes it. See [Export and import](guides/export-import.md).

## Is it safe to use cc-profiles while Claude Code is running?

Yes. Every file is written atomically, so Claude Code never reads half a file, every change is backed up first, and cc-profiles warns when a session is open in a profile it is about to change. Open sessions pick up most changes when they restart. See [Architecture](architecture.md).

## Can I undo a change made with cc-profiles?

Yes. Every operation creates a backup with a journal of its steps. Restore in the Backups tab undoes it, Show changes lists what it changed, and Keep protects a backup from the automatic cleanup. See [Backups](guides/backups.md).

## Can profiles share skills, plugins or settings?

Yes. A profile can share skills, plugins, agents, commands, `CLAUDE.md` or `settings.json` with the source profile through a symbolic link, so you install or edit them once and every sharing profile sees the change. See [Profiles and sharing](guides/profiles.md).

## How can I see how many tokens each Claude Code profile uses?

The Usage tab adds up the token usage Claude Code records on every reply, per day, project, model and profile, with an estimated cost at list price and a CSV export. See [Usage](guides/usage.md).

## Can each Claude Code profile use its own GitHub account?

Yes. Every profile gets its own GitHub CLI folder (`~/.config/gh-<id>`), and Profiles → **GitHub** picks which signed-in account each one uses and the name and email of its commits, so `gh` and `git push` in a work profile use your work account. Tokens stay in the system keychain. See [A GitHub account per profile](guides/profiles.md#a-github-account-per-profile).

## How do I create and use subagents in Claude Code?

The **Agents** tab creates them per profile with a form for their description, model, tools and instructions, and copies them to other profiles. In a session, Claude uses an agent by itself when its description fits the task; you can also ask for it by name, mention it with `@`, or start a whole session as that agent with `claude --agent <name>`. See [Agents](guides/agents.md#use-an-agent-in-claude-code).

## Can I turn off claude.ai connectors in one profile only?

Yes. Connectors such as Gmail or Google Drive belong to your claude.ai account, so every profile signed in with it has them, but the MCP tab can keep any of them, or all of them, out of one profile. See [claude.ai connectors](guides/skills-and-mcp.md#claudeai-connectors).

## Does uninstalling cc-profiles delete my profiles?

No. `cc-profiles uninstall` removes only what cc-profiles added (the `/cc-profiles` command, the profile by folder line) and the app itself; your profiles, conversations, memories, settings and logins stay, and Claude Code keeps working in each of them. If something is broken, `cc-profiles reinstall` installs it again and keeps your settings and backups. See [Uninstall](uninstall.md).

## Does cc-profiles send my data anywhere?

No. It runs on your computer and listens on `127.0.0.1` only, with a token on every request. It contacts the internet only to check for its own updates on PyPI, once a day (you can turn that off in the About panel, or check only when you click), and to install Claude Code when you click. To list your claude.ai connectors it runs `claude mcp list`, so that request is Claude Code's own, with its own sign-in. See [Security](https://github.com/andreaiannarone/cc-profiles#security) in the README.

## Which systems does cc-profiles run on, and what does it cost?

macOS and Linux, and Windows through WSL 2, with Python 3.9 or later and no other dependencies. It is free and open source under the GNU GPL v3.0 or later. See [Getting started](getting-started.md).
