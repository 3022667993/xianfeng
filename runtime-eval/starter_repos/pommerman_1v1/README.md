# Pommerman 1v1 Starter Repo

This directory is the starter codebase for a Pommerman 1v1 proxy agent in `runtime-eval`.

It is written for coding agents that will edit this repository across rounds. The main goal is to keep the submission small, robust, importable, deterministic enough to debug, and able to survive Pommerman-style bomb combat.

## 1. Purpose

This starter repo defines the minimal submission contract for the `pommerman_1v1` adapter.

`submission/main.py` is intentionally minimal. It provides the required `make_agent()` entry point, a `pommerman.agents.BaseAgent` subclass with `act(...)`, and a valid fallback action. It is not a strategy baseline. Coding agents are expected to replace it with their own behavior based on the game rules, action meanings, tournament objective, observation fields, and later feedback packages or replays.

How it is used in the runtime-eval pipeline:

1. The runner copies this directory into each model's per-agent workspace as `codebase_play_t`.
2. The runner exports `submission_t` from `submission/main.py`.
3. The Pommerman adapter runs the exported submission in a match.
4. In adaptive modes, OpenClaw-Minimal may revise `submission/main.py` between rounds.
5. The revised codebase becomes `codebase_post_t`, which can be propagated into the next round as `codebase_play_{t+1}`.

The primary file to edit is:

```text
submission/main.py
```

Keep this repo lightweight. Do not require network access, hidden memory, large downloads, external services, or expensive import-time setup.

This README is the benchmark-facing local rules and API guide for this Pommerman runtime-eval task. Coding agents should not rely on external websites, internet access, hidden files, private workspaces, or unofficial assumptions. If a detail is not specified here, write defensive code that preserves the required submission API and returns a valid action in `[0, 5]`.

## 2. What Pommerman Is

Pommerman is a Bomberman-like multi-agent grid game. Agents occupy cells on a board, choose one action per step, interact with walls, bombs, flames, items, and other agents, and may be marked dead when lethal mechanics reach their cell.

This starter repo documents only the current `runtime-eval` benchmark mode: `PommeFFACompetition-v0` used as a **Pommerman 1v1 fixed-background FFA proxy**. The README is the local source of rules and API details for coding agents in this benchmark.

## 3. Runtime-Eval Match Setup

In this project, the evaluated match is a 1v1 proxy inside a four-agent FFA board.

Each match contains:

```text
seat 0 = left_agent  = submitted evaluated agent A
seat 1 = right_agent = submitted evaluated agent B
seat 2 = dummy2      = suicidal filler background agent
seat 3 = dummy3      = suicidal filler background agent
```

The environment id is `PommeFFACompetition-v0`.

`dummy2` and `dummy3` are valid `pommerman.agents.BaseAgent` instances used only because the FFA environment expects four agents. They are not intended as competitive opponents. Their current filler behavior is deterministic: first `act(...)` returns `5` (`Bomb`), and later `act(...)` calls return `0` (`Stop`).

Important identity rules:

* `left` and `right` are only per-match seat assignments.
* Persistent identity is `agent_id`, not left/right.
* Across a tournament, the same agent may appear in different seats.
* Do not store strategy assumptions like "I am always left" or "I am always right".
* Background filler agents exist to satisfy the four-agent FFA environment.
* Background filler agents attempt to remove themselves early through legal actions.
* Background filler agents are not intended as competitive opponents.
* Submitted agents are evaluated as left vs right under the runner's pairwise result logic.
* The scheduled match is a single game named `match_a`.
* There is no paired `match_b` game inside the current benchmark mode.

The runner preserves raw match artifacts such as:

```text
metadata.json
scorecard.json
arena_result_match_a.json
trajectory_compact_match_a.jsonl
official_record_json_match_a/game_state.json
```

