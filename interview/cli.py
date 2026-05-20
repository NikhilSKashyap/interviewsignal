"""
interview CLI
-------------
Entry point for the `interview` command.

Usage:
  interview install              Install skill + hooks for Claude Code
  interview install --platform codex
  interview uninstall
  interview configure-email      Set up SMTP credentials
  interview dashboard            Open HM dashboard
  interview status               Show active session status
"""

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

INTERVIEW_DIR = Path.home() / ".interview"
SKILL_SRC = Path(__file__).parent / "skills" / "interview" / "SKILL.md"
SUBMIT_SKILL_SRC = Path(__file__).parent / "skills" / "submit" / "SKILL.md"

CODEX_INTERVIEW_ENTRY = """
## interview skill
When the user types `/interview <CODE>`, this is an interviewsignal candidate session.
Immediately run:

```bash
python -m interview.core.session start --code <CODE>
```

Do not inspect the repo first. Do not explain the plan first. Do not ask for
confirmation. After the command completes, show the full interview banner and
problem statement from stdout to the candidate verbatim. Do not add commentary
before or after it.

If stdout is not visible in the chat, read `~/.interview/active_session.json`
and render the interview code, start time, time limit, and `problem` field as
the visible session banner. Wait for the candidate's next message and treat all
subsequent work as part of the active interview session.

When the user types `/submit` and an interviewsignal session is active, run:

```bash
python -m interview.core.session seal
python -m interview.core.report generate --code <CODE>
python -m interview.core.transport send --code <CODE>
```

Show only the submission confirmation and any score output returned by the
configured sharing policy.
""".strip()


# ─── Platform install targets ────────────────────────────────────────────────

PLATFORMS = {
    "claude": {
        "name": "Claude Code",
        "skill_dir": Path.home() / ".claude" / "skills" / "interview",
        "claude_md": Path.home() / ".claude" / "CLAUDE.md",
        "settings_json": Path.home() / ".claude" / "settings.json",
    },
    "codex": {
        "name": "Codex",
        "agents_md": Path("AGENTS.md"),
        "hooks_json": Path(".codex") / "hooks.json",
    },
    "cursor": {
        "name": "Cursor",
        "cursorrules": Path(".cursorrules"),
    },
    "gemini": {
        "name": "Gemini CLI",
        "gemini_md": Path("GEMINI.md"),
        "settings_json": Path(".gemini") / "settings.json",
    },
    "aider": {
        "name": "Aider",
        "config_yml": Path(".aider.conf.yml"),
        "conventions_md": Path("CONVENTIONS.md"),
    },
}


def _upsert_interview_agents_entry(path: Path, entry: str = CODEX_INTERVIEW_ENTRY):
    """Add or replace the interviewsignal block in a Codex AGENTS.md file."""
    entry = entry.strip() + "\n"
    markers = ["\n## interview skill", "\n# interviewsignal"]
    if path.exists():
        content = path.read_text()
        search_content = "\n" + content
        start = -1
        marker_len = 0
        for marker in markers:
            idx = search_content.find(marker)
            if idx != -1 and (start == -1 or idx < start):
                start = idx
                marker_len = len(marker)
        if start != -1:
            content_start = max(start - 1, 0)
            section_start = start + marker_len
            next_heading = search_content.find("\n## ", section_start)
            next_top_heading = search_content.find("\n# ", section_start)
            next_candidates = [i for i in (next_heading, next_top_heading) if i != -1]
            content_end = (min(next_candidates) - 1) if next_candidates else len(content)
            prefix = content[:content_start].rstrip()
            suffix = content[content_end:].lstrip()
            updated = (prefix + "\n\n" if prefix else "") + entry
            if suffix:
                updated += "\n" + suffix
            path.write_text(updated)
            return
        path.write_text(content.rstrip() + "\n\n" + entry)
        return
    path.write_text(entry)


