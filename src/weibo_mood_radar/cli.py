from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from pathlib import Path

from weibo_mood_radar.analysis import build_report
from weibo_mood_radar.data_sources import load_snapshots
from weibo_mood_radar.data_sources.http import sync
from weibo_mood_radar.models import CHINA_TZ
from weibo_mood_radar.reporting import publish, render_report
from weibo_mood_radar.storage import write_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Weekly and monthly Weibo emotion reports")
    sub = parser.add_subparsers(dest="command", required=True)
    report = sub.add_parser("report", help="Create a single week or month report")
    report.add_argument("--input", required=True, type=Path)
    report.add_argument("--period", required=True, choices=["week", "month"])
    report.add_argument("--anchor", required=True, type=date.fromisoformat)
    report.add_argument("--output", required=True, type=Path)
    report.add_argument("--as-of", type=date.fromisoformat, default=datetime.now(CHINA_TZ).date())
    public = sub.add_parser("publish", help="Update README and report archives")
    source = public.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", type=Path)
    source.add_argument("--empty", action="store_true", help="Explicitly publish a no-data status")
    public.add_argument("--root", type=Path, default=Path("."))
    public.add_argument("--demo", action="store_true")
    public.add_argument("--as-of", type=date.fromisoformat, default=datetime.now(CHINA_TZ).date())
    fetch = sub.add_parser("sync", help="Fetch daily historical snapshots from an archive endpoint")
    fetch.add_argument("--output", type=Path, default=Path("data/snapshots/provider.json"))
    fetch.add_argument("--as-of", type=date.fromisoformat, default=datetime.now(CHINA_TZ).date())
    args = parser.parse_args()
    try:
        if args.command == "sync":
            sync(args.output, args.as_of)
            print("Validated source snapshots downloaded.")
        elif args.command == "publish":
            snapshots = load_snapshots(args.input) if args.input else []
            reports = publish(snapshots, args.root, args.as_of, args.demo)
            print(f"Updated README and {len(reports)} weekly/monthly reports.")
        else:
            anchor = datetime.combine(args.anchor, datetime.min.time(), tzinfo=CHINA_TZ)
            result = build_report(load_snapshots(args.input), args.period, anchor, args.as_of)
            if args.output.suffix != ".json":
                raise ValueError("--output must end in .json (a Markdown sibling is also written)")
            write_report(result, args.output)
            args.output.with_suffix(".md").write_text(render_report(result), encoding="utf-8")
            print(f"Wrote {result.period_id}: {result.comment_count} comments; {result.status}")
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.exit(1, f"Report update failed ({type(error).__name__}). Check input schema, paths, README markers, and data-source settings.\n")


if __name__ == "__main__":
    main()
