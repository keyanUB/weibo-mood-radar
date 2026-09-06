"""Entry point used by the scheduled GitHub workflow."""

import os
from datetime import datetime
from pathlib import Path

from weibo_mood_radar.data_sources import load_snapshots
from weibo_mood_radar.data_sources.http import sync
from weibo_mood_radar.models import CHINA_TZ
from weibo_mood_radar.reporting import publish


def main() -> None:
    root = Path(".")
    today = datetime.now(CHINA_TZ).date()
    if os.environ.get("DATA_SOURCE_URL"):
        path = root / "data/snapshots/provider.json"
        sync(path, today)
        publish(load_snapshots(path), root, today)
        print("Published source-backed weekly/monthly reports.")
    else:
        publish([], root, today, preserve_existing=True)
        print("No source configured. Updated dates and missing-data status; no emotions invented.")


if __name__ == "__main__":
    main()
