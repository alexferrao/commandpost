# CommandPost

> Remote-control Claude Code from your phone via Telegram — plan, review, and execute coding tasks from anywhere.

![Python 3.11+](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)
![MIT License](https://img.shields.io/badge/License-MIT-green.svg)
![Telegram](https://img.shields.io/badge/Telegram-Bot-2CA5E0?logo=telegram&logoColor=white)
![Claude Code](https://img.shields.io/badge/Claude-Code-7C3AED)

<!-- TODO: Record demo showing: send task via Telegram → get PDF plan → confirm → get result -->

---

## How It Works

```
📱 You (Telegram)              🖥️ Your Mac
─────────────────              ─────────────
"cc: fix the auth bug"    →   CommandPost receives task
                                Claude Code creates PLAN (no execution)
📄 PDF with plan + code   ←   Sends plan for review
"foxtrot-4097"            →   You confirm with safety code
                                Claude Code executes with permissions
📄 PDF with results       ←   Sends execution results
```

CommandPost splits every task into two phases: **plan** and **execute**. Nothing runs on your machine until you explicitly confirm.

---

## Features

- **Plan-then-execute workflow** — Claude Code proposes changes, you review before anything runs
- **Multi-project support** — switch between projects with `/projects` or `/p name`
- **Session persistence** — conversations resume where you left off per project
- **Safety confirmation codes** — NATO phonetic word + 4-digit number prevents accidental execution
- **Research mode** — `research: topic` for read-only analysis, no file modifications
- **PDF response delivery** — formatted plans and results delivered as documents in Telegram
- **Auto re-authentication** — detects expired Claude sessions and handles re-login via Telegram
- **Permission management** — `!allow command` to whitelist specific bash commands per project

---

## Quick Start

### Prerequisites

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) installed and authenticated
- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- Telegram bot token from [@BotFather](https://t.me/BotFather)
- Your Telegram user ID (get it from [@userinfobot](https://t.me/userinfobot))

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/alexferrao/commandpost.git ~/.commandpost
   ```

2. **Navigate to the directory**
   ```bash
   cd ~/.commandpost
   ```

3. **Install dependencies**
   ```bash
   uv sync
   ```

4. **Configure environment variables**
   ```bash
   cp .env.example .env
   ```

5. **Configure projects**
   ```bash
   cp projects.example.json projects.json
   ```

6. **Edit both files** with your Telegram bot token, admin user ID, and project paths

7. **Start CommandPost**
   ```bash
   ./start_watcher.sh
   ```

---

## Commands Reference

| Command | Description |
|---------|-------------|
| `cc: task description` | Send a coding task to Claude Code |
| `/projects` | Show all projects with switch buttons |
| `/p name` | Quick switch project (partial match) |
| `search: keyword` | Search transcript index |
| `research: topic` | Read-only analysis mode |
| `!allow command` | Add bash command to project allowlist |
| `yes` / confirmation code | Execute the proposed plan |
| `no` / `cancel` | Cancel pending plan |
| `/login` | Re-authenticate Claude Code |
| `/status` | Show current project and session info |
| `/help` | Show available commands |

---

## Security

> **Warning**
> This tool executes code on your machine. Treat it with the same caution you would give SSH access.

- **Restrict access.** Set `ADMIN_USER_ID` in your `.env` to restrict access to only your Telegram account. Without this, anyone who discovers your bot can run code on your machine.
- **The confirmation code system** (e.g., `foxtrot-4097`) is a guard against accidental taps, not cryptographic security. It prevents you from accidentally approving a plan with a stray tap — it does not protect against a compromised Telegram account.
- **Review every plan PDF before confirming.** The plan phase is read-only. The execute phase modifies files. Read the diff.
- **Consider running in a VM or container** for additional isolation, especially when working on unfamiliar codebases.
- **The `--dangerously-skip-permissions` flag** is used during the execute phase. This gives Claude Code full access to run bash commands and modify files without per-command approval. Understand what this means before using CommandPost.

---

## Architecture

CommandPost is a single-file Telegram bot (`watcher.py`) that polls for messages and delegates work to the Claude Code CLI.

```
Telegram ←→ watcher.py ←→ Claude Code CLI
                ↕
           state.json (session persistence)
```

- **Plan phase**: Runs `claude -p "analyze task" --output-format json` without execution permissions. Claude Code can read files but cannot modify anything.
- **Execute phase**: Runs `claude -p "execute plan" --dangerously-skip-permissions --resume session_id` with full permissions, continuing the existing conversation.
- **Session persistence**: `state.json` tracks one session per project, allowing conversations to resume across tasks.
- **PDF generation**: Plans and results are rendered as formatted PDFs via ReportLab for easy reading on mobile.

---

## Configuration

### Environment Variables (`.env`)

| Variable | Description | Required |
|----------|-------------|----------|
| `TELEGRAM_BOT_TOKEN` | Bot token from BotFather | Yes |
| `ADMIN_USER_ID` | Your Telegram user ID (restricts access) | Yes |
| `CLAUDE_PATH` | Path to Claude Code binary (default: `claude`) | No |
| `LOG_LEVEL` | Logging verbosity (default: `INFO`) | No |

### Project Configuration (`projects.json`)

```json
{
  "projects": [
    {
      "name": "my-app",
      "path": "/Users/you/code/my-app",
      "allowed_commands": ["npm test", "npm run build"]
    },
    {
      "name": "api-server",
      "path": "/Users/you/code/api-server",
      "allowed_commands": ["python -m pytest"]
    }
  ]
}
```

Each project defines a working directory and an optional allowlist of bash commands that Claude Code can run during execution.

---

## Requirements

- **Claude Code CLI** — installed and authenticated (`claude --version` should work)
- **Python 3.11+**
- **macOS or Linux** (macOS recommended; Linux supported)
- **Telegram bot** — created via [@BotFather](https://t.me/BotFather)

---

## Roadmap

- Docker container support for sandboxed execution
- Web dashboard for session monitoring
- Multi-user support with role-based access
- Webhook mode (replace polling) for faster response times

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

---

## License

[MIT](LICENSE)

---

## Author

Built by [Alex Ferrao](https://alexferrao.dev)
