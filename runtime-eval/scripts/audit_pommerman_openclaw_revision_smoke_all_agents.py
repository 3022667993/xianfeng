from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.audit_pommerman_openclaw_revision_smoke import (
    _audit_a00,
    audit_openclaw_revision_smoke,
)


def main() -> int:
    errors = _audit_a00()
    e2, w2 = audit_openclaw_revision_smoke(
        "pommerman_gptv16_a00_openclaw_revision_smoke_all_agents",
        require_all_agents=True,
    )
    errors.extend(e2)
    for w in w2:
        print(f"WARN {w}")
    if errors:
        print("openclaw_revision_smoke_all_agents_audit=FAIL")
        for e in errors:
            print(f"ERROR {e}")
        return 1
    print("openclaw_revision_smoke_all_agents_audit=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
