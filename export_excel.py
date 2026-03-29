"""
export_excel.py

Downloads all original emails (same logic as email_scraping.py) and writes them
to an Excel file with 4 columns:

  original_email | ai_response | intent | feedback

Attachments are fetched for each email and their text content is appended to the
original_email cell so that any context they carry is preserved.

Supported attachment types:
  - Plain text (.txt, .csv, .log, .xml, .json, .html, .htm) → extracted as-is
  - PDF (.pdf) → text extracted via pdfminer.six
  - Word (.docx) → text extracted via python-docx
  - Images / other → noted as "[Attachment: filename.ext — binary, not extracted]"

Usage:
  python export_excel.py                                    # all emails
  python export_excel.py --from 2026-03-01 --to 2026-04-01 # date range
  python export_excel.py --output my_export.xlsx            # custom output path
"""

import argparse
import base64
import io
import os
import re

import msal
import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
TENANT_ID = os.environ["TENANT_ID"]
CLIENT_ID = os.environ["CLIENT_ID"]
SHARED_MAILBOX = os.environ["SHARED_MAILBOX"]
SUBFOLDER_NAME = os.environ["SUBFOLDER_NAME"]

SCOPES = ["https://graph.microsoft.com/Mail.Read.Shared"]
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"

SELECT = (
    "id,conversationId,conversationIndex,subject,from,"
    "toRecipients,receivedDateTime,body,hasAttachments"
)

TEXT_EXTENSIONS = {".txt", ".csv", ".log", ".xml", ".json", ".html", ".htm", ".md"}

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def _authenticate():
    app = msal.PublicClientApplication(CLIENT_ID, authority=AUTHORITY)
    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(SCOPES, account=accounts[0])
    else:
        result = app.acquire_token_interactive(scopes=SCOPES)
    if "access_token" not in result:
        raise Exception(f"Auth failed: {result.get('error_description')}")
    return result["access_token"]


# ---------------------------------------------------------------------------
# Folder helpers
# ---------------------------------------------------------------------------

def _get_folders(headers, parent_id=None):
    if parent_id:
        url = f"https://graph.microsoft.com/v1.0/users/{SHARED_MAILBOX}/mailFolders/{parent_id}/childFolders"
    else:
        url = f"https://graph.microsoft.com/v1.0/users/{SHARED_MAILBOX}/mailFolders"
    return requests.get(url, headers=headers).json().get("value", [])


def _find_folder(headers, name):
    for folder in _get_folders(headers):
        if folder["displayName"].lower() == name.lower():
            return folder["id"]
        for child in _get_folders(headers, folder["id"]):
            if child["displayName"].lower() == name.lower():
                return child["id"]
    return None


# ---------------------------------------------------------------------------
# Email helpers
# ---------------------------------------------------------------------------

def _is_original(msg):
    """
    The conversationIndex for the root message decodes to exactly 22 bytes.
    Every reply appends 5 bytes, so anything longer is a reply.
    """
    idx = msg.get("conversationIndex", "")
    if not idx:
        return True
    try:
        return len(base64.b64decode(idx)) == 22
    except Exception:
        return True


# ---------------------------------------------------------------------------
# Attachment text extraction
# ---------------------------------------------------------------------------

def _extract_pdf_text(data: bytes) -> str:
    try:
        from pdfminer.high_level import extract_text as pdf_extract
        text = pdf_extract(io.BytesIO(data))
        return text.strip() if text else "[PDF: no extractable text]"
    except ImportError:
        return "[PDF: pdfminer not available — install pdfminer.six]"
    except Exception as e:
        return f"[PDF: extraction failed — {e}]"


def _extract_docx_text(data: bytes) -> str:
    try:
        from docx import Document
        doc = Document(io.BytesIO(data))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n".join(paragraphs) if paragraphs else "[DOCX: no extractable text]"
    except ImportError:
        return "[DOCX: python-docx not available — install python-docx]"
    except Exception as e:
        return f"[DOCX: extraction failed — {e}]"


def _attachment_text(name: str, content_bytes_b64: str) -> str:
    """Decode a base64 attachment and extract readable text where possible."""
    data = base64.b64decode(content_bytes_b64)
    ext = os.path.splitext(name)[1].lower()

    if ext in TEXT_EXTENSIONS:
        try:
            return data.decode("utf-8", errors="replace")
        except Exception:
            return f"[{ext.upper().lstrip('.')}: decode failed]"
    elif ext == ".pdf":
        return _extract_pdf_text(data)
    elif ext == ".docx":
        return _extract_docx_text(data)
    else:
        return f"[Attachment: {name} — binary file, not extracted]"


# ---------------------------------------------------------------------------
# Fetch attachments for a message
# ---------------------------------------------------------------------------

def _fetch_attachments(msg_id: str, headers: dict) -> list[dict]:
    """
    Returns a list of dicts with keys: name, text.
    Step 1: fetch metadata list (id, name, @odata.type only — no binary).
    Step 2: fetch each fileAttachment individually to get contentBytes.
    This avoids a single huge response that truncates on large attachments.
    """
    base = f"https://graph.microsoft.com/v1.0/users/{SHARED_MAILBOX}/messages/{msg_id}/attachments"

    # Step 1 — metadata only (id and name are base-type properties, always selectable)
    meta_resp = requests.get(f"{base}?$select=id,name", headers=headers).json()
    if "error" in meta_resp:
        print(f"\n  [attachment list error: {meta_resp['error'].get('message')}]")
        return []

    attachments = []
    for att in meta_resp.get("value", []):
        if att.get("@odata.type") != "#microsoft.graph.fileAttachment":
            continue

        att_id = att["id"]
        name = att.get("name", "unknown")

        # Step 2 — fetch full attachment by ID to get contentBytes
        full_resp = requests.get(f"{base}/{att_id}", headers=headers).json()
        if "error" in full_resp:
            attachments.append({"name": name, "text": f"[Attachment: fetch failed — {full_resp['error'].get('message')}]"})
            continue

        content_b64 = full_resp.get("contentBytes", "")
        if not content_b64:
            attachments.append({"name": name, "text": "[Attachment: empty content]"})
            continue

        text = _sanitize(_attachment_text(name, content_b64))
        attachments.append({"name": name, "text": text})

    return attachments