`arena_result_match_a.json` is the single-game arena result for the scheduled match.
`trajectory_compact_match_a.jsonl` is the single-game compact trajectory.
`official_record_json_match_a/game_state.json` may be generated when official Pommerman record JSON is enabled.
`actions.jsonl` rows in feedback packages use `step=t` for the action vector applied between official replay snapshots `game_state.state[t]` and `game_state.state[t+1]`, when full official replay is available.
The current probe stops a match after 800 environment steps if the environment has not already ended. Timeout/tie/draw interpretation is recorded by the runner scorecard fields.
Do not create paired aggregate scorecards or additional per-match games inside this starter repo. Pair-level aggregation is a post-analysis task outside the submission.

### Scorecard and Result Interpretation

`scorecard.json` is the runner's per-match result summary.

Common result fields:

* `left_right_winner` is the pairwise submitted-agent result from the runner perspective, usually `left`, `right`, or `draw`.
* `submitted_pair_outcome` is the model-visible pair outcome label, such as `left_win`, `right_win`, `timeout_draw`, dummy/background-agent loss cases, or arena fallback/invalid cases.
* `draw_type` explains why a pairwise draw occurred when the result is a draw.
* `environment_winners` contains raw environment winner ids when Pommerman reports winners.
* `environment_winner_labels` maps environment winners to labels such as `left`, `right`, `dummy2`, or `dummy3`.
* `reward` is the raw environment reward vector for seats `[left, right, dummy2, dummy3]`.
* `steps` is the number of environment steps executed.
* `arena_fallback_or_invalid` is true only when the arena failed or produced an invalid fallback result.

A `timeout_draw` means the match reached the configured step limit without a submitted pairwise winner. A timeout draw is a weak outcome when no submitted opponent was eliminated. A submitted agent can die early even if the final environment-level result is later reported as a draw. Early self-elimination is unfavorable evidence for later revisions. Dummy/background agents are environment fillers; dummy/background-agent wins are unfavorable for submitted agents.

Local engine boundary notes verified from the installed Pommerman package used by this benchmark:

* In FFA, the environment is done when the step count reaches `800` or when at most one agent remains alive.
* If exactly one agent remains alive, raw FFA rewards are `[+1, -1, -1, -1]` with `+1` at the surviving seat and `info["result"]` is `Win` with `info["winners"]`.
* At max-step timeout, raw FFA rewards are `[-1, -1, -1, -1]` and `info["result"]` is `Tie`.
* If zero agents remain alive at termination, `info["result"]` is `Tie`; raw rewards are not a submitted pairwise result by themselves.
* While the game is still running, raw FFA rewards are `0` for alive seats and `-1` for dead seats.
* Benchmark-facing interpretation comes from runner fields such as `left_right_winner`, `submitted_pair_outcome`, and `draw_type`, not from submission-side aggregation.

Do not compute pair-level aggregate results inside the submission. The runner/reporting layer handles result aggregation.

## 4. Objective

Your agent should improve tournament outcome against opponents under the runtime-eval scoring rules. Prefer robust wins over draws, and draws over losses. A timeout draw is a weak outcome when no submitted opponent is eliminated. Early self-elimination is unfavorable, even if the environment-level result is later reported as a draw. A dummy/background-agent win is unfavorable even when the two submitted agents are tied pairwise. A win caused mainly by the opponent's self-destruction is better than a draw or loss, but it is not strong evidence of a robust strategy by itself. Feedback packages from later rounds provide match evidence that can be used to revise strategy or behavior. If an agent is already winning, it can still improve robustness, consistency, and resilience. This README defines the rules, action meanings, objective, and submission API.

The starter implementation is intentionally weak. Initial synthesis should implement a complete behavior in `submission/main.py`; later revisions should use feedback packages, replay evidence, action logs, and scoreboard results to revise that behavior.

## 5. Action Space

Each step, the agent must return exactly one integer action in `[0, 5]`.

Standard Pommerman actions:

```text
0 = Stop
1 = Up
2 = Down
3 = Left
4 = Right
5 = Bomb
```

Rules and cautions:

* Return an integer-like scalar, not a string, tuple, list, or object.
* The returned integer must be in `[0, 5]`.
* Invalid or non-integer output can fail validation or produce unsafe runtime behavior.
* `action_space` may be `None`; do not require it for correctness.
* `act(...)` must return quickly.
* `0` means Stop; Stop still advances the environment one step.
* `5` means Bomb; Bomb placement has an effect only when the environment accepts it for the current agent state.

