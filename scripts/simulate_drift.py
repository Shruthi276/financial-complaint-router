"""Demonstrate drift detection -> alert -> automatic retraining.

Sends a burst of complaints whose vocabulary and topic mix differ from the
training data (e.g. "buy now pay later" and crypto-wallet complaints written in
slang). After DRIFT_MIN_SAMPLES requests the backend's drift score rises,
Prometheus fires DataDriftDetected after 1 minute, Alertmanager calls the
retrainer webhook and `dvc repro` runs. Watch it in the UI (Pipeline console /
Monitoring) or Grafana.

Usage: python scripts/simulate_drift.py --n 120 [--api http://localhost:8000]
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
import urllib.error
import urllib.request

TEMPLATES = [
    "bnpl app {verb} my {thing} and the klarna style installment got {state} lol",
    "my defi wallet {verb} the nft {thing} and the dao governance token is {state}",
    "the neobank chatbot {verb} my crypto staking {thing} and rewards are {state}",
    "afterpay {verb} my split payment {thing} and the merchant marked it {state}",
    "metamask bridge {verb} usdc {thing} gas fees {state} smart contract exploit",
]
VERBS = ["glitched", "rugpulled", "bricked", "ghosted", "shadowbanned", "frontran"]
THINGS = ["airdrop", "yield farm", "seed phrase", "liquidity pool", "paylater plan"]
STATES = ["sus", "borked", "nerfed", "rekt", "frozen fr fr"]


def post(api: str, text: str) -> dict:
    req = urllib.request.Request(f"{api}/api/v1/predict", data=json.dumps({"text": text}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--n", type=int, default=120)
    parser.add_argument("--delay", type=float, default=0.05)
    args = parser.parse_args()

    rng = random.Random(7)
    ok = 0
    for i in range(args.n):
        text = rng.choice(TEMPLATES).format(verb=rng.choice(VERBS), thing=rng.choice(THINGS),
                                            state=rng.choice(STATES))
        try:
            post(args.api, text)
            ok += 1
        except (urllib.error.URLError, TimeoutError) as exc:
            print(f"request {i} failed: {exc}", file=sys.stderr)
        time.sleep(args.delay)
    with urllib.request.urlopen(f"{args.api}/api/v1/monitoring/drift", timeout=10) as resp:
        report = json.loads(resp.read())
    print(f"sent {ok}/{args.n} drifted complaints")
    print(json.dumps(report, indent=2))
    print("\nPrometheus fires DataDriftDetected after ~1 minute of sustained drift; "
          "check http://localhost:9093 (Alertmanager) and the Pipeline console.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
