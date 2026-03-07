import hashlib
import os
import time

from azure.data.tables import TableServiceClient

def _get_connection_string():
    # Streamlit Cloud exposes secrets via st.secrets, not os.environ
    try:
        import streamlit as st
        return st.secrets["AZURE_STORAGE_CONNECTION_STRING"]
    except Exception:
        return os.environ["AZURE_STORAGE_CONNECTION_STRING"]
EMAILS_TABLE = "emails"
INTENTS_TABLE = "intents"
QUESTIONS_TABLE = "questions"


def _table(name):
    svc = TableServiceClient.from_connection_string(_get_connection_string())
    for attempt in range(20):
        try:
            return svc.create_table_if_not_exists(name)
        except Exception as e:
            if "TableBeingDeleted" in str(e) and attempt < 19:
                print(f"\r  Waiting for '{name}' to finish deleting... ({attempt + 1}s)", end="", flush=True)
                time.sleep(2)
            else:
                raise
    raise RuntimeError(f"Table '{name}' could not be recreated after reset.")


def _row_key(email_id):
    """Use an MD5 hash so long/special-char Graph API IDs are safe as RowKeys."""
    return hashlib.md5(email_id.encode()).hexdigest()


# --- Intents ---

def load_intents():
    return [e["RowKey"] for e in _table(INTENTS_TABLE).list_entities()]


def save_intent(intent):
    _table(INTENTS_TABLE).upsert_entity({"PartitionKey": "all", "RowKey": intent})


def rename_intent(old_name, new_name):
    """Re-inserts all emails and questions under new intent name."""
    emails_tbl = _table(EMAILS_TABLE)
    questions_tbl = _table(QUESTIONS_TABLE)
    intents_tbl = _table(INTENTS_TABLE)

    safe = old_name.replace("'", "''")

    emails = list(emails_tbl.query_entities(f"PartitionKey eq '{safe}'"))
    for e in emails:
        new_e = dict(e)
        new_e["PartitionKey"] = new_name
        emails_tbl.upsert_entity(new_e)
        emails_tbl.delete_entity(old_name, e["RowKey"])

    questions = list(questions_tbl.query_entities(f"PartitionKey eq '{safe}'"))
    for q in questions:
        new_q = dict(q)
        new_q["PartitionKey"] = new_name
        questions_tbl.upsert_entity(new_q)
        questions_tbl.delete_entity(old_name, q["RowKey"])

    intents_tbl.upsert_entity({"PartitionKey": "all", "RowKey": new_name})
    try:
        intents_tbl.delete_entity("all", old_name)
    except Exception:
        pass

    return len(emails)


def delete_intent(name):
    """Deletes an intent, all its emails, and all its questions."""
    emails_tbl = _table(EMAILS_TABLE)
    questions_tbl = _table(QUESTIONS_TABLE)
    intents_tbl = _table(INTENTS_TABLE)

    safe = name.replace("'", "''")

    emails = list(emails_tbl.query_entities(f"PartitionKey eq '{safe}'"))
    for e in emails:
        emails_tbl.delete_entity(name, e["RowKey"])

    questions = list(questions_tbl.query_entities(f"PartitionKey eq '{safe}'"))
    for q in questions:
        questions_tbl.delete_entity(name, q["RowKey"])

    try:
        intents_tbl.delete_entity("all", name)
    except Exception:
        pass

    return len(emails)


def reset_all():
    """Drop all tables (hard reset)."""
    svc = TableServiceClient.from_connection_string(_get_connection_string())
    for table_name in [EMAILS_TABLE, INTENTS_TABLE, QUESTIONS_TABLE]:
        try:
            svc.delete_table(table_name)
            print(f"  Dropped: {table_name}")
        except Exception:
            pass


# --- Questions (sub-intents, scoped per intent) ---

def load_all_questions():
    """Return {intent: [question_text, ...]} for all intents."""
    result = {}
    for e in _table(QUESTIONS_TABLE).list_entities():
        intent = e["PartitionKey"]
        text = e.get("text", "")
        if text:
            result.setdefault(intent, []).append(text)
    return result


def save_question(intent, question):
    _table(QUESTIONS_TABLE).upsert_entity({
        "PartitionKey": intent,
        "RowKey": hashlib.md5(question.encode()).hexdigest(),
        "text": question,
    })


# --- Emails ---

def save_email(email, intent, question=""):
    entity = {
        "PartitionKey": intent,
        "RowKey": _row_key(email["id"]),
        "email_id": email["id"],
        "subject": email.get("subject") or "",
        "from_name": email.get("from", {}).get("name", ""),
        "from_address": email.get("from", {}).get("address", ""),
        "receivedAt": email.get("receivedAt", ""),
        "body": (email.get("body") or "")[:30000],
        "month": email.get("receivedAt", "")[:7].replace("-", "_"),
        "question": question,
    }
    _table(EMAILS_TABLE).upsert_entity(entity)


def list_months():
    months = set()
    for e in _table(EMAILS_TABLE).list_entities(select=["month"]):
        m = e.get("month")
        if m:
            months.add(m)
    return sorted(months)


def load_emails(month=None):
    """Return {intent: {"count": N, "emails": [...]}} for the given month (or all)."""
    client = _table(EMAILS_TABLE)
    if month:
        entities = client.query_entities(f"month eq '{month}'")
    else:
        entities = client.list_entities()

    by_intent = {}
    for e in entities:
        intent = e["PartitionKey"]
        if intent not in by_intent:
            by_intent[intent] = {"count": 0, "emails": []}
        by_intent[intent]["emails"].append({
            "id": e.get("email_id", e["RowKey"]),
            "subject": e.get("subject", ""),
            "from": {
                "name": e.get("from_name", ""),
                "address": e.get("from_address", ""),
            },
            "receivedAt": e.get("receivedAt", ""),
            "body": e.get("body", ""),
            "question": e.get("question", ""),
        })
        by_intent[intent]["count"] += 1

    return by_intent
