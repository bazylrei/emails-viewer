import json
import sys

from dotenv import load_dotenv
import anthropic

load_dotenv()

import storage  # noqa: E402 — needs env vars loaded first

MODEL = "claude-sonnet-4-6"

client = anthropic.Anthropic()


def load_intents():
    return storage.load_intents()


def save_intents(intents):
    for intent in intents:
        storage.save_intent(intent)


def classify_email(email, intents):
    intent_list = "\n".join(f"- {name}" for name in sorted(intents)) if intents else "(none yet)"

    resp = client.messages.create(
        model=MODEL,
        max_tokens=150,
        system="You classify customer emails by business intent. Respond with JSON only, no markdown.",
        messages=[{
            "role": "user",
            "content": f"""Current intents:
{intent_list}

Does this email match an existing intent, or is it a new one?
- If it matches an existing intent, return the exact name from the list.
- If it is new, create a concise business-friendly name (2-4 words, title case).

Respond with JSON only: {{"intent": "Intent Name", "is_new": true}}

Subject: {email['subject']}
Body: {email['body'][:1500]}"""
        }]
    )

    raw = resp.content[0].text.strip()
    if "```" in raw:
        raw = raw.split("```")[1].lstrip("json").strip()
    return json.loads(raw)


def run(input_file):
    with open(input_file, encoding="utf-8") as f:
        emails = json.load(f)

    # Resume support: skip emails already in Table Storage
    existing = storage.load_emails()
    processed_ids = {e["id"] for bucket in existing.values() for e in bucket["emails"]}
    if processed_ids:
        print(f"Resuming — {len(processed_ids)} already done, {len(emails) - len(processed_ids)} remaining.\n")

    known_intents = load_intents()
    intents = list(set(known_intents))
    if known_intents:
        print(f"Loaded {len(known_intents)} known intents from Table Storage")
    errors = 0
    intent_counts = {}

    for email in emails:
        if email["id"] in processed_ids:
            print("s", end="", flush=True)  # skipped
            intent_counts[email.get("intent", "?")] = intent_counts.get(email.get("intent", "?"), 0) + 1
            continue

        try:
            result = classify_email(email, intents)
            intent = result["intent"]
            is_new = result.get("is_new", intent not in intents)

            if intent not in intents:
                intents.append(intent)
                storage.save_intent(intent)

            storage.save_email(email, intent)
            intent_counts[intent] = intent_counts.get(intent, 0) + 1

            # . = matched existing, + = new intent created
            print("+" if is_new else ".", end="", flush=True)

        except Exception as e:
            errors += 1
            print(f"\n  Error: {e}")

    print(f"\n\nDone — {len(emails)} emails → {len(intent_counts)} intents ({errors} errors)\n")
    for intent, count in sorted(intent_counts.items(), key=lambda x: -x[1]):
        print(f"  {count:4d}  {intent}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python classify.py emails/emails_2025_02.json")
        sys.exit(1)
    run(sys.argv[1])
