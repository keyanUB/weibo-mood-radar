from __future__ import annotations

import html
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

from weibo_mood_radar.analysis.aggregate import build_report, period_window
from weibo_mood_radar.models import CHINA_TZ, EMOTIONS, LABELS, MoodReport, Snapshot
from weibo_mood_radar.storage.json_report import write_report

STATUS = {"no_data": "暂无数据", "in_progress": "月内累计/周期未结束",
          "complete": "目标样本齐全", "partial": "样本不完整"}
FOLDERS = {"week": "weekly", "month": "monthly"}


def safe_text(value: object) -> str:
    text = html.escape(str(value), quote=True)
    text = re.sub(r"\s+", " ", text).strip()
    for char in ("\\", "|", "[", "]", "*", "_", "`"):
        text = text.replace(char, "\\" + char)
    return text


def safe_url(value: str) -> str | None:
    parts = urlsplit(value)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        return None
    # Only source links to Weibo are published; arbitrary external links stay out.
    if not any(parts.hostname == host or parts.hostname.endswith("." + host)
               for host in ("weibo.com", "weibo.cn")):
        return None
    return value.replace("(", "%28").replace(")", "%29").replace("<", "%3C").replace(">", "%3E")


def dominant(scores: dict, count: int) -> str:
    if not count:
        return "暂无评论数据"
    top = sorted(EMOTIONS, key=lambda key: scores[key], reverse=True)[:3]
    return "、".join(f"{LABELS[key]} {scores[key]:.2f}" for key in top)


def report_body(report: MoodReport, limit: int | None = None) -> str:
    end = (report.end_at - timedelta(days=1)).date()
    c = report.coverage
    lines = [
        f"**统计时间：{report.start_at.date()} 至 {end}（北京时间）**",
        "",
        f"数据：{'演示样本，非真实舆情' if report.is_demo else '尚无采样数据' if report.status == 'no_data' else '导入的微博样本'} | "
        f"状态：{STATUS[report.status]} | 截止：{report.as_of} 00:00（不含）",
        "",
        f"采样覆盖 **{c['observed_days']}/{c['expected_days']} 天**；"
        f"去重微博 **{report.post_count}** 条；去重评论 **{report.comment_count}** 条。",
        "",
        f"采样记录：微博 {c['post_samples']}/{c['post_target']}；"
        f"评论 {c['comment_samples']}/{c['comment_target']}（实收/目标，去重前）。",
        "",
        f"主要情绪：**{dominant(report.scores, report.comment_count)}**。",
        "",
    ]
    if report.comment_count:
        lines += ["| 喜悦 | 愤怒 | 悲伤 | 焦虑 | 厌恶 | 惊讶 | 中性/未识别 |",
                  "| ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
                  "| " + " | ".join(f"{report.scores[key]:.2f}" for key in EMOTIONS) + " |", ""]
    else:
        lines += ["本周期没有可评分的评论，不作情绪判断。", ""]
    if report.events:
        lines += ["| 热点事件 | 事件摘要（来源原文节选） | 评论数 | 主要情绪（0–100） |",
                  "| --- | --- | ---: | --- |"]
        for event in report.events[:limit]:
            lines.append(f"| {safe_text(event['title'])} | {safe_text(event['summary'])} | "
                         f"{event['comment_count']} | {dominant(event['scores'], event['comment_count'])} |")
        lines += [""]
    if limit is None:
        for number, event in enumerate(report.events, 1):
            lines += [f"### {number}. {safe_text(event['title'])}", "", safe_text(event["summary"]), "",
                      f"关联微博 {event['post_count']} 条，评论 {event['comment_count']} 条。", ""]
            if event["comment_count"]:
                lines += ["| 情绪 | 得分 |", "| --- | ---: |"]
                lines += [f"| {LABELS[key]} | {event['scores'][key]:.2f} |" for key in EMOTIONS]
                lines += [""]
            urls = [safe_url(url) for url in event["source_urls"]]
            links = [f"[微博来源 {i}](<{url}>)" for i, url in enumerate(filter(None, urls), 1)]
            if links:
                lines += [" · ".join(links), ""]
    if c["missing_dates"]:
        lines += ["缺失采样日期：" + "、".join(c["missing_dates"]), ""]
    lines += [
        "说明：以上为高赞评论样本的词典情绪指数，不是人口比例，也不代表全体网民。"
        "未命中情绪词归入“中性/未识别”；讽刺、反话与语境尚未经过模型校准。",
        "",
    ]
    return "\n".join(lines)


def render_report(report: MoodReport) -> str:
    label = "周报" if report.period == "week" else "月报"
    return f"# {report.period_id} {label}" + ("（演示）" if report.is_demo else "") + "\n\n" + report_body(report)


def replace_block(content: str, name: str, body: str) -> str:
    start, end = f"<!-- {name}:START -->", f"<!-- {name}:END -->"
    if content.count(start) != 1 or content.count(end) != 1 or content.index(start) >= content.index(end):
        raise ValueError(f"README must contain exactly one ordered {name} marker pair")
    before, rest = content.split(start)
    _, after = rest.split(end)
    return before + start + "\n\n" + body.strip() + "\n\n" + end + after


