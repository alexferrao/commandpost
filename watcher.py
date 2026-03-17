#!/usr/bin/env python3
"""
CommandPost v6 - Simple Project Switching for Claude Code via Telegram.

Flow:
1. /projects → shows all projects with tap-to-switch buttons
2. /p name → switches to project (partial match works)
3. cc: task → runs task in current project (auto-resume session)
4. search: keyword → search transcript index by topic/title/tags
5. research: topic → read-only analysis task (no code changes)
6. Reply with text → continue conversation
7. "yes/proceed" → execute proposed changes

That's it. Simple.
"""
import os
import sys
import json
import asyncio
import subprocess
import random
import sqlite3
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.enums import TA_LEFT

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters

# Configuration
COMMANDPOST_DIR = Path.home() / ".commandpost"
load_dotenv(COMMANDPOST_DIR / ".env")

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_USER_ID = int(os.environ.get("ADMIN_USER_ID", "0"))
STATE_FILE = COMMANDPOST_DIR / "state.json"
LOG_FILE = COMMANDPOST_DIR / "watcher.log"
MEDIA_DB_PATH = Path(os.environ.get("MEDIA_DB_PATH", "")) if os.environ.get("MEDIA_DB_PATH") else None

# Load project registry from projects.json
PROJECTS_FILE = COMMANDPOST_DIR / "projects.json"

def load_projects() -> dict:
    if not PROJECTS_FILE.exists():
        print(f"ERROR: {PROJECTS_FILE} not found. Copy projects.example.json to projects.json and configure your projects.")
        sys.exit(1)
    return json.loads(PROJECTS_FILE.read_text())

PROJECTS = load_projects()

if not BOT_TOKEN:
    print("ERROR: BOT_TOKEN not set. Copy .env.example to .env and add your Telegram bot token.")
    sys.exit(1)
if not ADMIN_USER_ID:
    print("ERROR: ADMIN_USER_ID not set. Add your Telegram user ID to .env.")
    sys.exit(1)

# Affirmative responses that trigger execution
AFFIRMATIVE_RESPONSES = [
    "yes", "proceed", "do it", "go ahead", "go", "ok", "okay", "yep", "sure",
    "execute", "run it", "fix it", "yes please", "y", "yeah", "yup", "continue"
]

# Permission management
SETTINGS_FILE_NAME = ".claude/settings.local.json"