## 6. Observation Interface

`submission/main.py` receives a Pommerman-style observation dictionary.

Common fields may include:

```text
board
position
ammo
blast_strength
can_kick
bomb_life
bomb_blast_strength
enemies
teammate
step_count
```

Some wrappers may include additional fields. Not every field is guaranteed in every environment or adapter version. Write defensive code.

Recommended parsing style:

```python
board = obs.get("board")
position = obs.get("position")
ammo = int(obs.get("ammo", 0) or 0)
blast_strength = int(obs.get("blast_strength", 2) or 2)
can_kick = bool(obs.get("can_kick", False))
bomb_life = obs.get("bomb_life")
bomb_blast_strength = obs.get("bomb_blast_strength")
enemies = obs.get("enemies", [])
step_count = int(obs.get("step_count", 0) or 0)
```

Defensive rules:

* Use `dict.get(...)`.
* Handle missing fields.
* Handle `None`.
* Handle NumPy arrays, lists, or tuples.
* Avoid assuming exact board constants unless helpers define them.
* Never crash on malformed or partial observations; return a valid fallback action instead.

Observation API pitfalls:

* `obs["board"]`, `obs["bomb_life"]`, `obs["bomb_blast_strength"]`, and similar fields may be NumPy arrays.
* Do not use NumPy arrays directly as booleans. Avoid `if board:`, `if not board:`, `if board[0]:`, and `if obs["bomb_life"] == 0:`.
* Use explicit checks such as `board is None`, `len(board)`, `board.shape`, or `.any()` / `.all()` when intentionally reducing boolean arrays.
* `obs` may not contain `"agent_id"`. If you need your own id, use `self.agent_id` from `pommerman.agents.BaseAgent` when available.
* If observation parsing fails, return a valid fallback action such as `0`.

## 7. Coordinate Convention

Pommerman observations commonly use grid coordinates as:

```text
(row, column)
```

Movement directions usually mean:

```text
Up    = row - 1
Down  = row + 1
Left  = column - 1
Right = column + 1
```

Always check board bounds before reading a cell.

Safe coordinate handling pattern:

```python
def in_bounds(board, r, c):
    return board is not None and 0 <= r < len(board) and 0 <= c < len(board[0])
```

If board shape is unknown or malformed, return a conservative valid action.

## 8. Board Concepts

The board is a grid. Exact numeric item constants can vary by wrapper or import style, so prefer named constants from the installed package when available and keep a fallback path when constants are unavailable.

Common board contents:

* Passages / empty cells: cells that are normally walkable.
* Rigid walls: blocking cells that normally cannot be destroyed and block blast propagation.
* Wooden walls: blocking cells that can be destroyed by explosions; destroyed wood may reveal another cell type or item.
* Bombs: occupied cells with a remaining life/timer and blast strength.
* Flames / explosions: lethal cells produced by bomb explosions.
* Fog: unknown or not-visible cells in modes that expose fog.
* Powerup cells: item cells such as extra ammo, increased blast range, or kick ability when present.
* Agent cells: cells occupied by one of the four agents.

## 9. Common Item Constants

Some Pommerman versions expose item enums similar to:

```text
Passage   = 0
Rigid     = 1
Wood      = 2
Bomb      = 3
Flames    = 4
Fog       = 5
ExtraBomb = 6
IncrRange = 7
Kick      = 8
Agent0    = 10
Agent1    = 11
Agent2    = 12
Agent3    = 13
```

Do not hard-code numeric constants unless the current starter code or adapter clearly uses them. If you must handle raw integers, isolate the mapping in one helper function and keep a safe fallback.

Defensive implementation notes:

* infer known cell categories from constants or observed values
* treat unknown or malformed values conservatively
* use helper constants if available
* avoid crashing if constants differ

Local engine boundary notes verified from the installed Pommerman package used by this benchmark:

* Current item values are the constants shown above.
* Hidden items are placed under wooden walls at reset.
* Hidden item types are `ExtraBomb`, `IncrRange`, and `Kick`.
* When a flame on a destroyed wooden wall expires, the board cell becomes the hidden item value if one was present, otherwise it becomes `Passage`.
* Revealed items are visible in later `board` observations when they are in the agent's observation view.

