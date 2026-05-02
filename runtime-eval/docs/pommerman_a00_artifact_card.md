# Pommerman + A00 Artifact Card

## Checkpoint
- Commit: `159b4593`
- Repository scope in this card: `runtime-eval`
- Status: smoke/artifact/reproducibility checkpoint

## 1) Scope
This checkpoint only covers Pommerman + A00.

Included:
- Pommerman + A00 smoke artifact paths
- Formal 6-model schedule dry-run manifest/audit
- 6-model execution smoke (`1 round x 3 matches`)

Explicitly not in scope:
- A01, A11, A10
- Lux, Kore, Halite
- Held-Out evaluations
- Full formal 10-round execution
- Paired aggregate scorecards

## 2) Current Validated Components
- A00 memory-minimal config: `configs/regimes/A00.yaml`
- 2-leg Pommerman smoke artifact
- `logs/pairing_manifest.json`
- Seed provenance in smoke artifacts/manifests
- Formal 6-model schedule dry-run
- 6-model execution smoke (`1 round x 3 matches`)
- DeepSeek/GLM roster config: `configs/models/openclaw_relay_6model_deepseek_glm.yaml`
- Per-agent workspace persistence layout

DeepSeek/GLM roster in this checkpoint:
- `relay_bailian_deepseek_v4_flash` -> `bailian/deepseek-v4-flash`
- `relay_deepseek_v2_5` -> `deepseek-ai/DeepSeek-V2.5`
- `relay_deepseek_v3` -> `deepseek-ai/DeepSeek-V3`
- `relay_glm_4_5v` -> `glm-4.5v`
- `relay_glm_4_6` -> `glm-4.6`
- `relay_glm_4_7` -> `glm-4.7`

## 3) Important Semantics
- `agent_id` is the persistent model identity.
- `left/right` is only per-match seat assignment.
- In 6-model execution smoke, persistent state is **per-agent**, not per `left/right`.
- Background agents are fixed: `dummy2`, `dummy3`.
- Raw per-match scorecards are preserved.
- No paired aggregate scorecard is generated.
- Pair-level aggregation is post-analysis only.
- Formal dry-run uses `planned_seed` with `seed_control_status=planned_not_executed`.
- Executed smoke records `requested_seed`; when environment-level application cannot be proven, status may be `requested_but_not_applied`.

## 4) Reproduction Commands
```bash
python -m pytest tests -q

bash scripts/run_pommerman_a00_artifact.sh

python scripts/audit_pommerman_formal_schedule.py \
  --models configs/models/openclaw_relay_6model_deepseek_glm.yaml

rm -rf logs/round_* \
       workspace/codebases/pommerman_gptv16_a00_6model_execution_smoke \
       workspace/submissions/pommerman_gptv16_a00_6model_execution_smoke \
       workspace/posts/pommerman_gptv16_a00_6model_execution_smoke

python -m runner.main \
  --regime configs/regimes/A00.yaml \
  --tournament configs/tournaments/pommerman_gptv16_a00_6model_execution_smoke.yaml \
  --models configs/models/openclaw_relay_6model_deepseek_glm.yaml

python scripts/audit_pommerman_6model_execution_smoke.py
```

## 5) Expected Success Signals
- `pytest` passes.
- `pairing_manifest_audit=PASS`.
- `formal_schedule_audit=PASS`.
- `execution_smoke_audit=PASS`.
- DeepSeek/GLM roster has 6 unique agents.
- No persistent `left/` or `right/` directories for 6-model execution smoke.

## 6) Output Artifacts
- `logs/pairing_manifest.json`
- `logs/pommerman_formal_schedule_manifest.json`
- `logs/round_1/round_manifest.json`
- `logs/round_1/match_1/`
- `logs/round_1/match_2/`
- `logs/round_1/match_3/`
- `workspace/codebases/<tournament>/<agent_id>/codebase_play_1/`
- `workspace/submissions/<tournament>/<agent_id>/submission_1/`
- `workspace/posts/<tournament>/<agent_id>/codebase_post_1/`

## 7) Known Warnings
- `seed requested but not applied` is acceptable for current executed smoke.
- Rationale: adapter records `requested_seed` but cannot prove environment-level seed application.
- This is a warning, not a failure.
