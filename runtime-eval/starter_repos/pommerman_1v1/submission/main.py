from __future__ import annotations

from typing import Any

try:
    from pommerman import agents as pommerman_agents
except Exception:  # pragma: no cover - fallback for local script smoke
    class _FallbackBaseAgent:
        def act(self, obs, action_space=None):
            return 0

    class _FallbackAgentsModule:
        BaseAgent = _FallbackBaseAgent

    pommerman_agents = _FallbackAgentsModule()


# Action ids expected by Pommerman.
STOP, UP, DOWN, LEFT, RIGHT, BOMB = 0, 1, 2, 3, 4, 5
MOVE_DELTAS = {
    STOP: (0, 0),
    UP: (-1, 0),
    DOWN: (1, 0),
    LEFT: (0, -1),
    RIGHT: (0, 1),
}

# Editable smoke marker retained for runtime-eval revision compatibility.
AGGRESSION = 0

# Common board encodings (defensive defaults).
PASSAGE, RIGID, WOOD, ITEM_BOMB, FLAMES = 0, 1, 2, 3, 4
POWERUPS = {6, 7, 8}


class ConservativeAgent(pommerman_agents.BaseAgent):
    """Small deterministic baseline focused on safety over aggression."""

    def act(self, obs: Any, action_space: Any = None) -> int:
        try:
            obs = obs if isinstance(obs, dict) else {}
            board = obs.get("board")
            rows, cols = self._board_dims(board)
            if rows <= 0 or cols <= 0:
                return STOP

            pos = obs.get("position", (0, 0))
            if not isinstance(pos, (tuple, list)) or len(pos) != 2:
                return STOP
            r, c = int(pos[0]), int(pos[1])
            if not (0 <= r < rows and 0 <= c < cols):
                return STOP

            ammo = int(obs.get("ammo", 0) or 0)
            blast_strength = int(obs.get("blast_strength", 2) or 2)
            bomb_life = obs.get("bomb_life")
            bomb_blast = obs.get("bomb_blast_strength")
            enemies = obs.get("enemies", []) or []

            threatened = self._threatened_cells(board, bomb_life, bomb_blast)
            current_danger = (r, c) in threatened or self._tile(board, r, c) in {ITEM_BOMB, FLAMES}

            legal = []
            for a in (UP, DOWN, LEFT, RIGHT):
                nr, nc = r + MOVE_DELTAS[a][0], c + MOVE_DELTAS[a][1]
                if self._walkable(board, nr, nc) and (nr, nc) not in threatened:
                    legal.append(a)

            # 1) If in danger, move to safest deterministic neighbor.
            if current_danger and legal:
                return self._best_move(board, r, c, legal)

            # 4) Bomb only when safe, useful, and escape exists.
            if not current_danger and ammo > 0 and self._bomb_useful(board, r, c, enemies):
                post_threat = set(threatened)
                post_threat |= self._blast_cells_from(board, r, c, max(1, blast_strength))
                escape = False
                for a in (UP, DOWN, LEFT, RIGHT):
                    nr, nc = r + MOVE_DELTAS[a][0], c + MOVE_DELTAS[a][1]
                    if self._walkable(board, nr, nc) and (nr, nc) not in post_threat:
                        escape = True
                        break
                if escape:
                    return BOMB

            # 2/3/5) Prefer safe deterministic movement.
            if legal:
                return self._best_move(board, r, c, legal)

            # 6) Stop as conservative fallback.
            return STOP
        except Exception:
            return STOP

    def _board_dims(self, board: Any) -> tuple[int, int]:
        try:
            if hasattr(board, "shape") and len(board.shape) >= 2:
                return int(board.shape[0]), int(board.shape[1])
            if isinstance(board, list) and board and isinstance(board[0], list):
                return len(board), len(board[0])
        except Exception:
            return 0, 0
        return 0, 0

    def _tile(self, board: Any, r: int, c: int) -> int:
        try:
            if hasattr(board, "__getitem__"):
                return int(board[r][c]) if isinstance(board, list) else int(board[r, c])
        except Exception:
            return RIGID
        return RIGID

    def _walkable(self, board, r: int, c: int) -> bool:
        rows, cols = self._board_dims(board)
        if not (0 <= r < rows and 0 <= c < cols):
            return False
        v = self._tile(board, r, c)
        if v in {RIGID, WOOD, ITEM_BOMB, FLAMES}:
            return False
        # Agent cells are usually >= 10 and should be treated as occupied.
        if v >= 10:
            return False
        return True

    def _blast_cells_from(self, board, r: int, c: int, strength: int) -> set[tuple[int, int]]:
        cells = {(r, c)}
        dirs = [(-1, 0), (1, 0), (0, -1), (0, 1)]
        rows, cols = self._board_dims(board)
        for dr, dc in dirs:
            for k in range(1, max(1, strength) + 1):
                nr, nc = r + dr * k, c + dc * k
                if not (0 <= nr < rows and 0 <= nc < cols):
                    break
                cells.add((nr, nc))
                tile = self._tile(board, nr, nc)
                if tile == RIGID:
                    break
                if tile == WOOD:
                    break
        return cells

    def _threatened_cells(self, board, bomb_life, bomb_blast) -> set[tuple[int, int]]:
        threatened: set[tuple[int, int]] = set()
        rows, cols = self._board_dims(board)
        if bomb_life is None or bomb_blast is None:
            for rr in range(rows):
                for cc in range(cols):
                    if self._tile(board, rr, cc) == FLAMES:
                        threatened.add((rr, cc))
            return threatened
        try:
            for rr in range(rows):
                for cc in range(cols):
                    if self._tile(board, rr, cc) == FLAMES:
                        threatened.add((rr, cc))
                    if float(bomb_life[rr, cc]) > 0:
                        bs = int(bomb_blast[rr, cc]) if int(bomb_blast[rr, cc]) > 0 else 2
                        threatened |= self._blast_cells_from(board, rr, cc, bs)
        except Exception:
            return threatened
        return threatened

    def _best_move(self, board, r: int, c: int, legal_moves: list[int]) -> int:
        # Deterministic scoring: favor powerups, then passages, then nearby wood.
        best_action = STOP
        best_score = -10**9
        for a in legal_moves:
            nr, nc = r + MOVE_DELTAS[a][0], c + MOVE_DELTAS[a][1]
            tile = self._tile(board, nr, nc)
            score = 0
            if tile in POWERUPS:
                score += 5
            if tile == PASSAGE:
                score += 2
            # Small bonus if near wood to keep forward progress potential.
            for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                rr, cc = nr + dr, nc + dc
                rows, cols = self._board_dims(board)
                if 0 <= rr < rows and 0 <= cc < cols:
                    if self._tile(board, rr, cc) == WOOD:
                        score += 1
                        break
            # Tie-breaker by fixed action ordering for determinism.
            score = score * 10 - a
            if score > best_score:
                best_score = score
                best_action = a
        return best_action if best_action in legal_moves else STOP

    def _bomb_useful(self, board, r: int, c: int, enemies: list[Any]) -> bool:
        # Conservative trigger: adjacent wood or adjacent enemy tile if visible.
        enemy_vals = set()
        for e in enemies:
            try:
                enemy_vals.add(int(e.value) if hasattr(e, "value") else int(e))
            except Exception:
                continue
        for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            rr, cc = r + dr, c + dc
            rows, cols = self._board_dims(board)
            if 0 <= rr < rows and 0 <= cc < cols:
                v = self._tile(board, rr, cc)
                if v == WOOD:
                    return True
                if v in enemy_vals:
                    return True
        return False


def make_agent():
    return ConservativeAgent()


if __name__ == "__main__":
    agent = make_agent()
    print(type(agent).__name__)
