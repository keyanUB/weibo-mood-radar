from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from weibo_mood_radar.models import Comment, Engagement, HotPost, Snapshot, china_time


def timestamp(value: str) -> datetime:
    return china_time(datetime.fromisoformat(value))


def identifier(value: object) -> str:
    if not isinstance(value, (str, int)) or isinstance(value, bool) or not str(value).strip():
        raise ValueError("IDs must be non-empty strings or integers")
    return str(value)


def engagement(item: dict) -> Engagement:
    values = [item.get(key, 0) for key in ("likes", "comments", "reposts")]
    if any(type(value) is not int or value < 0 for value in values):
        raise ValueError("Engagement counts must be non-negative integers")
    return Engagement(*values)


def parse_payload(payload: dict) -> list[Snapshot]:
    if payload.get("schema_version") != 1:
        raise ValueError("Expected schema_version=1 and explicit daily snapshots")
    if type(payload.get("is_demo")) is not bool:
        raise ValueError("is_demo must be an explicit boolean")
    result = []
    for raw in payload["snapshots"]:
        observed = timestamp(raw["observed_at"])
        posts = {}
        for item in raw["posts"]:
            post_id = identifier(item["id"])
            rank = item["rank"]
            if type(rank) is not int or rank < 1:
                raise ValueError("Post rank must be a positive integer")
            created = timestamp(item["created_at"])
            if created > observed:
                raise ValueError("A post cannot be created after its snapshot")
            comments = {}
            for row in item.get("comments", []):
                comment = Comment(identifier(row["id"]), str(row["text"]),
                                  timestamp(row["created_at"]), engagement(row.get("engagement", {})))
                if not created <= comment.created_at <= observed:
                    raise ValueError("Comment timestamp must be between post creation and observation")
                if not comment.text.strip():
                    continue
                previous = comments.get(comment.id)
                if previous is None or comment.engagement.likes > previous.engagement.likes:
                    comments[comment.id] = comment
            post = HotPost(
                id=post_id, text=str(item["text"]), author="",
                created_at=created, rank=rank, observed_at=observed,
                topics=tuple(str(topic) for topic in item.get("topics", [])),
                engagement=engagement(item.get("engagement", {})),
                comments=tuple(sorted(comments.values(), key=lambda c: (-c.engagement.likes, c.id))[:100]),
                event_id=str(item.get("event_id", "")), event_title=str(item.get("event_title", "")),
                source_url=str(item.get("source_url", "")),
            )
            if post_id not in posts or post.rank < posts[post_id].rank:
                posts[post_id] = post
        result.append(Snapshot(observed, tuple(sorted(posts.values(), key=lambda p: (p.rank, p.id))[:30]), payload["is_demo"]))
    return normalize_snapshots(result)


def normalize_snapshots(snapshots: list[Snapshot]) -> list[Snapshot]:
    if len({item.is_demo for item in snapshots}) > 1:
        raise ValueError("Demo and live snapshots must not be mixed")
    by_day = {}
    for snapshot in snapshots:
        key = snapshot.observed_at.date()
        if key in by_day and snapshot != by_day[key]:
            raise ValueError(f"Multiple different snapshots for {key}; provide one daily snapshot")
        by_day[key] = snapshot
    return sorted(by_day.values(), key=lambda item: item.observed_at)


def load_snapshots(path: Path) -> list[Snapshot]:
    files = sorted(path.glob("*.json")) if path.is_dir() else [path]
    if not files:
        raise ValueError("No JSON snapshots found")
    snapshots = []
    for file in files:
        snapshots.extend(parse_payload(json.loads(file.read_text(encoding="utf-8-sig"))))
    return normalize_snapshots(snapshots)
