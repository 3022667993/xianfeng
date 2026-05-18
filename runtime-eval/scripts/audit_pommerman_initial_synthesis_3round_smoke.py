from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.audit_pommerman_initial_synthesis import audit_pommerman_initial_synthesis
from scripts.audit_pommerman_openclaw_adaptive_3round_smoke import audit_openclaw_adaptive_3round_smoke


def audit_pommerman_initial_synthesis_3round_smoke(
    tournament_name: str = "pommerman_gptv16_a00_openclaw_initial_synthesis_3round_smoke",
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    e0, w0 = audit_pommerman_initial_synthesis(tournament_name=tournament_name)
    errors.extend(e0)
    warnings.extend(w0)

    e1, w1 = audit_openclaw_adaptive_3round_smoke(tournament_name=tournament_name)
    errors.extend(e1)
    warnings.extend(w1)

    cfg_path = Path("configs/tournaments/pommerman_gptv16_a00_openclaw_initial_synthesis_3round_smoke.yaml")
    if not cfg_path.exists():
        errors.append("missing initial synthesis 3round tournament config")

    return errors, warnings


def main() -> int:
    errors, warnings = audit_pommerman_initial_synthesis_3round_smoke()
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