def _install_claude(verbose=True):
    """Install skill + PreToolUse/PostToolUse hooks for Claude Code."""
    cfg = PLATFORMS["claude"]

    # 1. Copy SKILL.md files
    skill_dir = cfg["skill_dir"]
    skill_dir.mkdir(parents=True, exist_ok=True)
    dest = skill_dir / "SKILL.md"
    shutil.copy2(SKILL_SRC, dest)
    if verbose:
        print(f"  ✓ Skill installed: {dest}")

    submit_skill_dir = Path.home() / ".claude" / "skills" / "submit"
    submit_skill_dir.mkdir(parents=True, exist_ok=True)
    submit_dest = submit_skill_dir / "SKILL.md"
    shutil.copy2(SUBMIT_SKILL_SRC, submit_dest)
    if verbose:
        print(f"  ✓ Skill installed: {submit_dest}")

    # 2. Update CLAUDE.md
    claude_md = cfg["claude_md"]
    interview_entry = """
## interview skill
- **interview** (`~/.claude/skills/interview/SKILL.md`) — AI-native interview platform.
  - `/interview <CODE>` — Candidate session (captures all activity)
  - `/submit` — Submit session and email report to HM
When the user types `/interview` or `/submit`, invoke the Skill tool with `skill: "interview"` before doing anything else.
"""
    if claude_md.exists():
        content = claude_md.read_text()
        if "interview skill" not in content:
            claude_md.write_text(content + interview_entry)
            if verbose:
                print(f"  ✓ CLAUDE.md updated: {claude_md}")
    else:
        claude_md.parent.mkdir(parents=True, exist_ok=True)
        claude_md.write_text(interview_entry)
        if verbose:
            print(f"  ✓ CLAUDE.md created: {claude_md}")

    # 3. Install hooks in settings.json
    settings_json = cfg["settings_json"]
    if settings_json.exists():
        try:
            settings = json.loads(settings_json.read_text())
        except Exception:
            settings = {}
    else:
        settings = {}

    hook_cmd = f"{sys.executable} -m interview.hooks.claude_hook"

    hooks = settings.setdefault("hooks", {})

    hooks["PreToolUse"] = [{
        "matcher": "*",
        "hooks": [{
            "type": "command",
            "command": f"{hook_cmd} pre",
        }]
    }]

    hooks["PostToolUse"] = [{
        "matcher": "*",
        "hooks": [{
            "type": "command",
            "command": f"{hook_cmd} post",
        }]
    }]

    # Stop hook — reads conversation log, logs user_prompt + assistant_message
    hooks["Stop"] = [{
        "hooks": [{
            "type": "command",
            "command": f"{hook_cmd} stop",
        }]
    }]

    # 4. Add permissions so interview commands run without yes/no prompts
    # Use absolute paths computed at install time (like sys.executable) so they
    # work regardless of how Claude Code resolves ~ vs full paths.
    interview_home = str(Path.home() / ".interview")
    permissions = settings.setdefault("permissions", {})
    allow = permissions.setdefault("allow", [])
    interview_permissions = [
        "Bash(echo *)",
        f"Bash({sys.executable} -m interview.core.setup *)",
        f"Bash({sys.executable} -m interview.core.session *)",
        f"Bash({sys.executable} -m interview.core.report *)",
        f"Bash({sys.executable} -m interview.core.transport *)",
        "Bash(python -m interview.core.setup *)",
        "Bash(python -m interview.core.session *)",
        "Bash(python -m interview.core.report *)",
        "Bash(python -m interview.core.transport *)",
        "Bash(python3 -m interview.core.setup *)",
        "Bash(python3 -m interview.core.session *)",
        "Bash(python3 -m interview.core.report *)",
        "Bash(python3 -m interview.core.transport *)",
        "Bash(git init)",
        "Bash(git add *)",
        "Bash(git commit *)",
        "Bash(git push *)",
        "Bash(git remote *)",
        f"Read({interview_home}/*)",
        f"Write({interview_home}/*)",
    ]
    for p in interview_permissions:
        if p not in allow:
            allow.append(p)
    permissions["allow"] = allow

    settings_json.parent.mkdir(parents=True, exist_ok=True)
    settings_json.write_text(json.dumps(settings, indent=2))
    if verbose:
        print(f"  ✓ Hooks + permissions installed: {settings_json}")

    # Verify the hook is actually reachable in this Python environment
    import subprocess as _sp
    try:
        test = _sp.run(
            [sys.executable, "-m", "interview.hooks.claude_hook", "pre"],
            input='{"tool_name":"Bash","tool_input":{}}',
            capture_output=True, text=True, timeout=5,
        )
        if test.returncode != 0:
            raise RuntimeError(test.stderr.strip())
        if verbose:
            print(f"  ✓ Hook reachability check passed")
    except Exception as e:
        print(f"\n  ⚠  Hook reachability check FAILED: {e}")
        print(f"     The hook command is: {hook_cmd} pre")
        print(f"     If Claude Code uses a different Python, sessions won't be captured.")
        print(f"     Fix: reinstall interviewsignal inside Claude Code's Python environment.")