class CommandPostWatcher:
    def __init__(self):
        COMMANDPOST_DIR.mkdir(parents=True, exist_ok=True)
        self.bot = Bot(token=BOT_TOKEN)
        self.state = self.load_state()
        self.login_process = None  # Track active login process
        self.waiting_for_token = False  # Whether we're waiting for auth token

    def load_state(self) -> dict:
        if STATE_FILE.exists():
            state = json.loads(STATE_FILE.read_text())
            migrated = self.migrate_state(state)
            # Save migrated state immediately
            if migrated != state:
                STATE_FILE.write_text(json.dumps(migrated, indent=2))
            return migrated
        return {
            "current_project": next(iter(PROJECTS)),
            "projects": {},
            "last_update_id": 0,
            "processed_tasks": []
        }

    def migrate_state(self, state: dict) -> dict:
        """Migrate from old contexts format to new simplified projects format."""
        if "contexts" in state:
            self.log("Migrating from contexts to projects format...")
            projects = {}

            for key, data in state.get("contexts", {}).items():
                # Extract project name (ignore context suffix like :task-name)
                project = key.split(":")[0]

                # Keep most recent data for each project
                existing = projects.get(project, {})
                existing_activity = existing.get("last_activity", "")
                new_activity = data.get("last_activity", data.get("created", ""))

                if not existing or new_activity > existing_activity:
                    projects[project] = {
                        "session_id": data.get("session_id"),
                        "last_activity": new_activity,
                        "message_count": data.get("message_count", 0),
                        "pending_code": data.get("pending_code"),
                        "pending_prompt": data.get("pending_prompt")
                    }

            # Build new state
            new_state = {
                "current_project": state.get("active_context", "").split(":")[0] or "tb_suite_m4",
                "projects": projects,
                "last_update_id": state.get("last_update_id", 0),
                "processed_tasks": state.get("processed_tasks", [])
            }

            self.log(f"Migrated {len(projects)} projects")
            return new_state

        return state

    def save_state(self):
        STATE_FILE.write_text(json.dumps(self.state, indent=2))

    def get_current_project(self) -> str:
        return self.state.get("current_project", "tb_suite_m4")

    def set_current_project(self, project: str):
        self.state["current_project"] = project
        self.save_state()

    def get_project_data(self, project: str) -> dict:
        """Get session data for a project."""
        return self.state.get("projects", {}).get(project, {})

    def set_project_data(self, project: str, data: dict):
        """Set session data for a project."""
        if "projects" not in self.state:
            self.state["projects"] = {}
        self.state["projects"][project] = data
        self.save_state()

    def match_project(self, name: str) -> str | None:
        """Match partial project name to full project name."""
        name_lower = name.lower().strip()

        # Exact match
        if name_lower in PROJECTS:
            return name_lower

        # Partial match
        matches = [p for p in PROJECTS if name_lower in p.lower()]
        if len(matches) == 1:
            return matches[0]

        # Prefix match
        prefix_matches = [p for p in PROJECTS if p.lower().startswith(name_lower)]
        if len(prefix_matches) == 1:
            return prefix_matches[0]

        return None

    def generate_confirmation_code(self) -> str:
        words = ["alpha", "bravo", "delta", "echo", "foxtrot", "gamma", "nova", "sigma", "theta", "zeta"]
        return f"{random.choice(words)}-{random.randint(1000, 9999)}"

    def is_affirmative(self, text: str) -> bool:
        """Check if message is an affirmative response."""
        return text.lower().strip() in AFFIRMATIVE_RESPONSES

    def get_project_settings_path(self, project: str) -> Path:
        """Get the settings.local.json path for a project."""
        project_path = Path(PROJECTS.get(project, next(iter(PROJECTS.values()))))
        return project_path / SETTINGS_FILE_NAME

    def load_project_permissions(self, project: str) -> dict:
        """Load the permissions from a project's settings.local.json."""
        settings_path = self.get_project_settings_path(project)
        if settings_path.exists():
            try:
                return json.loads(settings_path.read_text())
            except:
                pass
        return {"permissions": {"allow": [], "deny": []}}

    def save_project_permissions(self, project: str, settings: dict):
        """Save permissions to a project's settings.local.json."""
        settings_path = self.get_project_settings_path(project)
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(json.dumps(settings, indent=2))

    def add_permission(self, project: str, command: str) -> bool:
        """Add a bash command to the project's allowlist. Returns True if added."""
        settings = self.load_project_permissions(project)

        if "permissions" not in settings:
            settings["permissions"] = {"allow": [], "deny": []}
        if "allow" not in settings["permissions"]:
            settings["permissions"]["allow"] = []

        perm_entry = f"Bash({command}:*)"

        if perm_entry in settings["permissions"]["allow"]:
            return False

        settings["permissions"]["allow"].append(perm_entry)
        self.save_project_permissions(project, settings)
        return True

    def get_allowlist(self, project: str) -> list:
        """Get the current allowlist for a project."""
        settings = self.load_project_permissions(project)
        return settings.get("permissions", {}).get("allow", [])

    def generate_tldr(self, content: str) -> str:
        """Extract key points for TLDR."""
        lines = content.strip().split('\n')
        tldr_lines = []

        for line in lines:
            line = line.strip()
            if not line:
                continue
            if line.startswith(('-', '*', '1.', '2.', '3.')):
                tldr_lines.append(line)
            elif len(tldr_lines) == 0 and len(line) > 20:
                tldr_lines.append(line)

            if len(tldr_lines) >= 3:
                break

        return '\n'.join(tldr_lines)[:500]

    def sanitize_text(self, text: str) -> str:
        """Remove non-ASCII characters and break long words for PDF compatibility."""
        # Replace common unicode with ASCII equivalents
        replacements = {
            '•': '-', '–': '-', '—': '-', ''': "'", ''': "'",
            '"': '"', '"': '"', '…': '...', '✓': '[x]', '✗': '[ ]',
            '→': '->', '←': '<-', '↔': '<->', '≥': '>=', '≤': '<=',
            '≠': '!=', '×': 'x', '÷': '/', '±': '+/-', '∞': 'inf',
        }
        for old, new in replacements.items():
            text = text.replace(old, new)
        # Remove any remaining non-ASCII
        text = text.encode('ascii', 'ignore').decode('ascii')

        # Break very long words (no spaces) that would overflow PDF
        words = text.split(' ')
        result = []
        for word in words:
            if len(word) > 80:
                # Insert spaces every 80 chars
                chunks = [word[i:i+80] for i in range(0, len(word), 80)]
                result.append(' '.join(chunks))
            else:
                result.append(word)
        return ' '.join(result)

    def escape_xml(self, text: str) -> str:
        """Escape special XML characters for reportlab."""
        return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    def create_pdf(self, title: str, content: str, metadata: dict = None) -> str:
        """Create a professional PDF from content using reportlab."""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        pdf_path = COMMANDPOST_DIR / f"response_{timestamp}.pdf"
        txt_path = COMMANDPOST_DIR / f"response_{timestamp}.txt"

        try:
            doc = SimpleDocTemplate(str(pdf_path), pagesize=letter,
                                    leftMargin=0.75*inch, rightMargin=0.75*inch,
                                    topMargin=0.75*inch, bottomMargin=0.75*inch)

            styles = getSampleStyleSheet()

            # Custom styles
            title_style = ParagraphStyle('Title', parent=styles['Heading1'],
                                         fontSize=16, textColor='#0066cc', spaceAfter=12)
            meta_style = ParagraphStyle('Meta', parent=styles['Normal'],
                                        fontSize=9, textColor='#666666', spaceAfter=3)
            h1_style = ParagraphStyle('H1', parent=styles['Heading1'],
                                      fontSize=14, textColor='#0066cc', spaceAfter=8, spaceBefore=12)
            h2_style = ParagraphStyle('H2', parent=styles['Heading2'],
                                      fontSize=12, spaceAfter=6, spaceBefore=10)
            h3_style = ParagraphStyle('H3', parent=styles['Heading3'],
                                      fontSize=11, spaceAfter=4, spaceBefore=8)
            body_style = ParagraphStyle('Body', parent=styles['Normal'],
                                        fontSize=10, spaceAfter=4, leading=14)
            bullet_style = ParagraphStyle('Bullet', parent=styles['Normal'],
                                          fontSize=10, leftIndent=20, spaceAfter=2, leading=13)
            code_style = ParagraphStyle('Code', parent=styles['Normal'],
                                        fontSize=9, fontName='Courier', textColor='#333333',
                                        leftIndent=20, spaceAfter=2, leading=11)

            story = []

            # Title
            story.append(Paragraph(self.escape_xml(title), title_style))

            # Metadata
            if metadata:
                for k, v in metadata.items():
                    story.append(Paragraph(f"{self.escape_xml(k)}: {self.escape_xml(str(v))}", meta_style))
                story.append(Spacer(1, 12))

            # Process content line by line
            in_code_block = False
            for line in content.split('\n'):
                line = line.rstrip()
                escaped = self.escape_xml(line)

                # Code block toggle
                if line.startswith('```'):
                    in_code_block = not in_code_block
                    continue

                if in_code_block:
                    story.append(Paragraph(escaped if escaped else ' ', code_style))
                    continue

                if not line:
                    story.append(Spacer(1, 6))
                    continue

                # Headers
                if line.startswith('### '):
                    story.append(Paragraph(self.escape_xml(line[4:]), h3_style))
                elif line.startswith('## '):
                    story.append(Paragraph(self.escape_xml(line[3:]), h2_style))
                elif line.startswith('# '):
                    story.append(Paragraph(self.escape_xml(line[2:]), h1_style))
                # Bullets
                elif line.strip().startswith(('- ', '* ', '• ')):
                    bullet_text = line.strip()[2:]
                    story.append(Paragraph(f"• {self.escape_xml(bullet_text)}", bullet_style))
                # Numbered lists
                elif line.strip() and line.strip()[0].isdigit() and '. ' in line[:4]:
                    story.append(Paragraph(self.escape_xml(line.strip()), bullet_style))
                # Indented code
                elif line.startswith('    ') or line.startswith('\t'):
                    story.append(Paragraph(escaped, code_style))
                # Regular text
                else:
                    # Clean markdown formatting for display
                    clean = line.replace('**', '').replace('`', '').replace('_', '')
                    story.append(Paragraph(self.escape_xml(clean), body_style))

            doc.build(story)
            return str(pdf_path)

        except Exception as e:
            # Fallback to text file
            self.log(f"PDF failed ({e}), using text fallback")
            txt_content = f"{title}\n{'='*len(title)}\n\n"
            if metadata:
                for k, v in metadata.items():
                    txt_content += f"{k}: {v}\n"
                txt_content += "\n"
            txt_content += content
            txt_path.write_text(txt_content)
            return str(txt_path)

    @staticmethod
    def get_clean_env():
        """Remove Claude Code session markers to prevent nested instance detection."""
        import os
        env = os.environ.copy()
        keys_to_remove = [k for k in env if 'CLAUDE' in k.upper()]
        for key in keys_to_remove:
            del env[key]
        return env

    async def check_auth(self) -> bool:
        """Check if Claude Code is authenticated."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "claude", "auth", "status", "--output-format", "json",
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self.get_clean_env()
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            data = json.loads(stdout.decode())
            return data.get("loggedIn", False)
        except Exception as e:
            self.log(f"Auth check failed: {e}")
            return False

    def is_auth_error(self, text: str) -> bool:
        """Detect if an error is auth-related."""
        auth_keywords = [
            "not logged in", "login", "auth", "unauthorized", "401",
            "authentication", "expired", "sign in", "re-authenticate",
            "session expired", "token expired", "please log in",
            "/login", "claude auth login"
        ]
        text_lower = text.lower()
        return any(kw in text_lower for kw in auth_keywords)

    async def start_login_flow(self, notify: bool = True) -> bool:
        """Start Claude auth login, capture URL, send to Telegram.
        Returns True if login completed successfully."""
        
        # Kill any existing login process
        if self.login_process and self.login_process.returncode is None:
            try:
                self.login_process.kill()
            except:
                pass

        self.log("Starting login flow...")
        self.waiting_for_token = False
        
        if notify:
            await self.bot.send_message(ADMIN_USER_ID, "🔐 Starting Claude Code login...")

        try:
            clean_env = self.get_clean_env()
            # Prevent it from opening a browser
            clean_env["BROWSER"] = "echo"
            
            self.login_process = await asyncio.create_subprocess_exec(
                "claude", "auth", "login",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=clean_env
            )

            # Read output to capture the URL
            url = None
            output = ""
            start = asyncio.get_event_loop().time()
            
            while asyncio.get_event_loop().time() - start < 10:
                try:
                    chunk = await asyncio.wait_for(
                        self.login_process.stdout.read(4096), timeout=2
                    )
                    if chunk:
                        output += chunk.decode()
                        # Look for the OAuth URL
                        for line in output.split('\n'):
                            if 'claude.ai/oauth' in line:
                                # Extract URL from the line
                                parts = line.split('visit: ')
                                if len(parts) > 1:
                                    url = parts[1].strip()
                                elif 'http' in line:
                                    # Find URL in line
                                    idx = line.find('https://')
                                    if idx >= 0:
                                        url = line[idx:].strip()
                        if url:
                            break
                    if self.login_process.returncode is not None:
                        break
                except asyncio.TimeoutError:
                    continue

            if url:
                self.log(f"Login URL captured")
                self.waiting_for_token = True
                await self.bot.send_message(
                    ADMIN_USER_ID,
                    f"🔑 **Tap to authenticate:**\n\n"
                    f"[Login Here]({url})\n\n"
                    f"_After logging in, the browser will show a token/code._\n"
                    f"_Just paste it here in Telegram and I'll handle it._",
                    parse_mode="Markdown",
                    disable_web_page_preview=True
                )
                # Don't wait here - return and let handle_message catch the token
                return False
            else:
                self.log(f"Couldn't capture login URL. Output: {output[:200]}")
                await self.bot.send_message(
                    ADMIN_USER_ID,
                    f"⚠️ Couldn't get login URL.\nOutput: {output[:300]}"
                )
                return False

        except Exception as e:
            self.log(f"Login flow error: {e}")
            await self.bot.send_message(ADMIN_USER_ID, f"❌ Login error: {e}")
            return False

    async def submit_login_token(self, token: str) -> bool:
        """Submit an auth token to the waiting login process."""
        if not self.login_process or self.login_process.returncode is not None:
            await self.bot.send_message(ADMIN_USER_ID, "❌ No active login process. Try /login again.")
            return False

        self.waiting_for_token = False
        self.log(f"Submitting auth token ({len(token)} chars)")

        try:
            # Write token to stdin of the login process
            self.login_process.stdin.write((token.strip() + "\n").encode())
            await self.login_process.stdin.drain()
            self.login_process.stdin.close()
            
            # Wait for the process to finish
            try:
                stdout, _ = await asyncio.wait_for(
                    self.login_process.communicate(), timeout=30
                )
                remaining_output = stdout.decode() if stdout else ""
                self.log(f"Login process output after token: {remaining_output[:300]}")
            except asyncio.TimeoutError:
                self.log("Login process timed out after token submission")
                if self.login_process.returncode is None:
                    self.login_process.kill()

            # Check if auth succeeded
            await asyncio.sleep(2)  # Give it a moment to write credentials
            if await self.check_auth():
                self.log("Login successful!")
                await self.bot.send_message(ADMIN_USER_ID, "✅ Logged in! You can resume tasks.")
                return True
            else:
                await self.bot.send_message(
                    ADMIN_USER_ID,
                    "❌ Token didn't work. Try /login again.\n"
                    "_Make sure you copy the entire token from the browser._"
                )
                return False

        except Exception as e:
            self.log(f"Token submission error: {e}")
            await self.bot.send_message(ADMIN_USER_ID, f"❌ Error submitting token: {e}")
            return False

    async def run_claude(self, prompt: str, project: str, session_id: str = None,
                         skip_permissions: bool = False) -> dict:
        """Run Claude Code asynchronously and return result with session info."""
        project_path = PROJECTS.get(project, next(iter(PROJECTS.values())))

        cmd = ["claude", "-p", prompt, "--output-format", "json"]

        if skip_permissions:
            cmd.append("--dangerously-skip-permissions")

        if session_id:
            cmd.extend(["--resume", session_id])

        self.log(f"Running Claude (session: {session_id or 'new'}, skip_perms: {skip_permissions})")

        try:
            clean_env = self.get_clean_env()
            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=project_path,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=clean_env
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=1800  # 30 minutes
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return {"text": "Timeout: Claude took longer than 30 minutes", "session_id": None, "cost": 0, "is_error": True}

            stdout_text = stdout.decode() if stdout else ""
            stderr_text = stderr.decode() if stderr else ""

            try:
                data = json.loads(stdout_text)
                return {
                    "text": data.get("result", ""),
                    "session_id": data.get("session_id"),
                    "cost": data.get("total_cost_usd", 0),
                    "is_error": data.get("is_error", False)
                }
            except json.JSONDecodeError:
                error_text = stdout_text or stderr_text or "No output"
                # Auto-detect auth errors and trigger login
                if self.is_auth_error(error_text):
                    self.log("Auth error detected, triggering login flow")
                    await self.bot.send_message(
                        ADMIN_USER_ID,
                        "🔒 Claude Code session expired. Starting re-auth..."
                    )
                    login_ok = await self.start_login_flow(notify=False)
                    if login_ok:
                        return {"text": "__AUTH_REFRESHED__", "session_id": session_id, "cost": 0, "is_error": False, "auth_refreshed": True}
                return {
                    "text": error_text,
                    "session_id": None,
                    "cost": 0,
                    "is_error": True
                }
        except Exception as e:
            error_msg = str(e)
            if self.is_auth_error(error_msg):
                self.log("Auth error in exception, triggering login flow")
                await self.bot.send_message(ADMIN_USER_ID, "🔒 Auth error. Starting re-auth...")
                login_ok = await self.start_login_flow(notify=False)
                if login_ok:
                    return {"text": "__AUTH_REFRESHED__", "session_id": session_id, "cost": 0, "is_error": False, "auth_refreshed": True}
            return {"text": f"Error running Claude: {e}", "session_id": None, "cost": 0, "is_error": True}

    async def send_response(self, title: str, content: str, project: str, footer: str = None):
        """Send response as PDF with TLDR in message."""
        data = self.get_project_data(project)
        msg_count = data.get("message_count", 0)

        pdf_path = self.create_pdf(
            title=f"{title} - {project}",
            content=content,
            metadata={
                "Project": project,
                "Messages": str(msg_count),
                "Time": datetime.now().strftime("%Y-%m-%d %H:%M")
            }
        )

        # Build caption with TLDR
        msg_parts = [f"{project} | {msg_count} msgs"]

        if content:
            tldr = self.generate_tldr(content)
            if tldr:
                msg_parts.append(f"\n\nTLDR:\n{tldr}")

        if footer:
            msg_parts.append(f"\n\n---\n{footer}")

        caption = ''.join(msg_parts)
        if len(caption) > 1024:
            caption = caption[:1020] + "..."

        with open(pdf_path, 'rb') as f:
            await self.bot.send_document(
                ADMIN_USER_ID, f, caption=caption,
                filename=f"{title.lower().replace(' ', '_')}_{project}.pdf"
            )

    async def start_task(self, task: str, project: str):
        """Start task - get plan first, wait for confirmation."""
        data = self.get_project_data(project)
        session_id = data.get("session_id")
        is_resuming = bool(session_id)

        plan_prompt = f"""Analyze this task and create a plan. DO NOT execute anything.

