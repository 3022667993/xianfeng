# Pommerman 1v1 Starter Repo

This directory is the starter codebase for a Pommerman 1v1 proxy agent in `runtime-eval`.

It is written for coding agents that will edit this repository across rounds. The main goal is to keep the submission small, robust, importable, deterministic enough to debug, and able to survive Pommerman-style bomb combat.

## 1. Purpose

This starter repo defines the minimal submission contract for the `pommerman_1v1` adapter.

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

## 2. What Pommerman Is

Pommerman is a Bomberman-like multi-agent grid game for AI and multi-agent learning research.

Agents move around a grid, place bombs, avoid explosions, destroy wooden walls, collect powerups, and try to survive while eliminating opponents.

The official Pommerman project includes several variants:

* **FFA**: Free-for-all. Four agents enter the board, and one wins.
* **Team**: Two teams of two agents.
* **Team Radio**: Team mode with a limited communication channel.

This starter repo is adapted for `runtime-eval`'s **Pommerman 1v1 fixed-background FFA proxy**.

## 3. Runtime-Eval Match Setup

In this project, the evaluated match is a 1v1 proxy inside a four-agent FFA board.

Each match contains:

```text
left_agent   = evaluated agent A
right_agent  = evaluated agent B
dummy2       = fixed background agent
dummy3       = fixed background agent
```

Important identity rules:

* `left` and `right` are only per-match seat assignments.
* Persistent identity is `agent_id`, not left/right.
* Across a tournament, the same agent may appear in different seats.
* Do not store strategy assumptions like "I am always left" or "I am always right".
* Treat dummy agents as hazards/noise, not as persistent evaluated opponents.

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
Do not create paired aggregate scorecards or additional per-match games inside this starter repo. Pair-level aggregation is a post-analysis task outside the submission.

## 4. Objective

Your agent should maximize its chance of surviving and beating the other evaluated agent.

Practical priorities:

1. Stay alive.
2. Avoid current and future blast paths.
3. Avoid trapping yourself with your own bomb.
4. Use bombs to pressure opponents or destroy wooden walls only when there is an escape route.
5. Collect powerups when safe.
6. Treat dummy agents as moving hazards.
7. Prefer robust safe movement over fragile aggression.

Survival is usually more important than early bombing. A dead agent cannot recover later in the match.

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

* Return an integer, not a string, tuple, list, or object.
* Invalid output may cause failure or a forced fallback action.
* Slow response may cause the environment to issue Stop.
* Stop is not automatically safe; stopping inside a blast path can be fatal.
* Bomb is only useful if you have ammo and an escape plan.

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

The board is a grid. Exact numeric item constants can vary by wrapper or import style, so prefer helper constants if the starter code provides them.

Common board contents:

### Passages / Empty Cells

Passages are usually walkable.

Use them for movement and escape routes.

### Rigid Walls

Rigid walls block movement.

They usually cannot be destroyed.

They also block bomb blast propagation.

### Wooden Walls

Wooden walls block movement.

They can be destroyed by bomb explosions.

Destroyed wooden walls may reveal passages or powerups.

### Bombs

Bombs occupy cells and threaten horizontal/vertical blast lines.

Bombs have timers and blast strengths.

A cell with a bomb is usually dangerous unless you can safely leave before it explodes.

### Flames / Explosions

Flames are dangerous.

Do not move into flames.

Do not stop on a cell that is currently flaming or likely to become flaming soon.

### Powerups

Powerups may appear after wooden walls are destroyed.

They can improve your agent, but they are not worth dying for.

## 9. Common Item Constants

Some Pommerman versions expose item enums similar to:

```text
Passage
Rigid
Wood
Bomb
Flames
Fog
ExtraBomb
IncrRange
Kick
Agent0
Agent1
Agent2
Agent3
```

Do not hard-code numeric constants unless the current starter code or adapter clearly uses them. If you must handle raw integers, isolate the mapping in one helper function and keep a safe fallback.

