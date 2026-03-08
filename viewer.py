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

@st.cache_data(ttl=300)
def get_months():
    return storage.list_months()

months = get_months()
if not months:
    st.warning("No data found. Run `python classify.py <emails_file>` first.")
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
all_emails_flat = [e for d in intents.values() for e in d["emails"]]
unique_questions = len(set(e["question"] for e in all_emails_flat if e.get("question")))
col1, col2, col3 = st.columns(3)
col1.metric("Total emails", total_emails)
col2.metric("Intents", len(intents))
col3.metric("Questions", unique_questions)

st.divider()

# --- Intent selector in sidebar ---
intent_options = [f"{name}  ({data['count']})" for name, data in sorted_intents]
selected_label = st.sidebar.radio("Intent", intent_options)
selected_intent = selected_label.rsplit("  (", 1)[0]

# --- Main: intent header ---
bucket = intents[selected_intent]
st.subheader(selected_intent)

# --- Question filter (dropdown, sorted by count) ---
question_counts = {}
for e in bucket["emails"]:
    q = e.get("question", "")
    if q:
        question_counts[q] = question_counts.get(q, 0) + 1

selected_question = None
if question_counts:
    sorted_questions = sorted(question_counts.items(), key=lambda x: -x[1])
    q_labels = ["All"] + [f"{q}  ({n})" for q, n in sorted_questions]
    selected_q_label = st.selectbox("Question", q_labels, label_visibility="collapsed")
    if selected_q_label != "All":
        selected_question = selected_q_label.rsplit("  (", 1)[0]

# --- Filtered email list ---
filtered = [
    e for e in bucket["emails"]
    if not selected_question or e.get("question") == selected_question
]
search = st.text_input("Search", placeholder="keyword...", label_visibility="collapsed")
if search:
    filtered = [e for e in filtered if search.lower() in (e["subject"] + e["body"]).lower()]

st.caption(f"{len(filtered)} email(s)")

for email in filtered:
    sender = email["from"].get("name") or email["from"].get("address", "Unknown")
    date = email["receivedAt"][:10] if email.get("receivedAt") else ""
    label = f"**{email['subject']}** — {sender} — {date}"

    with st.expander(label):
        st.write(f"**From:** {email['from'].get('name', '')} <{email['from'].get('address', '')}>")
        st.write(f"**Date:** {email['receivedAt']}")
        if email.get("question"):
            st.write(f"**Question:** {email['question']}")
        st.divider()
        st.text(email["body"])

# --- Manage Intents ---
st.divider()
with st.expander("Manage Intents"):
    all_intent_names = sorted(intents.keys())

    st.markdown("**Rename**")
    rename_src = st.selectbox("Intent to rename", all_intent_names, key="rename_src")
    rename_dst = st.text_input("New name", key="rename_dst")
    if st.button("Rename intent"):
        new_name = rename_dst.strip()
        if new_name and new_name != rename_src:
            count = storage.rename_intent(rename_src, new_name)
            st.success(f"Renamed '{rename_src}' → '{new_name}' ({count} emails updated)")
            get_months.clear()
            get_data.clear()
            st.rerun()
        else:
            st.warning("Enter a different name.")

    st.markdown("---")
    st.markdown("**Delete**")
    del_intent = st.selectbox("Intent to delete", all_intent_names, key="del_intent")
    st.caption(f"Permanently deletes {intents[del_intent]['count']} email(s) and all sub-questions.")
    if st.button("Delete intent", type="primary"):
        count = storage.delete_intent(del_intent)
        st.success(f"Deleted '{del_intent}' ({count} emails removed).")
        get_months.clear()
        get_data.clear()
        st.rerun()
