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

    # Stop hook — reads conversation log, logs user_prompt + assistant_message
    hooks["Stop"] = [{
        "hooks": [{
            "type": "command",
            "command": f"{hook_cmd} stop",
        }]
    }]

    # 4. Add permissions so interview commands run without yes/no prompts
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
        "Bash(cat ~/.interview/*)",
        "Write(~/.interview/*)",
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

    dimensions = result.get("dimensions", [])
    if dimensions:
        print(f"  Dimensions:")
        for d in dimensions:
            name = d.get("name", "")
            score = d.get("score", "—")
            just = d.get("justification", "")
            print(f"    {name}: {score}/10")
            if just:
                print(f"      {just}")
        print()

    summary = result.get("summary", "")
    if summary:
        print(f"  Summary:\n    {summary}\n")

    standouts = result.get("standout_moments", [])
    if standouts:
        print(f"  Standout moments:")
        for s in standouts:
            print(f"    • {s}")
        print()

    concerns = result.get("concerns", [])
    if concerns:
        print(f"  Concerns:")
        for c in concerns:
            print(f"    • {c}")
        print()

    debrief = result.get("debrief", "")
    if debrief:
        print(f"  Session debrief (Claude's analysis — not the hiring manager's evaluation):")
        print(f"{debrief}\n")

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
    sub.add_parser("dashboard", help="Open HM candidate dashboard")
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