Better approach:

* infer walkable cells from known safe values
* treat unknown occupied-looking cells as blocked
* treat bombs/flames as dangerous
* use helper constants if available
* avoid crashing if constants differ

## 10. Movement and Collision

All agents choose actions each step.

Movement can fail if the target cell is blocked or unsafe.

Important practical rules:

* Walls block movement.
* Bombs can block movement unless kicking is possible.
* Flames are lethal/dangerous.
* Other agents can block movement.
* Two agents trying to move into the same cell may bounce back.
* If a move fails, the agent may remain in place.
* Remaining in place can be dangerous if a bomb is about to explode.

When choosing a movement action:

1. Compute candidate neighbor cells.
2. Filter out cells outside the board.
3. Filter out walls, bombs, and flames.
4. Prefer cells not in current or future blast paths.
5. Avoid dead ends when bombs are nearby.
6. Choose the safest legal action.
7. If no safe action exists, choose the least bad fallback.

## 11. Bomb Rules

Bombs are the central mechanic.

### Placing Bombs

The Bomb action places a bomb if ammo is available.

After placing a bomb:

* the bomb starts a timer
* your ammo is reduced until the bomb explodes
* you may need to escape quickly
* you can trap yourself if you bomb inside a corridor or dead end

Only place a bomb when:

* you have ammo
* you can escape the blast radius
* the bomb pressures an opponent or opens useful wooden walls
* you are not trapping yourself against a wall, bomb, enemy, or dummy agent

### Bomb Timers

`bomb_life` often indicates when bombs will explode.

Use it to estimate immediate danger.

Small bomb life values are urgent.

### Blast Strength

`bomb_blast_strength` or your own `blast_strength` indicates how far explosions travel.

Blasts usually travel in straight horizontal and vertical lines.

### Blast Blocking

Blast propagation can be blocked by:

* rigid walls
* wooden walls
* possibly bombs or agents depending on engine state

Wooden walls can be destroyed when hit by flames.

### Chain Reactions

If an explosion reaches another bomb, that bomb may explode early.

This can create chain reactions.

When computing danger, consider:

* current flames
* bombs about to explode
* bombs that may be triggered by other bombs
* corridors where chain reactions leave no escape

## 12. Powerups

Common powerups include:

### ExtraBomb

Increases ammo, allowing more bombs to be active.

Useful for pressure and wall clearing.

### IncrRange

Increases blast strength.

Useful for reaching opponents or walls, but also increases self-trap risk.

### Kick

Allows kicking bombs.

Useful for opening paths or sending bombs toward opponents.

Powerup rule of thumb:

```text
A powerup is only good if the path to collect it is safe.
```

Do not chase a powerup into a blast path, dead end, or area controlled by bombs.

## 13. Danger Evaluation

A strong baseline agent should estimate danger before moving.

A cell is dangerous if:

* it currently contains flames
* it is in the blast line of a bomb about to explode
* it is a dead end near an active bomb
* moving there blocks all escape routes
* an enemy or dummy agent can easily trap you there
* a chain reaction may make it unsafe soon

Useful helper concepts:

```text
safe_now        = not currently flame/bomb/blocked
safe_next       = not likely to be hit soon
escape_routes   = number of safe neighboring cells
blast_path      = same row/column as bomb with no wall blocking
dead_end        = cell with too few safe exits
```

Prefer moves with:

```text
safe_now = true
safe_next = true
escape_routes > 0
not in blast_path
```

## 14. Estimating Blast Paths

A simple blast-path estimate:

1. For every bomb cell, get its `bomb_life` and `bomb_blast_strength`.
2. If the bomb is close to exploding, mark its row/column rays as dangerous.
3. Stop each ray when it hits a rigid wall.
4. Include wooden wall cells as dangerous, but do not continue beyond them.
5. Treat nearby bombs as possible chain-reaction sources.
6. Mark current flames as dangerous.

