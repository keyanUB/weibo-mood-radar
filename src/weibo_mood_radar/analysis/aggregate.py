from __future__ import annotations

from datetime import date, datetime, timedelta

from weibo_mood_radar.analysis.emotion import LexiconEmotionScorer, engagement_weight
from weibo_mood_radar.data_sources.snapshots import normalize_snapshots
from weibo_mood_radar.models import CHINA_TZ, EMOTIONS, MoodReport, Period, Snapshot, china_time


def period_window(period: Period, anchor: datetime) -> tuple[datetime, datetime]:
    start = china_time(anchor).replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "week":
        start -= timedelta(days=start.weekday())
        return start, start + timedelta(days=7)
    if period == "month":
        start = start.replace(day=1)
        return start, (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    raise ValueError("Only week and month reports are supported")


def period_id(period: Period, start: datetime) -> str:
    if period == "month":
        return start.strftime("%Y-%m")
    year, week, _ = start.isocalendar()
    return f"{year}-W{week:02d}"


def average(rows: list[tuple[dict, float]]) -> dict:
    weight = sum(row[1] for row in rows)
    return {emotion: round(sum(scores[emotion] * w for scores, w in rows) / weight, 2)
            if weight else 0.0 for emotion in EMOTIONS}


def build_report(snapshots: list[Snapshot], period: Period, anchor: datetime | None = None,
                 as_of: date | None = None, is_demo: bool = False) -> MoodReport:
    snapshots = normalize_snapshots(snapshots)
    anchor = anchor or datetime.now(CHINA_TZ)
    as_of = as_of or datetime.now(CHINA_TZ).date()
    start, end = period_window(period, anchor)
    scoped = [s for s in snapshots if start <= s.observed_at < end and s.observed_at.date() < as_of]
    posts = {}
    comments = {}
    for snapshot in scoped:
        for post in snapshot.posts:
            posts[post.id] = post
            for comment in post.comments:
                # Later observations replace the same comment, never multiply its vote.
                comments[(post.id, comment.id)] = comment
    scorer = LexiconEmotionScorer()
    scored = {key: (scorer.score(comment.text), engagement_weight(comment.engagement, "comment"))
              for key, comment in comments.items()}
    groups = {}
    for post in posts.values():
        key = ("event", post.event_id) if post.event_id else ("post", post.id)
        groups.setdefault(key, []).append(post)
    events = []
    for event_posts in groups.values():
        ids = {post.id for post in event_posts}
        rows = [row for key, row in scored.items() if key[0] in ids]
        lead = min(event_posts, key=lambda p: (p.rank, p.id))
        scores = average(rows)
        events.append({
            "title": lead.event_title or lead.text[:72],
            "summary": lead.text[:240],
            "summary_method": "source_excerpt",
            "post_count": len(event_posts), "comment_count": len(rows),
            "best_rank": min(p.rank for p in event_posts),
            "dominant_emotion": max(EMOTIONS, key=scores.get) if rows else None,
            "scores": scores,
            "source_urls": sorted({p.source_url for p in event_posts if p.source_url}),
        })
    events.sort(key=lambda e: (-e["comment_count"], e["best_rank"], e["title"]))
    days = sorted({s.observed_at.date() for s in scoped})
    expected = [start.date() + timedelta(days=i) for i in range((end - start).days)]
    missing = [day.isoformat() for day in expected if day < as_of and day not in days]
    post_samples = sum(len(s.posts) for s in scoped)
    comment_samples = sum(len(p.comments) for s in scoped for p in s.posts)
    filled = len(days) == len(expected) and all(len(s.posts) == 30 and all(len(p.comments) == 100 for p in s.posts) for s in scoped)
    status = "no_data" if not scoped else "in_progress" if end.date() > as_of else "complete" if filled else "partial"
    return MoodReport(
        period=period, period_id=period_id(period, start), start_at=start, end_at=end,
        as_of=as_of, is_demo=snapshots[0].is_demo if snapshots else is_demo, status=status,
        coverage={"observed_days": len(days), "expected_days": len(expected), "missing_dates": missing,
                  "post_samples": post_samples, "post_target": len(expected) * 30,
                  "comment_samples": comment_samples, "comment_target": len(expected) * 3000},
        post_count=len(posts), comment_count=len(comments), scores=average(list(scored.values())), events=events,
    )
