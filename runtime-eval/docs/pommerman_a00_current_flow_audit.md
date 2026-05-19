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
- Future 10-round formal run:
  - `configs/tournaments/pommerman_gptv16_a00_openclaw_initial_synthesis_10round_neutral_double_rr.yaml`

## Current 6-Agent Roster
- `relay_bailian_deepseek_v4_flash` -> `relay/bailian/deepseek-v4-flash`
- `relay_gemini_2_5_flash_thinking` -> `relay/gemini-2.5-flash-thinking`
- `relay_deepseek_v3` -> `relay/deepseek-ai/DeepSeek-V3.2`
- `relay_qwen3_5_plus` -> `relay/qwen3.5-plus`
- `relay_glm_4_6` -> `glm-4.6`
- `relay_glm_4_7` -> `glm-4.7`

## Pipeline Flow
### Initial Synthesis
- Starter repo is copied per agent.
- OpenClaw-Minimal is invoked once per model before any match feedback.
- The model writes `submission/main.py` before round 1.
- Required invariants: route matched, actual provider/model present, fallback false, effective initial submission change true, and unique initial hashes not all identical.

### Match Phase
- Each round has 3 matches over 6 agents.
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
python scripts/validate_openclaw_model_routes.py --models configs/models/openclaw_relay_6model_deepseek_glm.yaml
python scripts/audit_openclaw_model_routes.py
python scripts/probe_openclaw_runtime_route.py --model relay/qwen3.5-plus
python scripts/probe_openclaw_runtime_route.py --model relay/gemini-2.5-flash-thinking
python scripts/probe_openclaw_runtime_route.py --model glm-4.7
```

```bash
python -m runner.main \
  --regime configs/regimes/A00.yaml \
  --tournament configs/tournaments/pommerman_gptv16_a00_openclaw_initial_synthesis_3round_neutral_double_rr_smoke.yaml \
  --models configs/models/openclaw_relay_6model_deepseek_glm.yaml
```

```bash
python -m runner.main \
  --regime configs/regimes/A00.yaml \
  --tournament configs/tournaments/pommerman_gptv16_a00_openclaw_initial_synthesis_10round_neutral_double_rr.yaml \
  --models configs/models/openclaw_relay_6model_deepseek_glm.yaml
```

## Final Verdict
- Current code and tests are aligned around single-leg `double_round_robin`.
- The 3-round config is a prefix smoke.
- The 10-round config is the future formal run target.
