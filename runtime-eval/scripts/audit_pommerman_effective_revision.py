from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import yaml


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_file(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _iter_round_dirs(logs_root: Path) -> list[Path]:
    dirs = []
    for p in logs_root.glob("round_*"):
        if not p.is_dir():
            continue
        try:
            _ = int(p.name.split("_", 1)[1])
        except Exception:
            continue
        dirs.append(p)
    return sorted(dirs, key=lambda d: int(d.name.split("_", 1)[1]))


def _load_tournament_require_effective_change() -> bool:
    cfg_paths = [
        Path("configs/tournaments/pommerman_gptv16_a00_openclaw_initial_synthesis_3round_neutral_double_rr_smoke.yaml"),
        Path("configs/tournaments/pommerman_gptv16_a00_openclaw_initial_synthesis_10round_neutral_double_rr.yaml"),
    ]
    for cfg_path in cfg_paths:
        if not cfg_path.exists():
            continue
        try:
            cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(cfg, dict) and bool(cfg.get("require_effective_submission_change", False)):
            return True
    return False


def _extract_diff_targets(diff_path: Path, before_dir: Path, after_dir: Path) -> list[str]:
    if not diff_path.exists():
        return []
    try:
        text = diff_path.read_text(encoding="utf-8")
    except Exception:
        return []
    targets: list[str] = []
    seen: set[str] = set()
    before_root = before_dir.resolve()
    after_root = after_dir.resolve()
    for line in text.splitlines():
        if not (line.startswith("--- ") or line.startswith("+++ ")):
            continue
        raw = line[4:].strip()
        if raw == "/dev/null":
            continue
        rel: str | None = None
        if raw.startswith("/dev/null:"):
            rel = raw.split(":", 1)[1]
        else:
            try:
                rp = Path(raw).resolve()
                if before_root in rp.parents:
                    rel = str(rp.relative_to(before_root))
                elif after_root in rp.parents:
                    rel = str(rp.relative_to(after_root))
            except Exception:
                rel = None
        if rel is None:
            continue
        rel = rel.replace("\\", "/")
        if rel in seen:
            continue
        seen.add(rel)
        targets.append(rel)
    return targets


def audit_effective_revision(*, allow_all_noop: bool = False) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    logs_root = Path("logs")
    if not logs_root.exists():
        return ["missing logs directory"], warnings

    round_dirs = _iter_round_dirs(logs_root)
    if not round_dirs:
        return ["no logs/round_* directories found"], warnings

    all_revision_entries: list[tuple[int, dict]] = []
    revised_entries: list[tuple[int, dict]] = []

    for rd in round_dirs:
        round_idx = int(rd.name.split("_", 1)[1])
        rev_path = rd / "revision_manifest.json"
        if not rev_path.exists():
            continue
        payload = _load_json(rev_path)
        agents = payload.get("agents")
        if not isinstance(agents, list):
            errors.append(f"{rev_path}: agents must be a list")
            continue
        for entry in agents:
            if not isinstance(entry, dict):
                errors.append(f"{rev_path}: each agent entry must be an object")
                continue
            all_revision_entries.append((round_idx, entry))
            if bool(entry.get("revision_attempted")):
                revised_entries.append((round_idx, entry))

    if not revised_entries:
        errors.append("no revised agents found in revision manifests")
        return errors, warnings

    noop_count = 0
    require_effective_change_globally = _load_tournament_require_effective_change()
    for round_idx, entry in revised_entries:
        agent_id = entry.get("agent_id", "<unknown>")
        label = f"round_{round_idx}:{agent_id}"

        required = [
            "submission_main_sha256_before",
            "submission_main_sha256_after",
            "effective_submission_changed",
            "changed_files_hash_based",
        ]
        missing = [k for k in required if k not in entry]
        if missing:
            errors.append(f"{label}: missing required fields: {', '.join(missing)}")
            continue

        before_hash = entry.get("submission_main_sha256_before")
        after_hash = entry.get("submission_main_sha256_after")
        effective = bool(entry.get("effective_submission_changed"))
        changed_files = entry.get("changed_files")
        changed_hash_based = entry.get("changed_files_hash_based")
        if not isinstance(changed_files, list):
            changed_files = []
        if not isinstance(changed_hash_based, list):
            errors.append(f"{label}: changed_files_hash_based must be a list")
            changed_hash_based = []
        if not effective:
            noop_count += 1
            warnings.append(f"{label}: no-op revision for submission/main.py")
            if require_effective_change_globally:
                errors.append(f"{label}: require_effective_submission_change=true but effective_submission_changed=false")

        if "submission/main.py" in changed_files and not effective:
            errors.append(f"{label}: changed_files includes submission/main.py but effective_submission_changed=false")
        if "submission/main.py" in changed_hash_based and before_hash == after_hash:
            errors.append(f"{label}: changed_files_hash_based includes submission/main.py but hashes are equal")

        diff_path_raw = entry.get("diff_path")
        codebase_play_path_raw = entry.get("codebase_play_path")
        codebase_post_path_raw = entry.get("codebase_post_path")
        if isinstance(diff_path_raw, str) and isinstance(codebase_play_path_raw, str) and isinstance(codebase_post_path_raw, str):
            diff_targets = _extract_diff_targets(Path(diff_path_raw), Path(codebase_play_path_raw), Path(codebase_post_path_raw))
            if "submission/main.py" in diff_targets and before_hash == after_hash:
                errors.append(f"{label}: diff patch targets submission/main.py but hashes are equal")

    if len(revised_entries) == noop_count and not allow_all_noop:
        errors.append("all OpenClaw revisions were no-op for submitted code")

    for rd in round_dirs:
        round_idx = int(rd.name.split("_", 1)[1])
        prop_path = rd / "propagation_manifest.json"
        if not prop_path.exists():
            continue
        payload = _load_json(prop_path)
        agents = payload.get("agents")
        if not isinstance(agents, list):
            errors.append(f"{prop_path}: agents must be a list")
            continue
        for rec in agents:
            if not isinstance(rec, dict):
                errors.append(f"{prop_path}: each propagation entry must be an object")
                continue
            agent_id = rec.get("agent_id", "<unknown>")
            label = f"round_{round_idx}:{agent_id}"
            source = rec.get("source_post_path")
            target = rec.get("target_play_path")
            if not isinstance(source, str) or not isinstance(target, str):
                errors.append(f"{label}: propagation source/target paths missing")
                continue
            source_hash = _sha256_file(Path(source) / "submission" / "main.py")
            target_hash = _sha256_file(Path(target) / "submission" / "main.py")
            if source_hash != target_hash:
                errors.append(f"{label}: propagation hash mismatch post->{round_idx} play")

    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-all-noop", action="store_true")
    args = parser.parse_args()
    errors, warnings = audit_effective_revision(allow_all_noop=args.allow_all_noop)
    for w in warnings:
        print(f"WARN {w}")
    if errors:
        print("pommerman_effective_revision_audit=FAIL")
        for e in errors:
            print(f"ERROR {e}")
        return 1
    print("pommerman_effective_revision_audit=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
