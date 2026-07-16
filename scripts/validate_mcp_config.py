#!/usr/bin/env python3
"""Validate project MCP configuration for portability and security."""

import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

CONFIG_FILES = (Path(".mcp.json"), Path(".mcp.json.example"))
REMOTE_TYPES = {"http", "streamable-http", "ws", "sse"}
ALLOWED_TYPES = REMOTE_TYPES | {"stdio"}
SENSITIVE_NAME = re.compile(
    r"(?:authorization|cookie|credential|password|passwd|private[_-]?key|secret|token|api[_-]?key)",
    re.IGNORECASE,
)
FULL_ENV_REFERENCE = re.compile(r"^\$\{[A-Z_][A-Z0-9_]*\}$")
SENSITIVE_TEMPLATE = re.compile(
    r"^(?:(?:Bearer|Basic)\s+)?\$\{[A-Z_][A-Z0-9_]*\}$",
    re.IGNORECASE,
)
HIGH_CONFIDENCE_SECRET = re.compile(
    r"(?:"
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
    r"AKIA[0-9A-Z]{16}|"
    r"gh[pousr]_[A-Za-z0-9]{20,}|"
    r"github_pat_[A-Za-z0-9_]{20,}|"
    r"sk-(?:proj-)?[A-Za-z0-9_-]{20,}|"
    r"xox[baprs]-[A-Za-z0-9-]{20,}"
    r")"
)
SHELL_COMMANDS = {"bash", "cmd", "fish", "powershell", "pwsh", "sh", "zsh"}
PACKAGE_RUNNERS = {"npx", "uvx"}
EXACT_PYTHON_PACKAGE = re.compile(
    r"^[A-Za-z0-9_.-]+==[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$"
)


def error(path: Path, server: str, message: str) -> str:
    """Format a validation error."""
    prefix = f"{path}:{server}" if server else str(path)
    return f"{prefix}: {message}"


def validate_timeout(path: Path, name: str, config: dict[str, Any]) -> list[str]:
    """Validate an optional per-server timeout."""
    timeout = config.get("timeout")
    if timeout is None:
        return [error(path, name, "set an explicit timeout in milliseconds")]
    if not isinstance(timeout, int) or isinstance(timeout, bool) or not 1 <= timeout <= 600_000:
        return [error(path, name, "timeout must be an integer between 1 and 600000")]
    return []


def validate_remote(path: Path, name: str, config: dict[str, Any], server_type: str) -> list[str]:
    """Validate a remote MCP server."""
    errors: list[str] = []
    url = config.get("url")
    if not isinstance(url, str) or not url:
        return [error(path, name, "remote server requires a non-empty url")]

    if server_type == "sse":
        errors.append(error(path, name, "SSE is deprecated; use HTTP when the server supports it"))

    if not FULL_ENV_REFERENCE.fullmatch(url):
        parsed = urlparse(url)
        expected = "wss" if server_type == "ws" else "https"
        localhost = parsed.hostname in {"127.0.0.1", "::1", "localhost"}
        if parsed.scheme != expected and not localhost:
            errors.append(error(path, name, f"remote URL must use {expected} outside localhost"))
        if parsed.username is not None or parsed.password is not None:
            errors.append(error(path, name, "remote URL must not contain user information"))

    headers = config.get("headers", {})
    if not isinstance(headers, dict):
        errors.append(error(path, name, "headers must be an object"))
    else:
        for header_name, header_value in headers.items():
            if not isinstance(header_name, str) or not isinstance(header_value, str):
                errors.append(error(path, name, "header names and values must be strings"))
                continue
            if HIGH_CONFIDENCE_SECRET.search(header_value):
                errors.append(
                    error(path, name, f"header {header_name!r} contains a probable secret")
                )
            if SENSITIVE_NAME.search(header_name) and not SENSITIVE_TEMPLATE.fullmatch(
                header_value
            ):
                errors.append(
                    error(
                        path,
                        name,
                        f"sensitive header {header_name!r} must reference an environment variable",
                    )
                )
    return errors