def _install_codex(verbose=True):
    """Install skill for Codex via AGENTS.md + hooks.json."""
    agents_md = Path("AGENTS.md")
    codex_global_agents_md = Path.home() / ".codex" / "AGENTS.md"

    _upsert_interview_agents_entry(agents_md)
    if verbose:
        print(f"  ✓ AGENTS.md updated")

    codex_global_agents_md.parent.mkdir(parents=True, exist_ok=True)
    _upsert_interview_agents_entry(codex_global_agents_md)
    if verbose:
        print(f"  ✓ Codex global AGENTS.md updated: {codex_global_agents_md}")

    # Install a global /interview skill for Codex/Codex-like local skill loaders.
    # Keep /submit in AGENTS.md to avoid conflicts with other tools' global
    # submit skills.
    agents_skill_dir = Path.home() / ".agents" / "skills" / "interview"
    agents_skill_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SKILL_SRC, agents_skill_dir / "SKILL.md")
    if verbose:
        print(f"  ✓ Codex skill installed: {agents_skill_dir / 'SKILL.md'}")
        print(f"    Restart Codex if /interview is not recognized immediately.")

    hooks_dir = Path(".codex")
    hooks_dir.mkdir(exist_ok=True)
    hooks_file = hooks_dir / "hooks.json"
    hooks = {}
    if hooks_file.exists():
        try:
            hooks = json.loads(hooks_file.read_text())
        except Exception:
            pass

    # Migrate the early experimental shape written by interviewsignal <= 0.9.15.
    for stale_key in ("PreToolUse", "PostToolUse", "UserPromptSubmit", "Stop"):
        hooks.pop(stale_key, None)

    hook_cmd = f"{sys.executable} -m interview.hooks.codex_hook"
    if not isinstance(hooks.get("hooks"), dict):
        hooks["hooks"] = {}
    hook_events = hooks["hooks"]
    hook_events["UserPromptSubmit"] = [{
        "hooks": [{
            "type": "command",
            "command": f"{hook_cmd} user_prompt",
        }]
    }]
    hook_events["PreToolUse"] = [{
        "matcher": "*",
        "hooks": [{
            "type": "command",
            "command": f"{hook_cmd} pre",
        }]
    }]
    hook_events["PostToolUse"] = [{
        "matcher": "*",
        "hooks": [{
            "type": "command",
            "command": f"{hook_cmd} post",
        }]
    }]
    hook_events["Stop"] = [{
        "hooks": [{
            "type": "command",
            "command": f"{hook_cmd} stop",
        }]
    }]

    hooks_file.write_text(json.dumps(hooks, indent=2))
    if verbose:
        print(f"  ✓ Codex hooks installed: {hooks_file}")
        print(f"     Restart Codex after install so hooks are loaded.")

    import subprocess as _sp
    try:
        test = _sp.run(
            [sys.executable, "-m", "interview.hooks.codex_hook", "pre"],
            input=json.dumps({
                "tool_name": "local_shell",
                "tool_input": {
                    "command": "python -m interview.core.session log --event-type thinking",
                },
            }),
            capture_output=True, text=True, timeout=5,
        )
        if test.returncode != 0:
            raise RuntimeError(test.stderr.strip())
        if verbose:
            print(f"  ✓ Hook reachability check passed")
    except Exception as e:
        print(f"\n  ⚠  Hook reachability check FAILED: {e}")
        print(f"     The hook command is: {hook_cmd} pre")
        print(f"     Reinstall interviewsignal with the Python used by Codex.")


def _install_cursor(verbose=True):
    """Install skill instructions for Cursor via .cursorrules."""
    cursorrules = PLATFORMS["cursor"]["cursorrules"]
    entry = """
# interviewsignal — AI-native interview platform
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# When the user types `/interview <CODE>`, start an interview session:
#   1. Run: python -m interview.core.session start --code <CODE>
#   2. Read ~/.interview/active/meta.json for the problem statement
#   3. Present the problem and begin the session
#   4. All candidate work happens in the current project directory
#
# When the user types `/submit`, end the session:
#   1. Run: python -m interview.core.session seal
#   2. Run: python -m interview.core.transport submit
#   3. Show the candidate their score summary
#
# IMPORTANT: Capture all tool use (file writes, edits, terminal commands)
# by noting them in the session. The interview system tracks candidate
# thought process through their interaction with the AI assistant.
#
# Permissions needed:
#   - Read/Write ~/.interview/*
#   - Run python -m interview.core.* commands
#   - Run git commands (init, add, commit, push, remote)
"""
    if cursorrules.exists():
        content = cursorrules.read_text()
        if "interviewsignal" not in content:
            cursorrules.write_text(content + entry)
            if verbose:
                print(f"  ✓ .cursorrules updated: {cursorrules}")
        else:
            if verbose:
                print(f"  ✓ .cursorrules already configured")
    else:
        cursorrules.write_text(entry)
        if verbose:
            print(f"  ✓ .cursorrules created: {cursorrules}")

    if verbose:
        print(f"\n  ⚠  Cursor does not support lifecycle hooks.")
        print(f"     Activity capture is limited — candidate prompts and tool calls")
        print(f"     won't be logged automatically. For full capture, use Claude Code.")


