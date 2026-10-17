"""Checkpoint store. The live app reads models/ACTIVE and nothing else.

v0.x is a baseline that did not beat costs and a random entry. v1.0, v1.1, …
are issued only by ``create_passing_checkpoint`` after that bar is met.
Restoring a checkpoint rewrites the pointer. It does not place an order.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "models"
ACTIVE_PATH = MODELS / "ACTIVE"
CHECKPOINTS = MODELS / "checkpoints"
SIGNAL_MIRROR = ROOT / "app" / "signal_rule.json"

_VERSION = re.compile(r"^v(\d+)\.(\d+)$")


def parse_version(version: str) -> tuple[int, int]:
    match = _VERSION.match(version.strip())
    if not match:
        raise ValueError(f"version must look like v0.1 or v1.0, got {version!r}")
    return int(match.group(1)), int(match.group(2))


def passes_costs_and_random(results: dict[str, Any]) -> tuple[bool, list[str]]:
    """True only when the locked slice made money, the profit is significant, and it beat random entries.

    ``bootstrap.pValue`` is the share of day-resamples whose total is <= 0.
    A pass needs that share under 5 percent. ``random.pValue`` is the share of
    random same-length entries that did at least as well. A pass needs that
    under 5 percent too. Both numbers are the ones already published for the
    holdout. This function does not re-read the holdout.
    """
    reasons: list[str] = []
    hold = results.get("holdout") or {}
    net = hold.get("net")
    if net is None or float(net) <= 0:
        reasons.append("holdout net after costs is not positive")
    bootstrap = (results.get("bootstrap") or {}).get("pValue")
    if bootstrap is None or float(bootstrap) >= 0.05:
        reasons.append("holdout profit is not significant at 5 percent versus a flat result")
    random_p = (results.get("random") or {}).get("pValue")
    if random_p is None or float(random_p) >= 0.05:
        reasons.append("the rule does not beat random entries of the same length at 5 percent")
    return (not reasons), reasons


class Store:
    def __init__(self, root: Path | None = None, signal_mirror: Path | None = None) -> None:
        self.root = Path(root) if root is not None else MODELS
        self.signal_mirror = signal_mirror

    @property
    def active_path(self) -> Path:
        return self.root / "ACTIVE"

    @property
    def checkpoints(self) -> Path:
        return self.root / "checkpoints"

    def list_versions(self) -> list[str]:
        folder = self.checkpoints
        if not folder.is_dir():
            return []
        names = [path.name for path in folder.iterdir() if (path / "config.json").is_file()]
        return sorted(names, key=parse_version)

    def active_version(self) -> str:
        text = self.active_path.read_text(encoding="utf-8").strip()
        parse_version(text)
        if text not in self.list_versions():
            raise RuntimeError(f"ACTIVE points at {text}, which has no checkpoint")
        return text

    def load(self, version: str | None = None) -> dict[str, Any]:
        version = version or self.active_version()
        parse_version(version)
        path = self.checkpoints / version / "config.json"
        if not path.is_file():
            raise FileNotFoundError(f"no checkpoint at {path}")
        config = json.loads(path.read_text(encoding="utf-8"))
        if config.get("version") != version:
            raise RuntimeError(f"{path} says {config.get('version')}, folder is {version}")
        return config

    def signal_rule(self, version: str | None = None) -> dict[str, Any]:
        config = self.load(version)
        if not config.get("liveCapable"):
            raise RuntimeError(f"{config['version']} cannot drive the live list")
        rule = dict(config["signalRule"])
        rule["version"] = config["version"]
        rule["passedGate"] = bool(config.get("passedGate"))
        return rule

    def note(self, version: str | None = None) -> str:
        version = version or self.active_version()
        path = self.checkpoints / version / "NOTE.md"
        return path.read_text(encoding="utf-8") if path.is_file() else ""

    def last_passing(self, *, exclude: str | None = None) -> str | None:
        found: list[str] = []
        for version in self.list_versions():
            if version == exclude:
                continue
            if self.load(version).get("passedGate"):
                found.append(version)
        return found[-1] if found else None

    def restore(self, version: str) -> dict[str, Any]:
        """Point ACTIVE at ``version`` and mirror a live-capable rule. No orders."""
        config = self.load(version)
        if not config.get("liveCapable"):
            raise RuntimeError(
                f"{version} is a record only. The live list runs appear/disappear rules, so ACTIVE was not changed."
            )
        rule = dict(config["signalRule"])
        self.active_path.write_text(version + "\n", encoding="utf-8")
        if self.signal_mirror is not None:
            self.signal_mirror.write_text(json.dumps(rule, indent=2) + "\n", encoding="utf-8")
        return config

    def next_passing_version(self) -> str:
        majors = [parse_version(version) for version in self.list_versions() if parse_version(version)[0] >= 1]
        if not majors:
            return "v1.0"
        latest = max(majors)
        return f"v{latest[0]}.{latest[1] + 1}"


def create_passing_checkpoint(store: Store, version_results: dict[str, Any], config: dict[str, Any]) -> str:
    """Write the next v1.x folder. Refuses a result that failed costs or random entries."""
    ok, reasons = passes_costs_and_random(version_results)
    if not ok:
        raise RuntimeError("refusing a passing checkpoint: " + "; ".join(reasons))
    if not config.get("passedGate"):
        raise RuntimeError("config passedGate must be true")
    version = store.next_passing_version()
    folder = store.checkpoints / version
    folder.mkdir(parents=True, exist_ok=False)
    payload = dict(config)
    payload["version"] = version
    payload["passedGate"] = True
    payload["status"] = "passing"
    (folder / "config.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    (folder / "results.json").write_text(json.dumps(version_results, indent=2) + "\n", encoding="utf-8")
    return version


def default_store() -> Store:
    return Store(MODELS, SIGNAL_MIRROR)
