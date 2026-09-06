from __future__ import annotations

import json
import os
from datetime import date, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from weibo_mood_radar.data_sources.snapshots import parse_payload


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def sync(output: Path, as_of: date) -> None:
    url = os.environ.get("DATA_SOURCE_URL", "")
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        raise ValueError("Configure DATA_SOURCE_URL as an HTTPS snapshot archive endpoint")
    start = (as_of.replace(day=1) - timedelta(days=1)).replace(day=1)
    query = [(k, v) for k, v in parse_qsl(parts.query) if k not in ("start", "end")]
    query += [("start", start.isoformat()), ("end", as_of.isoformat())]
    endpoint = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))
    headers = {"Accept": "application/json", "User-Agent": "weibo-mood-radar/0.2"}
    if os.environ.get("DATA_SOURCE_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["DATA_SOURCE_TOKEN"]
    try:
        with build_opener(NoRedirect()).open(Request(endpoint, headers=headers), timeout=90) as response:
            data = response.read(128 * 1024 * 1024 + 1)
    except (HTTPError, URLError, TimeoutError) as error:
        raise ValueError("Data source request failed; check endpoint, token, and provider availability") from None
    if len(data) > 128 * 1024 * 1024:
        raise ValueError("Snapshot response exceeds 128 MiB")
    payload = json.loads(data.decode("utf-8-sig"))
    snapshots = parse_payload(payload)
    if payload["is_demo"] or not snapshots:
        raise ValueError("The live provider must return non-demo snapshots")
    if any(not start <= s.observed_at.date() < as_of for s in snapshots):
        raise ValueError("Provider returned snapshots outside the requested [start, end) interval")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temporary.replace(output)