Task: {task}

Provide:
1. What you will do
2. Files you'll read/modify
3. Any risks or considerations

Keep it concise but thorough."""

        status_icon = "🔄" if is_resuming else "🆕"
        await self.bot.send_message(ADMIN_USER_ID, f"{status_icon} Analyzing task for {project}...")

        result = await self.run_claude(plan_prompt, project, session_id=session_id)

        # Auto-retry after auth refresh
        if result.get("auth_refreshed"):
            self.log("Auth refreshed, retrying task...")
            await self.bot.send_message(ADMIN_USER_ID, "🔄 Auth refreshed, retrying task...")
            result = await self.run_claude(plan_prompt, project, session_id=session_id)

        if result["is_error"]:
            await self.send_response("Error", result["text"], project)
            return

        code = self.generate_confirmation_code()
        self.set_project_data(project, {
            "session_id": result["session_id"],
            "pending_code": code,
            "pending_prompt": task,
            "mode": "code",
            "message_count": data.get("message_count", 0) + 1,
            "last_activity": datetime.now().isoformat()
        })

        await self.send_response(
            title="Plan",
            content=result["text"],
            project=project,
            footer=f"Reply '{code}' or 'yes' to execute\nReply 'no' to cancel"
        )

    async def search_transcripts(self, query: str):
        """Search transcript index in media_library.db."""
        if not MEDIA_DB_PATH or not MEDIA_DB_PATH.exists():
            await self.bot.send_message(ADMIN_USER_ID, "❌ Transcript search not configured. Set MEDIA_DB_PATH in .env")
            return

        try:
            conn = sqlite3.connect(str(MEDIA_DB_PATH))
            cur = conn.cursor()

            keywords = query.lower().split()

            # Build WHERE clause: each keyword must match at least one field
            conditions = []
            params = []
            for kw in keywords:
                pattern = f"%{kw}%"
                conditions.append(
                    "(LOWER(COALESCE(title,'')) LIKE ? OR LOWER(COALESCE(ai_title,'')) LIKE ? "
                    "OR LOWER(COALESCE(ai_summary,'')) LIKE ? OR LOWER(COALESCE(transcript_preview,'')) LIKE ? "
                    "OR LOWER(COALESCE(description,'')) LIKE ?)"
                )
                params.extend([pattern] * 5)

            where = " AND ".join(conditions)
            sql = f"""
                SELECT m.title, m.ai_title, m.ai_summary, m.folder_path, m.platform,
                       GROUP_CONCAT(t.tag_name, ', ')
                FROM media_items m
                LEFT JOIN tags t ON t.media_id = m.id
                WHERE m.folder_path LIKE 'transcript_%' AND {where}
                GROUP BY m.id
                ORDER BY m.date_added DESC
                LIMIT 10
            """

            cur.execute(sql, params)
            rows = cur.fetchall()
            conn.close()

            if not rows:
                await self.bot.send_message(
                    ADMIN_USER_ID,
                    f"🔍 No results for \"{query}\"\n\nTry different keywords or wait for AI enrichment to index more transcripts."
                )
                return

            lines = [f"🔍 **Results for \"{query}\"** ({len(rows)} found):\n"]
            for i, (title, ai_title, ai_summary, folder, platform, tags) in enumerate(rows, 1):
                display_title = ai_title or title or "Untitled"
                lines.append(f"**{i}.** 📄 {display_title}")
                lines.append(f"   📁 `{folder}`")
                if tags:
                    lines.append(f"   🏷️ {tags}")
                if platform and platform != "unknown":
                    lines.append(f"   🌐 {platform}")
                lines.append("")

            msg = "\n".join(lines)
            if len(msg) > 4000:
                msg = msg[:3990] + "\n..."

            await self.bot.send_message(ADMIN_USER_ID, msg)

        except sqlite3.Error as e:
            await self.bot.send_message(ADMIN_USER_ID, f"❌ DB error: {e}")

    async def start_research(self, task: str, project: str):
        """Start research task — read-only analysis, no code changes."""
        data = self.get_project_data(project)
        session_id = data.get("session_id")
        is_resuming = bool(session_id)

        plan_prompt = f"""You are in RESEARCH MODE. Your job is to read files, analyze content, and research topics.