## 10. Movement and Collision

All agents choose actions each step. Movement actions request a move to an adjacent cell, but the environment may keep the agent in place when movement is blocked or otherwise invalid.

Current-mode mechanics to account for:

* Walls block movement.
* Bombs can block movement unless the current environment state allows kicking.
* Flames are lethal.
* Other agents can block movement.
* Simultaneous movement conflicts can leave agents in their prior cells.
* If a move fails, the agent may remain in place for that step.
* Board bounds must be checked before reading or targeting a cell.

### Local Engine Boundary Notes

Verified from the installed Pommerman package used by this benchmark:

* A move into a rigid wall, wooden wall, or off-board location is not accepted; the agent remains in its current cell for that step.
* Other agents can block movement. If multiple agents try to occupy the same target cell, the engine resolves the collision by reverting involved agents to prior cells.
* If two agents try to swap cells across the same border in one transition, the engine treats this as a crossing collision and reverts both to prior cells.
* Collision resolution is simultaneous and iterative; a failed movement can cause later dependent movements to fail in the same step.
* `can_kick` is a boolean observation field and agent attribute. When `can_kick` is false, moving into a bomb does not move the agent into the bomb cell.
* When `can_kick` is true, moving into a bomb attempts to push that bomb one cell in the same direction.
* A kicked bomb receives a moving direction and continues moving on later steps while not blocked.
* Kicked bomb movement can be blocked by board bounds, walls, powerup cells, agents, other bombs, or collision resolution.

## 11. Bomb Rules

Bombs are a central environment mechanic.

### Placing Bombs

The Bomb action requests bomb placement. The environment accepts placement only when the current state permits it, commonly when the agent has available ammo and the cell can hold a bomb.

After placing a bomb:

* the bomb starts a timer
* the agent's available ammo is reduced while that bomb is active
* ammo is normally restored after that bomb is processed as exploded by the environment
* the bomb's future explosion can affect cells in its row and column according to blast strength and blockers

Local engine boundary notes verified from the installed Pommerman package used by this benchmark:

* Agents start with `ammo = 1`, `blast_strength = 2`, and `can_kick = False`.
* When an agent successfully places a bomb, ammo decreases immediately.
* The source restores ammo to the bomb's owner when that bomb is processed as exploded. A local probe observed ammo restoration even when the bomb owner died in the explosion.
* Ammo is capped at `10` by the installed engine.

### Bomb Timers

`bomb_life` often indicates when bombs will explode.

Smaller values are closer to explosion in typical Pommerman observations.

Local timer semantics verified from the installed Pommerman package used by this benchmark:

* `DEFAULT_BOMB_LIFE` is `9`.
* Internally, a newly placed bomb is created with life `DEFAULT_BOMB_LIFE + 1`, then ticked during that same environment transition.
* In the next observation after placement, the visible `bomb_life` value is typically `9.0`.
* Visible `bomb_life` values decrease by `1.0` per environment step: `9.0, 8.0, ..., 1.0`.
* The bomb explodes on the transition after visible `bomb_life` was `1.0`.
* `bomb_life` is a NumPy array of float values in observations.
* Cells with no visible bomb use `0.0` in `bomb_life`.

### Blast Strength

`bomb_blast_strength` or your own `blast_strength` indicates how far explosions travel.

Blasts usually travel in straight row and column rays from the bomb cell.

### Blast Blocking

Blast propagation can be blocked by:

* rigid walls
* wooden walls
* other cells depending on engine state

Wooden walls can be destroyed when hit by flames. Flames are lethal to agents occupying affected cells.

### Flames

Local flame semantics verified from the installed Pommerman package used by this benchmark:

* Flames appear on the board with item value `4`.
* Observations include a `flame_life` NumPy array.
* Newly created flames have internal life `2`; because removal is checked before ticking, observed `flame_life` values appear as `3.0`, then `2.0`, then `1.0`, then disappear.
* A local probe observed flame board cells for three observations after the explosion transition.
* Flames are lethal to agents occupying affected cells during the transition.

