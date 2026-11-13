from __future__ import annotations

import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def main() -> None:
    from engine.recon.pipeline import run_recon_inventory
    from engine.safety.gate import SafetyGate
    from engine.safety.vault import Vault

    gate = SafetyGate(Vault.from_env())
    try:
        result = run_recon_inventory(gate, gate.vault)
    finally:
        gate.close()
    print(
        f"Inventoried {len(result.inventory)} reachable endpoints; "
        f"OpenAPI written to {result.openapi_path}."
    )


if __name__ == "__main__":
    main()
