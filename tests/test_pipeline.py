import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

from weibo_mood_radar.analysis import build_report
from weibo_mood_radar.analysis.aggregate import period_window
from weibo_mood_radar.analysis.emotion import LexiconEmotionScorer
from weibo_mood_radar.data_sources import load_snapshots
from weibo_mood_radar.data_sources.snapshots import parse_payload
from weibo_mood_radar.data_sources.http import sync
from weibo_mood_radar.reporting import publish, render_report, replace_block, safe_url

ROOT = Path(__file__).resolve().parents[1]


def payload():
    return {
        "schema_version": 1, "is_demo": False,
        "snapshots": [{
            "observed_at": "2026-06-01T23:30:00+08:00",
            "posts": [{
                "id": "p1", "rank": 1, "created_at": "2026-05-01T10:00:00+08:00",
                "text": "愤怒！", "event_id": "event-a", "event_title": "测试事件",
                "comments": [{"id": "c1", "created_at": "2026-05-01T11:00:00+08:00",
                              "text": "开心", "engagement": {"likes": 10}}],
            }],
        }],
    }


class AggregationTests(unittest.TestCase):
    def test_only_week_month_and_iso_year(self):
        for invalid in ("day", "year"):
            with self.assertRaises(ValueError):
                period_window(invalid, datetime(2026, 1, 1))
        report = build_report([], "week", datetime(2021, 1, 1), date(2021, 1, 4))
        self.assertEqual(report.period_id, "2020-W53")
        self.assertEqual(report.start_at.date(), date(2020, 12, 28))

    def test_leap_month_and_year_end(self):
        start, end = period_window("month", datetime(2024, 2, 15))
        self.assertEqual((end - start).days, 29)
        _, end = period_window("month", datetime(2026, 12, 31))
        self.assertEqual(end.date(), date(2027, 1, 1))

    def test_observation_date_and_comment_only_scoring(self):
        report = build_report(parse_payload(payload()), "week", datetime(2026, 6, 1), date(2026, 6, 8))
        self.assertEqual(report.post_count, 1)
        self.assertEqual(report.comment_count, 1)
        self.assertGreater(report.scores["joy"], 0)
        self.assertEqual(report.scores["anger"], 0)

    def test_utc_and_exclusive_cutoff(self):
        raw = payload()
        raw["snapshots"][0]["observed_at"] = "2026-05-31T16:30:00Z"
        snapshots = parse_payload(raw)
        report = build_report(snapshots, "month", datetime(2026, 6, 1), date(2026, 6, 2))
        self.assertEqual(report.comment_count, 1)
        before = build_report(snapshots, "month", datetime(2026, 6, 1), date(2026, 6, 1))
        self.assertEqual(before.comment_count, 0)

    def test_dedup_uses_latest_observation(self):
        raw = payload()
        second = copy.deepcopy(raw["snapshots"][0])
        second["observed_at"] = "2026-06-02T23:30:00+08:00"
        second["posts"][0]["comments"][0]["text"] = "愤怒"
        raw["snapshots"].append(second)
        report = build_report(parse_payload(raw), "week", datetime(2026, 6, 1), date(2026, 6, 8))
        self.assertEqual(report.comment_count, 1)
        self.assertEqual(report.coverage["comment_samples"], 2)
        self.assertEqual(report.scores["joy"], 0)
        self.assertGreater(report.scores["anger"], 0)

    def test_month_deduplicates_across_weeks(self):
        raw = payload()
        second = copy.deepcopy(raw["snapshots"][0])
        second["observed_at"] = "2026-06-09T23:30:00+08:00"
        raw["snapshots"].append(second)
        month = build_report(parse_payload(raw), "month", datetime(2026, 6, 1), date(2026, 7, 1))
        self.assertEqual(month.comment_count, 1)
        self.assertEqual(month.coverage["observed_days"], 2)

    def test_event_grouping_without_topic_conflation(self):
        raw = payload()
        second = copy.deepcopy(raw["snapshots"][0]["posts"][0])
        second["id"] = "p2"
        second["rank"] = 2
        raw["snapshots"][0]["posts"].append(second)
        report = build_report(parse_payload(raw), "week", datetime(2026, 6, 1), date(2026, 6, 8))
        self.assertEqual(len(report.events), 1)
        self.assertEqual(report.events[0]["comment_count"], 2)
        second["event_id"] = ""
        report = build_report(parse_payload(raw), "week", datetime(2026, 6, 1), date(2026, 6, 8))
        self.assertEqual(len(report.events), 2)

    def test_missing_and_empty_comments(self):
        empty = build_report([], "week", datetime(2026, 6, 1), date(2026, 6, 8))
        self.assertEqual(empty.status, "no_data")
        self.assertEqual(len(empty.coverage["missing_dates"]), 7)
        self.assertIn("不作情绪判断", render_report(empty))
        raw = payload()
        raw["snapshots"][0]["posts"][0]["comments"] = []
        report = build_report(parse_payload(raw), "week", datetime(2026, 6, 1), date(2026, 6, 8))
        self.assertIsNone(report.events[0]["dominant_emotion"])
        self.assertEqual(report.status, "partial")

    def test_sample_fixture_week_month(self):
        snapshots = load_snapshots(ROOT / "examples/snapshots.json")
        week = build_report(snapshots, "week", datetime(2026, 6, 1), date(2026, 6, 8))
        self.assertEqual((week.post_count, week.comment_count), (3, 8))
        self.assertEqual(week.coverage["observed_days"], 3)
        self.assertEqual(week.coverage["comment_samples"], 14)
        self.assertTrue(week.is_demo)
        self.assertAlmostEqual(sum(week.scores.values()), 100, delta=0.05)
        month = build_report(snapshots, "month", datetime(2026, 6, 1), date(2026, 6, 8))
        self.assertEqual(month.status, "in_progress")


