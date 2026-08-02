"""Tests for measured Graphify context savings."""

import shutil
import tempfile
from pathlib import Path

from src.graphify_metrics import corpus_tokens_from_report, query_tokens_from_output, record_query
from src.tracker import SavingsTracker


class TestGraphifyMetrics:
    def setup_method(self):
        self.tmp_root = Path(tempfile.mkdtemp())
        self.project = self.tmp_root / "project"
        graph_dir = self.project / "graphify-out"
        graph_dir.mkdir(parents=True)
        (graph_dir / "GRAPH_REPORT.md").write_text(
            "# Graph Report\n\n## Corpus Check\n- 120 files · ~90,000 words\n",
            encoding="utf-8",
        )
        self.db_dir = self.tmp_root / "db"
        SavingsTracker.DB_DIR = str(self.db_dir)
        SavingsTracker.DB_PATH = str(self.db_dir / "savings.db")

    def teardown_method(self):
        SavingsTracker.DB_DIR = None
        SavingsTracker.DB_PATH = None
        shutil.rmtree(self.tmp_root, ignore_errors=True)

    def test_reads_graphify_baseline(self):
        assert corpus_tokens_from_report(self.project) == 120000

    def test_estimates_query_tokens_using_graphify_rule(self):
        assert query_tokens_from_output("x" * 400) == 100

    def test_records_query_measurement(self):
        result = record_query(
            self.project,
            "How does authentication work?",
            "NODE Auth\nEDGE Auth --uses--> Database\n" * 10,
            session_id="kilo-session",
        )
        assert result["recorded"] is True
        assert result["baseline_tokens"] == 120000
        assert result["saved_tokens"] > 0

        tracker = SavingsTracker(session_id="kilo-session")
        stats = tracker.get_graphify_stats()
        tracker.close()
        assert stats["session"]["queries"] == 1
        assert stats["session"]["saved_tokens"] == result["saved_tokens"]

    def test_missing_report_is_not_recorded(self):
        assert record_query(self.tmp_root / "missing", "question", "NODE x")["recorded"] is False
