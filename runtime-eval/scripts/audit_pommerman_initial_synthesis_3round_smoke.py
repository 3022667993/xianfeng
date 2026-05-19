from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.audit_pommerman_initial_synthesis import audit_pommerman_initial_synthesis
from scripts.audit_pommerman_openclaw_adaptive_3round_smoke import audit_openclaw_adaptive_3round_smoke


DEFAULT_TOURNAMENT_CONFIG = Path(
    "configs/tournaments/pommerman_gptv16_a00_openclaw_initial_synthesis_3round_smoke.yaml"
)
DEFAULT_TOURNAMENT_NAME = "pommerman_gptv16_a00_openclaw_initial_synthesis_3round_smoke"


def _load_tournament_config_name(tournament_config_path: Path) -> str:
    try:
        payload = yaml.safe_load(tournament_config_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"failed to read tournament config: {tournament_config_path}: {exc!r}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"invalid tournament config payload: {tournament_config_path}")
    tournament_name = payload.get("name")
    if not isinstance(tournament_name, str) or not tournament_name.strip():
        raise ValueError(f"tournament config missing non-empty name: {tournament_config_path}")
    return tournament_name.strip()


def audit_pommerman_initial_synthesis_3round_smoke(
    tournament_name: str = DEFAULT_TOURNAMENT_NAME,
    tournament_config_path: Path = DEFAULT_TOURNAMENT_CONFIG,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    e0, w0 = audit_pommerman_initial_synthesis(tournament_name=tournament_name)
    errors.extend(e0)
    warnings.extend(w0)

    e1, w1 = audit_openclaw_adaptive_3round_smoke(tournament_name=tournament_name)
    errors.extend(e1)
    warnings.extend(w1)

    if not tournament_config_path.exists():
        errors.append(f"missing initial synthesis 3round tournament config: {tournament_config_path}")
    else:
        try:
            configured_name = _load_tournament_config_name(tournament_config_path)
            if configured_name != tournament_name:
                errors.append(
                    "tournament_name mismatch with config: "
                    f"{tournament_name} != {configured_name} ({tournament_config_path})"
                )
        except ValueError as exc:
            errors.append(str(exc))

    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Audit Pommerman A00 initial-synthesis + adaptive 3-round smoke artifacts.\n"
            "Example:\n"
            "  python scripts/audit_pommerman_initial_synthesis_3round_smoke.py "
            "--tournament configs/tournaments/"
            "pommerman_gptv16_a00_openclaw_initial_synthesis_3round_neutral_smoke.yaml"
        )
    )
    parser.add_argument(
        "--tournament",
        default=str(DEFAULT_TOURNAMENT_CONFIG),
        help="Path to tournament YAML config (default: coached 3-round smoke config).",
    )
    parser.add_argument(
        "--tournament-name",
        default=None,
        help="Optional explicit tournament name override. Defaults to config `name`.",
    )
    args = parser.parse_args()

    tournament_config_path = Path(args.tournament)
    tournament_name = args.tournament_name
    if tournament_name is None:
        try:
            tournament_name = _load_tournament_config_name(tournament_config_path)
        except ValueError as exc:
            print("pommerman_initial_synthesis_3round_smoke_audit=FAIL")
            print(f"ERROR {exc}")
            return 1

    errors, warnings = audit_pommerman_initial_synthesis_3round_smoke(
        tournament_name=tournament_name,
        tournament_config_path=tournament_config_path,
    )
    for w in warnings:
        print(f"WARN {w}")
    if errors:
        print("pommerman_initial_synthesis_3round_smoke_audit=FAIL")
        for e in errors:
            print(f"ERROR {e}")
        return 1
    print("pommerman_initial_synthesis_3round_smoke_audit=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