You must NOT modify, create, or delete any files. Read-only.

Task: {task}

Provide:
1. What you'll read/analyze
2. What research you'll do (web search, cross-reference, etc.)
3. What you expect to find or summarize

Keep it concise but thorough."""

        status_icon = "🔄" if is_resuming else "🔬"
        await self.bot.send_message(ADMIN_USER_ID, f"{status_icon} Research task for {project}...")

        result = await self.run_claude(plan_prompt, project, session_id=session_id)

        if result.get("auth_refreshed"):
            self.log("Auth refreshed, retrying research task...")
            await self.bot.send_message(ADMIN_USER_ID, "🔄 Auth refreshed, retrying...")
            result = await self.run_claude(plan_prompt, project, session_id=session_id)

        if result["is_error"]:
            await self.send_response("Error", result["text"], project)
            return

        code = self.generate_confirmation_code()
        self.set_project_data(project, {
            "session_id": result["session_id"],
            "pending_code": code,
            "pending_prompt": task,
            "mode": "research",
            "message_count": data.get("message_count", 0) + 1,
            "last_activity": datetime.now().isoformat()
        })

        await self.send_response(
            title="Research Plan",
            content=result["text"],
            project=project,
            footer=f"Reply '{code}' or 'yes' to proceed\nReply 'no' to cancel"
        )

    async def execute_plan(self, project: str):
        """Execute - tell Claude to proceed with its proposed plan."""
        data = self.get_project_data(project)
        if not data or not data.get("session_id"):
            return

        mode = data.get("mode", "code")

        if mode == "research":
            await self.bot.send_message(ADMIN_USER_ID, f"🔬 Researching in {project}...")
            exec_prompt = "Proceed with the research plan. Read the files, analyze the content, and provide your findings. Do NOT modify any files."
        else:
            await self.bot.send_message(ADMIN_USER_ID, f"⚡ Executing in {project}...")
            exec_prompt = "Proceed with the plan you proposed. Execute it now."

        result = await self.run_claude(
            prompt=exec_prompt,
            project=project,
            session_id=data["session_id"],
            skip_permissions=True
        )

        # Auto-retry after auth refresh
        if result.get("auth_refreshed"):
            self.log("Auth refreshed, retrying execution...")
            await self.bot.send_message(ADMIN_USER_ID, "🔄 Auth refreshed, retrying...")
            result = await self.run_claude(
                prompt="Proceed with the plan you proposed. Execute it now.",
                project=project,
                session_id=data["session_id"],
                skip_permissions=True
            )

        self.set_project_data(project, {
            **data,
            "session_id": result["session_id"],
            "pending_code": None,
            "pending_prompt": None,
            "message_count": data.get("message_count", 0) + 1,
            "last_activity": datetime.now().isoformat()
        })

        await self.send_response("Result", result["text"], project,
            footer="Reply to continue, 'yes' to proceed, or cc: new task")

    async def continue_conversation(self, message: str, project: str):
        """Continue with follow-up question/instruction."""
        data = self.get_project_data(project)
        if not data or not data.get("session_id"):
            await self.bot.send_message(ADMIN_USER_ID, "No active session. Start with: cc: your task")
            return

        await self.bot.send_message(ADMIN_USER_ID, f"🔍 Processing in {project}...")

        plan_prompt = f"""The user wants to continue with this follow-up:

