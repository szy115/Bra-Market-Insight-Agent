from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ANSI_ESCAPE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


class OpenCLIError(RuntimeError):
    """An OpenCLI command failed or returned malformed output."""


class OpenCLIUnavailableError(OpenCLIError):
    """OpenCLI or its Chrome Browser Bridge is unavailable."""


@dataclass(frozen=True)
class CommandOutput:
    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


CommandRunner = Callable[[Sequence[str], int], CommandOutput]


def strip_ansi(value: str) -> str:
    return ANSI_ESCAPE.sub("", value)


def parse_json_document(value: str) -> Any:
    """Parse the first complete JSON document while tolerating CLI banners."""

    cleaned = strip_ansi(value).lstrip("\ufeff")
    decoder = json.JSONDecoder()
    for index, character in enumerate(cleaned):
        if character not in "[{":
            continue
        try:
            parsed, _end = decoder.raw_decode(cleaned[index:])
        except json.JSONDecodeError:
            continue
        return parsed
    diagnostic = cleaned.strip().replace("\r", " ").replace("\n", " ")[:500]
    raise OpenCLIError(f"OPENCLI_OUTPUT_INVALID: no JSON document found: {diagnostic}")


def find_opencli(explicit: str | Path | None = None) -> str:
    configured = str(explicit or os.getenv("OPENCLI_PATH", "")).strip()
    if configured:
        candidate = Path(configured).expanduser()
        if candidate.is_file():
            return str(candidate)
        resolved = shutil.which(configured)
        if resolved:
            return resolved
        raise OpenCLIUnavailableError(f"OpenCLI executable was not found: {configured}")

    names = ("opencli.cmd", "opencli.exe", "opencli") if os.name == "nt" else ("opencli",)
    for name in names:
        resolved = shutil.which(name)
        if resolved:
            return resolved
    raise OpenCLIUnavailableError(
        "OpenCLI is not installed or is not on PATH. Install Agent Reach/OpenCLI first."
    )


