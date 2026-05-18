# Pommerman A00 Current Flow Audit

## 1. Current Scope
- Pommerman + A00 only.
- Current 6-agent roster:
  - `relay_bailian_deepseek_v4_flash` -> `relay/bailian/deepseek-v4-flash`
  - `relay_gemini_2_5_flash_thinking` -> `relay/gemini-2.5-flash-thinking`
  - `relay_deepseek_v3` -> `relay/deepseek-ai/DeepSeek-V3.2`
  - `relay_qwen3_5_plus` -> `relay/qwen3.5-plus`
  - `relay_glm_4_6` -> `glm-4.6`
  - `relay_glm_4_7` -> `glm-4.7`
- Qwen is intentional and uses the runtime-valid route `relay/qwen3.5-plus`.
- Full 10-round real run has not been executed.
- Full board/observation replay remains future work.

## 2. Prompt Variants
- `anti_draw_coached`: engineering smoke prompt with explicit anti-draw tactical guidance.
- `neutral`: formal-style prompt closer to CodeClash; objective/constraints only.
- Revision still has a prompt because the model needs task, feedback sources, and constraints.
- The key distinction is whether the prompt injects tactical advice.

## 3. Full Pipeline Flow

### A. Initial Synthesis
- Starter repo is copied per agent.
- OpenClaw-Minimal is invoked once per model before any match feedback.
- The model writes `submission/main.py` before round 1.
- Outputs:
  - `logs/initial_synthesis_manifest.json`
  - `logs/round_1/initial_propagation_manifest.json`
  - `workspace/posts/<tournament>/<agent>/codebase_initial_post_0`
  - `workspace/codebases/<tournament>/<agent>/codebase_play_1`
- Required invariants:
  - route matched
  - actual provider/model non-empty
  - fallback false
  - effective initial submission change true
  - unique initial hashes >= 2; all-identical fails

### B. Round 1 Match Phase
- Round 1 uses model-specific `codebase_play_1`, not the raw starter repo.
- 3 matches, 6 agents, perfect matching.
- Per-match artifacts:
  - `metadata.json`
  - `scorecard.json`
  - `arena_result_match_a.json`
  - `arena_result_match_b.json`
  - `trajectory_summary.json`
  - `trajectory_events.json`
  - `trajectory_compact_match_a.jsonl`
  - `trajectory_compact_match_b.jsonl`
  - `agent_feedback_<agent_id>.json`
  - `agent_feedback_<agent_id>.md`
  - `build.log`
  - `test.log`
  - `stderr.log`

### C. Feedback Phase
- Process feedback v1.
- Compact trajectory v2.
- Seed provenance is recorded.
- Anti-draw diagnostics:
  - `bomb_action_rate`
  - `stop_action_rate`
  - `average_terminal_step`
  - `non_draw_match_count`

### D. Revision Phase After Round 1 and Round 2
- OpenClaw-Minimal is invoked for every agent.
- The model reads feedback artifacts.
- The model must effectively change `submission/main.py` when required.
- Metadata-only changes do not count.
- Route provenance must be matched.
- No fallback is accepted.
- Timeout, route-unknown, and no-op are classified and retried if configured.

### E. Propagation Phase
- `codebase_post_1 -> codebase_play_2`
- `codebase_post_2 -> codebase_play_3`
- Propagation hash equality is required.

### F. Round 2 and Round 3
- Use propagated code.
- Repeat match and feedback artifacts.

## 4. Audit Scripts
- `scripts/audit_openclaw_model_routes.py`
  - Inputs: model roster config, route validation outputs.
  - Outputs: route audit status.
  - Meaning: confirms configured routes are accepted by static model-route checks.
  - Does not prove runtime invocation success.
- `scripts/probe_openclaw_runtime_route.py`
  - Inputs: provider_model string.
  - Outputs: runtime route probe JSON in `logs/openclaw_runtime_route_probe.json`.
  - Meaning: verifies actual runtime routing and provider/model provenance.
  - Does not prove full tournament success.
- `scripts/audit_pommerman_initial_synthesis.py`
  - Inputs: `logs/initial_synthesis_manifest.json`.
  - Outputs: PASS/FAIL.
  - Meaning: checks initial synthesis provenance, hashes, and uniqueness.
  - Does not prove round outcomes.
- `scripts/audit_pommerman_initial_synthesis_3round_smoke.py`
  - Inputs: initial synthesis + 3-round manifests.
  - Outputs: PASS/FAIL.
  - Meaning: checks full smoke flow shape, propagation, and round coverage.
  - Does not prove strategy quality.