def _install_gemini(verbose=True):
    """Install skill + hooks for Gemini CLI via GEMINI.md + .gemini/settings.json."""
    # 1. GEMINI.md — project-level instructions
    gemini_md = PLATFORMS["gemini"]["gemini_md"]
    entry = """
## interview skill
- **interview** — AI-native interview platform (interviewsignal).
  - `/interview <CODE>` — Start a candidate session (captures all activity)
  - `/submit` — Seal session and submit report to hiring manager

When the user types `/interview`, run:
  `python -m interview.core.session start --code <CODE>`
then read ~/.interview/active/meta.json for the problem.

When the user types `/submit`, run:
  `python -m interview.core.session seal`
  `python -m interview.core.transport submit`
"""
    if gemini_md.exists():
        content = gemini_md.read_text()
        if "interviewsignal" not in content and "interview skill" not in content:
            gemini_md.write_text(content + entry)
            if verbose:
                print(f"  ✓ GEMINI.md updated: {gemini_md}")
        else:
            if verbose:
                print(f"  ✓ GEMINI.md already configured")
    else:
        gemini_md.write_text(entry)
        if verbose:
            print(f"  ✓ GEMINI.md created: {gemini_md}")

    # 2. .gemini/settings.json — hooks for activity capture
    settings_dir = Path(".gemini")
    settings_dir.mkdir(exist_ok=True)
    settings_json = PLATFORMS["gemini"]["settings_json"]

    settings = {}
    if settings_json.exists():
        try:
            settings = json.loads(settings_json.read_text())
        except Exception:
            pass

    hook_cmd = f"{sys.executable} -m interview.hooks.claude_hook"
    hooks = settings.setdefault("hooks", {})
    hooks["preToolUse"] = {"command": f"{hook_cmd} pre"}
    hooks["postToolUse"] = {"command": f"{hook_cmd} post"}

    settings_json.write_text(json.dumps(settings, indent=2))
    if verbose:
        print(f"  ✓ Hooks installed: {settings_json}")


def _install_aider(verbose=True):
    """Install skill instructions for Aider via .aider.conf.yml + CONVENTIONS.md."""
    # 1. CONVENTIONS.md — Aider reads this via the `read:` directive
    conventions = PLATFORMS["aider"]["conventions_md"]
    entry = """
## interviewsignal — AI-native interview platform

When the user types `/interview <CODE>`, start an interview session:
  1. Run: python -m interview.core.session start --code <CODE>
  2. Read ~/.interview/active/meta.json for the problem statement
  3. Present the problem and begin the session

When the user types `/submit`, end the session:
  1. Run: python -m interview.core.session seal
  2. Run: python -m interview.core.transport submit
  3. Show the candidate their score summary

All candidate work happens in the current project directory. Track file
writes, edits, and terminal commands — the interview system captures
thought process through AI assistant interaction.
"""
    if conventions.exists():
        content = conventions.read_text()
        if "interviewsignal" not in content:
            conventions.write_text(content + entry)
            if verbose:
                print(f"  ✓ CONVENTIONS.md updated: {conventions}")
        else:
            if verbose:
                print(f"  ✓ CONVENTIONS.md already configured")
    else:
        conventions.write_text(entry)
        if verbose:
            print(f"  ✓ CONVENTIONS.md created: {conventions}")

    # 2. .aider.conf.yml — tell Aider to load CONVENTIONS.md
    config_yml = PLATFORMS["aider"]["config_yml"]
    config_lines = []
    has_read = False
    if config_yml.exists():
        content = config_yml.read_text()
        config_lines = content.splitlines()
        for line in config_lines:
            if line.strip().startswith("read:") or "CONVENTIONS.md" in line:
                has_read = True
                break

    if not has_read:
        config_lines.append("read: [CONVENTIONS.md]")
        config_yml.write_text("\n".join(config_lines) + "\n")
        if verbose:
            print(f"  ✓ .aider.conf.yml updated: {config_yml}")
    else:
        if verbose:
            print(f"  ✓ .aider.conf.yml already configured")

    if verbose:
        print(f"\n  ⚠  Aider does not support lifecycle hooks.")
        print(f"     Activity capture is limited — candidate prompts and tool calls")
        print(f"     won't be logged automatically. For full capture, use Claude Code.")


def cmd_install(args):
    platform_name = args.platform or "claude"
    print(f"\nInstalling interviewsignal for {PLATFORMS.get(platform_name, {}).get('name', platform_name)}...\n")

    installers = {
        "claude": _install_claude,
        "codex": _install_codex,
        "cursor": _install_cursor,
        "gemini": _install_gemini,
        "aider": _install_aider,
    }
    installer = installers.get(platform_name)
    if not installer:
        print(f"  Platform '{platform_name}' not recognized.")
        print(f"  Supported: {', '.join(installers.keys())}")
        return
    installer()

    # Collect candidate identity once — stored in config so /interview needs no prompting
    config_file = INTERVIEW_DIR / "config.json"
    config = {}
    if config_file.exists():
        try:
            config = json.loads(config_file.read_text())
        except Exception:
            pass

    existing_name = config.get("candidate_name", "")
    existing_email = config.get("candidate_email", "")

    print()
    if existing_name and existing_email:
        print(f"  Identity: {existing_name} <{existing_email}>")
        update = input("  Update? [y/N] ").strip().lower()
        if update != "y":
            print()
            print(f"\n✓ interviewsignal installed.\n")
            print(f"  Hiring manager: run 'interview dashboard' to create interviews and review submissions")
            platform_hint = "Codex" if platform_name == "codex" else "Claude Code"
            print(f"  Candidate:      open {platform_hint} and type /interview <CODE>\n")
            return

    print("  To skip the name/email prompt during interviews, we'll save your identity now.")
    name = input("  Your name: ").strip()
    email = input("  Your email: ").strip()

    if name or email:
        if name:
            config["candidate_name"] = name
        if email:
            config["candidate_email"] = email
        INTERVIEW_DIR.mkdir(parents=True, exist_ok=True)
        tmp = config_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(config, indent=2))
        tmp.rename(config_file)
        os.chmod(config_file, 0o600)
        print(f"  ✓ Identity saved.")

    print(f"\n✓ interviewsignal installed.\n")
    print(f"  Hiring manager: run 'interview dashboard' to create interviews and review submissions")
    platform_hint = "Codex" if platform_name == "codex" else "Claude Code"
    print(f"  Candidate:      open {platform_hint} and type /interview <CODE>\n")