def validate_stdio_args(path: Path, name: str, command: str, args: list[str]) -> list[str]:
    """Reject literal credentials and unpinned package-runner dependencies."""
    errors: list[str] = []
    for index, value in enumerate(args):
        if HIGH_CONFIDENCE_SECRET.search(value):
            errors.append(error(path, name, f"argument {index} contains a probable secret"))
        flag, separator, inline_value = value.partition("=")
        if SENSITIVE_NAME.search(flag.lstrip("-")) and flag.startswith("-"):
            candidate = (
                inline_value if separator else (args[index + 1] if index + 1 < len(args) else "")
            )
            if not FULL_ENV_REFERENCE.fullmatch(candidate):
                errors.append(
                    error(
                        path,
                        name,
                        f"sensitive argument {value!r} must use an environment reference",
                    )
                )

    executable = Path(command).name.lower()
    if executable not in PACKAGE_RUNNERS:
        return errors
    if any("@latest" in value or value.endswith(":latest") for value in args):
        errors.append(error(path, name, f"{executable} dependencies must not use latest tags"))
    if executable == "uvx" and "--from" in args:
        index = args.index("--from")
        package = args[index + 1] if index + 1 < len(args) else ""
        if not EXACT_PYTHON_PACKAGE.fullmatch(package):
            errors.append(error(path, name, "uvx --from dependency must use an exact == version"))
    elif executable == "uvx":
        package = next((value for value in args if not value.startswith("-")), "")
        if not EXACT_PYTHON_PACKAGE.fullmatch(package):
            errors.append(error(path, name, "uvx package must use an exact == version"))
    if executable == "npx":
        package = next((value for value in args if not value.startswith("-")), "")
        version_separator = package.rfind("@")
        version = package[version_separator + 1 :] if version_separator > 0 else ""
        if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?", version):
            errors.append(error(path, name, "npx package must include an exact @version"))
    return errors


def validate_stdio(path: Path, name: str, config: dict[str, Any]) -> list[str]:
    """Validate a local stdio MCP server."""
    errors: list[str] = []
    command = config.get("command")
    args = config.get("args", [])
    if not isinstance(command, str) or not command:
        errors.append(error(path, name, "stdio server requires a command"))
    elif Path(command).name.lower() in SHELL_COMMANDS:
        errors.append(error(path, name, "shell wrappers are not allowed as stdio commands"))

    if not isinstance(args, list) or not all(isinstance(value, str) for value in args):
        errors.append(error(path, name, "args must be an array of strings"))
    elif isinstance(command, str):
        errors.extend(validate_stdio_args(path, name, command, args))

    env = config.get("env", {})
    if not isinstance(env, dict):
        errors.append(error(path, name, "env must be an object"))
    else:
        for variable, value in env.items():
            if not isinstance(variable, str) or not isinstance(value, str):
                errors.append(error(path, name, "environment names and values must be strings"))
                continue
            if HIGH_CONFIDENCE_SECRET.search(value):
                errors.append(
                    error(
                        path,
                        name,
                        f"environment variable {variable!r} contains a probable secret",
                    )
                )
            if SENSITIVE_NAME.search(variable) and not FULL_ENV_REFERENCE.fullmatch(value):
                errors.append(
                    error(
                        path,
                        name,
                        f"sensitive environment variable {variable!r} "
                        "must be a direct environment reference",
                    )
                )
    return errors


def validate_server(path: Path, name: str, config: Any) -> list[str]:
    """Validate one MCP server entry."""
    if not isinstance(config, dict):
        return [error(path, name, "server configuration must be an object")]

    server_type = config.get("type")
    if server_type is None and "command" in config:
        server_type = "stdio"
    if not isinstance(server_type, str) or server_type not in ALLOWED_TYPES:
        return [error(path, name, f"type must be one of {sorted(ALLOWED_TYPES)}")]
    if "url" in config and "type" not in config:
        return [error(path, name, "URL-based servers must declare an explicit type")]

    errors = validate_timeout(path, name, config)
    if server_type in REMOTE_TYPES:
        errors.extend(validate_remote(path, name, config, server_type))
    else:
        errors.extend(validate_stdio(path, name, config))
    return errors


def validate_file(path: Path) -> list[str]:
    """Validate one project-format MCP configuration file."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [error(path, "", f"invalid JSON: {exc}")]
    if not isinstance(document, dict):
        return [error(path, "", "top-level value must be an object")]
    servers = document.get("mcpServers")
    if not isinstance(servers, dict):
        return [error(path, "", "top-level mcpServers must be an object")]

    errors: list[str] = []
    for name, config in servers.items():
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", name):
            errors.append(
                error(
                    path,
                    str(name),
                    "server name must use letters, numbers, underscores, or hyphens",
                )
            )
            continue
        if name == "workspace":
            errors.append(error(path, name, "server name 'workspace' is reserved by Claude Code"))
            continue
        errors.extend(validate_server(path, name, config))
    return errors


def main() -> int:
    """Validate available MCP configuration files."""
    existing = [path for path in CONFIG_FILES if path.exists()]
    if not existing:
        print("No project MCP configuration found; nothing to validate.")
        return 0

    errors = [item for path in existing for item in validate_file(path)]
    if errors:
        print("MCP configuration validation failed:", file=sys.stderr)
        for item in errors:
            print(f"- {item}", file=sys.stderr)
        return 1

    print("MCP configuration validation passed:")
    for path in existing:
        print(f"- {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