- `scripts/audit_pommerman_openclaw_adaptive_3round_smoke.py`
  - Inputs: round manifests and propagation manifests.
  - Outputs: PASS/FAIL.
  - Meaning: checks adaptive-round integrity and required revision properties.
  - Does not prove that revisions improved win rate.
- `scripts/audit_pommerman_process_feedback.py`
  - Inputs: match feedback artifacts.
  - Outputs: PASS/FAIL.
  - Meaning: verifies process-feedback artifacts exist and are well formed.
  - Does not prove match quality.
- `scripts/audit_pommerman_compact_trajectory.py`
  - Inputs: compact trajectory artifacts.
  - Outputs: PASS/FAIL.
  - Meaning: verifies compact trajectory generation and schema.
  - Does not prove game performance.
- `scripts/audit_pommerman_seed_control.py`
  - Inputs: match seed provenance.
  - Outputs: PASS/FAIL.
  - Meaning: checks seed application and provenance.
  - Does not prove model behavior.
- `scripts/audit_pommerman_effective_revision.py`
  - Inputs: revision manifests and propagation manifests.
  - Outputs: PASS/FAIL.
  - Meaning: checks hash-based effective revisions and propagation integrity.
  - Does not prove match results.
- `scripts/analyze_pommerman_revision_effectiveness.py`
  - Inputs: current logs/manifests.
  - Outputs: diagnostic table.
  - Meaning: summarizes hashes, route provenance, tie rates, and action diagnostics.
  - Does not enforce correctness.

## 5. Known Issues Fixed
- Seed requested but not applied -> fixed via `env.seed(...)`.
- Starter-repo import in copied probe -> fixed.
- Metadata-only diff falsely marked `submission/main.py` changed -> fixed with hash-based effective revision.
- `__pycache__` / notes blocking copy-back -> fixed with ignored generated/bookkeeping policy.
- `qwen/qwen3.5-plus` static-known but runtime unknown -> fixed by `relay/qwen3.5-plus`.
- All initial submissions identical -> fixed with per-agent strategy profiles.
- Stale AGGRESSION bootstrap task conflicting with neutral prompt -> removed.
- OpenClaw subprocess timeout handling -> added.

## 6. Checkpoint Status and Remaining Risks
- `anti_draw_coached` initial-synthesis 3-round smoke checkpoint has passed with:
  - initial synthesis audit PASS
  - initial_synthesis_3round_smoke audit PASS
  - process feedback PASS
  - compact trajectory PASS
  - seed control PASS
  - effective revision PASS
  - `unique_initial_submission_hashes=6`
- `neutral` initial-synthesis 3-round smoke remains pending/incomplete due to `relay_glm_4_7` timeout in round_1 revision.
- Timeout retries are configured and tested in unit tests.
- Generated artifacts are not tracked by git in `workspace/` or `logs/`.
- README/docs reflect the prompt variants and current roster.
- Full 10-round real run remains future work.
- Round 1 match outcomes are still all draws (`draw_rate=1.0`, `non_draw_match_count=0`), which looks like strategy quality rather than a runtime plumbing failure.

## 7. Clean Reproduction Commands
```bash
python -m pytest tests -q
python scripts/validate_openclaw_model_routes.py --models configs/models/openclaw_relay_6model_deepseek_glm.yaml
python scripts/audit_openclaw_model_routes.py
python scripts/probe_openclaw_runtime_route.py --model relay/qwen3.5-plus
python scripts/probe_openclaw_runtime_route.py --model relay/gemini-2.5-flash-thinking
python scripts/probe_openclaw_runtime_route.py --model glm-4.7
```

```bash
rm -rf logs/round_* logs/initial_synthesis_manifest.json \
       workspace/codebases/pommerman_gptv16_a00_openclaw_initial_synthesis_3round_neutral_smoke \
       workspace/submissions/pommerman_gptv16_a00_openclaw_initial_synthesis_3round_neutral_smoke \
       workspace/posts/pommerman_gptv16_a00_openclaw_initial_synthesis_3round_neutral_smoke \
       openclaw_workspaces/minimal/runtime_eval_runs
```

```bash
python -m runner.main \
  --regime configs/regimes/A00.yaml \
  --tournament configs/tournaments/pommerman_gptv16_a00_openclaw_initial_synthesis_3round_smoke.yaml \
  --models configs/models/openclaw_relay_6model_deepseek_glm.yaml

python -m runner.main \
  --regime configs/regimes/A00.yaml \
  --tournament configs/tournaments/pommerman_gptv16_a00_openclaw_initial_synthesis_3round_neutral_smoke.yaml \
  --models configs/models/openclaw_relay_6model_deepseek_glm.yaml
```

```bash
git ls-files workspace
git ls-files logs
git status --short
```

## 8. Final Verdict
BLOCKED_BY_TIMEOUT
