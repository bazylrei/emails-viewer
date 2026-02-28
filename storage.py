import hashlib
import os

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


def _table(name):
    svc = TableServiceClient.from_connection_string(_get_connection_string())
    return svc.create_table_if_not_exists(name)


def _row_key(email_id):
    """Use an MD5 hash so long/special-char Graph API IDs are safe as RowKeys."""
    return hashlib.md5(email_id.encode()).hexdigest()


# --- Intents ---

def load_intents():
    return [e["RowKey"] for e in _table(INTENTS_TABLE).list_entities()]


def save_intent(intent):
    _table(INTENTS_TABLE).upsert_entity({"PartitionKey": "all", "RowKey": intent})


# --- Emails ---

def save_email(email, intent):
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
    }
    _table(EMAILS_TABLE).upsert_entity(entity)


def list_months():
    months = set()
    for e in _table(EMAILS_TABLE).list_entities():
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
        })
        by_intent[intent]["count"] += 1

    return by_intent
