# grip as an MCP server

`grip-mcp` runs grip as a stdio MCP server: any MCP client (Claude Code, Claude
Desktop, Cursor, or a custom client) can drive a real browser through it.

## Install

```bash
pip install "grip-browser[mcp]"
```

This installs the `grip-mcp` console script alongside the base `grip` package.
Optional: set `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` in the environment the
server runs in if you want the `run` tool (goal-based autonomous browsing) —
the other eleven tools don't need an LLM key.

## Claude Code

```bash
claude mcp add grip -- grip-mcp
```

Or scoped to a project, in `.mcp.json`:

```json
{
  "mcpServers": {
    "grip": {
      "command": "grip-mcp"
    }
  }
}
```

## Claude Desktop

Add to `claude_desktop_config.json` (Settings → Developer → Edit Config):

```json
{
  "mcpServers": {
    "grip": {
      "command": "grip-mcp"
    }
  }
}
```

If `grip-mcp` isn't on Claude Desktop's `PATH` (common when it's installed
into a virtualenv), point at the interpreter directly:

```json
{
  "mcpServers": {
    "grip": {
      "command": "/path/to/venv/bin/grip-mcp"
    }
  }
}
```

Restart Claude Desktop after editing the config.

## Cursor

Add to `.cursor/mcp.json` (project-local) or `~/.cursor/mcp.json` (global):

```json
{
  "mcpServers": {
    "grip": {
      "command": "grip-mcp"
    }
  }
}
```

## Passing an LLM key for the `run` tool

Any of the configs above accept an `env` block:

```json
{
  "mcpServers": {
    "grip": {
      "command": "grip-mcp",
      "env": {
        "ANTHROPIC_API_KEY": "sk-ant-..."
      }
    }
  }
}
```

## Tools

| tool | args | does |
|---|---|---|
| `open` | `url` | Open a URL in a fresh page, return its snapshot |
| `goto` | `url` | Navigate the current page to a URL |
| `snapshot` | — | Re-snapshot the current page; returns only what changed since the last snapshot the client was shown |
| `click` | `target` | Click an element by description or ref |
| `type` | `target`, `text` | Type text into an input |
| `select` | `target`, `value` | Choose an option in a `<select>` dropdown, by visible option text (preferred) or its value attribute |
| `read` | — | Read the page as citable prose blocks, boilerplate removed |
| `screenshot` | — | Capture a JPEG screenshot of the current page, base64-encoded |
| `run` | `goal`, `url` | Drive the browser toward a goal autonomously (needs an LLM key) |
| `list_tabs` | — | List open tabs (`target_id`, url, which one is active) |
| `switch_tab` | `target_id` | Make an already-open tab active for subsequent tool calls |
| `close_tab` | `target_id` (optional) | Close a tab; the active tab if `target_id` is omitted |

`open` and `run` are the only tools that don't require a prior `open` call —
every other tool operates on the page `open`/`run` left current, i.e. the
active tab. `open` opens a *new* tab and makes it active without closing any
others; use `switch_tab`/`close_tab` to manage the ones left behind.

## Session model

One browser, one *active* page, per server process — there is no
multi-session registry. `open` can leave more than one tab alive at once
(`list_tabs`/`switch_tab`/`close_tab` manage them), but there is still only
one active tab and one conversation driving it. If you need multiple
concurrent browsing sessions, run multiple `grip-mcp` processes.

*(ponytail: a session registry keyed by client-supplied IDs is a real feature,
but a speculative one — nothing here sends a session id yet. Future work if a
client that needs it shows up.)*

## Shutdown

The server closes the browser (Chrome process + its temp profile dir) when
the stdio connection closes cleanly. If the process is killed (`SIGKILL`),
nothing can run its cleanup — that's a real, separate limitation, not
something this shutdown path can catch.