### Chain Reactions

If an explosion reaches another bomb, that bomb may explode early. This can create chain reactions.

Local chain-reaction semantics verified from the installed Pommerman package used by this benchmark:

* During explosion processing, bombs whose position is reached by the current explosion map have their life set to `0`.
* The engine continues processing newly exploded bombs in the same environment step until no new explosions remain.
* Exact ordering inside one transition is an engine detail; submissions should treat bombs in affected blast rays as capable of exploding earlier than their visible timer alone suggests.

## 12. Powerups

Common powerups include:

### ExtraBomb

Increases ammo, allowing more bombs to be active.

### IncrRange

Increases blast strength.

### Kick

Allows kicking bombs when the environment state supports it.

Powerup availability depends on board state. The submission should tolerate observations where no powerups are present.

## 13. Danger Evaluation

A cell can be lethal or hazardous if:

* it currently contains flames
* it is in a row/column ray of a bomb that can explode before the agent leaves
* a chain reaction can make it affected by flames
* it is occupied by blocking objects or agents in a way that prevents movement away before lethal mechanics occur

Useful helper concepts:

```text
safe_now        = not currently flame/bomb/blocked
safe_next       = not likely to be hit soon
escape_routes   = number of safe neighboring cells
blast_path      = same row/column as bomb with no wall blocking
dead_end        = cell with too few safe exits
```

## 14. Estimating Blast Paths

A local blast-path estimate can be computed from observation fields:

1. For every bomb cell, get its `bomb_life` and `bomb_blast_strength`.
2. Use the bomb's row/column rays up to its blast strength.
3. Stop each ray when it hits a rigid wall.
4. Include wooden wall cells as affected, but do not continue beyond them.
5. Treat nearby bombs as possible chain-reaction sources.
6. Mark current flames as lethal.

This estimate does not need to be perfect. It should not crash when bomb arrays are missing, malformed, or represented as NumPy arrays.

## 15. Escape Routes

An escape route is a sequence of legal future positions that can leave a lethal or soon-lethal cell before lethal mechanics apply.

Observation-derived route checks may consider:

* board bounds
* blocking walls
* active bombs
* current flames
* nearby agents
* bomb life/timer values
* blast strength and blockers

If route computation fails because observations are missing or malformed, preserve API validity and return a valid action.

## 16. Strategy Implementation

Implement your own behavior in `submission/main.py`. Use this README for the rules, actions, objective, observation fields, and submission contract. In later rounds, use feedback packages, replay evidence, action logs, run logs, and scoreboard results as evidence for revisions.

The starter code intentionally does not include pathfinding, danger maps, action heuristics, or matchup-specific logic. A valid submission may use any legal action in `[0, 5]`, but it should return quickly, handle missing observation fields, and keep the public API unchanged.

## 17. FFA Proxy Context

This runtime-eval setup is not a pure two-agent duel. It is a two-evaluated-agent proxy inside a four-agent FFA board.

Implications:

* dummy2/dummy3 are suicidal filler background agents that exist to satisfy the four-agent FFA environment
* dummy2/dummy3 attempt to remove themselves early through legal actions
* do not assume only the evaluated opponent matters
* the evaluated opponent is the main comparison target
* dummy agents are not intended as competitive opponents
* submitted agents are still evaluated as left vs right under the runner's pairwise result logic
* avoid overfitting to left/right seat identity

## 18. Submission Contract

Required files:

```text
submission/main.py
scripts/build.sh
scripts/run_submission.sh
tests/smoke.sh
```

The adapter validates this contract before arena integration.

Contract requirements:

* Keep `submission/main.py` importable.
* Define `make_agent()`.
* `make_agent()` must return an instance of a class that subclasses `pommerman.agents.BaseAgent`.
* The class must implement `act(self, obs, action_space=None)` or a compatible signature.
* Do not change the interface expected by `scripts/run_submission.sh`.
* Return one integer action in `[0, 5]`.
* Return quickly.
* Do not require internet access.
* Do not perform heavy work at import time.
* Do not write outside this repository.
* Do not delete runner-generated artifacts.
* Do not create aggregate scorecards.
* Do not depend on hidden state outside the codebase.

