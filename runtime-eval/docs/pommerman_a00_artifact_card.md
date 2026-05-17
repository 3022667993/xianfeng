# Pommerman + A00 Artifact Card

## Checkpoint
- Scope: `runtime-eval` only
- Experiment family: Pommerman + A00 only
- Latest verified code checkpoint includes: `bb050e14` (Add two-round OpenClaw adaptive smoke)
- Status: smoke/artifact/reproducibility checkpoint with validated route, revision, and adaptive smokes

## 1) Scope
Included:
- A00 artifact/smoke paths
- Formal schedule dry-run + audit
- Generic schedule builder/audit helpers
- 6-model execution smoke
- 10-round adaptive dry-run
- Pommerman process feedback v1
- OpenClaw route validation
- Real OpenClaw-Minimal revision smokes (single-agent and all-agent, both 1-round)
- 2-round real OpenClaw adaptive smoke
- Pommerman seed control applied via `env.seed(...)`
- Compact trajectory v2 has run

Not included:
- A01, A11, A10
- Lux, Kore, Halite, Held-Out
- Paired aggregate scorecards
- Full board/observation replay
- Full 10-round real OpenClaw adaptive run

## 2) Current Completed Stages
1. A00 artifact/smoke layer
- 2-leg smoke artifact completed.
- Raw per-match scorecards preserved.
- `logs/pairing_manifest.json` generated and audited.
- Seed provenance recorded.
- Seed control is applied via `env.seed(...)`.

2. Formal schedule dry-run
- Two-cycle double round robin.
- 6 agents, 10 rounds, 3 matches per round, 30 total matches.
- Cycle mapping:
  - cycle_1 rounds `1-5`
  - cycle_2 rounds `6-10`
- cycle_2 repeats cycle_1 pair order with seats swapped.
- No paired aggregate scorecard.

3. Generic scheduler
- Supports 6/8/10/12/13 agents.
- Even `N`: perfect matching each round.
- Odd `N`: BYE scheduling.
- BYE is schedule-only; BYE is not treated as an agent artifact.

4. 6-model execution smoke
- `1 round x 3 matches`.
- Per-agent workspace persistence.
- No persistent `left/right` state directories.

5. 10-round adaptive dry-run
- `10 rounds x 3 matches` (30 matches).
- Low-cost dryrun/noop revision path.
- Round-to-round propagation: `codebase_post_t -> codebase_play_{t+1}`.
- This is not real OpenClaw revision execution.

6. OpenClaw route validation
- `scripts/validate_openclaw_model_routes.py`
- `scripts/audit_openclaw_model_routes.py`
- Confirms all six current `provider_model` refs are known routes.
- Fallback to `relay/gpt-4.1` does not count as success.

7. Pommerman process feedback v1
- Audit:
  - `scripts/audit_pommerman_process_feedback.py`
- Process feedback v1 has run.
- Generated per match:
  - `logs/round_<r>/match_<m>/trajectory_summary.json`
  - `logs/round_<r>/match_<m>/agent_feedback_<agent_id>.json`
  - `logs/round_<r>/match_<m>/agent_feedback_<agent_id>.md`
- Source artifacts (result-level only):
  - `metadata.json`
  - `scorecard.json`
  - `arena_result_match_a.json`
  - `arena_result_match_b.json`
- Seat-swap handling:
  - combines `match_a` and `match_b` outcomes for tested agents
  - feedback files are generated for tested agents only (not `dummy2` / `dummy3`)
- Hint policy:
  - seat-swap instability hint only when `outcome_changed_under_swap=true` or `seat_sensitivity_observed=true`
  - neutral robustness hint when no seat-swap outcome change was observed
- Explicit limitations:
  - no tick-level actions, board states, bomb events, or death causes are recorded yet
  - this is not full replay

8. Real OpenClaw-Minimal revision smokes
- Single-agent real revision smoke passes.
- All-agent real revision smoke passes.
- For all six agents in all-agent smoke:
  - `revision_ok=true`
  - `provider_route_status=matched`
  - `fallback_used=false`
- This remains a 1-round smoke, not the full 10-round real experiment.

9. 2-round real OpenClaw adaptive smoke
- Config:
  - `configs/tournaments/pommerman_gptv16_a00_openclaw_adaptive_2round_smoke.yaml`
- Audit:
  - `scripts/audit_pommerman_openclaw_adaptive_2round_smoke.py`