def cmd_uninstall(args):
    platform_name = args.platform or "claude"
    if platform_name == "claude":
        cfg = PLATFORMS["claude"]
        skill_dir = cfg["skill_dir"]
        if skill_dir.exists():
            shutil.rmtree(skill_dir)
            print(f"  ✓ Skill removed: {skill_dir}")

        submit_skill_dir = Path.home() / ".claude" / "skills" / "submit"
        if submit_skill_dir.exists():
            shutil.rmtree(submit_skill_dir)
            print(f"  ✓ Skill removed: {submit_skill_dir}")

        # Remove hooks from settings.json
        settings_json = cfg["settings_json"]
        if settings_json.exists():
            try:
                settings = json.loads(settings_json.read_text())
                hooks = settings.get("hooks", {})
                for hook_type in ["PreToolUse", "PostToolUse", "Stop"]:
                    hooks.pop(hook_type, None)
                settings_json.write_text(json.dumps(settings, indent=2))
                print(f"  ✓ Hooks removed from {settings_json}")
            except Exception as e:
                print(f"  ⚠ Could not update settings.json: {e}")

        print(f"\n✓ interviewsignal uninstalled.")
    elif platform_name == "codex":
        hooks_file = PLATFORMS["codex"]["hooks_json"]
        if hooks_file.exists():
            try:
                settings = json.loads(hooks_file.read_text())
                hook_events = settings.get("hooks", {})
                if isinstance(hook_events, dict):
                    for hook_type in ["UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"]:
                        groups = hook_events.get(hook_type)
                        if isinstance(groups, list):
                            filtered = []
                            for group in groups:
                                handlers = group.get("hooks", []) if isinstance(group, dict) else []
                                ours = any(
                                    isinstance(h, dict)
                                    and "interview.hooks.codex_hook" in h.get("command", "")
                                    for h in handlers
                                )
                                if not ours:
                                    filtered.append(group)
                            if filtered:
                                hook_events[hook_type] = filtered
                            else:
                                hook_events.pop(hook_type, None)
                    settings["hooks"] = hook_events
                    hooks_file.write_text(json.dumps(settings, indent=2))
                    print(f"  ✓ Codex hooks removed from {hooks_file}")
            except Exception as e:
                print(f"  ⚠ Could not update {hooks_file}: {e}")

        print(f"\n✓ interviewsignal uninstalled.")
    else:
        print(f"  Platform '{platform_name}' uninstall is not implemented.")


def cmd_configure_email(args):
    from interview.core.email_sender import configure_email_interactive
    configure_email_interactive()


def cmd_configure_relay(args):
    """
    Configure how interview sessions are delivered to the HM.

    Three options:
      1. Hosted relay  — relay.interviewsignal.dev (shared, free to try)
      2. Your own relay — Railway / Render / self-hosted (private, ~$5/mo)
      3. Email only    — SMTP, no server needed (free, manual workflow)
    """
    config_file = Path.home() / ".interview" / "config.json"
    config_file.parent.mkdir(parents=True, exist_ok=True)

    config = {}
    if config_file.exists():
        try:
            config = json.loads(config_file.read_text())
        except Exception:
            pass

    current_url     = config.get("relay_url", "")
    current_hm_key  = config.get("hm_key", "")
    current_mode    = "relay" if current_url else ("email" if config.get("smtp_host") else "none")

    print("\nHow do you want to deliver interview sessions?")
    print("─" * 50)
    print("  1. Your own relay  Railway / Render / self-hosted — private, ~$5/mo")
    print("  2. Email only      SMTP — no server, reports arrive by email")
    print()

    current_label = {"relay": "1", "email": "2", "none": "1"}.get(current_mode, "1")
    choice = input(f"Choice [{current_label}]: ").strip() or current_label

    if choice == "1":
        # ── Self-hosted / own relay ───────────────────────────────────────────
        print()
        print("  Enter your relay URL (Railway / Render / your own server).")
        print()
        prompt = f"Relay URL [{current_url}]: " if current_url else "Relay URL: "
        relay_url = input(prompt).strip().rstrip("/") or current_url

        if not relay_url:
            print("\n  No URL entered — no changes made.\n")
            return

        # Add https:// if user forgot the scheme
        if relay_url and "://" not in relay_url:
            relay_url = "https://" + relay_url

        print("\nRelay API key — only needed if you set RELAY_API_KEY on your server.")
        api_key = input("API key [blank]: ").strip()

        config["relay_url"] = relay_url
        if api_key:
            config["relay_api_key"] = api_key
        config.pop("smtp_host", None)

        config_file.write_text(json.dumps(config, indent=2))
        os.chmod(config_file, 0o600)

        if current_hm_key and current_url == relay_url:
            key_preview = current_hm_key[:8] + "..."
            print(f"\n✓ Relay configured: {relay_url}")
            print(f"  hm_key: {key_preview} (already registered)\n")
        else:
            print(f"\n  Registering with relay...")
            _register_relay(relay_url, config, config_file)

    elif choice == "2":
        # ── Email only ────────────────────────────────────────────────────────
        config.pop("relay_url", None)
        config.pop("hm_key", None)
        config.pop("relay_api_key", None)

        config_file.write_text(json.dumps(config, indent=2))
        os.chmod(config_file, 0o600)

        print(f"\n✓ Email mode selected.")
        print(f"  Sessions will be sent by SMTP when candidates run /submit.")
        print(f"  Run 'interview configure-email' to set up your SMTP credentials.\n")

    else:
        print(f"\n  Unknown choice '{choice}' — no changes made.\n")


