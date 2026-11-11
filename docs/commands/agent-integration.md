# `noesis hook` and `noesis integrate`

Connect noesis to an agent. Flows: [hook](../workflows/hook-claude-code.md),
[integrate](../workflows/integrate-claude-code.md).

| Command | Does |
|---|---|
| `hook claude-code` | Handle one Claude Code hook event (PostToolUse `git commit`, Stop, SessionEnd). Reads the hook JSON on stdin, prints nothing, always exits 0. Run by Claude Code, never by hand. |
| `integrate claude-code install` | Add the noesis hooks (PostToolUse `git commit`, Stop, SessionEnd) to Claude Code's settings; other hooks are kept. Previews first, writes with `--yes`. |
| `integrate claude-code uninstall` | Remove every noesis hook; other hooks are kept. Previews first, writes with `--yes`. |
| `integrate claude-code status` | Show which noesis hooks are registered. |
