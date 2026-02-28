"""One-time migration: results/*.json → Azure Table Storage."""
import glob
import json
import os

from dotenv import load_dotenv

load_dotenv()

import storage  # noqa: E402 — needs env vars loaded first

RESULTS_DIR = "results"

result_files = sorted(glob.glob(os.path.join(RESULTS_DIR, "results_*.json")))
if not result_files:
    print("No result files found in results/. Nothing to migrate.")
    raise SystemExit(0)

total_emails = 0
total_intents = 0

for path in result_files:
    month = os.path.basename(path).replace("results_", "").replace(".json", "")
    print(f"\nMigrating {month}...", end=" ", flush=True)

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    for intent, bucket in data["intents"].items():
        storage.save_intent(intent)
        total_intents += 1
        for email in bucket["emails"]:
            storage.save_email(email, intent)
            total_emails += 1
            print(".", end="", flush=True)

print(f"\n\nDone. Migrated {total_emails} emails across {total_intents} intents.")