def _register_relay(relay_url: str, config: dict, config_file: Path):
    """Attempt to register with the relay and store the hm_key. Shared helper."""
    try:
        from interview.core.transport import RelayTransport, set_hm_key
        hm_key = RelayTransport.register_hm(relay_url)
        set_hm_key(hm_key)
        key_preview = hm_key[:8] + "..."
        print(f"✓ Relay configured: {relay_url}")
        print(f"  hm_key: {key_preview} — your sessions are private to you")
        print(f"  Run 'interview dashboard' to review candidates\n")
    except Exception as e:
        print(f"  ⚠ Could not register: {e}")
        print(f"  Relay URL saved. Re-run 'interview configure-relay' once the relay is reachable.\n")


def cmd_configure_api_key(args):
    """Store Anthropic API key in ~/.interview/config.json (direct access shortcut)."""
    import getpass
    config_file = Path.home() / ".interview" / "config.json"
    config_file.parent.mkdir(parents=True, exist_ok=True)

    config = {}
    if config_file.exists():
        try:
            config = json.loads(config_file.read_text())
        except Exception:
            pass

    print("\nConfigure Anthropic API key for interviewsignal grading")
    print("─" * 50)
    print("Get your key at: https://console.anthropic.com/settings/keys")
    print("Enterprise / proxy users: run 'interview configure-llm' instead.\n")

    key = getpass.getpass("Anthropic API key (sk-ant-...): ").strip()
    if not key.startswith("sk-"):
        print("⚠ Key doesn't look right — should start with 'sk-'. Saved anyway.")

    config["anthropic_api_key"] = key
    config_file.write_text(json.dumps(config, indent=2))
    os.chmod(config_file, 0o600)
    print(f"\n✓ API key saved to {config_file}")
    print(f"  You can also set ANTHROPIC_API_KEY environment variable instead.\n")


