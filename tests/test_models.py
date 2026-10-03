"""Checkpoint restore and the rollback monitor. These tests do not read the holdout."""

from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from models.cli import main
from models.monitor import apply_decision, assess_backtest, assess_trades, decide
from models.registry import Store, create_passing_checkpoint, passes_costs_and_random


def _rule() -> dict:
    return {
        "id": "midmorning",
        "confirm": 1,
        "exit_lag": 1,
        "minute_from": 600,
        "minute_to": 660,
        "use_stop": True,
        "stop_scale": 1.0,
    }


def _baseline(version: str, *, passed: bool, bps: float = -8.4) -> dict:
    return {
        "version": version,
        "status": "passing" if passed else "baseline",
        "passedGate": passed,
        "liveCapable": True,
        "kind": "appear_disappear",
        "signalRule": _rule(),
        "expected": {"avgNetBps": bps, "net": 1.0 if passed else -268.0, "winRate": 0.37, "tradesPerDay": 1.5, "maxDrawdown": 100},
    }


def _write(store: Store, config: dict) -> None:
    folder = store.checkpoints / config["version"]
    folder.mkdir(parents=True)
    (folder / "config.json").write_text(json.dumps(config), encoding="utf-8")
    (folder / "NOTE.md").write_text(f"# {config['version']}\n\nNote.\n", encoding="utf-8")


class ModelTests(unittest.TestCase):
    def test_shipped_baseline_fails_costs_and_random(self) -> None:
        root = Path(__file__).resolve().parents[1]
        store = Store(root / "models")
        self.assertEqual(store.active_version(), "v0.1")
        results = json.loads((root / "models" / "checkpoints" / "v0.1" / "results.json").read_text(encoding="utf-8"))
        ok, reasons = passes_costs_and_random(results)
        self.assertFalse(ok)
        self.assertTrue(any("not positive" in reason for reason in reasons))
        self.assertTrue(any("not significant" in reason for reason in reasons))
        self.assertTrue(any("random" in reason for reason in reasons))
        self.assertFalse(store.load()["passedGate"])
        self.assertIn("lost $268", store.note())
        with self.assertRaises(RuntimeError):
            create_passing_checkpoint(store, results, {"passedGate": True, "liveCapable": True, "signalRule": _rule(), "expected": {}})

    def test_restore_points_active_at_a_live_checkpoint(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(Path(tmp))
            mirror = Path(tmp) / "signal_rule.json"
            store.signal_mirror = mirror
            _write(store, _baseline("v0.1", passed=False))
            other = _baseline("v0.2", passed=False)
            other["signalRule"] = {**_rule(), "minute_to": 720}
            _write(store, other)
            (store.active_path).write_text("v0.1\n", encoding="utf-8")
            store.restore("v0.2")
            self.assertEqual(store.active_version(), "v0.2")
            saved = json.loads(mirror.read_text(encoding="utf-8"))
            self.assertEqual(saved["minute_to"], 720)
            record = _baseline("v0.0", passed=False)
            record["version"] = "v0.3"
            record["liveCapable"] = False
            _write(store, record)
            with self.assertRaises(RuntimeError):
                store.restore("v0.3")
            self.assertEqual(store.active_version(), "v0.2")

    def _store(self, root: Path) -> Store:
        (root / "checkpoints").mkdir(parents=True)
        return Store(root)

    def test_paper_underperformance_rolls_back_only_to_a_passing_checkpoint(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = self._store(root)
            _write(store, _baseline("v0.1", passed=False, bps=-8.0))
            passing = _baseline("v1.0", passed=True, bps=5.0)
            _write(store, passing)
            store.active_path.write_text("v0.1\n", encoding="utf-8")
            bad = [-40.0] * 30
            assessment = assess_trades(bad, -8.0)
            self.assertTrue(assessment.tripped)
            decision = decide(store, assessment)
            self.assertEqual(decision.action, "rollback")
            self.assertEqual(decision.target, "v1.0")
            changelog = root / "CHANGELOG.md"
            changelog.write_text("# log\n", encoding="utf-8")
            state = root / "state.json"
            first = apply_decision(store, decision, changelog=changelog, state_path=state)
            self.assertTrue(first["logged"])
            self.assertEqual(store.active_version(), "v1.0")
            second = apply_decision(store, decision, changelog=changelog, state_path=state)
            self.assertFalse(second["logged"])
            self.assertEqual(changelog.read_text(encoding="utf-8").count("ROLLBACK"), 1)

    def test_without_a_passing_checkpoint_the_trip_is_held(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = self._store(root)
            _write(store, _baseline("v0.1", passed=False, bps=-8.0))
            store.active_path.write_text("v0.1\n", encoding="utf-8")
            decision = decide(store, assess_trades([-40.0] * 30, -8.0))
            self.assertEqual(decision.action, "withheld")
            changelog = root / "CHANGELOG.md"
            changelog.write_text("# log\n", encoding="utf-8")
            apply_decision(store, decision, changelog=changelog, state_path=root / "state.json")
            self.assertEqual(store.active_version(), "v0.1")
            self.assertIn("ROLLBACK HELD", changelog.read_text(encoding="utf-8"))
            self.assertIn("No passing checkpoint", changelog.read_text(encoding="utf-8"))

    def test_a_small_gap_does_not_trip(self) -> None:
        quiet = assess_trades([-9.0] * 30, -8.4)
        self.assertFalse(quiet.tripped)
        short = assess_trades([-40.0] * 10, -8.4)
        self.assertFalse(short.tripped)
        close = assess_backtest(-12.0, 100, -8.4)
        self.assertFalse(close.tripped)
        worse = assess_backtest(-20.0, 100, -8.4)
        self.assertTrue(worse.tripped)

    def test_a_passing_result_can_be_checkpointed(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(Path(tmp))
            results = {"holdout": {"net": 25.0}, "bootstrap": {"pValue": 0.01}, "random": {"pValue": 0.02}}
            self.assertTrue(passes_costs_and_random(results)[0])
            version = create_passing_checkpoint(
                store,
                results,
                {"passedGate": True, "liveCapable": True, "signalRule": _rule(), "expected": {"avgNetBps": 4.0}},
            )
            self.assertEqual(version, "v1.0")
            self.assertTrue(store.load("v1.0")["passedGate"])

    def test_cli_lists_the_shipped_baseline(self) -> None:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = main(["list"])
        self.assertEqual(code, 0)
        self.assertIn("v0.1  baseline active", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
