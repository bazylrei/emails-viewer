import json
import sys

from dotenv import load_dotenv
import anthropic

load_dotenv()

import storage  # noqa: E402 — needs env vars loaded first

MODEL = "claude-sonnet-4-6"

client = anthropic.Anthropic()


def classify_email(email, intents, intent_questions):
    """
    intents: list of known intent names
    intent_questions: {intent: [question, ...]} — questions scoped per intent
    """
    if intents:
        lines = []
        for intent in sorted(intents):
            lines.append(f"- {intent}")
            for q in sorted(intent_questions.get(intent, [])):
                lines.append(f"  · {q}")
        hierarchy = "\n".join(lines)
    else:
        hierarchy = "(none yet)"

    resp = client.messages.create(
        model=MODEL,
        max_tokens=200,
        system="You classify customer emails by business intent and core question. Respond with JSON only, no markdown.",
        messages=[{
            "role": "user",
            "content": f"""Known intents and their sub-questions:
{hierarchy}

Classify this email:
1. intent — match an existing intent exactly (copy the name letter-for-letter), or create a new one (2-4 words, Title Case).
2. question — the specific thing being asked, as a short natural question (6-10 words, ends with "?"). Strip all specifics: product numbers, order IDs, company names, dates. Reuse an existing sub-question for the chosen intent if it fits exactly, otherwise write a new generic one.

Respond with JSON only: {{"intent": "...", "is_new_intent": false, "question": "...", "is_new_question": true}}

Subject: {email['subject']}
Body: {email['body'][:1500]}"""
        }]
    )

    raw = resp.content[0].text.strip()
    if "```" in raw:
        raw = raw.split("```")[1].lstrip("json").strip()
    return json.loads(raw)


def run(input_file, backfill=False):
    with open(input_file, encoding="utf-8") as f:
        emails = json.load(f)

    existing = storage.load_emails()

    if backfill:
        # Re-classify only emails that are missing a question
        processed_ids = {e["id"] for bucket in existing.values() for e in bucket["emails"] if e.get("question")}
        print(f"Backfill — {len(processed_ids)} already have a question, {len(emails) - len(processed_ids)} to classify.\n")
    else:
        processed_ids = {e["id"] for bucket in existing.values() for e in bucket["emails"]}
        if processed_ids:
            print(f"Resuming — {len(processed_ids)} done, {len(emails) - len(processed_ids)} remaining.\n")

    intents = list(set(storage.load_intents()))
    intent_questions = storage.load_all_questions()  # {intent: [q, ...]}
    if intents:
        print(f"Loaded {len(intents)} intents, {sum(len(v) for v in intent_questions.values())} questions\n")

    errors = 0
    intent_counts = {}

    for email in emails:
        if email["id"] in processed_ids:
            print("s", end="", flush=True)
            continue

        try:
            result = classify_email(email, intents, intent_questions)
            intent = result["intent"]
            question = result.get("question", "")
            is_new_intent = result.get("is_new_intent", intent not in intents)
            is_new_question = result.get("is_new_question", question not in intent_questions.get(intent, []))

            if intent not in intents:
                intents.append(intent)
                storage.save_intent(intent)

            if question and question not in intent_questions.get(intent, []):
                intent_questions.setdefault(intent, []).append(question)
                storage.save_question(intent, question)

            storage.save_email(email, intent, question)
            intent_counts[intent] = intent_counts.get(intent, 0) + 1

            # . = all existing  + = new intent  ? = new question
            if is_new_intent:
                print("+", end="", flush=True)
            elif is_new_question:
                print("?", end="", flush=True)
            else:
                print(".", end="", flush=True)

        except Exception as e:
            errors += 1
            print(f"\n  Error: {e}")

    total_questions = sum(len(v) for v in intent_questions.values())
    print(f"\n\nDone — {len(emails)} emails → {len(intent_counts)} intents, {total_questions} questions ({errors} errors)\n")
    for intent, count in sorted(intent_counts.items(), key=lambda x: -x[1]):
        qs = intent_questions.get(intent, [])
        print(f"  {count:4d}  {intent}  ({len(qs)} questions)")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0].startswith("--"):
        print("Usage: python classify.py <emails_file> [--backfill] [--reset]")
        sys.exit(1)

    input_file = args[0]
    flags = set(args[1:])

    if "--reset" in flags:
        print("Hard reset — dropping all tables...")
        storage.reset_all()
        print("Done. Re-classifying from scratch.\n")

    run(input_file, backfill="--backfill" in flags)