{message}

Analyze and create a plan. DO NOT execute anything yet."""

        result = await self.run_claude(
            prompt=plan_prompt,
            project=project,
            session_id=data["session_id"]
        )

        # Auto-retry after auth refresh
        if result.get("auth_refreshed"):
            self.log("Auth refreshed, retrying continue...")
            await self.bot.send_message(ADMIN_USER_ID, "🔄 Auth refreshed, retrying...")
            result = await self.run_claude(
                prompt=plan_prompt,
                project=project,
                session_id=data["session_id"]
            )

        code = self.generate_confirmation_code()
        self.set_project_data(project, {
            **data,
            "session_id": result["session_id"],
            "pending_code": code,
            "pending_prompt": message,
            "message_count": data.get("message_count", 0) + 1,
            "last_activity": datetime.now().isoformat()
        })

        await self.send_response(
            title="Follow-up Plan",
            content=result["text"],
            project=project,
            footer=f"Reply '{code}' or 'yes' to execute\nReply 'no' to cancel"
        )

    async def message_handler(self, update, context):
        """Handle messages: cc: tasks, confirmations, or continuations."""
        if not update.message or update.message.from_user.id != ADMIN_USER_ID:
            return

        text = update.message.text
        if not text:
            return

        text = text.strip()
        self.log(f"Received: {text[:50]}...")

        # Intercept auth token if we're waiting for one
        if self.waiting_for_token:
            # If it looks like a token (long string, no spaces or short command)
            # and not a regular command
            if not text.startswith('/') and not text.startswith('cc:') and not text.startswith('!'):
                self.log("Intercepting message as auth token")
                await self.submit_login_token(text)
                return
        project = self.get_current_project()
        data = self.get_project_data(project)

        # Permission commands: !allow <command>
        if text.startswith("!allow "):
            command = text[7:].strip()
            if not command:
                await self.bot.send_message(ADMIN_USER_ID, "Usage: `!allow <command>`")
                return

            if self.add_permission(project, command):
                await self.bot.send_message(
                    ADMIN_USER_ID,
                    f"✅ Added to **{project}** allowlist:\n`Bash({command}:*)`",
                )
            else:
                await self.bot.send_message(
                    ADMIN_USER_ID,
                    f"Already in **{project}** allowlist",
                )
            return

        # New task
        if text.lower().startswith("cc:"):
            task = text[3:].strip()
            if not task:
                await self.bot.send_message(ADMIN_USER_ID, "Please provide a task after cc:")
                return

            self.log(f"Task for project: {project}")
            await self.start_task(task, project)
            return

        # Search transcripts
        if text.lower().startswith("search:"):
            query = text[7:].strip()
            if not query:
                await self.bot.send_message(ADMIN_USER_ID, "Usage: `search: keyword`")
                return
            self.log(f"Transcript search: {query}")
            await self.search_transcripts(query)
            return

        # Research task (read-only analysis)
        if text.lower().startswith("research:"):
            task = text[9:].strip()
            if not task:
                await self.bot.send_message(ADMIN_USER_ID, "Usage: `research: topic or folder name`")
                return
            self.log(f"Research task for project: {project}")
            await self.start_research(task, project)
            return

        # Cancel
        if text.lower() in ["no", "cancel", "stop"]:
            self.set_project_data(project, {
                **data,
                "pending_code": None,
                "pending_prompt": None
            })
            await self.bot.send_message(ADMIN_USER_ID, "Cancelled.")
            return

        # Check confirmation code
        if data and data.get("pending_code"):
            if text.lower() == data["pending_code"].lower():
                self.log(f"Confirmation code matched")
                await self.execute_plan(project)
                return

        # Check affirmative response (yes, proceed, do it, etc.)
        if data and data.get("session_id") and self.is_affirmative(text):
            self.log(f"Affirmative response: {text}")
            await self.execute_plan(project)
            return

        # Otherwise, it's a follow-up question/instruction
        if data and data.get("session_id"):
            self.log(f"Continuing conversation")
            await self.continue_conversation(text, project)
        else:
            await self.bot.send_message(
                ADMIN_USER_ID,
                f"📂 Current: **{project}**\n\n"
                f"Start with: `cc: your task`\n"
                f"`search: keyword` to find transcripts\n"
                f"`research: topic` for read-only analysis\n"
                f"Or `/projects` to switch",
            )

    async def help_command(self, update, context):
        """Show help and available commands."""
        current = self.get_current_project()
        help_text = f"""CommandPost v6 - Simple Project Switching

