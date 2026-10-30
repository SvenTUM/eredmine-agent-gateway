# eredmine-agent-gateway

`eredmine-agent-gateway` gives automation scripts and AI agents **read-only** access to Easy8 (Easy Redmine). Every request uses the personal API key of the calling user, so Easy8's access rights always apply. Write requests are blocked unless `ERAG_ALLOW_WRITE=true` is set.

## Entry Points

- **Agent tools** (`whoami`, `list_projects`, `search_issues`, `get_issue`, `get_issue_history`, `list_time_entries`, `project_summary`) with compact, token-efficient JSON output.
- **Local MCP server** for Claude Code, opencode and Antigravity (`agy`): `erag mcp` (optional extra `mcp`).
- **Open WebUI workspace tool** for self-hosted LLMs: see [docs/open_webui_tool.adoc](docs/open_webui_tool.adoc).
- **CLI** `erag` and the **Python API** `Easy8Manager`.

## Quick Start

The package contains no installation-specific values. Put the address of your Easy8 server, and if needed its closed statuses and priorities, into `~/.erag/config.ini` (see [Configuration](docs/user_manual.adoc#configuration)):

```ini
[easy8]
base_url = https://easy8.example.com
```

Then:

```bash
pip install "eredmine-agent-gateway @ git+https://github.com/SvenTUM/eredmine-agent-gateway@v4.0.0"
export REDMINE_API_KEY=<your-personal-key>
erag whoami
erag issues --assigned-to me
```

Run the MCP server without installation:

```bash
uvx --from "eredmine-agent-gateway[mcp] @ git+https://github.com/SvenTUM/eredmine-agent-gateway@v4.0.0" erag mcp
```

## Public API

- `from eredmine_agent_gateway.manager import Easy8Manager`
- `from eredmine_agent_gateway.tools import Easy8Tools` (Read-only agent tools, identical output to MCP and CLI)
- `from eredmine_agent_gateway.db import Easy8DB` (Local, per-user SQLite cache)
- `from eredmine_agent_gateway.sync import sync_project` (Incremental synchronization into the local cache)
- `from eredmine_agent_gateway.reporting import generate_base_report` (Deterministic Markdown report from the local cache)
- `from eredmine_agent_gateway.stats import compute_project_stats, format_stats_text, format_stats_json` (Offline project statistics)
- `from eredmine_agent_gateway.summary import generate_summary` (Live Markdown project summary with warnings)

## Documentation

See the [user manual](docs/user_manual.adoc) for configuration, the tool reference and MCP setup per harness.

## Security

Please report vulnerabilities privately as described in [SECURITY.md](SECURITY.md), not in public issues.

## License

Copyright (C) 2026 Sven van Crombrugge

This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version. See [LICENSE](LICENSE) for details.

## Trademarks

This is an independent project. It is not affiliated with or endorsed by Easy Software or the Redmine project. Easy8, Easy Redmine and Redmine are trademarks of their respective owners.
