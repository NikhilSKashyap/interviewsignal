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
    # More platforms: cursor, gemini, aider — Phase 2
}


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
  - `/interview hm` — Hiring manager setup
  - `/interview <CODE>` — Candidate session (captures all activity)
  - `/submit` — Submit session and email report to HM
  - `/interview dashboard` — HM candidate review dashboard
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

    # Stop hook — seal session if one is active
    hooks["Stop"] = [{
        "hooks": [{
            "type": "command",
            "command": f"{sys.executable} -m interview.core.session status",
        }]
    }]

    settings_json.parent.mkdir(parents=True, exist_ok=True)
    settings_json.write_text(json.dumps(settings, indent=2))
    if verbose:
        print(f"  ✓ Hooks installed: {settings_json}")


def _install_codex(verbose=True):
    """Install skill for Codex via AGENTS.md + hooks.json."""
    agents_md = Path("AGENTS.md")
    entry = """
## interview skill
Type `$interview hm` to set up an interview as a hiring manager.
Type `$interview <CODE>` to start a candidate session.
Type `$submit` to end the session and send the report.
"""
    if agents_md.exists():
        content = agents_md.read_text()
        if "interview skill" not in content:
            agents_md.write_text(content + entry)
    else:
        agents_md.write_text(entry)
    if verbose:
        print(f"  ✓ AGENTS.md updated")

    hooks_dir = Path(".codex")
    hooks_dir.mkdir(exist_ok=True)
    hooks_file = hooks_dir / "hooks.json"
    hooks = {}
    if hooks_file.exists():
        try:
            hooks = json.loads(hooks_file.read_text())
        except Exception:
            pass

    hook_cmd = f"{sys.executable} -m interview.hooks.claude_hook"
    hooks["PreToolUse"] = {"command": f"{hook_cmd} pre"}
    hooks_file.write_text(json.dumps(hooks, indent=2))
    if verbose:
        print(f"  ✓ Codex hooks installed: {hooks_file}")


def cmd_install(args):
    platform_name = args.platform or "claude"
    print(f"\nInstalling interviewsignal for {PLATFORMS.get(platform_name, {}).get('name', platform_name)}...\n")

    if platform_name == "claude":
        _install_claude()
    elif platform_name == "codex":
        _install_codex()
    else:
        print(f"  Platform '{platform_name}' not yet supported. Coming soon.")
        print(f"  Supported: claude, codex")
        return

    print(f"\n✓ interviewsignal installed.\n")
    print(f"  Hiring manager: open Claude Code and type /interview hm")
    print(f"  Candidate:      open Claude Code and type /interview <CODE>\n")


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


def cmd_configure_email(args):
    from interview.core.email_sender import configure_email_interactive
    configure_email_interactive()


def cmd_configure_relay(args):
    """Configure relay server URL and API key."""
    config_file = Path.home() / ".interview" / "config.json"
    config_file.parent.mkdir(parents=True, exist_ok=True)

    config = {}
    if config_file.exists():
        try:
            config = json.loads(config_file.read_text())
        except Exception:
            pass

    current_url = config.get("relay_url", "")
    print("\nConfigure interviewsignal relay")
    print("─" * 45)
    print("Hosted default:  https://relay.interviewsignal.dev")
    print("Self-hosted:     https://interviews.yourcompany.com\n")

    prompt = f"Relay URL [{current_url}]: " if current_url else "Relay URL: "
    relay_url = input(prompt).strip() or current_url
    relay_url = relay_url.rstrip("/")

    api_key = input("Relay API key: ").strip()

    if relay_url:
        config["relay_url"] = relay_url
    if api_key:
        config["relay_api_key"] = api_key

    config_file.write_text(json.dumps(config, indent=2))
    os.chmod(config_file, 0o600)

    if relay_url:
        print(f"\n✓ Relay configured: {relay_url}")
        print(f"  /submit   → routes to relay (candidates need api key too)")
        print(f"  dashboard → reads sessions from relay\n")
    else:
        print(f"\n  No relay URL set — staying in email mode.\n")


def cmd_configure_api_key(args):
    """Store Anthropic API key in ~/.interview/config.json."""
    import getpass
    from pathlib import Path
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
    print("Get your key at: https://console.anthropic.com/settings/keys\n")

    key = getpass.getpass("Anthropic API key (sk-ant-...): ").strip()
    if not key.startswith("sk-"):
        print("⚠ Key doesn't look right — should start with 'sk-'. Saved anyway.")

    config["anthropic_api_key"] = key
    import os
    config_file.write_text(json.dumps(config, indent=2))
    os.chmod(config_file, 0o600)
    print(f"\n✓ API key saved to {config_file}")
    print(f"  You can also set ANTHROPIC_API_KEY environment variable instead.\n")


def cmd_dashboard(args):
    from interview.dashboard.serve import start_dashboard
    start_dashboard()


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
    sub.add_parser("configure-api-key", help="Store Anthropic API key for grading")
    sub.add_parser("configure-relay", help="Set relay server URL and API key")
    sub.add_parser("dashboard", help="Open HM candidate dashboard")
    sub.add_parser("status", help="Show active session status")

    args = parser.parse_args()

    if args.command == "install":
        cmd_install(args)
    elif args.command == "uninstall":
        cmd_uninstall(args)
    elif args.command == "configure-email":
        cmd_configure_email(args)
    elif args.command == "configure-api-key":
        cmd_configure_api_key(args)
    elif args.command == "configure-relay":
        cmd_configure_relay(args)
    elif args.command == "dashboard":
        cmd_dashboard(args)
    elif args.command == "status":
        cmd_status(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
