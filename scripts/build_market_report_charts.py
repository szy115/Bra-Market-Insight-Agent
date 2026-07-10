from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from insight_agent.report_charts import build_market_report_charts  # noqa: E402


def _extract_market_report_data(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise SystemExit("Input JSON must be an object.")
    if isinstance(payload.get("market_report_data"), dict):
        return payload["market_report_data"]
    if isinstance(payload.get("marketReportData"), dict):
        return payload["marketReportData"]
    if isinstance(payload.get("data"), dict):
        data = payload["data"]
        if isinstance(data.get("market_report_data"), dict):
            return data["market_report_data"]
        if isinstance(data.get("marketReportData"), dict):
            return data["marketReportData"]
        if data.get("schema_version") == "market_report_data.v1":
            return data
    if payload.get("schema_version") == "market_report_data.v1":
        return payload
    raise SystemExit("Could not find MarketReportData in input JSON.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build business chart specs from MarketReportData.")
    parser.add_argument("input", help="Path to MarketReportData JSON or a tool result containing it.")
    parser.add_argument("--output", "-o", help="Write chart specs JSON to this path. Defaults to stdout.")
    args = parser.parse_args()

    input_path = Path(args.input)
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    report_data = _extract_market_report_data(payload)
    chart_payload = build_market_report_charts(report_data)

    output = json.dumps(chart_payload, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(output + "\n", encoding="utf-8")
    else:
        print(output)


if __name__ == "__main__":
    main()
