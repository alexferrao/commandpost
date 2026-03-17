# Contributing to CommandPost

Thanks for your interest in contributing! CommandPost is a Telegram bot for remote-controlling Claude Code, and we welcome improvements of all kinds.

## Architecture

CommandPost is intentionally a **single-file project** (`watcher.py`). Please keep it that way unless there's a genuinely strong reason to split things out. This makes the bot easy to deploy, read, and reason about.

## How to Contribute

1. **Fork** the repository
2. **Create a branch** for your change (`git checkout -b my-feature`)
3. **Make your changes** in `watcher.py` (or supporting files like `.env.example`, docs, etc.)
4. **Test locally** by running the bot against a real Telegram chat and Claude Code session
5. **Submit a PR** with a clear description of what you changed and why

## Guidelines

- **Preserve the plan-then-confirm-then-execute flow.** This is the core safety mechanism of CommandPost. Any change that bypasses or weakens the confirmation step needs a very good justification.
- **Python 3.11+** is required. Use type hints where reasonable -- they help, but don't over-annotate obvious cases.
- Keep commits focused and PR descriptions clear.
- If you're adding a new command or mode, document it in the PR.

## Running Locally

1. Copy `.env.example` to `.env` and fill in your Telegram bot token and chat ID
2. Run `python watcher.py`
3. Send commands to your bot via Telegram to verify your changes

## Questions?

Open an issue or start a discussion. We're happy to help.
