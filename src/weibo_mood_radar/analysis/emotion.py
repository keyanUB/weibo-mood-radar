from __future__ import annotations

import math
import re

from weibo_mood_radar.models import EMOTIONS, EmotionName, Engagement

URL_RE = re.compile(r"https?://\S+")
SPACE_RE = re.compile(r"\s+")

LEXICON: dict[EmotionName, tuple[str, ...]] = {
    "joy": ("开心", "高兴", "支持", "喜欢", "太好了", "暖心", "期待", "赞", "稳了"),
    "anger": ("愤怒", "生气", "离谱", "过分", "气死", "抵制", "严查", "不满", "荒唐"),
    "sadness": ("难过", "心疼", "遗憾", "惋惜", "失望", "泪目", "悲伤", "可惜"),
    "anxiety": ("担心", "焦虑", "害怕", "恐慌", "怎么办", "不安", "危险", "风险"),
    "disgust": ("恶心", "反感", "无语", "讨厌", "讽刺", "恶劣", "下头", "垃圾"),
    "surprise": ("震惊", "惊讶", "没想到", "居然", "竟然", "离奇", "突然", "反转"),
    "neutral": (),
}

NEGATIONS = ("不", "没", "无", "别")
AMPLIFIERS = ("太", "非常", "特别", "真的", "超级")


class LexiconEmotionScorer:
    """Transparent baseline scorer for Chinese short social text."""

    def score(self, text: str) -> dict[EmotionName, float]:
        cleaned = normalize_text(text)
        raw_scores = {emotion: 0.0 for emotion in EMOTIONS}

        for emotion, words in LEXICON.items():
            if emotion == "neutral":
                continue
            for word in words:
                start = 0
                while True:
                    index = cleaned.find(word, start)
                    if index == -1:
                        break
                    raw_scores[emotion] += self._keyword_weight(cleaned, index)
                    start = index + len(word)

        emotional_total = sum(raw_scores[emotion] for emotion in EMOTIONS if emotion != "neutral")
        if emotional_total == 0:
            raw_scores["neutral"] = 1.0
        else:
            raw_scores["neutral"] = max(0.05, 1.0 / (1.0 + emotional_total))

        total = sum(raw_scores.values())
        return {emotion: round((raw_scores[emotion] / total) * 100, 2) for emotion in EMOTIONS}

    def _keyword_weight(self, text: str, index: int) -> float:
        prefix = text[max(0, index - 4) : index]
        weight = 1.0
        if any(word in prefix for word in AMPLIFIERS):
            weight += 0.4
        if any(word in prefix for word in NEGATIONS):
            weight *= 0.45
        return weight


def normalize_text(text: str) -> str:
    text = URL_RE.sub("", text)
    text = SPACE_RE.sub(" ", text)
    return text.strip()


def engagement_weight(engagement: Engagement, source_type: str) -> float:
    if source_type == "comment":
        signal = engagement.likes
    else:
        signal = engagement.likes + engagement.comments + engagement.reposts
    return round(1 + math.log1p(max(signal, 0)), 4)