- Execution structure:
  - round 1: 3 raw matches
  - round 1 post-match: all 6 agents get real OpenClaw-Minimal revision
  - round 2: 3 raw matches using propagated `codebase_play_2`
- Verification:
  - all 6 revision entries have `revision_ok=true`
  - all 6 have `provider_route_status=matched`
  - `fallback_used=false` for all agents
  - `logs/round_2/propagation_manifest.json` records `codebase_post_1 -> codebase_play_2` for every agent
  - `propagation_ok=true`, `source_revision_ok=true`, `source_provider_route_status=matched`
- This remains a smoke, not the full 10-round real OpenClaw experiment.

10. Pommerman seed control applied
- Audit:
  - `scripts/audit_pommerman_seed_control.py`
- Expected success:
  - `pommerman_seed_control_audit=PASS`
- Seed provenance fields are propagated into:
  - `metadata.json`
  - `scorecard.json`
  - `arena_result_match_a.json`
  - `arena_result_match_b.json`
  - `trajectory_summary.json`
  - `trajectory_events.json`
- Current status:
  - `seed_control_status=applied`
  - `applied_seed=requested_seed`
  - `seed=requested_seed`
  - `seed_control_method_applied=env.seed(...)`
- Previous warning `seed requested but not applied` is resolved for current Pommerman adaptive smoke.

11. Feedback available to models each round
- Models can read:
  - `metadata.json`
  - `scorecard.json`
  - `arena_result_match_a.json`
  - `arena_result_match_b.json`
  - `build.log`
  - `test.log`
  - `stderr.log`
  - `trajectory_summary.json`
  - `agent_feedback_<agent_id>.json`
  - `agent_feedback_<agent_id>.md`
  - `trajectory_compact_match_a.jsonl`
  - `trajectory_compact_match_b.jsonl`
  - `trajectory_events.json`
  - `notes/revision_log.md` and `revision_audit.json` from prior revisions when present
- `process feedback v1` is a factual summary layer.
- compact trajectory v2 has run.
- compact trajectory v2 is lightweight per-step process feedback.
- compact trajectory v2 is not full replay.
- no full board arrays or full observations are stored.
- death causes, bomb ownership, and power-up pickup causes remain future work unless explicitly supported by compact fields.

12. Revision autonomy
- Runner/config decides OpenClaw invocation using:
  - `revision_rounds`
  - `revision_subset_size`
  - `require_all_agents_revised`
- During OpenClaw revision, models autonomously decide how to modify code.
- A model may make small changes or no meaningful code change.
- Audits verify invocation, provider route, `fallback_used=false`, and `revision_ok`.
- Audits do not require a forced code diff in every round.

## 3) Current Route-Valid 6-Agent Roster
Config:
- `configs/models/openclaw_relay_6model_deepseek_glm.yaml`

Agents:
- `relay_bailian_deepseek_v4_flash` -> `relay/bailian/deepseek-v4-flash`
- `relay_gemini_2_5_flash_thinking` -> `relay/gemini-2.5-flash-thinking`
- `relay_deepseek_v3` -> `relay/deepseek-ai/DeepSeek-V3.2`
- `relay_qwen3_5_plus` -> `relay/qwen3.5-plus`
- `relay_glm_4_7` -> `glm-4.7`
- `relay_glm_4_6` -> `glm-4.6`

## 4) Route Corrections (Historical Note)
- `deepseek-ai/DeepSeek-V2.5` removed (not route-valid in installed OpenClaw catalog).
- `deepseek-ai/DeepSeek-V3` replaced by `relay/deepseek-ai/DeepSeek-V3.2` (bare route failed real invocation).
- `glm-4.5v` removed (real invocation failed due to provider schema/tool payload rejection).
- `llama-3.1-70b-instruct` considered but not used (not found as a known route in installed catalog).

## 5) Key Semantics
- `agent_id` is persistent model identity.
- `left/right` is match seat assignment only.
- Background agents are fixed: `dummy2`, `dummy3`.
- Raw scorecards are preserved.
- Pair-level aggregation is post-analysis only.
- No paired aggregate scorecard is generated.
- No persistent `left/right` workspace state in execution/revision/adaptive smokes.

