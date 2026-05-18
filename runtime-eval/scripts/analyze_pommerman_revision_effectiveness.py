from __future__ import annotations

import json
from pathlib import Path


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _iter_rounds() -> list[int]:
    rounds: list[int] = []
    for p in Path("logs").glob("round_*"):
        if not p.is_dir():
            continue
        try:
            rounds.append(int(p.name.split("_", 1)[1]))
        except Exception:
            continue
    return sorted(set(rounds))


def _round_tie_rate(round_idx: int) -> str:
    rd = Path("logs") / f"round_{round_idx}"
    rm = rd / "round_manifest.json"
    if not rm.exists():
        return "n/a"
    try:
        matches = _load_json(rm).get("matches", [])
    except Exception:
        return "n/a"
    if not isinstance(matches, list) or not matches:
        return "n/a"
    draws = 0
    total = 0
    for m in matches:
        if not isinstance(m, dict):
            continue
        sc_path = m.get("scorecard_path")
        if not isinstance(sc_path, str):
            continue
        total += 1
        try:
            sc = _load_json(Path(sc_path))
            if sc.get("left_right_winner") == "draw":
                draws += 1
        except Exception:
            pass
    if total == 0:
        return "n/a"
    return f"{draws}/{total} ({draws/total:.1%})"


def _round_extra_metrics(round_idx: int) -> tuple[str, str, str, str]:
    rd = Path("logs") / f"round_{round_idx}"
    rm = rd / "round_manifest.json"
    if not rm.exists():
        return "n/a", "n/a", "n/a", "n/a"
    try:
        matches = _load_json(rm).get("matches", [])
    except Exception:
        return "n/a", "n/a", "n/a", "n/a"
    if not isinstance(matches, list) or not matches:
        return "n/a", "n/a", "n/a", "n/a"
    bomb_rates: list[float] = []
    stop_rates: list[float] = []
    terminal_steps: list[float] = []
    non_draw = 0
    for m in matches:
        if not isinstance(m, dict):
            continue
        sc_path = m.get("scorecard_path")
        if isinstance(sc_path, str):
            try:
                sc = _load_json(Path(sc_path))
                if sc.get("left_right_winner") != "draw":
                    non_draw += 1
            except Exception:
                pass
        md_path = m.get("metadata_path")
        if not isinstance(md_path, str):
            continue
        try:
            md = _load_json(Path(md_path))
        except Exception:
            continue
        for aid in [md.get("left_agent_id"), md.get("right_agent_id")]:
            if not isinstance(aid, str):
                continue
            fbp = Path(Path(md_path).parent / f"agent_feedback_{aid}.json")
            if not fbp.exists():
                continue
            try:
                fb = _load_json(fbp)
            except Exception:
                continue
            d = fb.get("diagnostics", {})
            if not isinstance(d, dict):
                continue
            br = d.get("bomb_action_rate")
            sr = d.get("stop_action_rate")
            ts = d.get("average_terminal_step")
            if isinstance(br, (int, float)):
                bomb_rates.append(float(br))
            if isinstance(sr, (int, float)):
                stop_rates.append(float(sr))
            if isinstance(ts, (int, float)):
                terminal_steps.append(float(ts))
    if not bomb_rates and not stop_rates and not terminal_steps:
        return "n/a", "n/a", "n/a", str(non_draw)
    bomb_avg = (sum(bomb_rates) / len(bomb_rates)) if bomb_rates else 0.0
    stop_avg = (sum(stop_rates) / len(stop_rates)) if stop_rates else 0.0
    terminal_avg = (sum(terminal_steps) / len(terminal_steps)) if terminal_steps else 0.0
    return f"{bomb_avg:.3f}", f"{stop_avg:.3f}", f"{terminal_avg:.1f}", str(non_draw)


def _build_propagation_lookup() -> dict[tuple[int, str], str]:
    out: dict[tuple[int, str], str] = {}
    for round_idx in _iter_rounds():
        prop = Path("logs") / f"round_{round_idx}" / "propagation_manifest.json"
        if not prop.exists():
            continue
        try:
            entries = _load_json(prop).get("agents", [])
        except Exception:
            continue
        if not isinstance(entries, list):
            continue
        for rec in entries:
            if not isinstance(rec, dict):
                continue
            aid = rec.get("agent_id")
            if not isinstance(aid, str):
                continue
            out[(round_idx, aid)] = str(rec.get("propagation_matches_post"))
    return out


