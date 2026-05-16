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
- OpenClaw route validation
- Real OpenClaw-Minimal revision smokes (single-agent and all-agent, both 1-round)
- 2-round real OpenClaw adaptive smoke

Not included:
- A01, A11, A10
- Lux, Kore, Halite, Held-Out
- Paired aggregate scorecards
- Full 10-round real OpenClaw adaptive tournament execution

## 2) Current Completed Stages
1. A00 artifact/smoke layer
- 2-leg smoke artifact completed.
- Raw per-match scorecards preserved.
- `logs/pairing_manifest.json` generated and audited.
- Seed provenance recorded.
- `requested_but_not_applied` seed warnings are acceptable.

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

7. Real OpenClaw-Minimal revision smokes
- Single-agent real revision smoke passes.
- All-agent real revision smoke passes.
- For all six agents in all-agent smoke:
  - `revision_ok=true`
  - `provider_route_status=matched`
  - `fallback_used=false`
- This remains a 1-round smoke, not the full 10-round real experiment.

8. 2-round real OpenClaw adaptive smoke
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

## 3) Current Route-Valid 6-Agent Roster
Config:
- `configs/models/openclaw_relay_6model_deepseek_glm.yaml`

Agents:
- `relay_bailian_deepseek_v4_flash` -> `relay/bailian/deepseek-v4-flash`
- `relay_gemini_2_5_flash_thinking` -> `relay/gemini-2.5-flash-thinking`
- `relay_deepseek_v3` -> `relay/deepseek-ai/DeepSeek-V3.2`
- `relay_glm_4_7` -> `glm-4.7`
- `relay_glm_4_6` -> `glm-4.6`
- `relay_glm_4_6v` -> `relay/glm-4.6v`

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
```

## 7) Expected Success Signals
- `pytest` passes
- `pairing_manifest_audit=PASS`
- `formal_schedule_audit=PASS`
- `openclaw_model_route_audit=PASS`
- `openclaw_revision_smoke_audit=PASS`
- `openclaw_revision_smoke_all_agents_audit=PASS`
- `openclaw_adaptive_2round_smoke_audit=PASS`
- `adaptive_dryrun_audit=PASS`

## 8) Output Artifacts
- `logs/pairing_manifest.json`
- `logs/pommerman_formal_schedule_manifest.json`
- `logs/round_1/round_manifest.json`
- `logs/round_1/revision_manifest.json`
- `logs/round_2/round_manifest.json`
- `logs/round_2/propagation_manifest.json`
- `logs/round_1/match_1/`, `logs/round_1/match_2/`, `logs/round_1/match_3/`
- `logs/round_2/match_1/`, `logs/round_2/match_2/`, `logs/round_2/match_3/`
- `workspace/codebases/<tournament>/<agent_id>/codebase_play_1/`
- `workspace/submissions/<tournament>/<agent_id>/submission_1/`
- `workspace/posts/<tournament>/<agent_id>/codebase_post_1/`
- `workspace/codebases/<tournament>/<agent_id>/codebase_play_2/`
- `workspace/submissions/<tournament>/<agent_id>/submission_2/`
- `workspace/posts/<tournament>/<agent_id>/codebase_post_2/`

## 9) Known Warnings
- `requested_seed` with `seed_control_status=requested_but_not_applied` is acceptable for current smoke/adaptive layers because environment-level seed application is not yet proven.
- This is a warning, not a failure.

## 10) Strict Status Wording
- 2-round real OpenClaw adaptive smoke has run.
- 10-round adaptive dry-run has run.
- Full 10-round real OpenClaw adaptive run remains future work.