def build_opencli_command_prefix(executable: str | Path) -> tuple[str, ...]:
    """Bypass Windows npm .cmd shims so JavaScript is never parsed by cmd.exe."""

    resolved = Path(executable)
    if os.name != "nt" or resolved.suffix.lower() not in {".cmd", ".bat"}:
        return (str(resolved),)

    package_root = resolved.parent / "node_modules" / "@jackwener" / "opencli"
    package_json = package_root / "package.json"
    try:
        package_data = json.loads(package_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise OpenCLIUnavailableError(
            "Refusing to execute an npm .cmd/.bat shim because Windows would parse browser arguments. "
            "Reinstall OpenCLI so its Node entry point is available."
        ) from None
    bin_config = package_data.get("bin") if isinstance(package_data, dict) else None
    relative_entry = bin_config.get("opencli") if isinstance(bin_config, dict) else None
    if not isinstance(relative_entry, str) or not relative_entry:
        raise OpenCLIUnavailableError("OpenCLI package.json does not define its Node entry point.")
    entry = package_root / relative_entry
    node = resolved.parent / "node.exe"
    node_executable = str(node) if node.is_file() else shutil.which("node")
    if not node_executable or not entry.is_file():
        raise OpenCLIUnavailableError(
            "OpenCLI's Node executable or JavaScript entry point could not be resolved safely."
        )
    return (node_executable, str(entry))


def _default_runner(command: Sequence[str], timeout_seconds: int) -> CommandOutput:
    creationflags = 0
    if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
        creationflags = subprocess.CREATE_NO_WINDOW
    try:
        completed = subprocess.run(  # noqa: S603
            list(command),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
            shell=False,
            creationflags=creationflags,
        )
    except subprocess.TimeoutExpired as exc:
        raise OpenCLIError(f"OpenCLI command timed out after {timeout_seconds}s") from exc
    except OSError as exc:
        raise OpenCLIUnavailableError(f"Could not launch OpenCLI: {exc}") from exc
    return CommandOutput(
        command=tuple(str(part) for part in command),
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


class OpenCLIClient:
    """Thin, shell-free wrapper around the OpenCLI Chrome Browser Bridge."""

    def __init__(
        self,
        executable: str | Path | None = None,
        *,
        profile: str = "",
        timeout_seconds: int = 60,
        runner: CommandRunner | None = None,
    ) -> None:
        self.executable = find_opencli(executable)
        self.command_prefix = build_opencli_command_prefix(self.executable)
        self.profile = self._validate_profile(profile)
        self.timeout_seconds = max(5, min(int(timeout_seconds), 300))
        self._runner = runner or _default_runner

    @staticmethod
    def _validate_profile(profile: str) -> str:
        normalized = profile.strip()
        if normalized and not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", normalized):
            raise ValueError("OpenCLI profile aliases may only contain letters, digits, '_' and '-'.")
        return normalized

    @staticmethod
    def validate_session(session: str) -> str:
        normalized = session.strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", normalized):
            raise ValueError("Browser session names may only contain letters, digits, '_' and '-'.")
        return normalized

    def run(
        self,
        args: Sequence[str],
        *,
        timeout_seconds: int | None = None,
        allow_nonzero: bool = False,
    ) -> CommandOutput:
        command = [*self.command_prefix, *(str(part) for part in args)]
        output = self._runner(command, timeout_seconds or self.timeout_seconds)
        if output.returncode != 0 and not allow_nonzero:
            diagnostic = strip_ansi(output.stderr or output.stdout).strip()[-1200:]
            raise OpenCLIError(
                f"OpenCLI command failed with exit code {output.returncode}: {diagnostic}"
            )
        return output

    def run_json(
        self,
        args: Sequence[str],
        *,
        timeout_seconds: int | None = None,
        allow_nonzero: bool = False,
    ) -> Any:
        output = self.run(
            args,
            timeout_seconds=timeout_seconds,
            allow_nonzero=allow_nonzero,
        )
        try:
            return parse_json_document(output.stdout)
        except OpenCLIError:
            if output.returncode != 0:
                diagnostic = strip_ansi(output.stderr or output.stdout).strip()[-1200:]
                raise OpenCLIError(
                    f"OpenCLI command failed with exit code {output.returncode}: {diagnostic}"
                ) from None
            raise

    def bridge_health(self) -> dict[str, Any]:
        status = self.run(["daemon", "status"])
        status_text = strip_ansi(f"{status.stdout}\n{status.stderr}")
        connected = bool(re.search(r"^\s*Extension:\s*connected\b", status_text, flags=re.I | re.M))

        profiles: list[str] = []
        profile_output = self.run(["profile", "list"], allow_nonzero=True)
        profile_text = strip_ansi(f"{profile_output.stdout}\n{profile_output.stderr}")
        for match in re.finditer(
            r"^\s*([A-Za-z0-9_-]+)\s+(?:—|-)\s+connected\b",
            profile_text,
            flags=re.I | re.M,
        ):
            profiles.append(match.group(1))

        return {
            "opencli_path": self.executable,
            "bridge_connected": connected,
            "profiles": sorted(set(profiles)),
            "selected_profile": self.profile or None,
        }

    @staticmethod
    def network_cache_path(session: str) -> Path:
        normalized_session = OpenCLIClient.validate_session(session)
        configured = os.getenv("OPENCLI_CACHE_DIR", "").strip()
        base = Path(configured).expanduser() if configured else Path.home() / ".opencli" / "cache"
        cache_root = (base / "browser-network").resolve()
        target = (cache_root / f"{normalized_session}.json").resolve()
        if target.parent != cache_root:
            raise OpenCLIError("Resolved OpenCLI cache path escaped the browser-network directory.")
        return target

    def delete_network_cache(self, session: str) -> bool:
        target = self.network_cache_path(session)
        try:
            target.unlink(missing_ok=True)
        except OSError as exc:
            raise OpenCLIError(f"Could not remove temporary OpenCLI network cache: {exc}") from exc
        return not target.exists()

    def browser_args(self, session: str, *args: str) -> list[str]:
        normalized_session = self.validate_session(session)
        prefix: list[str] = []
        if self.profile:
            prefix.extend(["--profile", self.profile])
        return [*prefix, "browser", normalized_session, *args]

    def browser_text(
        self,
        session: str,
        *args: str,
        timeout_seconds: int | None = None,
        allow_nonzero: bool = False,
    ) -> CommandOutput:
        return self.run(
            self.browser_args(session, *args),
            timeout_seconds=timeout_seconds,
            allow_nonzero=allow_nonzero,
        )

    def browser_json(
        self,
        session: str,
        *args: str,
        timeout_seconds: int | None = None,
        allow_nonzero: bool = False,
    ) -> Any:
        return self.run_json(
            self.browser_args(session, *args),
            timeout_seconds=timeout_seconds,
            allow_nonzero=allow_nonzero,
        )
