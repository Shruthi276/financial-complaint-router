"""Roll back (or forward) the served model by moving the @champion alias.

The model-server supervisor notices the alias change within ~20 s and deploys
that version - no rebuild or restart needed.

Usage: python scripts/rollback.py --version 3 [--model complaint-router]
"""

from __future__ import annotations

import argparse
import sys

from mlflow import MlflowClient
from mlflow.exceptions import MlflowException


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", required=True, help="registry version to serve")
    parser.add_argument("--model", default="complaint-router")
    args = parser.parse_args()

    client = MlflowClient()
    try:
        current = client.get_model_version_by_alias(args.model, "champion").version
    except MlflowException:
        current = None
    try:
        client.get_model_version(args.model, args.version)
    except MlflowException:
        print(f"Version {args.version} of {args.model} does not exist", file=sys.stderr)
        return 1
    client.set_registered_model_alias(args.model, "champion", args.version)
    client.set_model_version_tag(args.model, args.version, "rolled_back_from", str(current))
    print(f"@champion: v{current} -> v{args.version}. The model server will redeploy within ~20 s.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