# ---------------------------------------------------------------------------
# Sanitize text for Excel (strip illegal XML control characters)
# ---------------------------------------------------------------------------

# openpyxl rejects any character that is illegal in XML 1.0:
# all control chars except \t (0x09), \n (0x0A), \r (0x0D)
_ILLEGAL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

def _sanitize(text: str) -> str:
    return _ILLEGAL_CHARS_RE.sub("", text)


# ---------------------------------------------------------------------------
# Format a single email into a readable string
# ---------------------------------------------------------------------------

def _format_email(msg: dict, attachments: list[dict]) -> str:
    from_addr = msg.get("from", {}).get("emailAddress", {})
    sender = f"{from_addr.get('name', '')} <{from_addr.get('address', '')}>".strip()
    to_list = ", ".join(
        f"{r.get('name', '')} <{r.get('address', '')}>".strip()
        for r in msg.get("toRecipients", [])
    )
    body = _sanitize(msg.get("body", {}).get("content", "").strip())

    lines = [
        f"Subject: {msg.get('subject', '')}",
        f"From:    {sender}",
        f"To:      {to_list}",
        f"Date:    {msg.get('receivedDateTime', '')}",
        "",
        body,
    ]

    for att in attachments:
        lines += [
            "",
            f"--- Attachment: {att['name']} ---",
            att["text"],
        ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main export function
# ---------------------------------------------------------------------------

def export_to_excel(month: int, year: int):
    """
    Fetch all original emails for the given month/year and write them to an
    Excel file named cx_emails_MM_YYYY.xlsx.

    Args:
        month: Month number (1–12)
        year:  Four-digit year, e.g. 2026
    """
    import calendar

    date_from = f"{year}-{month:02d}-01"
    next_month = month % 12 + 1
    next_year = year + 1 if month == 12 else year
    date_to = f"{next_year}-{next_month:02d}-01"
    output_path = f"cx_emails_{month:02d}_{year}.xlsx"

    token = _authenticate()
    auth_headers = {"Authorization": f"Bearer {token}"}
    msg_headers = {**auth_headers, "Prefer": 'outlook.body-content-type="text"'}

    folder_id = _find_folder(auth_headers, SUBFOLDER_NAME)
    if not folder_id:
        raise Exception(f"Folder '{SUBFOLDER_NAME}' not found")

    date_filter = (
        f"&$filter=receivedDateTime ge {date_from}T00:00:00Z"
        f" and receivedDateTime lt {date_to}T00:00:00Z"
    )

    url = (
        f"https://graph.microsoft.com/v1.0/users/{SHARED_MAILBOX}"
        f"/mailFolders/{folder_id}/messages"
        f"?$top=999&$select={SELECT}&$orderby=receivedDateTime desc{date_filter}"
    )

    rows = []
    total_fetched = 0
    total_originals = 0

    print("Fetching emails", end="", flush=True)

    while url:
        resp = requests.get(url, headers=msg_headers).json()
        page = resp.get("value", [])
        total_fetched += len(page)

        for msg in page:
            if not _is_original(msg):
                print("-", end="", flush=True)
                continue

            total_originals += 1
            print(".", end="", flush=True)

            attachments = []
            if msg.get("hasAttachments"):
                attachments = _fetch_attachments(msg["id"], auth_headers)

            email_text = _format_email(msg, attachments)
            rows.append({
                "original_email": email_text,
                "ai_response": "",
                "intent": "",
                "feedback": "",
            })

        url = resp.get("@odata.nextLink")

    print(f"\nFetched {total_originals} original emails from {total_fetched} total.")

    df = pd.DataFrame(rows, columns=["original_email", "ai_response", "intent", "feedback"])

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Emails")

        # Auto-size columns and wrap text in original_email
        ws = writer.sheets["Emails"]
        from openpyxl.styles import Alignment

        for col_cells in ws.iter_cols():
            col_letter = col_cells[0].column_letter
            header = col_cells[0].value or ""
            if header == "original_email":
                ws.column_dimensions[col_letter].width = 80
                for cell in col_cells[1:]:
                    cell.alignment = Alignment(wrap_text=True, vertical="top")
            else:
                ws.column_dimensions[col_letter].width = 30
                for cell in col_cells[1:]:
                    cell.alignment = Alignment(vertical="top")

    print(f"Saved → {output_path}")
    return output_path


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import datetime

    parser = argparse.ArgumentParser(description="Export original emails to Excel")
    parser.add_argument("--month", type=int, default=datetime.date.today().month,
                        help="Month number (1–12), defaults to current month")
    parser.add_argument("--year", type=int, default=datetime.date.today().year,
                        help="Four-digit year, defaults to current year")
    args = parser.parse_args()

    export_to_excel(month=args.month, year=args.year)