class SourceTests(unittest.TestCase):
    def test_top_30_top_100_and_duplicate_ids(self):
        raw = payload()
        template = raw["snapshots"][0]["posts"][0]
        template["comments"] = [
            {"id": f"c{i:03d}", "created_at": "2026-05-02T10:00:00+08:00",
             "text": "支持", "engagement": {"likes": i}}
            for i in range(110)
        ]
        raw["snapshots"][0]["posts"] = [
            dict(copy.deepcopy(template), id=f"p{i:03d}", rank=i)
            for i in range(35, 0, -1)
        ]
        raw["snapshots"][0]["posts"].append(copy.deepcopy(raw["snapshots"][0]["posts"][-1]))
        posts = parse_payload(raw)[0].posts
        self.assertEqual(len(posts), 30)
        self.assertEqual(posts[0].rank, 1)
        self.assertEqual(posts[-1].rank, 30)
        self.assertEqual(len(posts[0].comments), 100)
        self.assertEqual(posts[0].comments[0].engagement.likes, 109)
        self.assertEqual(posts[0].comments[-1].engagement.likes, 10)

    def test_invalid_engagement_and_future_text(self):
        raw = payload()
        raw["snapshots"][0]["posts"][0]["comments"][0]["engagement"]["likes"] = -1
        with self.assertRaises(ValueError):
            parse_payload(raw)
        raw = payload()
        raw["snapshots"][0]["posts"][0]["comments"][0]["created_at"] = "2027-01-01T00:00:00"
        with self.assertRaises(ValueError):
            parse_payload(raw)

    def test_duplicate_day_and_demo_mix(self):
        raw = payload()
        raw["snapshots"].append(copy.deepcopy(raw["snapshots"][0]))
        self.assertEqual(len(parse_payload(raw)), 1)
        raw["snapshots"][1]["observed_at"] = "2026-06-01T22:00:00+08:00"
        with self.assertRaises(ValueError):
            parse_payload(raw)
        from weibo_mood_radar.data_sources.snapshots import normalize_snapshots
        live = parse_payload(payload())
        demo_raw = payload()
        demo_raw["is_demo"] = True
        with self.assertRaises(ValueError):
            normalize_snapshots(live + parse_payload(demo_raw))

    def test_sync_request_and_validation_without_network(self):
        raw = payload()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "provider.json"
            with patch.dict(os.environ, {"DATA_SOURCE_URL": "https://provider.example/archive", "DATA_SOURCE_TOKEN": "test-token"}):
                with patch("weibo_mood_radar.data_sources.http.build_opener") as builder:
                    builder.return_value.open.return_value.__enter__.return_value.read.return_value = json.dumps(raw).encode()
                    sync(output, date(2026, 6, 8))
                    request = builder.return_value.open.call_args.args[0]
                    self.assertIn("start=2026-05-01", request.full_url)
                    self.assertIn("end=2026-06-08", request.full_url)
                    self.assertEqual(request.get_header("Authorization"), "Bearer test-token")
            self.assertEqual(len(load_snapshots(output)), 1)

    def test_unknown_text_and_amplifier(self):
        scorer = LexiconEmotionScorer()
        self.assertEqual(scorer.score("今天是星期一")["neutral"], 100)
        self.assertGreater(scorer.score("非常开心")["joy"], scorer.score("开心")["joy"])


class PublishTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "README.md").write_text(
            "# Keep this introduction\n\n<!-- LATEST:START -->\nold\n<!-- LATEST:END -->\n\n"
            "<!-- DEMO:START -->\ndemo\n<!-- DEMO:END -->\n", encoding="utf-8")

    def test_idempotent_publish_and_no_raw_comments(self):
        publish(parse_payload(payload()), self.root, date(2026, 6, 8))
        first = {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        publish(parse_payload(payload()), self.root, date(2026, 6, 8))
        second = {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(first, second)
        readme = (self.root / "README.md").read_text(encoding="utf-8")
        self.assertIn("# Keep this introduction", readme)
        self.assertIn("2026-06-01 至 2026-06-07", readme)
        report = (self.root / "reports/weekly/2026-W23.json").read_text(encoding="utf-8")
        self.assertNotIn('"c1"', report)
        self.assertNotIn('"text"', report)
        self.assertTrue((self.root / "reports/README.md").exists())

    def test_guard_demo_and_coverage_regression(self):
        demo = payload()
        demo["is_demo"] = True
        with self.assertRaises(ValueError):
            publish(parse_payload(demo), self.root, date(2026, 6, 8))
        publish(parse_payload(payload()), self.root, date(2026, 6, 8))
        before = (self.root / "README.md").read_bytes()
        with self.assertRaises(ValueError):
            publish([], self.root, date(2026, 6, 8))
        self.assertEqual(before, (self.root / "README.md").read_bytes())

    def test_no_source_preserves_live_and_creates_new_period(self):
        publish(parse_payload(payload()), self.root, date(2026, 6, 8))
        old = (self.root / "reports/monthly/2026-06.json").read_bytes()
        publish([], self.root, date(2026, 6, 15), preserve_existing=True)
        self.assertEqual(old, (self.root / "reports/monthly/2026-06.json").read_bytes())
        new = json.loads((self.root / "reports/weekly/2026-W24.json").read_text(encoding="utf-8"))
        self.assertEqual(new["status"], "no_data")
        self.assertIn("数据源未配置", (self.root / "README.md").read_text(encoding="utf-8"))

    def test_demo_and_live_archive_coexist(self):
        publish(load_snapshots(ROOT / "examples/snapshots.json"), self.root, date(2026, 6, 8), demo=True)
        publish([], self.root, date(2026, 9, 6), preserve_existing=True)
        self.assertTrue((self.root / "reports/demo/weekly/2026-W23.json").exists())
        self.assertTrue((self.root / "reports/weekly/2026-W35.json").exists())
        index = (self.root / "reports/README.md").read_text(encoding="utf-8")
        self.assertIn("demo/weekly/2026-W23.md", index)
        self.assertIn("weekly/2026-W35.md", index)

    def test_markers_and_markdown_escaping(self):
        with self.assertRaises(ValueError):
            replace_block("missing markers", "LATEST", "body")
        raw = payload()
        raw["snapshots"][0]["posts"][0]["text"] = "<script>x</script> | [bad](https://bad.example)"
        result = render_report(build_report(parse_payload(raw), "week", datetime(2026, 6, 1), date(2026, 6, 8)))
        self.assertNotIn("<script>", result)
        self.assertIn(r"\|", result)
        self.assertIsNone(safe_url("javascript:alert(1)"))
        self.assertIsNone(safe_url("https://weibo.com.bad.example"))
        self.assertIsNotNone(safe_url("https://weibo.com/123/456"))

    def test_cli_rejects_day(self):
        result = subprocess.run(
            [sys.executable, "-m", "weibo_mood_radar.cli", "report", "--input", "unused",
             "--period", "day", "--anchor", "2026-06-01", "--output", "unused.json"],
            capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid choice", result.stderr)


if __name__ == "__main__":
    unittest.main()
