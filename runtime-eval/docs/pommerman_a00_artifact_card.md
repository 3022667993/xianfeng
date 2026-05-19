# Pommerman + A00 Artifact Card

## Scope
- Repository scope: `runtime-eval`.
- Experiment family: Pommerman + A00 only.
- Current formal schedule: single-leg `double_round_robin`.
- One scheduled match equals one arena game.
- The only current internal arena-result leg label is `match_a`.
- Within-match paired seat-swap artifacts are pruned from the current OpenClaw smoke path.

## Current Configs
- Current 3-round prefix smoke:
  - `configs/tournaments/pommerman_gptv16_a00_openclaw_initial_synthesis_3round_neutral_double_rr_smoke.yaml`
- Preferred full formal run:
  - `configs/tournaments/pommerman_gptv16_a00_openclaw_initial_synthesis_full_neutral_double_rr.yaml`
- Current model roster:
  - `configs/models/openclaw_relay_current.yaml`
- To replace the active roster, edit only entries in `configs/models/openclaw_relay_current.yaml`.
- Active auto configs support even `N`; odd `N` requires BYE scheduling, which is not implemented.

## Current Artifact Contract
- Per match:
  - `metadata.json`
  - `scorecard.json`
  - `arena_result_match_a.json`
  - `trajectory_summary.json`
  - `trajectory_compact_match_a.jsonl`
  - `trajectory_events.json`
  - `agent_feedback_<agent_id>.json`
  - `agent_feedback_<agent_id>.md`
  - `build.log`
  - `test.log`
  - `stderr.log`
- Per round:
  - `logs/round_<r>/round_manifest.json`
  - `logs/round_<r>/revision_manifest.json` for revision rounds
  - `logs/round_<r>/propagation_manifest.json` for propagated rounds
- Per run:
  - `logs/initial_synthesis_manifest.json`
  - `logs/round_1/initial_propagation_manifest.json`
  - `logs/tournament_report.json`
  - `logs/tournament_report.md`

## Current Non-Artifacts
- `arena_result_match_b.json` is not required by current formal semantics.
- `trajectory_compact_match_b.jsonl` is not required by current formal semantics.
- Paired aggregate scorecards are not generated in the current formal path.
- Full board/observation replay is still future work unless a later feedback package adds an official replay source such as `record_json_dir`.

## Feedback
- Feedback Package v4 is current.
- Feedback Package v4 uses factual match metadata, scorecards, official record JSON when available, compact trajectory actions, and public runtime logs.
- Compact trajectory v2 is lightweight process feedback, not full replay.
- Death causes, bomb ownership, and power-up pickup causes remain future work unless supported by compact fields or a later replay artifact.

## Audits
```bash
python -m pytest tests -q

python scripts/audit_pommerman_double_round_robin_schedule.py \
  --tournament pommerman_gptv16_a00_openclaw_initial_synthesis_3round_neutral_double_rr_smoke
python scripts/audit_pommerman_initial_synthesis.py
python scripts/audit_pommerman_initial_synthesis_3round_smoke.py \
  --tournament configs/tournaments/pommerman_gptv16_a00_openclaw_initial_synthesis_3round_neutral_double_rr_smoke.yaml
python scripts/audit_pommerman_feedback_package.py
python scripts/audit_pommerman_process_feedback.py
python scripts/audit_pommerman_compact_trajectory.py
python scripts/audit_pommerman_seed_control.py
python scripts/audit_pommerman_effective_revision.py
python scripts/write_pommerman_tournament_report.py \
  --tournament pommerman_gptv16_a00_openclaw_initial_synthesis_3round_neutral_double_rr_smoke
```

## Expected Success Signals
- `pommerman_double_round_robin_schedule_audit=PASS`
- `pommerman_initial_synthesis_audit=PASS`
- `pommerman_initial_synthesis_3round_smoke_audit=PASS`
- `pommerman_feedback_package_audit=PASS`
- `pommerman_process_feedback_audit=PASS`
- `pommerman_compact_trajectory_audit=PASS`
- `pommerman_seed_control_audit=PASS`
- `pommerman_effective_revision_audit=PASS`

## Generated Artifacts Policy
- `workspace/` is generated runtime state.
- `logs/round_*` are generated run artifacts.
- Generated artifacts should not be versioned.
- Check with:
  - `git ls-files workspace`
  - `git ls-files logs`