Recommended minimal pattern:

```python
from pommerman import agents


class Agent(agents.BaseAgent):
    def act(self, obs, action_space=None):
        return 0


def make_agent():
    return Agent()
```

## 19. Repository Layout

Primary file:

```text
submission/main.py
```

Main agent logic. This is the primary file to edit.

Support files:

```text
scripts/build.sh
```

Lightweight build/contract check.

```text
scripts/run_submission.sh
```

Local smoke execution of the submission contract.

```text
tests/smoke.sh
```

Minimal test.

Optional/supporting files, if present:

```text
scripts/run_arena.sh
```

Local/proxy arena entry point.

```text
scripts/pommerman_ffa_probe.py
```

Pommerman FFA proxy probe.

```text
notes/revision_log.md
```

Runner/OpenClaw revision notes.

Do not treat `notes/revision_log.md` as hidden memory. It is a normal file artifact and may be overwritten or appended by the runner.

## 20. Local Checks

Before handing off changes, run:

```bash
bash scripts/build.sh
bash scripts/run_submission.sh
bash tests/smoke.sh
```

If available:

```bash
bash scripts/run_arena.sh
```

A good change should:

* keep the submission importable
* return valid actions
* avoid crashes
* pass smoke tests
* keep behavior deterministic enough to debug

## 21. Runtime-Eval / OpenClaw-Minimal Notes

In OpenClaw-Minimal workflows:

* Edit only `submission/main.py` unless explicitly instructed otherwise.
* Do not depend on internet, browser tools, hidden memory, or external services.
* Keep changes small and testable.
* Use runner feedback and scorecards when present.
* Do not delete runner-generated artifacts.
* Do not create paired aggregate scorecards.
* Do not assume left/right seat identity persists across matches.
* Do not broaden the submission interface.
* Do not add heavyweight dependencies.

OpenClaw may revise this code after a match. The next round may run the revised codebase.

## 22. What To Optimize

The tournament runner, not this starter repo, defines final scoring.

Still, useful local objectives are:

* return valid actions
* avoid crashes on valid observations
* improve future tournament outcomes against opponents
* prefer robust wins over draws
* prefer draws over losses
* treat timeout draws as weak outcomes when no submitted opponent is eliminated
* treat early self-elimination as unfavorable, even if the environment-level result is later reported as a draw
* treat dummy/background-agent wins as unfavorable
* treat wins caused mainly by opponent self-destruction as better than draws or losses, but not strong evidence of robust strategy by themselves
* favor future decisive outcomes while preserving valid actions and avoiding obvious self-destruction
* improve robustness, consistency, or resilience when previous results are already favorable

Raw scorecards and arena result files are written by the runner. This starter repo should not compute pair-level aggregate results.

## 23. Common Failure Modes

Avoid these mistakes:

* returning a non-integer action
* returning an action outside `[0, 5]`
* crashing on missing observation fields
* assuming fixed board constants without checking
* implementing no behavior beyond the fallback action
* ignoring hazardous observations
* assuming one fixed board encoding without defensive checks
* assuming dummy agents are harmless
* assuming you are always left or always right
* performing expensive computation every step
* doing network calls
* writing files outside the repo
* deleting runner artifacts
* changing the submission interface

## 24. Minimal Starter Code

The provided starter code is only a valid skeleton:

* `make_agent()` returns a `pommerman.agents.BaseAgent` instance
* the agent object has `act(obs, action_space=None)`
* `act(...)` returns one integer action in `[0, 5]`

It is acceptable for this fallback to be weak. The benchmark expects coding agents to implement their own strategy or behavior from the documented rules, objective, observations, and feedback evidence.

## 25. Local Source Of Truth

This README is the benchmark-facing rules and API guide for this Pommerman runtime-eval task. Coding agents should not rely on external websites, internet access, hidden files, private workspaces, or official documentation outside this repository.

If a detail is not specified here, write defensive code that preserves the required submission API, handles missing or malformed observations, returns quickly, and returns a valid integer action in `[0, 5]`.