## 6) Reproduction Commands
```bash
python -m pytest tests -q

bash scripts/run_pommerman_a00_artifact.sh

python scripts/validate_openclaw_model_routes.py \
  --models configs/models/openclaw_relay_6model_deepseek_glm.yaml
python scripts/audit_openclaw_model_routes.py

python scripts/audit_pommerman_process_feedback.py
python scripts/audit_pommerman_compact_trajectory.py
python scripts/audit_pommerman_seed_control.py

python scripts/audit_pommerman_formal_schedule.py \
  --models configs/models/openclaw_relay_6model_deepseek_glm.yaml

python -m runner.main \
  --regime configs/regimes/A00.yaml \
  --tournament configs/tournaments/pommerman_gptv16_a00_openclaw_revision_smoke.yaml \
  --models configs/models/openclaw_relay_6model_deepseek_glm.yaml
python scripts/audit_pommerman_openclaw_revision_smoke.py

python -m runner.main \
  --regime configs/regimes/A00.yaml \
  --tournament configs/tournaments/pommerman_gptv16_a00_openclaw_revision_smoke_all_agents.yaml \
  --models configs/models/openclaw_relay_6model_deepseek_glm.yaml
python scripts/audit_pommerman_openclaw_revision_smoke_all_agents.py

python -m runner.main \
  --regime configs/regimes/A00.yaml \
  --tournament configs/tournaments/pommerman_gptv16_a00_openclaw_adaptive_2round_smoke.yaml \
  --models configs/models/openclaw_relay_6model_deepseek_glm.yaml
python scripts/audit_pommerman_openclaw_adaptive_2round_smoke.py

python -m runner.main \
  --regime configs/regimes/A00.yaml \
  --tournament configs/tournaments/pommerman_gptv16_a00_6model_adaptive_dryrun.yaml \
  --models configs/models/openclaw_relay_6model_deepseek_glm.yaml
python scripts/audit_pommerman_10round_adaptive_dryrun.py

# Optional inspection examples
find logs/round_1/match_1 -maxdepth 1 -type f | sort | grep -E "trajectory|agent_feedback"
sed -n '1,220p' logs/round_1/match_1/agent_feedback_<agent_id>.md
```

## 7) Expected Success Signals
- `pytest` passes
- `pairing_manifest_audit=PASS`
- `formal_schedule_audit=PASS`
- `openclaw_model_route_audit=PASS`
- `pommerman_process_feedback_audit=PASS`
- `pommerman_compact_trajectory_audit=PASS`
- `pommerman_seed_control_audit=PASS`
- `openclaw_revision_smoke_audit=PASS`
- `openclaw_revision_smoke_all_agents_audit=PASS`
- `openclaw_adaptive_2round_smoke_audit=PASS`
- `adaptive_dryrun_audit=PASS`
- no `seed requested but not applied` warnings for current Pommerman adaptive smoke

## 8) Output Artifacts
- `logs/pairing_manifest.json`
- `logs/pommerman_formal_schedule_manifest.json`
- `logs/round_1/round_manifest.json`
- `logs/round_1/revision_manifest.json`
- `logs/round_2/round_manifest.json`
- `logs/round_2/propagation_manifest.json`
- `logs/round_<r>/match_<m>/trajectory_summary.json`
- `logs/round_<r>/match_<m>/agent_feedback_<agent_id>.json`
- `logs/round_<r>/match_<m>/agent_feedback_<agent_id>.md`
- `logs/round_1/match_1/`, `logs/round_1/match_2/`, `logs/round_1/match_3/`
- `logs/round_2/match_1/`, `logs/round_2/match_2/`, `logs/round_2/match_3/`
- `workspace/codebases/<tournament>/<agent_id>/codebase_play_1/`
- `workspace/submissions/<tournament>/<agent_id>/submission_1/`
- `workspace/posts/<tournament>/<agent_id>/codebase_post_1/`
- `workspace/codebases/<tournament>/<agent_id>/codebase_play_2/`
- `workspace/submissions/<tournament>/<agent_id>/submission_2/`
- `workspace/posts/<tournament>/<agent_id>/codebase_post_2/`

## 9) Generated Artifacts Policy
- `workspace/` is generated runtime state.
- `logs/round_*` are generated run artifacts.
- Generated artifacts should not be versioned.
- Verify generated paths are not tracked:
  - `git ls-files workspace`
  - `git ls-files logs`

## 10) Strict Status Wording
- process feedback v1 has run.
- 2-round real OpenClaw adaptive smoke has run.
- 10-round adaptive dry-run has run.
- compact trajectory v2 has run.
- full board/observation replay remains future work.
- Full 10-round real OpenClaw adaptive run remains future work.