def cmd_configure_llm(args):
    """
    Configure the LLM endpoint used for grading.

    Covers three deployment patterns:
      Direct      — Anthropic API key, default base URL
      Enterprise  — Internal proxy (Floodgate, Azure AI, Bedrock gateway…)
                    Same API shape, different URL + optional custom headers.
      OpenAI-compat — Proxy that speaks Chat Completions format instead.
    """
    config_file = Path.home() / ".interview" / "config.json"
    config_file.parent.mkdir(parents=True, exist_ok=True)

    config = {}
    if config_file.exists():
        try:
            config = json.loads(config_file.read_text())
        except Exception:
            pass

    current_url    = config.get("anthropic_base_url", "")
    current_model  = config.get("grading_model", "")
    current_format = config.get("api_format", "anthropic")
    current_hdrs   = json.dumps(config.get("anthropic_extra_headers") or {})

    print("\nConfigure LLM endpoint for interviewsignal grading")
    print("─" * 55)
    print("Direct (default):    leave Base URL blank, enter Anthropic key")
    print("Enterprise proxy:    enter your proxy URL; API key optional")
    print("OpenAI-compatible:   enter proxy URL, set format to 'openai'")
    print()

    # ── Base URL ──────────────────────────────────────────────────────────────
    prompt = f"Base URL [{current_url or 'https://api.anthropic.com'}]: "
    base_url = input(prompt).strip().rstrip("/")
    if not base_url:
        base_url = current_url  # keep existing or leave blank (= use default)

    # ── API key ───────────────────────────────────────────────────────────────
    import getpass
    if base_url and base_url != "https://api.anthropic.com":
        print("\nAPI key — leave blank if your proxy handles auth (e.g. SSO / network-level).")
    else:
        print("\nGet your Anthropic key at: console.anthropic.com/settings/keys")
    key = getpass.getpass("API key [blank = keep existing / not required]: ").strip()

    # ── API format ────────────────────────────────────────────────────────────
    print(f"\nAPI format: 'anthropic' (default) or 'openai' (Chat Completions compatible)")
    fmt = input(f"Format [{current_format}]: ").strip().lower() or current_format
    if fmt not in ("anthropic", "openai"):
        print(f"  ⚠ Unknown format '{fmt}' — defaulting to 'anthropic'.")
        fmt = "anthropic"

    # ── Model override ────────────────────────────────────────────────────────
    default_model = "claude-3-5-haiku-20241022"
    print(f"\nModel name — your proxy may use a different alias or version ID.")
    model = input(f"Model [{current_model or default_model}]: ").strip() or current_model

    # ── Extra headers ─────────────────────────────────────────────────────────
    print(f"\nExtra headers — JSON dict for team/project routing (e.g. X-Team-ID).")
    print(f"  Example: {{\"X-Team-ID\": \"ml-hiring\", \"X-Project\": \"interviews\"}}")
    hdrs_raw = input(f"Extra headers [{current_hdrs}]: ").strip() or current_hdrs
    try:
        extra_headers = json.loads(hdrs_raw) if hdrs_raw and hdrs_raw != "{}" else {}
    except Exception:
        print("  ⚠ Could not parse headers as JSON — ignoring.")
        extra_headers = config.get("anthropic_extra_headers") or {}

    # ── Save ──────────────────────────────────────────────────────────────────
    if base_url:
        config["anthropic_base_url"] = base_url
    if key:
        config["anthropic_api_key"] = key
    if fmt != "anthropic":
        config["api_format"] = fmt
    elif "api_format" in config:
        del config["api_format"]          # remove if reset to default
    if model and model != default_model:
        config["grading_model"] = model
    elif "grading_model" in config and not model:
        del config["grading_model"]
    if extra_headers:
        config["anthropic_extra_headers"] = extra_headers
    elif "anthropic_extra_headers" in config:
        del config["anthropic_extra_headers"]

    config_file.write_text(json.dumps(config, indent=2))
    os.chmod(config_file, 0o600)

    # ── Summary ───────────────────────────────────────────────────────────────
    effective_url = base_url or "https://api.anthropic.com"
    effective_model = model or default_model
    key_display = (key[:8] + "...") if key else "(none — proxy handles auth)"
    print(f"\n✓ LLM grading configured:")
    print(f"  Base URL:  {effective_url}")
    print(f"  API key:   {key_display}")
    print(f"  Format:    {fmt}")
    print(f"  Model:     {effective_model}")
    if extra_headers:
        print(f"  Headers:   {json.dumps(extra_headers)}")
    print()


def cmd_configure_github_app(args):
    """
    Configure GitHub OAuth for the relay server.

    This is for relay operators — not candidates. Sets GITHUB_CLIENT_ID and
    GITHUB_CLIENT_SECRET env vars that the relay reads at startup.

    How to create a GitHub OAuth App:
      1. GitHub → Settings → Developer settings → OAuth Apps → New OAuth App
      2. Application name:  interviewsignal (or your company name)
      3. Homepage URL:      your relay URL  (e.g. https://relay.example.com)
      4. Callback URL:      <relay_url>/auth/github/callback
      5. Click Register Application
      6. Copy Client ID and generate a Client Secret
    """
    print("\nConfigure GitHub OAuth for the relay server")
    print("─" * 52)
    print("Create an OAuth App at: github.com/settings/developers")
    print("Callback URL: <your_relay_url>/auth/github/callback\n")

    client_id = input("GitHub Client ID: ").strip()
    if not client_id:
        print("\n  No Client ID entered — no changes made.\n")
        return

    import getpass
    client_secret = getpass.getpass("GitHub Client Secret: ").strip()
    if not client_secret:
        print("\n  No Client Secret entered — no changes made.\n")
        return

    relay_base = input("Your relay base URL (e.g. https://relay.example.com): ").strip().rstrip("/")

    print("\n  Set these environment variables on your relay server:\n")
    print(f"  GITHUB_CLIENT_ID={client_id}")
    print(f"  GITHUB_CLIENT_SECRET={client_secret}")
    if relay_base:
        print(f"  RELAY_BASE_URL={relay_base}")
    print()
    print("  Railway / Render: add them in the Variables / Environment tab.")
    print("  Docker:           add them to your docker-compose.yml or .env file.")

    # Also save to local config for self-hosted single-machine deployments
    config_file = Path.home() / ".interview" / "config.json"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config = {}
    if config_file.exists():
        try:
            config = json.loads(config_file.read_text())
        except Exception:
            pass
    config["github_client_id"]     = client_id
    config["github_client_secret"] = client_secret
    if relay_base:
        config["relay_base_url"] = relay_base
    config_file.write_text(json.dumps(config, indent=2))
    os.chmod(config_file, 0o600)
    print(f"\n✓ Also saved to {config_file} for local relay deployments.\n")