This estimate does not need to be perfect. A conservative approximation is usually better than ignoring bombs.

## 15. Escape Routes

Before placing a bomb, estimate whether you can escape.

Do not bomb if:

* you are in a corridor with no exit
* all adjacent cells are blocked
* the only exit leads into another blast path
* a dummy or opponent can body-block your path
* you are already standing in danger

A simple rule:

```text
Only bomb when at least one safe neighboring cell or short path is available.
```

## 16. Basic Strategy

Good Pommerman agents tend to follow these priorities:

1. Do not die.
2. Escape imminent bomb blasts.
3. Avoid dead ends.
4. Keep distance from active bombs unless you know they are safe.
5. Collect powerups only when safe.
6. Bomb wooden walls when you can escape.
7. Bomb near opponents only when you can escape.
8. Avoid standing next to opponents if they can trap you.
9. Treat dummy agents as moving hazards.
10. Use Bomb sparingly; bad bombs often cause suicide.

Practical fallback order:

```text
1. Move to a safe adjacent cell.
2. Move to the least dangerous adjacent cell.
3. Stop only if staying is safer than moving.
4. Bomb only if there is ammo and a safe escape path.
```

## 17. FFA Proxy Tactics

This runtime-eval setup is not a pure two-agent duel. It is a two-evaluated-agent proxy inside a four-agent FFA board.

Implications:

* dummy2/dummy3 may block paths, place bombs, or create noise
* do not assume only the evaluated opponent can harm you
* the evaluated opponent is the main comparison target, but survival against the whole board matters
* avoid strategies that rely on dummy agents behaving cooperatively
* avoid overfitting to left/right seat identity
* robust survival is often better than fragile attack logic

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
* Preserve the expected public entry point used by the existing starter code.
* Do not change the interface expected by `scripts/run_submission.sh`.
* Return one integer action in `[0, 5]`.
* Return quickly.
* Do not require internet access.
* Do not perform heavy work at import time.
* Do not write outside this repository.
* Do not delete runner-generated artifacts.
* Do not create aggregate scorecards.
* Do not depend on hidden state outside the codebase.

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

* survive longer
* avoid invalid actions
* avoid suicide bombs
* escape blast paths
* improve safe movement
* exploit safe bomb opportunities
* collect safe powerups
* beat the evaluated opponent more often than it beats you

Raw scorecards and arena result files are written by the runner. This starter repo should not compute pair-level aggregate results.

## 23. Common Failure Modes

Avoid these mistakes:

* returning a non-integer action
* returning an action outside `[0, 5]`
* crashing on missing observation fields
* assuming fixed board constants without checking
* bombing in a dead end
* stopping inside a blast path
* chasing unsafe powerups
* ignoring chain reactions
* ignoring bomb kick interactions
* assuming dummy agents are harmless
* assuming you are always left or always right
* performing expensive computation every step
* doing network calls
* writing files outside the repo
* deleting runner artifacts
* changing the submission interface

## 24. Minimal Safe Baseline Advice

If you are unsure what to improve, start with these simple upgrades:

1. Add robust observation parsing.
2. Add board-bound checks.
3. Identify blocked cells.
4. Identify current flames.
5. Estimate bomb blast paths.
6. Prefer safe neighboring moves.
7. Avoid bombing unless there is a clear escape route.
8. Add a deterministic fallback action.

A boring agent that survives is often better than an aggressive agent that kills itself.

## 25. Official References

* [https://pommerman.readthedocs.io/en/latest/](https://pommerman.readthedocs.io/en/latest/)
* [https://pommerman.readthedocs.io/en/latest/README/](https://pommerman.readthedocs.io/en/latest/README/)
* [https://pommerman.readthedocs.io/en/latest/game_rules/](https://pommerman.readthedocs.io/en/latest/game_rules/)
* [https://github.com/MultiAgentLearning/playground](https://github.com/MultiAgentLearning/playground)