Current project: {current}

Commands:
  /projects - Show all projects (tap to switch)
  /p name - Quick switch (partial match works)
  cc: task - Run task in current project
  search: keyword - Search transcript index
  research: topic - Read-only analysis task
  yes / proceed - Execute proposed plan
  /status - Current project status
  /login - Re-authenticate Claude Code from phone
  /auth - Check auth status

Permissions:
  !allow cmd - Add command to allowlist
  /allowlist - View allowed commands

Examples:
  /p voice → switches to voice_clipboard
  cc: fix the bug
  search: cooking recipe
  research: read transcript_20260305_080537 and summarize
  yes
"""
        await update.message.reply_text(help_text)

    async def projects_command(self, update, context):
        """Show all projects with inline buttons to switch."""
        current = self.get_current_project()

        lines = ["📂 **Projects**\n"]
        keyboard = []
        row = []

        for name in PROJECTS:
            data = self.get_project_data(name)
            is_current = name == current

            # Project info
            icon = "➡️ " if is_current else ""
            msg_count = data.get("message_count", 0)

            # Last activity
            age_str = ""
            if data.get("last_activity"):
                try:
                    last = datetime.fromisoformat(data["last_activity"])
                    age = datetime.now() - last
                    if age.days > 0:
                        age_str = f"{age.days}d"
                    elif age.seconds > 3600:
                        age_str = f"{age.seconds // 3600}h"
                    else:
                        age_str = f"{age.seconds // 60}m"
                except:
                    pass

            if msg_count > 0:
                lines.append(f"{icon}**{name}** ({msg_count} msgs{', ' + age_str if age_str else ''})")
            else:
                lines.append(f"{icon}{name}")

            # Button - make short label
            btn_label = f"{'✓ ' if is_current else ''}{name[:12]}"
            row.append(InlineKeyboardButton(btn_label, callback_data=f"proj_{name}"))

            # 3 buttons per row
            if len(row) == 3:
                keyboard.append(row)
                row = []

        # Add remaining buttons
        if row:
            keyboard.append(row)

        lines.append("\n_Tap to switch_")

        await update.message.reply_text(
            '\n'.join(lines),
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    async def project_command(self, update, context):
        """Switch to project by name (partial match works)."""
        args = context.args

        if not args:
            current = self.get_current_project()
            data = self.get_project_data(current)
            msg_count = data.get("message_count", 0)
            path = PROJECTS.get(current, "")
            await update.message.reply_text(
                f"📂 **Current:** {current}\n"
                f"📁 {path}\n"
                f"💬 {msg_count} messages\n\n"
                f"Use `/p name` to switch",
            )
            return

        name = args[0].lower()
        matched = self.match_project(name)

        if matched:
            self.set_current_project(matched)
            data = self.get_project_data(matched)
            msg_count = data.get("message_count", 0)
            path = PROJECTS.get(matched, "")

            await update.message.reply_text(
                f"✅ Switched to: **{matched}**\n"
                f"📁 {path}\n"
                f"💬 {msg_count} messages\n\n"
                f"Ready for tasks!",
            )
        else:
            # Show suggestions
            suggestions = ', '.join(list(PROJECTS.keys())[:5])
            await update.message.reply_text(
                f"Unknown project: `{name}`\n\n"
                f"Available: {suggestions}...\n\n"
                f"Use `/projects` to see all",
            )

    async def status_command(self, update, context):
        """Show current project status."""
        project = self.get_current_project()
        data = self.get_project_data(project)

        msg_count = data.get("message_count", 0)
        has_session = bool(data.get("session_id"))
        pending = bool(data.get("pending_code"))
        path = PROJECTS.get(project, "")

        status = "⏳ Awaiting confirmation" if pending else ("✅ Active session" if has_session else "🆕 No session")

        await update.message.reply_text(
            f"📊 **Status**\n\n"
            f"**Project:** {project}\n"
            f"**Path:** {path}\n"
            f"**Messages:** {msg_count}\n"
            f"**Status:** {status}",
        )

    async def allowlist_command(self, update, context):
        """Show the allowlist for the current project."""
        project = self.get_current_project()
        allowlist = self.get_allowlist(project)

        if not allowlist:
            await update.message.reply_text(
                f"📋 **{project}** allowlist is empty.\n\n"
                f"Add commands with:\n`!allow <command>`",
            )
            return

        lines = [f"📋 **{project}** Allowlist:\n"]
        for i, perm in enumerate(allowlist, 1):
            lines.append(f"`{i}. {perm}`")

        lines.append(f"\n_Add more with:_ `!allow <command>`")
        await update.message.reply_text('\n'.join(lines))

    async def login_command(self, update, context):
        """Trigger Claude Code re-authentication from Telegram."""
        if update.message.from_user.id != ADMIN_USER_ID:
            return
        
        await self.start_login_flow()

    async def auth_command(self, update, context):
        """Check Claude Code auth status."""
        if update.message.from_user.id != ADMIN_USER_ID:
            return
        
        try:
            proc = await asyncio.create_subprocess_exec(
                "claude", "auth", "status", "--output-format", "json",
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self.get_clean_env()
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            data = json.loads(stdout.decode())
            
            if data.get("loggedIn"):
                await update.message.reply_text(
                    f"✅ **Logged in**\n"
                    f"Email: {data.get('email', 'unknown')}\n"
                    f"Plan: {data.get('subscriptionType', 'unknown')}\n"
                    f"Method: {data.get('authMethod', 'unknown')}"
                )
            else:
                await update.message.reply_text(
                    "❌ **Not logged in**\n\nUse /login to authenticate."
                )
        except Exception as e:
            await update.message.reply_text(f"⚠️ Auth check failed: {e}")

    async def button_callback(self, update, context):
        """Handle button presses."""
        query = update.callback_query
        await query.answer()

        # Project switching
        if query.data.startswith("proj_"):
            project = query.data[5:]  # Remove "proj_"
            if project in PROJECTS:
                self.set_current_project(project)
                data = self.get_project_data(project)
                msg_count = data.get("message_count", 0)
                path = PROJECTS.get(project, "")

                await query.edit_message_text(
                    f"✅ Switched to: **{project}**\n"
                    f"📁 {path}\n"
                    f"💬 {msg_count} messages\n\n"
                    f"Ready for tasks!",
                )
            else:
                await query.edit_message_text(f"Project not found: {project}")
            return

    def log(self, message: str):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_FILE, "a") as f:
            f.write(f"[{timestamp}] {message}\n")
        print(f"[{timestamp}] {message}")

    async def run(self):
        """Run the Telegram bot."""
        app = Application.builder().token(BOT_TOKEN).build()
        app.add_handler(CommandHandler("help", self.help_command))
        app.add_handler(CommandHandler("start", self.help_command))
        app.add_handler(CommandHandler("projects", self.projects_command))
        app.add_handler(CommandHandler("p", self.project_command))
        app.add_handler(CommandHandler("project", self.project_command))
        app.add_handler(CommandHandler("status", self.status_command))
        app.add_handler(CommandHandler("allowlist", self.allowlist_command))
        app.add_handler(CommandHandler("login", self.login_command))
        app.add_handler(CommandHandler("auth", self.auth_command))
        app.add_handler(CallbackQueryHandler(self.button_callback))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.message_handler))

        self.log("CommandPost v6 started")
        print("🔭 CommandPost v6 running - Simple Project Switching")
        print("Commands: /help, /projects, /p name, cc: task")
        print("Press Ctrl+C to stop\n")

        async with app:
            await app.start()
            self.log("Telegram bot started")
            await app.updater.start_polling()

            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                pass
            finally:
                await app.updater.stop()
                await app.stop()


async def main():
    watcher = CommandPostWatcher()
    await watcher.run()


if __name__ == "__main__":
    asyncio.run(main())
