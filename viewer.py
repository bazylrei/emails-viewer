import streamlit as st
from dotenv import load_dotenv

load_dotenv()

import storage  # noqa: E402 — needs env vars loaded first
from auth import check_password

st.set_page_config(page_title="Email Intent Viewer", layout="wide")

if not check_password():
    st.stop()

st.title("Email Intent Viewer")

# --- Sidebar ---
st.sidebar.header("Filters")

months = storage.list_months()
if not months:
    st.warning("No data found. Run `python migrate.py` or `python classify.py <emails_file>` first.")
    st.stop()

selected_month = st.sidebar.selectbox("Month", ["All"] + months)

# --- Load data ---
@st.cache_data(ttl=300)
def get_data(month):
    return storage.load_emails(month if month != "All" else None)

intents = get_data(selected_month)

if not intents:
    st.info("No emails for the selected month.")
    st.stop()

sorted_intents = sorted(intents.items(), key=lambda x: -x[1]["count"])

# --- Top summary ---
total_emails = sum(d["count"] for d in intents.values())
col1, col2 = st.columns(2)
col1.metric("Total emails", total_emails)
col2.metric("Unique intents", len(intents))

st.divider()

# --- Intent selector in sidebar ---
intent_options = [f"{name}  ({data['count']})" for name, data in sorted_intents]
selected_label = st.sidebar.radio("Intent", intent_options)
selected_intent = selected_label.rsplit("  (", 1)[0]

# --- Email list ---
bucket = intents[selected_intent]
st.subheader(f"{selected_intent} — {bucket['count']} email(s)")

search = st.text_input("Search within this intent", placeholder="keyword...")

for email in bucket["emails"]:
    if search and search.lower() not in (email["subject"] + email["body"]).lower():
        continue

    sender = email["from"].get("name") or email["from"].get("address", "Unknown")
    date = email["receivedAt"][:10]
    label = f"**{email['subject']}** — {sender} — {date}"

    with st.expander(label):
        st.write(f"**From:** {email['from'].get('name', '')} <{email['from'].get('address', '')}>")
        st.write(f"**Date:** {email['receivedAt']}")
        st.divider()
        st.text(email["body"])
