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
- Not implemented here:
  - A01, A11, A10
  - Lux, Kore, Halite, Held-Out
  - Full 10-round real OpenClaw adaptive tournament

## Current Route-Valid 6-Agent Roster
Config: `configs/models/openclaw_relay_6model_deepseek_glm.yaml`
- `relay_bailian_deepseek_v4_flash` -> `relay/bailian/deepseek-v4-flash`
- `relay_gemini_2_5_flash_thinking` -> `relay/gemini-2.5-flash-thinking`
- `relay_deepseek_v3` -> `relay/deepseek-ai/DeepSeek-V3.2`
- `relay_glm_4_7` -> `glm-4.7`
- `relay_glm_4_6` -> `glm-4.6`
- `relay_glm_4_6v` -> `relay/glm-4.6v`

## Reproduction Commands
```bash
python -m pytest tests -q

bash scripts/run_pommerman_a00_artifact.sh

python scripts/validate_openclaw_model_routes.py \
  --models configs/models/openclaw_relay_6model_deepseek_glm.yaml
python scripts/audit_openclaw_model_routes.py

python scripts/audit_pommerman_process_feedback.py

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

## Expected Success Signals
- `pytest` passes
- `pairing_manifest_audit=PASS`
- `formal_schedule_audit=PASS`
- `openclaw_model_route_audit=PASS`
- `pommerman_process_feedback_audit=PASS`
- `openclaw_revision_smoke_audit=PASS`
- `openclaw_revision_smoke_all_agents_audit=PASS`
- `openclaw_adaptive_2round_smoke_audit=PASS`
- `adaptive_dryrun_audit=PASS`

## Known Warning
- `requested_seed` with `seed_control_status=requested_but_not_applied` is acceptable for current smoke/adaptive layers.
- This is a warning, not a failure.

## Status Wording
- **process feedback v1 has run.**
- **2-round real OpenClaw adaptive smoke has run.**
- **10-round adaptive dry-run has run.**
- **compact trajectory v2 remains future work.**
- **full tick-level replay remains future work.**
- **Full 10-round real OpenClaw adaptive run remains future work.**

Detailed protocol notes: `docs/pommerman_a00_artifact_card.md`.
