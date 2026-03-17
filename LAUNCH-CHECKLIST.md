# CommandPost Launch Checklist

## Pre-Launch

- [ ] Revoke old Telegram bot token via BotFather, create new one
- [ ] Verify all hardcoded credentials removed (`grep -r "8379615695" .` returns nothing)
- [ ] Verify no personal paths remain (`grep -r "/Users/alex" watcher.py` returns nothing)
- [ ] Test fresh setup: clone → uv sync → configure .env + projects.json → start
- [ ] Run bot end-to-end: send task → receive plan PDF → confirm → receive result
- [ ] Record demo GIF showing the full flow in Telegram
- [ ] Add demo GIF to README
- [ ] Create GitHub repo (public, MIT license)
- [ ] git init → git add → initial commit → push
- [ ] Set GitHub topics (20): python, telegram-bot, telegram, claude, claude-code, ai-agent, remote-execution, developer-tools, automation, cli, macos, self-hosted, productivity, coding-assistant, llm, anthropic, devtools, terminal, ai-coding, open-source
- [ ] Write GitHub repo description: "Remote-control Claude Code from your phone via Telegram — plan, review, and execute coding tasks from anywhere."
- [ ] Review README renders correctly on GitHub

## Launch Day

- [ ] Post to Hacker News (Show HN)
- [ ] Post to r/ClaudeAI
- [ ] Post to r/selfhosted
- [ ] Post to r/commandline
- [ ] Post to r/MacOS
- [ ] Tweet thread from personal account
- [ ] Monitor comments and respond promptly (first 2 hours critical)

## Post-Launch (Week 1)

- [ ] Respond to all GitHub issues within 24 hours
- [ ] Write a follow-up post if it gains traction
- [ ] Add any quick-win features requested by the community
- [ ] Update README based on common questions

## Post-Launch (Month 1)

- [ ] Evaluate Docker container support based on demand
- [ ] Consider webhook mode if polling latency is a common complaint
- [ ] Tag v1.0.1 if bug fixes are needed
