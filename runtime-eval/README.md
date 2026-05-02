# runtime-eval

Current checkpoint (GitHub commit `159b4593`) is a **Pommerman + A00 smoke/artifact/reproducibility** slice.

## Scope
- Implemented: Pommerman + A00 only.
- Not implemented in this checkpoint: A01, A11, A10, Lux, Kore, Halite, Held-Out, or full formal 10-round execution.

## Validated Components
- A00 memory-minimal config.
- 2-leg Pommerman smoke artifact and `pairing_manifest.json`.
- Smoke seed provenance recording.
- Formal 6-model schedule dry-run manifest/audit.
- 6-model execution smoke (`1 round x 3 matches`).
- DeepSeek/GLM 6-model roster: `configs/models/openclaw_relay_6model_deepseek_glm.yaml`.
- Per-agent workspace layout for 6-model execution smoke.

## Reproduce
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

## Expected Signals
- `pytest` passes.
- `pairing_manifest_audit=PASS`.
- `formal_schedule_audit=PASS`.
- `execution_smoke_audit=PASS`.
- DeepSeek/GLM roster has 6 unique agents.
- No persistent `left/` or `right/` dirs for 6-model execution smoke workspaces.

See detailed protocol notes: `docs/pommerman_a00_artifact_card.md`.
