from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from runner.adapters.base import BaseGameAdapter


class Pommerman1v1Adapter(BaseGameAdapter):
    name = "pommerman_1v1"

    REQUIRED_FILES = [
        "submission/main.py",
        "scripts/build.sh",
        "scripts/run_submission.sh",
        "tests/smoke.sh",
        "scripts/run_arena.sh",
        "scripts/pommerman_ffa_probe.py",
    ]

    def validate_submission(self, codebase_dir: Path) -> tuple[bool, str]:
        missing = []
        for rel in self.REQUIRED_FILES:
            path = codebase_dir / rel
            if not path.exists():
                missing.append(rel)

        if missing:
            return False, f"missing required files: {missing}"

        return True, "starter repo contract valid"

    def export_submission(self, codebase_dir: Path, submission_dir: Path) -> tuple[bool, str]:
        src = codebase_dir / "submission"
        if not src.exists():
            return False, "missing submission/ directory in codebase"

        if submission_dir.exists():
            shutil.rmtree(submission_dir)
        shutil.copytree(src, submission_dir)

        exported_main = submission_dir / "main.py"
        if not exported_main.exists():
            return False, "exported submission missing main.py"

        return True, "submission exported"

    def _run_cmd(self, codebase_dir: Path, cmd: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            cmd,
            cwd=codebase_dir,
            capture_output=True,
            text=True,
            check=False,
        )

    @staticmethod
    def _load_compact_rows(path: Path) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        if not path.exists():
            return rows
        for line in path.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except Exception:
                continue
            if isinstance(payload, dict):
                rows.append(payload)
        return rows

    @staticmethod
    def _events_from_rows(
        rows: list[dict[str, Any]],
        *,
        trajectory_path: Path,
        winner_seats: Any,
    ) -> dict[str, Any]:
        if not rows:
            return {
                "trajectory_path": str(trajectory_path),
                "capture_status": "unsupported",
                "step_count": 0,
                "terminal_step": None,
                "winner_seats": winner_seats if isinstance(winner_seats, list) else None,
                "first_reward_change_step": None,
                "alive_change_steps": [],
                "final_reward": None,
                "capture_notes": ["trajectory_empty_or_unavailable"],
            }
        alive_change_steps: list[int] = []
        first_reward_change_step: int | None = None
        terminal_step: int | None = None
        capture_notes: list[str] = []
        for row in rows:
            flags = row.get("event_flags") if isinstance(row.get("event_flags"), dict) else {}
            step = row.get("step")
            if flags.get("alive_changed") is True and isinstance(step, int):
                alive_change_steps.append(step)
            if first_reward_change_step is None and flags.get("reward_changed") is True and isinstance(step, int):
                first_reward_change_step = step
            if flags.get("terminal") is True and isinstance(step, int):
                terminal_step = step
            notes = row.get("capture_notes")
            if isinstance(notes, list):
                for n in notes:
                    if isinstance(n, str) and n not in capture_notes:
                        capture_notes.append(n)
        final_reward = rows[-1].get("reward")
        status = "captured"
        if capture_notes:
            status = "partial"
        return {
            "trajectory_path": str(trajectory_path),
            "capture_status": status,
            "step_count": len(rows),
            "terminal_step": terminal_step,
            "winner_seats": winner_seats if isinstance(winner_seats, list) else None,
            "first_reward_change_step": first_reward_change_step,
            "alive_change_steps": alive_change_steps,
            "final_reward": final_reward,
            "capture_notes": capture_notes,
        }

    @staticmethod
    def _normalize_seed_provenance(
        *,
        requested_seed: int | None,
        applied_seed: int | None,
        seed: int | None,
        status: str | None,
        error: str | None,
        attempted: list[str] | None,
        method_applied: str | None,
        env_seed_return: Any,
    ) -> tuple[int | None, int | None, int | None, str, str | None, list[str], str | None, Any]:
        normalized_status = status if isinstance(status, str) else None
        methods = attempted if isinstance(attempted, list) else []
        err = error if isinstance(error, str) else None
        method = method_applied if isinstance(method_applied, str) else None
        app = applied_seed if isinstance(applied_seed, int) else None
        req = requested_seed if isinstance(requested_seed, int) else None
        seeded = seed if isinstance(seed, int) else None

        if normalized_status not in {"applied", "requested_but_not_applied", "unsupported_by_environment", "not_requested"}:
            if req is None:
                normalized_status = "not_requested"
            elif app == req:
                normalized_status = "applied"
            else:
                normalized_status = "requested_but_not_applied"

        if normalized_status == "applied":
            if req is None or app != req:
                normalized_status = "requested_but_not_applied" if req is not None else "not_requested"
                app = None
                seeded = None
                method = None
            else:
                seeded = req
                err = None
                if not method:
                    method = "unknown_env_seed_api"
        elif normalized_status in {"requested_but_not_applied", "unsupported_by_environment"}:
            app = None
            seeded = None
            method = None
            env_seed_return = None
            if not methods:
                methods = ["env.reset(seed=...)", "env.seed(...)"]
            if req is not None and (not isinstance(err, str) or not err.strip()):
                err = "requested seed could not be applied by environment seed/reset APIs"
        else:
            app = None
            seeded = None
            err = None
            env_seed_return = None
            if req is None:
                methods = []
                method = None

        return req, app, seeded, normalized_status, err, methods, method, env_seed_return

    @staticmethod
    def _seed_control_from_payload(
        payload: dict[str, Any], requested_seed: int | None
    ) -> tuple[int | None, int | None, int | None, str, str | None, list[str], str | None, Any]:
        req_raw = payload.get("requested_seed")
        req = req_raw if isinstance(req_raw, int) else requested_seed
        return Pommerman1v1Adapter._normalize_seed_provenance(
            requested_seed=req,
            applied_seed=payload.get("applied_seed"),
            seed=payload.get("seed"),
            status=payload.get("seed_control_status"),
            error=payload.get("seed_control_error"),
            attempted=payload.get("seed_control_methods_attempted"),
            method_applied=payload.get("seed_control_method_applied"),
            env_seed_return=payload.get("seed_control_env_seed_return"),
        )

    @staticmethod
    def _seed_status_for_match(req: int | None, app: int | None, payload: dict[str, Any]) -> str:
        status = payload.get("seed_control_status")
        if isinstance(status, str) and status in {"applied", "requested_but_not_applied", "unsupported_by_environment"}:
            return status
        if req is not None and app == req:
            return "applied"
        if req is not None:
            return "requested_but_not_applied"
        return "unsupported_by_environment"

    def run_match(
        self,
        left_codebase: Path,
        right_codebase: Path,
        round_dir: Path,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        round_dir = round_dir.resolve()
        round_dir.mkdir(parents=True, exist_ok=True)

        requested_seed = config.get("requested_seed")
        if requested_seed is None and isinstance(config.get("seed"), int):
            requested_seed = int(config["seed"])

        left_build = self._run_cmd(left_codebase, ["bash", "scripts/build.sh"])
        right_build = self._run_cmd(right_codebase, ["bash", "scripts/build.sh"])

        left_smoke = self._run_cmd(left_codebase, ["bash", "tests/smoke.sh"])
        right_smoke = self._run_cmd(right_codebase, ["bash", "tests/smoke.sh"])

        build_log = []
        build_log.append("=== LEFT BUILD ===")
        build_log.append(left_build.stdout)
        build_log.append(left_build.stderr)
        build_log.append("=== RIGHT BUILD ===")
        build_log.append(right_build.stdout)
        build_log.append(right_build.stderr)
        (round_dir / "build.log").write_text("\n".join(build_log), encoding="utf-8")

        test_log = []
        test_log.append("=== LEFT SMOKE ===")
        test_log.append(left_smoke.stdout)
        test_log.append(left_smoke.stderr)
        test_log.append("=== RIGHT SMOKE ===")
        test_log.append(right_smoke.stdout)
        test_log.append(right_smoke.stderr)
        (round_dir / "test.log").write_text("\n".join(test_log), encoding="utf-8")

        stderr_chunks = []
        if left_build.stderr:
            stderr_chunks.append(f"[LEFT BUILD STDERR]\\n{left_build.stderr}")
        if right_build.stderr:
            stderr_chunks.append(f"[RIGHT BUILD STDERR]\\n{right_build.stderr}")
        if left_smoke.stderr:
            stderr_chunks.append(f"[LEFT SMOKE STDERR]\\n{left_smoke.stderr}")
        if right_smoke.stderr:
            stderr_chunks.append(f"[RIGHT SMOKE STDERR]\\n{right_smoke.stderr}")

        left_ok = (left_build.returncode == 0) and (left_smoke.returncode == 0)
        right_ok = (right_build.returncode == 0) and (right_smoke.returncode == 0)

        arena_result_match_a_path = (round_dir / "arena_result_match_a.json").resolve()
        arena_result_match_b_path = (round_dir / "arena_result_match_b.json").resolve()
        compact_match_a_path = (round_dir / "trajectory_compact_match_a.jsonl").resolve()
        compact_match_b_path = (round_dir / "trajectory_compact_match_b.jsonl").resolve()
        trajectory_events_path = (round_dir / "trajectory_events.json").resolve()
        legacy_arena_result_path = round_dir / "arena_result.json"
        legacy_pair_scorecard_path = round_dir / "pair_scorecard.json"
        if legacy_arena_result_path.exists():
            legacy_arena_result_path.unlink()
        if legacy_pair_scorecard_path.exists():
            legacy_pair_scorecard_path.unlink()
        paired_match_id = f"{round_dir.name}_seat_swap_pair_1"
        left_submission_main = (left_codebase / "submission" / "main.py").resolve()
        right_submission_main = (right_codebase / "submission" / "main.py").resolve()
        fallback_seed_status = "requested_but_not_applied" if requested_seed is not None else "unsupported_by_environment"

        if left_ok and right_ok:
            req_a = req_b = requested_seed
            app_a = app_b = seed_a = seed_b = None
            status_a = status_b = "requested_but_not_applied"
            err_a = err_b = None
            attempted_a = attempted_b = ["env.reset(seed=...)", "env.seed(...)"] if requested_seed is not None else []
            method_a = method_b = None
            env_seed_ret_a = env_seed_ret_b = None
            arena_run_match_a = self._run_cmd(
                left_codebase,
                [
                    "bash",
                    "scripts/run_arena.sh",
                    str(arena_result_match_a_path),
                    str(left_submission_main),
                    str(right_submission_main),
                    str(compact_match_a_path),
                    str(requested_seed) if requested_seed is not None else "",
                ],
            )
            arena_run_match_b = self._run_cmd(
                left_codebase,
                [
                    "bash",
                    "scripts/run_arena.sh",
                    str(arena_result_match_b_path),
                    str(right_submission_main),
                    str(left_submission_main),
                    str(compact_match_b_path),
                    str(requested_seed) if requested_seed is not None else "",
                ],
            )

            if arena_run_match_a.stderr:
                stderr_chunks.append(f"[ARENA MATCH A STDERR]\\n{arena_run_match_a.stderr}")
            if arena_run_match_b.stderr:
                stderr_chunks.append(f"[ARENA MATCH B STDERR]\\n{arena_run_match_b.stderr}")

            if (
                arena_run_match_a.returncode == 0
                and arena_run_match_b.returncode == 0
                and arena_result_match_a_path.exists()
                and arena_result_match_b_path.exists()
            ):
                arena_payload_match_a = json.loads(arena_result_match_a_path.read_text(encoding="utf-8"))
                arena_payload_match_b = json.loads(arena_result_match_b_path.read_text(encoding="utf-8"))
                req_a, app_a, seed_a, status_a, err_a, attempted_a, method_a, env_seed_ret_a = self._seed_control_from_payload(
                    arena_payload_match_a, requested_seed
                )
                req_b, app_b, seed_b, status_b, err_b, attempted_b, method_b, env_seed_ret_b = self._seed_control_from_payload(
                    arena_payload_match_b, requested_seed
                )
                arena_payload_match_a["paired_match_id"] = paired_match_id
                arena_payload_match_a["match_label"] = "match_a"
                arena_payload_match_a["left_submission"] = str(left_submission_main)
                arena_payload_match_a["right_submission"] = str(right_submission_main)
                arena_payload_match_a["seat_assignment"] = {
                    "seat_0_submission": "left",
                    "seat_1_submission": "right",
                    "seat_2_submission": "dummy2",
                    "seat_3_submission": "dummy3",
                }
                arena_payload_match_b["paired_match_id"] = paired_match_id
                arena_payload_match_b["match_label"] = "match_b"
                arena_payload_match_b["left_submission"] = str(left_submission_main)
                arena_payload_match_b["right_submission"] = str(right_submission_main)
                arena_payload_match_b["seat_assignment"] = {
                    "seat_0_submission": "right",
                    "seat_1_submission": "left",
                    "seat_2_submission": "dummy2",
                    "seat_3_submission": "dummy3",
                }
                for payload, req, app, seed, status, err, attempted, method, env_seed_ret in [
                    (arena_payload_match_a, req_a, app_a, seed_a, status_a, err_a, attempted_a, method_a, env_seed_ret_a),
                    (arena_payload_match_b, req_b, app_b, seed_b, status_b, err_b, attempted_b, method_b, env_seed_ret_b),
                ]:
                    payload["requested_seed"] = req
                    payload["applied_seed"] = app
                    payload["seed"] = seed
                    payload["seed_control_status"] = status
                    payload["seed_control_error"] = err
                    payload["seed_control_methods_attempted"] = attempted
                    payload["seed_control_method_applied"] = method
                    payload["seed_control_env_seed_return"] = env_seed_ret
                arena_result_match_a_path.write_text(
                    json.dumps(arena_payload_match_a, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                arena_result_match_b_path.write_text(
                    json.dumps(arena_payload_match_b, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                rows_a = self._load_compact_rows(compact_match_a_path)
                rows_b = self._load_compact_rows(compact_match_b_path)
                for row in rows_a:
                    row["leg_label"] = "match_a"
                for row in rows_b:
                    row["leg_label"] = "match_b"
                compact_match_a_path.write_text(
                    "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows_a),
                    encoding="utf-8",
                )
                compact_match_b_path.write_text(
                    "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows_b),
                    encoding="utf-8",
                )
                round_name = round_dir.parent.name
                round_idx = None
                if round_name.startswith("round_"):
                    try:
                        round_idx = int(round_name.split("_", 1)[1])
                    except Exception:
                        round_idx = None
                match_idx = None
                if round_dir.name.startswith("match_"):
                    try:
                        match_idx = int(round_dir.name.split("_", 1)[1])
                    except Exception:
                        match_idx = None
                left_agent_id = left_codebase.parent.name
                right_agent_id = right_codebase.parent.name
                pair_id = "__vs__".join(sorted([left_agent_id, right_agent_id]))
                trajectory_events_payload = {
                    "schema_version": "pommerman_compact_trajectory_events_v2",
                    "round_idx": round_idx,
                    "match_idx": match_idx,
                    "match_id": round_dir.name,
                    "pair_id": pair_id,
                    "legs": {
                        "match_a": self._events_from_rows(
                            rows_a,
                            trajectory_path=compact_match_a_path,
                            winner_seats=((arena_payload_match_a.get("info") or {}).get("winners")),
                        ),
                        "match_b": self._events_from_rows(
                            rows_b,
                            trajectory_path=compact_match_b_path,
                            winner_seats=((arena_payload_match_b.get("info") or {}).get("winners")),
                        ),
                    },
                    "agent_event_summaries": {
                        left_agent_id: {
                            "agent_id": left_agent_id,
                            "roles_seen": ["left", "right"],
                            "observed_steps": [
                                len(rows_a),
                                len(rows_b),
                            ],
                            "alive_change_observed": bool(
                                self._events_from_rows(
                                    rows_a,
                                    trajectory_path=compact_match_a_path,
                                    winner_seats=((arena_payload_match_a.get("info") or {}).get("winners")),
                                )["alive_change_steps"]
                                or self._events_from_rows(
                                    rows_b,
                                    trajectory_path=compact_match_b_path,
                                    winner_seats=((arena_payload_match_b.get("info") or {}).get("winners")),
                                )["alive_change_steps"]
                            ),
                            "terminal_outcomes": [
                                self._events_from_rows(
                                    rows_a,
                                    trajectory_path=compact_match_a_path,
                                    winner_seats=((arena_payload_match_a.get("info") or {}).get("winners")),
                                )["terminal_step"],
                                self._events_from_rows(
                                    rows_b,
                                    trajectory_path=compact_match_b_path,
                                    winner_seats=((arena_payload_match_b.get("info") or {}).get("winners")),
                                )["terminal_step"],
                            ],
                            "compact_process_observations": [
                                "Compact trajectory captured without full board replay.",
                            ],
                        },
                        right_agent_id: {
                            "agent_id": right_agent_id,
                            "roles_seen": ["left", "right"],
                            "observed_steps": [
                                len(rows_a),
                                len(rows_b),
                            ],
                            "alive_change_observed": bool(
                                self._events_from_rows(
                                    rows_a,
                                    trajectory_path=compact_match_a_path,
                                    winner_seats=((arena_payload_match_a.get("info") or {}).get("winners")),
                                )["alive_change_steps"]
                                or self._events_from_rows(
                                    rows_b,
                                    trajectory_path=compact_match_b_path,
                                    winner_seats=((arena_payload_match_b.get("info") or {}).get("winners")),
                                )["alive_change_steps"]
                            ),
                            "terminal_outcomes": [
                                self._events_from_rows(
                                    rows_a,
                                    trajectory_path=compact_match_a_path,
                                    winner_seats=((arena_payload_match_a.get("info") or {}).get("winners")),
                                )["terminal_step"],
                                self._events_from_rows(
                                    rows_b,
                                    trajectory_path=compact_match_b_path,
                                    winner_seats=((arena_payload_match_b.get("info") or {}).get("winners")),
                                )["terminal_step"],
                            ],
                            "compact_process_observations": [
                                "Compact trajectory captured without full board replay.",
                            ],
                        },
                    },
                    "limitations": [
                        "compact trajectory v2 does not store full board arrays",
                        "compact trajectory v2 does not store full observations",
                        "death causes, bomb ownership, and power-up pickup causes are only recorded if available from compact fields",
                    ],
                    "requested_seed": req_a,
                    "applied_seed": app_a,
                    "seed": seed_a,
                    "seed_control_status": status_a,
                    "seed_control_error": err_a,
                    "seed_control_methods_attempted": attempted_a,
                    "seed_control_method_applied": method_a,
                    "seed_control_env_seed_return": env_seed_ret_a,
                    "requested_seed_match_b": req_b,
                    "applied_seed_match_b": app_b,
                    "seed_match_b": seed_b,
                    "seed_control_status_match_b": status_b,
                    "seed_control_error_match_b": err_b,
                    "seed_control_methods_attempted_match_b": attempted_b,
                    "seed_control_method_applied_match_b": method_b,
                    "seed_control_env_seed_return_match_b": env_seed_ret_b,
                }
                trajectory_events_path.write_text(
                    json.dumps(trajectory_events_payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

                scorecard_payload = {
                    **arena_payload_match_a,
                    "paired_match_id": paired_match_id,
                    "match_label": "match_a",
                    "seat_assignment": {
                        "seat_0_submission": "left",
                        "seat_1_submission": "right",
                        "seat_2_submission": "dummy2",
                        "seat_3_submission": "dummy3",
                    },
                    "requested_seed": req_a,
                    "applied_seed": app_a,
                    "seed": seed_a,
                    "seed_control_status": status_a,
                    "seed_control_error": err_a,
                    "seed_control_methods_attempted": attempted_a,
                    "seed_control_method_applied": method_a,
                    "seed_control_env_seed_return": env_seed_ret_a,
                }

                (round_dir / "scorecard.json").write_text(
                    json.dumps(scorecard_payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

                winner = arena_payload_match_a.get("left_right_winner", "draw")
                result = "submission_vs_submission_ffa_proxy_completed"
                runtime_ok = bool(arena_payload_match_a.get("done", False)) and bool(
                    arena_payload_match_b.get("done", False)
                )
                stderr_excerpt_parts = []
                if arena_run_match_a.stderr:
                    stderr_excerpt_parts.append(arena_run_match_a.stderr[:150])
                if arena_run_match_b.stderr:
                    stderr_excerpt_parts.append(arena_run_match_b.stderr[:150])
                stderr_excerpt = " | ".join(stderr_excerpt_parts)
            else:
                env_seed_ret_a = env_seed_ret_b = None
                if requested_seed is not None:
                    err_a = err_b = "arena probe failed before seed application could be confirmed"
                winner = "draw"
                result = "arena_probe_failed"
                runtime_ok = False
                stderr_excerpt_parts = []
                if arena_run_match_a.stderr:
                    stderr_excerpt_parts.append(arena_run_match_a.stderr[:150])
                if arena_run_match_b.stderr:
                    stderr_excerpt_parts.append(arena_run_match_b.stderr[:150])
                stderr_excerpt = " | ".join(stderr_excerpt_parts) if stderr_excerpt_parts else "arena probe failed"
        else:
            req_a = req_b = requested_seed
            app_a = app_b = seed_a = seed_b = None
            status_a = status_b = "requested_but_not_applied" if requested_seed is not None else "not_requested"
            err_a = err_b = (
                "build or smoke failed before seed application could be attempted"
                if requested_seed is not None
                else None
            )
            attempted_a = attempted_b = ["env.reset(seed=...)", "env.seed(...)"] if requested_seed is not None else []
            method_a = method_b = None
            env_seed_ret_a = env_seed_ret_b = None
            winner = "draw"
            result = "build_or_smoke_failed"
            runtime_ok = False
            stderr_excerpt = "build or smoke failed"

        (round_dir / "stderr.log").write_text("\\n\\n".join(stderr_chunks), encoding="utf-8")

        return {
            "winner": winner,
            "result": result,
            "runtime_diagnostics": {
                "compile_ok": left_build.returncode == 0 and right_build.returncode == 0,
                "runtime_ok": runtime_ok,
                "invalid_actions": 0 if runtime_ok else 1,
                "timeout": False,
                "stderr_excerpt": stderr_excerpt,
                "validate_submission_ok": True,
                "validate_submission_msg": "starter repo contract valid",
                "left_build_rc": left_build.returncode,
                "right_build_rc": right_build.returncode,
                "left_smoke_rc": left_smoke.returncode,
                "right_smoke_rc": right_smoke.returncode,
                "seed_control_status": status_a if left_ok and right_ok else fallback_seed_status,
            },
        }
