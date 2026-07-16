"""Shared helpers for Claude Code project hooks."""

import json
import os
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def read_input() -> dict[str, Any]:
    """Read and validate the hook JSON payload from stdin."""
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError("Claude Code supplied invalid hook JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("Claude Code hook payload must be a JSON object")
    return payload


def project_root(payload: dict[str, Any]) -> Path:
    """Resolve the project root without trusting arbitrary hook input paths."""
    configured = os.environ.get("CLAUDE_PROJECT_DIR")
    if configured:
        return Path(configured).resolve()
    cwd = payload.get("cwd")
    if isinstance(cwd, str):
        return Path(cwd).resolve()
    return Path.cwd().resolve()


def run(command: list[str], cwd: Path, timeout: int = 10) -> subprocess.CompletedProcess[str]:
    """Run a subprocess without a shell and capture text output."""
    return subprocess.run(  # noqa: S603 -- argv is controlled and shell=False.
        command,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def emit_hook_output(event: str, **fields: Any) -> None:
    """Emit Claude Code hook-specific JSON output."""
    print(json.dumps({"hookSpecificOutput": {"hookEventName": event, **fields}}))


def deny_tool(reason: str) -> None:
    """Deny a PreToolUse action with a visible reason."""
    emit_hook_output(
        "PreToolUse",
        permissionDecision="deny",
        permissionDecisionReason=reason,
    )


def ask_tool(reason: str) -> None:
    """Escalate a PreToolUse action for explicit human confirmation."""
    emit_hook_output(
        "PreToolUse",
        permissionDecision="ask",
        permissionDecisionReason=reason,
    )


def block_action(reason: str) -> None:
    """Block the current agent loop with a visible reason."""
    print(json.dumps({"decision": "block", "reason": reason}))


def run_pre_tool_hook(callback: Callable[[], None]) -> None:
    """Run a security hook and fail closed on malformed input or internal errors."""
    try:
        callback()
    except Exception as exc:
        print(
            f"Security hook failed closed ({type(exc).__name__}). Review hook diagnostics.",
            file=sys.stderr,
        )
        raise SystemExit(2) from exc


def run_blocking_check(callback: Callable[[], None], *, check_name: str) -> None:
    """Run a post-action check and stop the agent loop when the check itself fails."""
    try:
        callback()
    except Exception as exc:
        block_action(
            f"{check_name} could not complete ({type(exc).__name__}). "
            "Stop and inspect the hook before continuing."
        )


def log_event(payload: dict[str, Any], hook: str, category: str, decision: str) -> None:
    """Append a structured audit line for a hook decision.

    Records only the category label, decision, and tool name so the log stays
    safe to inspect or ship to an observability pipeline; it never contains
    command text, file contents, or matched values. Failures to write are
    silent because an audit trail must never block a tool call.
    """
    tool_name = payload.get("tool_name")
    entry = {
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        "hook": hook,
        "category": category,
        "decision": decision,
        "tool_name": tool_name if isinstance(tool_name, str) else None,
    }
    log_path = project_root(payload) / ".claude" / "logs" / "hooks-audit.jsonl"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")
    except OSError:
        return


def path_within(path: Path, root: Path) -> bool:
    """Return whether path resolves inside root."""
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True
