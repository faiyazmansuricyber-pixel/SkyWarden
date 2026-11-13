from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx


ROOT_DIR = Path(__file__).resolve().parents[1]
ADMIN_RELEASE_URL = "http://127.0.0.1:8002/__admin/release"
DEPLOY_WEBHOOK_URL = "http://127.0.0.1:9000/webhook/deploy"

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def _changed_files() -> list[str]:
    working_tree = subprocess.run(
        ["git", "diff", "--name-only", "HEAD"],
        cwd=ROOT_DIR,
        check=True,
        capture_output=True,
        text=True,
    )
    changed = [path for path in working_tree.stdout.splitlines() if path]
    if changed:
        return changed

    committed = subprocess.run(
        ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"],
        cwd=ROOT_DIR,
        check=True,
        capture_output=True,
        text=True,
    )
    return [path for path in committed.stdout.splitlines() if path]


def main() -> None:
    parser = argparse.ArgumentParser(description="Deploy a SkyVoyage mock release.")
    parser.add_argument("version", choices=("v3.0", "v3.1"))
    args = parser.parse_args()

    try:
        with httpx.Client(timeout=5.0) as client:
            admin_response = client.put(
                ADMIN_RELEASE_URL,
                json={"version": args.version},
            )
            admin_response.raise_for_status()
            print(f"Set SkyVoyage release to {args.version}.")

            payload = {
                "version": args.version,
                "changed_files": _changed_files(),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            try:
                webhook_response = client.post(DEPLOY_WEBHOOK_URL, json=payload)
                webhook_response.raise_for_status()
            except httpx.RequestError as error:
                print(
                    "Warning: deploy webhook engine is not running; "
                    "release was updated and deployment will continue."
                )
                print(f"Webhook connection detail: {error}")
                return
            except httpx.HTTPStatusError as error:
                print(
                    "Warning: deploy webhook engine returned "
                    f"HTTP {error.response.status_code}; release was updated and deployment will continue."
                )
                return
            print(f"Sent deploy webhook (HTTP {webhook_response.status_code}).")
    except httpx.RequestError as error:
        raise SystemExit(
            "Could not reach the local admin app on 127.0.0.1:8002; "
            "start it with `python -m target_app.admin` and retry."
        ) from error
    except httpx.HTTPStatusError as error:
        raise SystemExit(
            f"The local admin app rejected the release update (HTTP {error.response.status_code})."
        ) from error


if __name__ == "__main__":
    main()
