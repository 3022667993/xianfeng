# Pommerman A00 Current Flow Audit

## Current State
- Pommerman + A00 is the active scope.
- Current formal semantics are single-leg `double_round_robin`.
- One scheduled match equals one arena game.
- `match_a` is the internal single-game label.
- `match_b` is no longer a current formal artifact.
- Legacy paired/adaptive/revision OpenClaw smoke files have been pruned from the current mainline.
- Current 3-round prefix smoke:
  - `configs/tournaments/pommerman_gptv16_a00_openclaw_initial_synthesis_3round_neutral_double_rr_smoke.yaml`
- Preferred full formal run:
  - `configs/tournaments/pommerman_gptv16_a00_openclaw_initial_synthesis_full_neutral_double_rr.yaml`

## Current Active Roster
- Active model config: `configs/models/openclaw_relay_current.yaml`
- To replace the roster, edit only `id`/`agent_id`, `provider_model`, and optional `stratum` entries in that file.
- Keep `agent_id` values unique and validate provider model strings before running smoke.
- Even `N` is supported by auto tournament fields; odd `N` is unsupported until BYE scheduling exists.

## Pipeline Flow
### Initial Synthesis
- Starter repo is copied per agent.
- OpenClaw-Minimal is invoked once per model before any match feedback.
- The model writes `submission/main.py` before round 1.
- Required invariants: route matched, actual provider/model present, fallback false, effective initial submission change true, and unique initial hashes not all identical.

### Match Phase
- Each round has `N / 2` matches over even `N` agents.
- Round manifests use `schedule_mode=double_round_robin` and `match_legs=single`.
- Match artifacts include `metadata.json`, `scorecard.json`, `arena_result_match_a.json`, trajectory summaries/events, compact trajectory for `match_a`, and per-agent feedback files.

### Feedback Phase
- Feedback Package v4 is current.
- Process feedback v2 and compact trajectory v2 are current factual summary layers.
- Full board/observation replay remains future work.

### Revision Phase
- Revision rounds are configured by `revision_rounds`.
- OpenClaw-Minimal receives feedback artifacts and must modify submitted code when effective change is required.
- Metadata-only edits do not count as submitted-code changes.
- Route provenance must be matched and fallback must be false.

### Propagation Phase
- `codebase_post_<r>` propagates to `codebase_play_<r+1>`.
- Propagation hash equality is required.

## Current Audits
- `scripts/audit_openclaw_model_routes.py`
- `scripts/probe_openclaw_runtime_route.py`
- `scripts/audit_pommerman_double_round_robin_schedule.py`
- `scripts/audit_pommerman_initial_synthesis.py`
- `scripts/audit_pommerman_initial_synthesis_3round_smoke.py`
- `scripts/audit_pommerman_feedback_package.py`
- `scripts/audit_pommerman_process_feedback.py`
- `scripts/audit_pommerman_compact_trajectory.py`
- `scripts/audit_pommerman_seed_control.py`
- `scripts/audit_pommerman_effective_revision.py`
- `scripts/analyze_pommerman_revision_effectiveness.py`
- `scripts/write_pommerman_tournament_report.py`

## Clean Reproduction Commands
```bash
python -m pytest tests -q
python scripts/validate_openclaw_model_routes.py --models configs/models/openclaw_relay_current.yaml
python scripts/audit_openclaw_model_routes.py
python scripts/probe_openclaw_runtime_route.py --model <provider/model>
```

```bash
python -m runner.main \
  --regime configs/regimes/A00.yaml \
  --tournament configs/tournaments/pommerman_gptv16_a00_openclaw_initial_synthesis_3round_neutral_double_rr_smoke.yaml \
  --models configs/models/openclaw_relay_current.yaml
```

```bash
python -m runner.main \
  --regime configs/regimes/A00.yaml \
  --tournament configs/tournaments/pommerman_gptv16_a00_openclaw_initial_synthesis_full_neutral_double_rr.yaml \
  --models configs/models/openclaw_relay_current.yaml
```

## Final Verdict
- Current code and tests are aligned around single-leg `double_round_robin`.
- The 3-round config is a prefix smoke.
- The full config resolves formal run length dynamically for even-N rosters.
