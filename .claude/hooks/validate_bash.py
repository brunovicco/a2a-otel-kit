#!/usr/bin/env python3
"""Block destructive or credential-exposing shell commands."""

import re
import shlex

from _common import deny_tool, log_event, read_input, run_pre_tool_hook

RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(^|[;&|]\s*)sudo\b", re.IGNORECASE), "sudo is not allowed from Claude Code"),
    (re.compile(r"\bgit\s+reset\s+--hard\b", re.IGNORECASE), "git reset --hard is destructive"),
    (
        re.compile(r"\bgit\s+clean\s+-(?:[^\s]*f[^\s]*d|[^\s]*d[^\s]*f)", re.IGNORECASE),
        "git clean -fd is destructive",
    ),
    (
        re.compile(r"\bgit\s+push\b[^\n]*(?:--force|-f\b)", re.IGNORECASE),
        "force push is not allowed",
    ),
    (
        re.compile(r"\brm\s+-[^\n]*r[^\n]*f\s+(?:/|~|\.|\.\.|\$HOME)(?:\s|$)", re.IGNORECASE),
        "recursive deletion of a broad path is blocked",
    ),
    (
        re.compile(r"\bchmod\s+(?:-R\s+)?777\b", re.IGNORECASE),
        "world-writable permissions are blocked",
    ),
    (
        re.compile(r"\b(?:curl|wget)\b[^\n|]*\|\s*(?:bash|sh|zsh)\b", re.IGNORECASE),
        "piping remote content directly to a shell is blocked",
    ),
    (
        re.compile(r"\bterraform\s+destroy\b", re.IGNORECASE),
        "terraform destroy requires an explicit human-controlled workflow",
    ),
    (
        re.compile(
            r"\bclaude\s+mcp\s+add\b[^\n]*(?:--header|-H|--env|-e)[^\n]*(?:Bearer|token|secret|password|api[_-]?key)",
            re.IGNORECASE,
        ),
        "MCP credentials must not be passed as command-line literals",
    ),
    (
        re.compile(r"\bkubectl\s+delete\s+(?:namespace|ns)\b", re.IGNORECASE),
        "namespace deletion is blocked",
    ),
    (
        re.compile(r"\bdocker\s+system\s+prune\b[^\n]*-a", re.IGNORECASE),
        "global Docker pruning is blocked",
    ),
    (
        re.compile(r"\b(?:mkfs|fdisk|dd\s+if=)\b", re.IGNORECASE),
        "low-level disk operations are blocked",
    ),
)

SENSITIVE_PATH = re.compile(
    r"(?:^|[/\\\s'\"=])(?:"
    r"\.env(?!\.example)(?:\.[A-Za-z0-9_-]+)?|"
    r"id_(?:rsa|ed25519)|"
    r"terraform\.tfstate(?:\.[A-Za-z0-9_-]+)?|"
    r"(?:secrets?|credentials?)(?:/|\\)"
    r")",
    re.IGNORECASE,
)

SHELL_SEPARATORS = frozenset({";", "&", "&&", "|", "||"})
JQ_OPTIONS_WITH_ONE_VALUE = frozenset({"-L", "--library-path", "--indent"})
JQ_OPTIONS_WITH_TWO_VALUES = frozenset(
    {"--arg", "--argjson", "--argfile", "--slurpfile", "--rawfile"}
)
JQ_FILE_FILTER_OPTIONS = frozenset({"-f", "--from-file"})


def shell_tokens(command: str) -> list[str]:
    """Split a command while preserving shell control operators."""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|")
    lexer.whitespace_split = True
    lexer.commenters = ""
    return list(lexer)


def jq_filter_indexes(tokens: list[str]) -> set[int]:
    """Return inline jq program positions, which are expressions rather than paths."""
    filters: set[int] = set()
    for index, token in enumerate(tokens):
        if token.rsplit("/", maxsplit=1)[-1] != "jq":
            continue

        cursor = index + 1
        uses_file_filter = False
        while cursor < len(tokens) and tokens[cursor] not in SHELL_SEPARATORS:
            option = tokens[cursor]
            if option == "--":
                cursor += 1
                break
            if option in JQ_FILE_FILTER_OPTIONS:
                uses_file_filter = True
                cursor += 2
                continue
            if option in JQ_OPTIONS_WITH_TWO_VALUES:
                cursor += 3
                continue
            if option in JQ_OPTIONS_WITH_ONE_VALUE:
                cursor += 2
                continue
            if option.startswith("-"):
                cursor += 1
                continue
            break

        if not uses_file_filter and cursor < len(tokens) and tokens[cursor] not in SHELL_SEPARATORS:
            filters.add(cursor)
    return filters


def references_sensitive_path(command: str) -> bool:
    """Detect sensitive path arguments without treating jq selectors as file paths."""
    tokens = shell_tokens(command)
    ignored = jq_filter_indexes(tokens)
    return any(
        SENSITIVE_PATH.search(token) is not None
        for index, token in enumerate(tokens)
        if index not in ignored
    )


def main() -> None:
    """Inspect a Bash tool call and deny known dangerous patterns."""
    payload = read_input()
    tool_input = payload.get("tool_input", {})
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str):
        return

    if references_sensitive_path(command):
        log_event(payload, "validate_bash", "sensitive-file", "deny")
        deny_tool(
            "Blocked command: shell commands may not reference sensitive files. "
            "Use an example file or environment-variable names only."
        )
        return

    for pattern, reason in RULES:
        if pattern.search(command):
            log_event(payload, "validate_bash", "destructive-command", "deny")
            deny_tool(f"Blocked command: {reason}.")
            return


if __name__ == "__main__":
    run_pre_tool_hook(main)