def archive_index(root: Path) -> None:
    lines = ["# 周报与月报归档", "", "演示数据与真实数据分开归档；月内累计报告会在后续运行时更新。", "",
             "| 类型 | 周期 | 数据 | 状态 | 覆盖天数 | 评论数 | 报告 |", "| --- | --- | --- | --- | ---: | ---: | --- |"]
    for path in sorted(root.glob("**/*.json"), reverse=True):
        data = json.loads(path.read_text(encoding="utf-8"))
        rel = path.relative_to(root).as_posix()
        c = data["coverage"]
        lines.append(f"| {'周报' if data['period'] == 'week' else '月报'} | {data['period_id']} | "
                     f"{'演示' if data['is_demo'] else '待采样' if data['status'] == 'no_data' else '真实导入'} | {STATUS[data['status']]} | "
                     f"{c['observed_days']}/{c['expected_days']} | {data['comment_count']} | "
                     f"[阅读]({rel[:-5]}.md) · [JSON]({rel}) |")
    (root / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def publish(snapshots: list[Snapshot], root: Path, as_of: date, demo: bool = False,
            preserve_existing: bool = False) -> list[MoodReport]:
    if preserve_existing and snapshots:
        raise ValueError("preserve_existing is only for missing-source status updates")
    if any(s.is_demo != demo for s in snapshots):
        raise ValueError("Use --demo for demo input; do not publish demo data as live")
    readme_path = root / "README.md"
    readme = readme_path.read_text(encoding="utf-8")
    marker = "DEMO" if demo else "LATEST"
    replace_block(readme, marker, "")
    anchor = datetime.combine(as_of, datetime.min.time(), tzinfo=CHINA_TZ)
    current_week, _ = period_window("week", anchor)
    current_month, _ = period_window("month", anchor)
    latest_week = current_week - timedelta(days=7)
    previous_month, _ = period_window("month", current_month - timedelta(days=1))
    targets = {("week", latest_week), ("month", current_month), ("month", previous_month)}
    for snapshot in snapshots:
        if snapshot.observed_at.date() < as_of:
            for period in ("week", "month"):
                start, end = period_window(period, snapshot.observed_at)
                if period == "month" or end <= anchor:
                    targets.add((period, start))
    reports = [build_report(snapshots, period, start, as_of, demo) for period, start in sorted(targets)]
    reports_root = root / "reports"
    base = reports_root / "demo" if demo else reports_root
    if preserve_existing:
        for index, report in enumerate(reports):
            path = base / FOLDERS[report.period] / (report.period_id + ".json")
            if path.exists():
                old = json.loads(path.read_text(encoding="utf-8"))
                if not old["coverage"]["observed_days"]:
                    continue
                old["start_at"] = datetime.fromisoformat(old["start_at"])
                old["end_at"] = datetime.fromisoformat(old["end_at"])
                old["as_of"] = date.fromisoformat(old["as_of"])
                reports[index] = MoodReport(**old)
    # Validate every replacement before writing anything, to catch truncated source feeds.
    for report in reports:
        path = base / FOLDERS[report.period] / (report.period_id + ".json")
        if path.exists():
            old = json.loads(path.read_text(encoding="utf-8"))
            if old["as_of"] > as_of.isoformat() or old["coverage"]["observed_days"] > report.coverage["observed_days"]:
                raise ValueError(f"Refusing to replace a newer or more complete report: {path.name}")
    for report in reports:
        path = base / FOLDERS[report.period] / (report.period_id + ".json")
        write_report(report, path)
        path.with_suffix(".md").write_text(render_report(report), encoding="utf-8")

    def report_link(report: MoodReport) -> str:
        rel = (base / FOLDERS[report.period] / report.period_id).relative_to(root).as_posix()
        return f"[完整报告]({rel}.md) · [JSON]({rel}.json)"

    weekly = next(r for r in reports if r.period == "week" and r.start_at == latest_week)
    monthly = next(r for r in reports if r.period == "month" and r.start_at == current_month)
    closed = next(r for r in reports if r.period == "month" and r.start_at == previous_month)
    body = ("### 演示周报\n\n" if demo else "### 最新已结束周\n\n")
    if preserve_existing:
        body += f"> 更新检查：{as_of}（北京时间）。数据源未配置；保留已有报告，新增周期显示暂无数据。\n\n"
    body += report_body(weekly, limit=10) + "\n" + report_link(weekly) + "\n\n"
    body += "### 月度聚合\n\n"
    for report in (monthly, closed):
        body += f"**{report.period_id}** · {STATUS[report.status]} · 覆盖 {report.coverage['observed_days']}/{report.coverage['expected_days']} 天\n\n"
        body += f"{dominant(report.scores, report.comment_count)} · {report_link(report)}\n\n"
    body += "[全部周报/月报归档](reports/README.md)"
    readme_path.write_text(replace_block(readme, marker, body), encoding="utf-8")
    archive_index(reports_root)
    return reports
