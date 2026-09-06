from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Literal

Period = Literal["week", "month"]
EmotionName = Literal["joy", "anger", "sadness", "anxiety", "disgust", "surprise", "neutral"]
EMOTIONS: tuple[EmotionName, ...] = (
    "joy", "anger", "sadness", "anxiety", "disgust", "surprise", "neutral",
)
LABELS = dict(zip(EMOTIONS, ("喜悦", "愤怒", "悲伤", "焦虑", "厌恶", "惊讶", "中性/未识别")))
CHINA_TZ = timezone(timedelta(hours=8))


def china_time(value: datetime) -> datetime:
    return value.replace(tzinfo=CHINA_TZ) if value.tzinfo is None else value.astimezone(CHINA_TZ)


@dataclass(frozen=True)
class Engagement:
    likes: int = 0
    comments: int = 0
    reposts: int = 0


@dataclass(frozen=True)
class Comment:
    id: str
    text: str
    created_at: datetime
    engagement: Engagement = field(default_factory=Engagement)


@dataclass(frozen=True)
class HotPost:
    id: str
    text: str
    author: str
    created_at: datetime
    rank: int
    observed_at: datetime
    topics: tuple[str, ...] = ()
    engagement: Engagement = field(default_factory=Engagement)
    comments: tuple[Comment, ...] = ()
    event_id: str = ""
    event_title: str = ""
    source_url: str = ""


@dataclass(frozen=True)
class Snapshot:
    observed_at: datetime
    posts: tuple[HotPost, ...]
    is_demo: bool = False


@dataclass(frozen=True)
class MoodReport:
    period: Period
    period_id: str
    start_at: datetime
    end_at: datetime
    as_of: date
    is_demo: bool
    status: str
    coverage: dict[str, object]
    post_count: int
    comment_count: int
    scores: dict[EmotionName, float]
    events: list[dict[str, object]]
    model: str = "lexicon-v1 (uncalibrated baseline)"