def cmd_dashboard(args):
    from interview.dashboard.serve import start_dashboard
    start_dashboard(getattr(args, "code", None))


def cmd_status(args):
    from interview.core.session import get_session_status
    status = get_session_status()
    if status:
        tl_str = ""
        if status.get("time_limit_minutes"):
            remaining = status["time_limit_minutes"] - status["elapsed_minutes"]
            tl_str = f" | {max(0, round(remaining, 1))}min remaining"
        print(f"\n  Active session: {status['code']}")
        print(f"  Elapsed: {status['elapsed_minutes']} minutes{tl_str}")
        print(f"  Events captured: {status['event_count']}")
        print(f"\n  Type /submit to end the session.\n")
    else:
        print(f"\n  No active session.\n")


def cmd_score(args):
    """
    Fetch the candidate's own score from the relay.

    Reads the cid from the local session manifest (computed from github_id or email).
    Calls GET /sessions/{code}/{cid}/score — open route, no HM auth needed.
    """
    code = args.code.strip().upper()
    session_dir = Path.home() / ".interview" / "sessions" / code
    manifest_file = session_dir / "manifest.json"

    if not manifest_file.exists():
        print(f"\n  ✗ No local session found for {code}.")
        print(f"    Make sure you ran /submit for this interview.\n")
        return

    import hashlib
    manifest = json.loads(manifest_file.read_text())

    github_id = manifest.get("github_id")
    candidate_email = manifest.get("candidate_email", "")
    if github_id:
        cid = hashlib.sha256(f"github:{github_id}".encode()).hexdigest()[:12]
    elif candidate_email:
        cid = hashlib.sha256(candidate_email.lower().strip().encode()).hexdigest()[:12]
    else:
        print(f"\n  ✗ Cannot determine candidate ID — no github_id or email in manifest.\n")
        return

    from interview.core.transport import get_relay_url, RelayTransport, TransportError
    relay_url = get_relay_url()
    if not relay_url:
        relay_url_in_manifest = manifest.get("relay_url", "")
        if relay_url_in_manifest:
            relay_url = relay_url_in_manifest
    if not relay_url:
        print(f"\n  ✗ No relay configured.")
        print(f"    Score sharing is only available when a relay is in use.")
        print(f"    Run 'interview configure-relay' to set one up.\n")
        return

    transport = RelayTransport(relay_url)
    try:
        result = transport.get_score(code, cid)
    except TransportError as e:
        print(f"\n  ✗ Could not fetch score: {e}\n")
        return

    if result is None or not result.get("available"):
        reason = (result or {}).get("reason", "Score is not available for this interview.")
        print(f"\n  Score not available: {reason}\n")
        return

    print(f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"  SCORE — {code}")
    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    overall = result.get("overall_score")
    if overall is not None:
        print(f"\n  Overall: {overall}/10\n")

    summary = result.get("summary", "")
    if summary:
        print(f"  {summary}\n")

    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")


def main():
    parser = argparse.ArgumentParser(
        prog="interview",
        description="interviewsignal — AI-native interview platform",
    )
    sub = parser.add_subparsers(dest="command")

    p_install = sub.add_parser("install", help="Install skill + hooks")
    p_install.add_argument("--platform", default="claude",
                           choices=["claude", "codex", "cursor", "gemini", "aider"],
                           help="AI coding platform to install for")

    p_uninstall = sub.add_parser("uninstall", help="Remove skill + hooks")
    p_uninstall.add_argument("--platform", default="claude")

    sub.add_parser("configure-email", help="Set up SMTP credentials")
    sub.add_parser("configure-api-key", help="Store Anthropic API key (direct access)")
    sub.add_parser("configure-llm", help="Configure LLM endpoint for grading (enterprise proxies, custom base URL)")
    sub.add_parser("configure-relay", help="Set relay server URL and API key")
    p_dashboard = sub.add_parser("dashboard", help="Open HM candidate dashboard")
    p_dashboard.add_argument("code", nargs="?", default=None, help="Jump directly to a candidate (e.g. INT-1234-AB)")
    sub.add_parser("status", help="Show active session status")

    p_score = sub.add_parser("score", help="Fetch your score for a submitted interview")
    p_score.add_argument("code", help="Interview code (e.g. INT-4829-XK)")

    # Relay operator commands — hidden from main help (run once when deploying the relay)
    sub.add_parser("configure-github-app", help=argparse.SUPPRESS)

    args = parser.parse_args()

    if args.command == "install":
        cmd_install(args)
    elif args.command == "uninstall":
        cmd_uninstall(args)
    elif args.command == "configure-email":
        cmd_configure_email(args)
    elif args.command == "configure-api-key":
        cmd_configure_api_key(args)
    elif args.command == "configure-llm":
        cmd_configure_llm(args)
    elif args.command == "configure-relay":
        cmd_configure_relay(args)
    elif args.command == "configure-github-app":
        cmd_configure_github_app(args)
    elif args.command == "dashboard":
        cmd_dashboard(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "score":
        cmd_score(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