def _load_initial_synthesis_by_agent() -> tuple[dict[str, dict], int]:
    path = Path("logs/initial_synthesis_manifest.json")
    if not path.exists():
        return {}, 0
    try:
        agents = _load_json(path).get("agents", [])
    except Exception:
        return {}, 0
    if not isinstance(agents, list):
        return {}, 0
    by_agent: dict[str, dict] = {}
    hashes: set[str] = set()
    for entry in agents:
        if not isinstance(entry, dict):
            continue
        aid = entry.get("agent_id")
        if not isinstance(aid, str):
            continue
        by_agent[aid] = entry
        h = entry.get("initial_submission_sha256")
        if isinstance(h, str):
            hashes.add(h)
    return by_agent, len(hashes)


def main() -> int:
    logs = Path("logs")
    if not logs.exists():
        print("logs directory not found")
        return 0

    rounds = _iter_rounds()
    if not rounds:
        print("no logs/round_* directories found")
        return 0

    prop_lookup = _build_propagation_lookup()
    init_lookup, unique_initial_hashes = _load_initial_synthesis_by_agent()
    rows: list[list[str]] = []
    header = [
        "round",
        "agent_id",
        "initial_strategy_profile_id",
        "starter_hash",
        "initial_hash",
        "effective_initial_changed",
        "revision_ok",
        "provider_route_status",
        "fallback_used",
        "before_hash",
        "after_hash",
        "effective_submission_changed",
        "diff_bytes",
        "changed_files_hash_based",
        "openclaw_changedFiles",
        "propagated_hash_match",
        "round_tie_rate",
        "bomb_action_rate",
        "stop_action_rate",
        "average_terminal_step",
        "non_draw_match_count",
    ]

    for round_idx in rounds:
        rev = Path("logs") / f"round_{round_idx}" / "revision_manifest.json"
        tie_rate = _round_tie_rate(round_idx)
        bomb_rate, stop_rate, avg_terminal_step, non_draw_count = _round_extra_metrics(round_idx)
        if not rev.exists():
            continue
        try:
            agents = _load_json(rev).get("agents", [])
        except Exception as exc:
            print(f"round_{round_idx}: failed to read revision_manifest.json: {exc!r}")
            continue
        if not isinstance(agents, list):
            print(f"round_{round_idx}: revision manifest agents is not a list")
            continue
        for a in agents:
            if not isinstance(a, dict):
                continue
            aid = str(a.get("agent_id"))
            init = init_lookup.get(aid, {})
            rows.append(
                [
                    str(round_idx),
                    aid,
                    str(init.get("initial_strategy_profile_id", "n/a")),
                    str(init.get("starter_submission_sha256", "n/a")),
                    str(init.get("initial_submission_sha256", "n/a")),
                    str(init.get("effective_initial_submission_changed", "n/a")),
                    str(a.get("revision_ok")),
                    str(a.get("provider_route_status")),
                    str(a.get("fallback_used")),
                    str(a.get("submission_main_sha256_before")),
                    str(a.get("submission_main_sha256_after")),
                    str(a.get("effective_submission_changed")),
                    str(a.get("diff_bytes")),
                    str(a.get("changed_files_hash_based")),
                    str(a.get("changed_files_reported_by_openclaw")),
                    prop_lookup.get((round_idx + 1, aid), "n/a"),
                    tie_rate,
                    bomb_rate,
                    stop_rate,
                    avg_terminal_step,
                    non_draw_count,
                ]
            )

    if not rows:
        print("no revision entries found")
        return 0

    widths = [len(h) for h in header]
    for r in rows:
        for i, cell in enumerate(r):
            widths[i] = max(widths[i], len(cell))

    def fmt_row(cells: list[str]) -> str:
        return " | ".join(cells[i].ljust(widths[i]) for i in range(len(cells)))

    print(fmt_row(header))
    print("-+-".join("-" * w for w in widths))
    for r in rows:
        print(fmt_row(r))
    if init_lookup:
        print(f"unique_initial_submission_hashes={unique_initial_hashes}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
