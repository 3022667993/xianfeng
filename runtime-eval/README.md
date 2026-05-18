# runtime-eval

Checkpoint scope is **Pommerman + A00 only**.

## Checkpoint
- Latest verified code checkpoint includes commit: `bb050e14` (Add two-round OpenClaw adaptive smoke).

## Scope
- Implemented and validated in this checkpoint:
  - 2-leg Pommerman A00 smoke artifact
  - Formal schedule dry-run + audit
  - 6-model execution smoke (`1 round x 3 matches`)
  - 10-round adaptive dry-run (`10 rounds x 3 matches`)
  - Pommerman process feedback v1
  - OpenClaw model route validation
  - Real OpenClaw-Minimal revision smokes:
    - single-agent (`1 round`)
    - all-agent (`1 round`, all 6 agents)
  - 2-round real OpenClaw adaptive smoke (`2 rounds x 3 matches`)
  - 3-round real OpenClaw adaptive smoke with pre-round initial synthesis (`3 rounds x 3 matches`)
  - Pommerman seed control applied via `env.seed(...)`
  - Compact trajectory v2 has run
- Not implemented here:
  - A01, A11, A10
  - Lux, Kore, Halite, Held-Out
  - Full board/observation replay
  - Full 10-round real OpenClaw adaptive run

## Current Route-Valid 6-Agent Roster
Config: `configs/models/openclaw_relay_6model_deepseek_glm.yaml`
- `relay_bailian_deepseek_v4_flash` -> `relay/bailian/deepseek-v4-flash`
- `relay_gemini_2_5_flash_thinking` -> `relay/gemini-2.5-flash-thinking`
- `relay_deepseek_v3` -> `relay/deepseek-ai/DeepSeek-V3.2`
- `relay_qwen3_5_plus` -> `relay/qwen3.5-plus`
- `relay_glm_4_7` -> `glm-4.7`
- `relay_glm_4_6` -> `glm-4.6`

## Reproduction Commands
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
  --tournament configs/tournaments/pommerman_gptv16_a00_openclaw_initial_synthesis_3round_smoke.yaml \
  --models configs/models/openclaw_relay_6model_deepseek_glm.yaml
python scripts/audit_pommerman_initial_synthesis.py
python scripts/audit_pommerman_initial_synthesis_3round_smoke.py

# Neutral prompt variant (formal-style objective/constraints)
python -m runner.main \
  --regime configs/regimes/A00.yaml \
  --tournament configs/tournaments/pommerman_gptv16_a00_openclaw_initial_synthesis_3round_neutral_smoke.yaml \
  --models configs/models/openclaw_relay_6model_deepseek_glm.yaml

python -m runner.main \
  --regime configs/regimes/A00.yaml \
  --tournament configs/tournaments/pommerman_gptv16_a00_6model_adaptive_dryrun.yaml \
  --models configs/models/openclaw_relay_6model_deepseek_glm.yaml
python scripts/audit_pommerman_10round_adaptive_dryrun.py

# Optional inspection examples
find logs/round_1/match_1 -maxdepth 1 -type f | sort | grep -E "trajectory|agent_feedback"
sed -n '1,220p' logs/round_1/match_1/agent_feedback_<agent_id>.md
```

## Expected Success Signals
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
- `pommerman_initial_synthesis_audit=PASS`
- `pommerman_initial_synthesis_3round_smoke_audit=PASS`
- `adaptive_dryrun_audit=PASS`
- no `seed requested but not applied` warnings for current Pommerman adaptive smoke

## Seed Control Applied
- Seed control is applied via `env.seed(...)`.
- Audit command: `python scripts/audit_pommerman_seed_control.py`.
- Expected result: `pommerman_seed_control_audit=PASS`.
- Seed provenance fields are propagated into:
  - `metadata.json`
  - `scorecard.json`
  - `arena_result_match_a.json`
  - `arena_result_match_b.json`
  - `trajectory_summary.json`
  - `trajectory_events.json`
- Current status fields:
  - `seed_control_status=applied`
  - `applied_seed=requested_seed`
  - `seed=requested_seed`
  - `seed_control_method_applied=env.seed(...)`

## Feedback Inputs Per Round
- Models can read these generated artifacts for each match:
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
- compact trajectory v2 is lightweight per-step process feedback, not full replay.
- full board/observation replay remains future work.
- Death causes, bomb ownership, and power-up pickup causes remain future work unless explicitly supported by compact fields.

## Revision Autonomy
- Runner/config controls revision invocation via `revision_rounds`, `revision_subset_size`, and `require_all_agents_revised`.
- During OpenClaw revision, the model autonomously decides how to modify code.
- A model may make small changes or no meaningful code change.
- Route provenance is required for accepted synthesis/revision:
  - `provider_route_status=matched`
  - non-empty `actual_provider` and `actual_model`
  - `fallback_used=false`
- If route provenance is unknown, run is treated as unverified and retried from clean base when configured.

## Prompt Variants
- OpenClaw initial synthesis and revision prompts are required to define task, artifacts, and constraints.
- Prompt behavior is controlled by config keys:
  - `initial_synthesis_prompt_variant`
  - `revision_prompt_variant`
- Supported values:
  - `anti_draw_coached`: engineering smoke behavior with explicit anti-draw tactical coaching.
  - `neutral`: formal-style objective/constraints prompt (no detailed Pommerman tactical prescriptions).
- `configs/tournaments/pommerman_gptv16_a00_openclaw_initial_synthesis_3round_smoke.yaml` keeps `anti_draw_coached`.
- `configs/tournaments/pommerman_gptv16_a00_openclaw_initial_synthesis_3round_neutral_smoke.yaml` uses `neutral`.
- Full 10-round real OpenClaw run remains future work.

## Generated Artifacts Policy
- `workspace/` is generated runtime state.
- `logs/round_*` are generated run artifacts.
- Generated artifacts should not be versioned.
- Verify with:
  - `git ls-files workspace`
  - `git ls-files logs`

## Status Wording
- **process feedback v1 has run.**
- **2-round real OpenClaw adaptive smoke has run.**
- **10-round adaptive dry-run has run.**
- **compact trajectory v2 has run.**
- **full board/observation replay remains future work.**
- **Full 10-round real OpenClaw adaptive run remains future work.**

Detailed protocol notes: `docs/pommerman_a00_artifact_card.md`.
