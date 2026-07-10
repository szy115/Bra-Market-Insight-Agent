from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from .crawler import (
    MarketScopeAuthenticationRequired,
    MarketScopeCaptureError,
    capture_marketscope,
)
from .opencli_client import OpenCLIClient, OpenCLIError, OpenCLIUnavailableError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="insight-marketscope",
        description=(
            "Capture MarketScope UI text and authenticated JSON responses through the "
            "OpenCLI Chrome Browser Bridge without reading Chrome cookies or profile files."
        ),
    )
    parser.add_argument("--opencli", default="", help="Optional path to opencli executable.")
    parser.add_argument("--profile", default="", help="Optional connected OpenCLI profile alias.")
    parser.add_argument("--timeout", type=int, default=60, help="Per-command timeout in seconds.")

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("doctor", help="Check OpenCLI and Browser Bridge connectivity.")

    capture = subparsers.add_parser("capture", help="Capture one or more MarketScope pages.")
    capture.add_argument("urls", nargs="+", help="MarketScope page URLs to load in background tabs.")
    capture.add_argument("--output", default="", help="Output JSON path; defaults under .cache/marketscope.")
    capture.add_argument("--session", default="marketscope", help="Safe OpenCLI session prefix.")
    capture.add_argument("--settle-seconds", type=int, default=5, help="XHR wait window, 1-30 seconds.")
    capture.add_argument("--chunk-size", type=int, default=40_000, help="Visible-page text cap.")
    capture.add_argument(
        "--max-body-chars",
        type=int,
        default=1_048_576,
        help="Maximum body characters requested from each captured response.",
    )
    capture.add_argument("--max-entries", type=int, default=100, help="Maximum API responses per page.")
    capture.add_argument(
        "--passive-only",
        action="store_true",
        help="Do not call the three audited GET-only fallback endpoints.",
    )
    capture.add_argument(
        "--keep-tab",
        action="store_true",
        help="Keep crawler-created Chrome tabs open for troubleshooting.",
    )
    return parser


def _print_json(payload: object, *, stream: object = sys.stdout) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2), file=stream)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        client = OpenCLIClient(
            args.opencli or None,
            profile=args.profile,
            timeout_seconds=args.timeout,
        )
        if args.command == "doctor":
            health = client.bridge_health()
            _print_json(health)
            return 0 if health.get("bridge_connected") else 2

        result = capture_marketscope(
            client,
            args.urls,
            output_path=Path(args.output) if args.output else None,
            session_prefix=args.session,
            settle_seconds=args.settle_seconds,
            chunk_size=args.chunk_size,
            max_body_chars=args.max_body_chars,
            max_entries=args.max_entries,
            probe_readonly=not args.passive_only,
            keep_tab=args.keep_tab,
        )
        _print_json(
            {
                "ok": True,
                "source_mode": result.source_mode,
                "output_path": str(result.output_path),
                "page_count": result.page_count,
                "api_entry_count": result.api_entry_count,
                "warnings": result.warnings,
            }
        )
        return 0
    except MarketScopeAuthenticationRequired as exc:
        _print_json({"ok": False, "code": "AUTH_REQUIRED", "message": str(exc)}, stream=sys.stderr)
        return 4
    except (OpenCLIUnavailableError, OpenCLIError) as exc:
        _print_json({"ok": False, "code": "OPENCLI_UNAVAILABLE", "message": str(exc)}, stream=sys.stderr)
        return 3
    except (MarketScopeCaptureError, ValueError) as exc:
        _print_json({"ok": False, "code": "CAPTURE_FAILED", "message": str(exc)}, stream=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
