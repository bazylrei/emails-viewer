import argparse
import base64
import json
import os
from collections import defaultdict

import msal
import requests
from dotenv import load_dotenv

load_dotenv()

# --- CONFIG ---
TENANT_ID = os.environ["TENANT_ID"]
CLIENT_ID = os.environ["CLIENT_ID"]
SHARED_MAILBOX = os.environ["SHARED_MAILBOX"]
SUBFOLDER_NAME = os.environ["SUBFOLDER_NAME"]
OUTPUT_DIR = os.environ["OUTPUT_DIR"]

SCOPES = ["https://graph.microsoft.com/Mail.Read.Shared"]
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"

# Only fetch the fields we actually need
SELECT = "id,conversationId,conversationIndex,subject,from,toRecipients,receivedDateTime,body,hasAttachments"

# --- AUTH ---
app = msal.PublicClientApplication(CLIENT_ID, authority=AUTHORITY)

accounts = app.get_accounts()
if accounts:
    result = app.acquire_token_silent(SCOPES, account=accounts[0])
else:
    result = app.acquire_token_interactive(scopes=SCOPES)

if "access_token" not in result:
    raise Exception(f"Auth failed: {result.get('error_description')}")

token = result["access_token"]
headers = {"Authorization": f"Bearer {token}"}
# Request plain text bodies instead of HTML (cleaner for LLM input)
msg_headers = {**headers, "Prefer": 'outlook.body-content-type="text"'}

# --- FIND SUBFOLDER ---
def get_folders(parent_id=None):
    if parent_id:
        url = f"https://graph.microsoft.com/v1.0/users/{SHARED_MAILBOX}/mailFolders/{parent_id}/childFolders"
    else:
        url = f"https://graph.microsoft.com/v1.0/users/{SHARED_MAILBOX}/mailFolders"
    return requests.get(url, headers=headers).json().get("value", [])

def find_folder(name):
    for folder in get_folders():
        if folder["displayName"].lower() == name.lower():
            return folder["id"]
        for child in get_folders(folder["id"]):
            if child["displayName"].lower() == name.lower():
                return child["id"]
    return None

folder_id = find_folder(SUBFOLDER_NAME)
if not folder_id:
    raise Exception(f"Folder '{SUBFOLDER_NAME}' not found")

# --- HELPERS ---
def is_original(msg):
    """
    The conversationIndex for the root message decodes to exactly 22 bytes.
    Every reply appends 5 bytes, so anything longer is a reply.
    """
    idx = msg.get("conversationIndex", "")
    if not idx:
        return True  # can't tell, include it
    try:
        return len(base64.b64decode(idx)) == 22
    except Exception:
        return True

def slim(msg):
    """Extract only the fields relevant for LLM classification."""
    return {
        "id": msg.get("id"),
        "conversationId": msg.get("conversationId"),
        "subject": msg.get("subject"),
        "from": msg.get("from", {}).get("emailAddress", {}),
        "to": [r["emailAddress"] for r in msg.get("toRecipients", [])],
        "receivedAt": msg.get("receivedDateTime"),
        "body": msg.get("body", {}).get("content", ""),
        "hasAttachments": msg.get("hasAttachments"),
    }

# --- PAGINATE + FILTER + GROUP BY MONTH ---
os.makedirs(OUTPUT_DIR, exist_ok=True)

def flush_month(month_key, emails):
    path = os.path.join(OUTPUT_DIR, f"emails_{month_key}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(emails, f, indent=2, ensure_ascii=False)
    # \r moves to start of line, \033[K clears it, then print the summary
    print(f"\r\033[K  {month_key}: {len(emails)} originals saved → {path}", flush=True)

parser = argparse.ArgumentParser()
parser.add_argument("--from", dest="date_from", help="Start date (e.g. 2026-03-01)")
parser.add_argument("--to", dest="date_to", help="End date exclusive (e.g. 2026-04-01)")
args = parser.parse_args()

date_filter = ""
if args.date_from and args.date_to:
    date_filter = f"&$filter=receivedDateTime ge {args.date_from}T00:00:00Z and receivedDateTime lt {args.date_to}T00:00:00Z"

url = (
    f"https://graph.microsoft.com/v1.0/users/{SHARED_MAILBOX}/mailFolders/{folder_id}/messages"
    f"?$top=999&$select={SELECT}&$orderby=receivedDateTime desc{date_filter}"
)

by_month = defaultdict(list)
total_fetched = 0
total_originals = 0

while url:
    resp = requests.get(url, headers=msg_headers).json()
    page = resp.get("value", [])
    total_fetched += len(page)
    months_in_page = set()

    for msg in page:
        if is_original(msg):
            email = slim(msg)
            month_key = email["receivedAt"][:7].replace("-", "_")
            by_month[month_key].append(email)
            months_in_page.add(month_key)
            total_originals += 1
            print(".", end="", flush=True)
        else:
            print("-", end="", flush=True)

    # Any month absent from this page won't appear in future pages — flush it now
    for month_key in list(by_month):
        if month_key not in months_in_page:
            flush_month(month_key, by_month.pop(month_key))

    url = resp.get("@odata.nextLink")

# Flush whatever remains (the oldest month and any stragglers)
for month_key in sorted(by_month):
    flush_month(month_key, by_month.pop(month_key))

print(f"\nDone. {total_originals} originals from {total_fetched} total messages.")