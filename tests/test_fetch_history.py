"""The history fetch plans 5-minute reads and never touches the order API."""

from __future__ import annotations

import ast
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
import pandas as pd

from scripts.fetch_history import (
    BAR_SIZE,
    DASHBOARD_CLIENT_ID,
    DURATION,
    HISTORY_END,
    HISTORY_START,
    KEEP_UP_TO_DATE,
    LONG_BACKFILL_END,
    PANEL_START,
    STOCK_BACKFILL_END,
    USE_RTH,
    WHAT_TO_SHOW,
    Pacer,
    bars_to_frame,
    check_client_id,
    chunk_covered,
    chunk_ends,
    chunk_sessions,
    classify_errors,
    default_jobs,
    main,
    missing_chunks,
    write_chunk,
)


class _Bar:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class FetchPlanTests(unittest.TestCase):
    def test_plan_is_five_minute_trades_only(self):
        self.assertEqual(BAR_SIZE, "5 mins")
        self.assertEqual(DURATION, "1 W")
        self.assertEqual(WHAT_TO_SHOW, "TRADES")
        self.assertTrue(USE_RTH)
        self.assertFalse(KEEP_UP_TO_DATE)

    def test_chunk_counts_match_the_request(self):
        self.assertEqual(len(chunk_ends(PANEL_START, HISTORY_END)), 290)
        self.assertEqual(len(chunk_ends(HISTORY_START, STOCK_BACKFILL_END)), 242)
        self.assertEqual(len(chunk_ends(HISTORY_START, LONG_BACKFILL_END)), 182)

    def test_windows_cover_every_weekday_without_a_gap(self):
        start = date(2024, 1, 2)
        end = date(2024, 2, 2)
        covered = set()
        for chunk_end in chunk_ends(start, end):
            covered.update(chunk_sessions(chunk_end))
        day = start
        while day <= end:
            if day.weekday() < 5:
                self.assertIn(day, covered)
            day = day.fromordinal(day.toordinal() + 1)

    def test_existing_week_is_not_requested_again(self):
        end = date(2024, 1, 5)  # Friday
        present = set(chunk_sessions(end))
        self.assertTrue(chunk_covered(present, end))
        self.assertEqual(missing_chunks(present, end, end, "JPM", set()), [])
        # Three sessions is a short holiday week, so it is still requested.
        thin = set(list(present)[:3])
        self.assertEqual(missing_chunks(thin, end, end, "JPM", set()), [end])
        self.assertEqual(
            missing_chunks(set(), end, end, "JPM", {("JPM", end)}),
            [],
        )

    def test_jobs_are_priority_ordered_and_skip_the_dashboard_id(self):
        jobs = default_jobs()
        self.assertEqual([job.priority for job in jobs], sorted(job.priority for job in jobs))
        symbols = {job.symbol for job in jobs if job.priority == 1}
        self.assertEqual(
            symbols,
            {"JPM", "BAC", "V", "XOM", "CVX", "JNJ", "UNH", "WMT", "PG", "HON", "NFLX", "ORCL"},
        )
        self.assertTrue(all(job.role == "context" for job in jobs if job.symbol == "XLF"))
        self.assertNotIn("LLY", symbols)
        with self.assertRaises(ValueError):
            check_client_id(DASHBOARD_CLIENT_ID)

    def test_source_has_no_order_api(self):
        path = Path(__file__).resolve().parents[1] / "scripts" / "fetch_history.py"
        tree = ast.parse(path.read_text())
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        attrs = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        called = names | attrs
        for forbidden in ("placeOrder", "cancelOrder", "reqOpenOrders", "reqExecutions", "bracketOrder"):
            self.assertNotIn(forbidden, called)
        joined = path.read_text()
        self.assertIn("keepUpToDate=False", joined)
        self.assertIn("readonly", joined)

    def test_bars_match_raw5_columns_and_drop_the_extended_session(self):
        start = date(2024, 1, 2)
        end = date(2024, 1, 2)
        rth = datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc)  # 09:30 ET
        late = datetime(2024, 1, 2, 21, 0, tzinfo=timezone.utc)  # 16:00 ET
        pre = datetime(2024, 1, 2, 13, 0, tzinfo=timezone.utc)  # 08:00 ET
        bars = [
            _Bar(date=rth, open=10, high=11, low=9, close=10.5, volume=100, average=10.2, barCount=4),
            _Bar(date=late, open=10, high=11, low=9, close=10.5, volume=100, average=10.2, barCount=4),
            _Bar(date=pre, open=10, high=11, low=9, close=10.5, volume=100, average=10.2, barCount=4),
        ]
        frame = bars_to_frame(bars, start, end, set(), assume_utc=True)
        self.assertEqual(list(frame.columns), ["date", "open", "high", "low", "close", "volume", "average", "barCount"])
        self.assertEqual(len(frame), 1)
        self.assertEqual(str(frame["date"].dtype), "datetime64[us, US/Eastern]")
        self.assertEqual(frame["volume"].dtype.name, "float64")
        self.assertEqual(frame["barCount"].dtype.name, "int64")
        self.assertEqual(frame["date"].iloc[0].hour, 9)
        self.assertEqual(frame["date"].iloc[0].minute, 30)
        again = bars_to_frame(bars, start, end, {"2024-01-02 09:30"}, assume_utc=True)
        self.assertTrue(again.empty)

    def test_merge_keeps_bars_already_in_the_file(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            day = date(2024, 1, 2)
            first = bars_to_frame(
                [
                    _Bar(
                        date=datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc),
                        open=1, high=1, low=1, close=1, volume=1, average=1, barCount=1,
                    )
                ],
                day,
                day,
                set(),
            )
            second = bars_to_frame(
                [
                    _Bar(
                        date=datetime(2024, 1, 2, 14, 35, tzinfo=timezone.utc),
                        open=2, high=2, low=2, close=2, volume=2, average=2, barCount=2,
                    )
                ],
                day,
                day,
                set(),
            )
            path = write_chunk(folder, first)
            merged = write_chunk(folder, second)
            self.assertEqual(path, merged)
            saved = pd.read_parquet(path)
            self.assertEqual(len(saved), 2)
            self.assertEqual(saved["close"].tolist(), [1.0, 2.0])

    def test_pacer_spaces_calls(self):
        clock = {"t": 0.0}
        slept = []

        def now():
            return clock["t"]

        def sleep(seconds):
            slept.append(seconds)
            clock["t"] += seconds

        pacer = Pacer(min_interval=11, window=600, max_calls=2, sleep=sleep, now=now)
        pacer.wait()
        pacer.wait()
        pacer.wait()
        self.assertTrue(slept)
        self.assertGreaterEqual(sum(slept), 11)
        self.assertGreaterEqual(clock["t"], 11)

    def test_error_classes(self):
        self.assertEqual(classify_errors([]), "ok")
        self.assertEqual(classify_errors([(162, "Historical data request pacing violation")]), "pacing")
        self.assertEqual(classify_errors([(162, "HMDS query returned no data")]), "empty")
        self.assertEqual(classify_errors([(200, "No security definition has been found")]), "unknown")
        self.assertEqual(classify_errors([(2104, "Market data farm connection is OK")]), "ok")

    def test_dry_run_does_not_need_a_gateway(self):
        import io
        import tempfile
        from contextlib import redirect_stdout

        with tempfile.TemporaryDirectory() as tmp:
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = main(["--dry-run", "--root", tmp, "--max-priority", "1"])
        self.assertEqual(code, 0)
        self.assertIn("Dry run: Gateway was not contacted.", buf.getvalue())
        self.assertIn("3480", buf.getvalue())
        err = io.StringIO()
        with redirect_stdout(err):
            self.assertEqual(main(["--client-id", "7", "--dry-run"]), 2)
        self.assertIn("dashboard", err.getvalue())


if __name__ == "__main__":
    unittest.main()
