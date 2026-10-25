"""
MagicalBoundries lead intake + CRM + WhatsApp dispatch service.

Required deployment:
  pip install fastapi uvicorn requests python-multipart

Run:
  uvicorn main:app --host 0.0.0.0 --port $PORT

Important:
- Use a Render Persistent Disk mounted at /data, or set DB_FILE to a persistent database path.
- WhatsApp Cloud API only sends reliably when the recipient is eligible and the message type/template is permitted.
- Configure an approved template that matches your Meta WhatsApp Manager exactly. This code never pretends an HTTP 200 means delivery.
"""

import html
import json
import logging
import os
import re
import smtplib
import sqlite3
import time
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Any, Dict, Iterable, Optional, Tuple

import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, PlainTextResponse, JSONResponse

APP_NAME = "MagicalBoundries Lead CRM"
BASE_URL = os.getenv("PUBLIC_BASE_URL", "https://real-estate-dy59.onrender.com").rstrip("/")
OWNER_WHATSAPP = os.getenv("OWNER_WHATSAPP", "918851692559")  # E.164 digits; India country code included
OWNER_EMAIL = os.getenv("OWNER_EMAIL", "info@magicalboundries.com")
GRAPH_VERSION = os.getenv("META_GRAPH_VERSION", "v23.0")
DB_FILE = os.getenv("DB_FILE") or ("/data/leads.db" if os.path.isdir("/data") else "leads.db")
REQUEST_TIMEOUT = float(os.getenv("OUTBOUND_TIMEOUT_SECONDS", "12"))
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "")

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger(APP_NAME)

app = FastAPI(title=APP_NAME, version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[x.strip() for x in os.getenv("CORS_ORIGINS", "*").split(",") if x.strip()],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# Keys are case-insensitive fragments searched across project/campaign/agent metadata.
# Override/add mappings with PROJECT_BROCHURES_JSON in Render Environment.
# No fabricated PDF URLs: populate PROJECT_BROCHURES_JSON with real, public HTTPS PDF links.
# Each key is a phrase found in a project/campaign name; each value is its actual brochure URL.
DEFAULT_BROCHURES = {}
try:
    PROJECT_BROCHURES = {**DEFAULT_BROCHURES, **json.loads(os.getenv("PROJECT_BROCHURES_JSON", "{}"))}
except Exception:
    log.exception("PROJECT_BROCHURES_JSON is invalid JSON; using built-in brochure mappings.")
    PROJECT_BROCHURES = DEFAULT_BROCHURES

# WhatsApp template configuration. Values must exactly match the approved Meta template.
BROCHURE_TEMPLATE_NAME = os.getenv("WHATSAPP_TEMPLATE_NAME", "brochure_dispatch_v3").strip()
BROCHURE_TEMPLATE_LANGUAGE = os.getenv("WHATSAPP_TEMPLATE_LANGUAGE", "en_US").strip()
OWNER_TEMPLATE_NAME = os.getenv("OWNER_WHATSAPP_TEMPLATE_NAME", "").strip()
OWNER_TEMPLATE_LANGUAGE = os.getenv("OWNER_WHATSAPP_TEMPLATE_LANGUAGE", "en_US").strip()
BROCHURE_TEMPLATE_HEADER_TYPE = os.getenv("WHATSAPP_TEMPLATE_HEADER_TYPE", "document").strip().lower()

# Optional JSON defining template body parameters in the exact order expected by Meta.
# Example ONLY if the approved template has 3 body variables:
# BROCHURE_TEMPLATE_BODY_PARAMS_JSON=["customer_name","project","brochure_url"]
try:
    BROCHURE_TEMPLATE_BODY_PARAMS = json.loads(os.getenv("BROCHURE_TEMPLATE_BODY_PARAMS_JSON", "[]"))
except Exception:
    BROCHURE_TEMPLATE_BODY_PARAMS = []
try:
    OWNER_TEMPLATE_BODY_PARAMS = json.loads(os.getenv("OWNER_TEMPLATE_BODY_PARAMS_JSON", "[]"))
except Exception:
    OWNER_TEMPLATE_BODY_PARAMS = []

PHONE_KEYS = {
    "phone", "phone_number", "mobile", "mobile_number", "whatsapp", "whatsapp_number",
    "customer_phone", "customer_mobile", "callee_phone", "callee_number", "callee", "contact_number",
    "to_number", "recipient_phone", "recipient", "lead_phone", "caller_number", "caller_phone",
    "caller", "from_number", "from", "to", "destination_number", "customerNumber",
    "phoneNumber", "phoneNumberE164", "contact_phone", "contact_mobile", "lead_mobile",
}
NAME_KEYS = {"name", "contact_name", "customer_name", "lead_name", "full_name", "contactName"}
EMAIL_KEYS = {"email", "email_address", "customer_email", "lead_email"}
PROJECT_KEYS = {
    "project", "project_name", "property", "property_name", "property_type",
    "campaign", "campaign_name", "campaign_id", "agent_name", "agent", "assistant_name",
    "campaignName", "projectName", "listing_name", "product_name",
}
SUMMARY_KEYS = {"summary", "ai_summary", "call_summary", "transcript_summary", "notes", "description"}
STATUS_KEYS = {"status", "call_status", "outcome", "disposition", "result", "event", "event_type", "call_result"}
EVENT_ID_KEYS = {"event_id", "webhook_id", "call_id", "conversation_id", "session_id", "id"}
PHONE_VALID_RE = re.compile(r"^\d{8,15}$")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def db_connect() -> sqlite3.Connection:
    parent = os.path.dirname(os.path.abspath(DB_FILE))
    os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(DB_FILE, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=20000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    with db_connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL DEFAULT 'Unknown',
                phone TEXT NOT NULL DEFAULT '',
                email TEXT NOT NULL DEFAULT '',
                project TEXT NOT NULL DEFAULT 'Unidentified project',
                summary TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT 'Unknown',
                created_at TEXT NOT NULL,
                outcome TEXT NOT NULL DEFAULT 'Captured',
                call_status TEXT NOT NULL DEFAULT '',
                event_id TEXT,
                raw_payload TEXT NOT NULL DEFAULT '{}',
                brochure_url TEXT NOT NULL DEFAULT '',
                owner_whatsapp_status TEXT NOT NULL DEFAULT 'not_attempted',
                customer_whatsapp_status TEXT NOT NULL DEFAULT 'not_attempted',
                email_status TEXT NOT NULL DEFAULT 'not_attempted'
            )
        """)
        # Safe, additive migration for databases created by earlier versions.
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(leads)").fetchall()}
        additions = {
            "call_status": "TEXT NOT NULL DEFAULT ''",
            "event_id": "TEXT",
            "raw_payload": "TEXT NOT NULL DEFAULT '{}'",
            "brochure_url": "TEXT NOT NULL DEFAULT ''",
            "owner_whatsapp_status": "TEXT NOT NULL DEFAULT 'not_attempted'",
            "customer_whatsapp_status": "TEXT NOT NULL DEFAULT 'not_attempted'",
            "email_status": "TEXT NOT NULL DEFAULT 'not_attempted'",
        }
        for col, ddl in additions.items():
            if col not in existing:
                conn.execute(f"ALTER TABLE leads ADD COLUMN {col} {ddl}")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_leads_event_id ON leads(event_id) WHERE event_id IS NOT NULL AND event_id != ''")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_leads_created_at ON leads(created_at)")
    log.info("Database ready at %s", DB_FILE)


init_db()


def import_legacy_local_database() -> None:
    """One-time best-effort import from an old local leads.db into a mounted DB_FILE."""
    target = os.path.abspath(DB_FILE)
    legacy = os.path.abspath("leads.db")
    if target == legacy or not os.path.isfile(legacy):
        return
    try:
        with db_connect() as target_conn:
            target_conn.execute("CREATE TABLE IF NOT EXISTS migration_markers (marker TEXT PRIMARY KEY, migrated_at TEXT NOT NULL)")
            if target_conn.execute("SELECT 1 FROM migration_markers WHERE marker='legacy_local_leads_db_v1'").fetchone():
                return
            source_conn = sqlite3.connect(f"file:{legacy}?mode=ro", uri=True, timeout=10)
            source_conn.row_factory = sqlite3.Row
            try:
                tables = {r["name"] for r in source_conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if "leads" not in tables:
                    return
                source_columns = {r["name"] for r in source_conn.execute("PRAGMA table_info(leads)")}
                target_columns = {r["name"] for r in target_conn.execute("PRAGMA table_info(leads)")}
                common = [c for c in ("id", "name", "phone", "email", "project", "summary", "source", "created_at", "outcome", "call_status", "event_id", "raw_payload", "brochure_url", "owner_whatsapp_status", "customer_whatsapp_status", "email_status") if c in source_columns and c in target_columns]
                if common:
                    rows = source_conn.execute("SELECT " + ",".join('"' + c + '"' for c in common) + " FROM leads ORDER BY id").fetchall()
                    for row in rows:
                        values = {c: row[c] for c in common}
                        # Fill columns introduced by this version with safe defaults.
                        values.setdefault("name", "Unknown")
                        values.setdefault("phone", "")
                        values.setdefault("email", "")
                        values.setdefault("project", "Unidentified project")
                        values.setdefault("summary", "")
                        values.setdefault("source", "Legacy import")
                        values.setdefault("created_at", now_iso())
                        values.setdefault("outcome", "Imported from previous database")
                        values.setdefault("call_status", "")
                        values.setdefault("event_id", None)
                        values.setdefault("raw_payload", "{}")
                        values.setdefault("brochure_url", "")
                        values.setdefault("owner_whatsapp_status", "legacy/unknown")
                        values.setdefault("customer_whatsapp_status", "legacy/unknown")
                        values.setdefault("email_status", "legacy/unknown")
                        cols = [c for c in ("id", "name", "phone", "email", "project", "summary", "source", "created_at", "outcome", "call_status", "event_id", "raw_payload", "brochure_url", "owner_whatsapp_status", "customer_whatsapp_status", "email_status") if c in target_columns]
                        target_conn.execute("INSERT OR IGNORE INTO leads (" + ",".join(cols) + ") VALUES (" + ",".join("?" for _ in cols) + ")", [values[c] for c in cols])
                target_conn.execute("INSERT INTO migration_markers(marker, migrated_at) VALUES (?, ?)", ("legacy_local_leads_db_v1", now_iso()))
                log.info("Legacy database import completed from %s", legacy)
            finally:
                source_conn.close()
    except Exception:
        log.exception("Legacy leads.db import failed; original source database was not modified")


import_legacy_local_database()


def norm_key(key: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def walk_items(obj: Any, depth: int = 0) -> Iterable[Tuple[str, Any]]:
    if depth > 12:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield str(k), v
            if isinstance(v, (dict, list)):
                yield from walk_items(v, depth + 1)
    elif isinstance(obj, list):
        for item in obj:
            if isinstance(item, (dict, list)):
                yield from walk_items(item, depth + 1)


def find_value(payload: dict, keys: set) -> Any:
    wanted = {norm_key(k) for k in keys}
    # Prefer top-level values first, then nested objects.
    for k, v in payload.items():
        if norm_key(k) in wanted and v not in (None, "", [], {}):
            if isinstance(v, (str, int, float)):
                return v
            if isinstance(v, dict):
                for nested_key in ("value", "number", "phone", "name", "text", "label"):
                    if nested_key in v and v[nested_key] not in (None, ""):
                        return v[nested_key]
    for k, v in walk_items(payload):
        if norm_key(k) in wanted and v not in (None, "", [], {}):
            if isinstance(v, (str, int, float)):
                return v
            if isinstance(v, dict):
                for nested_key in ("value", "number", "phone", "name", "text", "label"):
                    if nested_key in v and v[nested_key] not in (None, ""):
                        return v[nested_key]
    return None


def clean_phone(value: Any) -> str:
    if value is None:
        return ""
    # Handle common "tel:+91..." and number objects.
    raw = str(value).strip()
    if raw.lower().startswith("tel:"):
        raw = raw[4:]
    digits = "".join(ch for ch in raw if ch.isdigit())
    # Indian local ten-digit numbers are normalized to E.164.
    if len(digits) == 10:
        digits = "91" + digits
    return digits if PHONE_VALID_RE.fullmatch(digits) else ""


def find_customer_phone(payload: dict, source: str = "") -> str:
    """Prefer the actual customer/callee/caller field over agent/system phone fields."""
    all_text = (source + " " + json.dumps(payload, ensure_ascii=False, default=str)).lower()
    incoming = any(x in all_text for x in ("incoming", "inbound"))
    outgoing = any(x in all_text for x in ("outgoing", "outbound"))
    if incoming:
        priority = ("caller_phone", "caller_number", "caller", "from_number", "from", "customer_phone", "customer_mobile", "lead_phone", "phone_number", "mobile_number", "whatsapp_number", "phone")
    elif outgoing:
        priority = ("callee_phone", "callee_number", "callee", "to_number", "recipient_phone", "customer_phone", "customer_mobile", "lead_phone", "phone_number", "mobile_number", "whatsapp_number", "phone")
    else:
        priority = ("customer_phone", "customer_mobile", "lead_phone", "callee_phone", "caller_phone", "phone_number", "mobile_number", "whatsapp_number", "phone", "to_number", "from_number")
    # Exact preferred key order, including nested payload objects.
    items = list(walk_items(payload))
    for preferred in priority:
        wanted = norm_key(preferred)
        for key, value in items:
            if norm_key(key) == wanted and value not in (None, "", [], {}):
                if isinstance(value, dict):
                    value = next((value[k] for k in ("value", "number", "phone", "text") if k in value and value[k]), "")
                candidate = clean_phone(value)
                if candidate:
                    return candidate
    # Fallback to any known phone field, but never invent a number.
    return clean_phone(find_value(payload, PHONE_KEYS))


def flatten_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value).strip()
    if isinstance(value, list):
        return " | ".join(filter(None, (flatten_text(x) for x in value)))[:3000]
    if isinstance(value, dict):
        preferred = []
        for k, v in value.items():
            if isinstance(v, (str, int, float, bool)) and v not in ("", None):
                preferred.append(f"{k}: {v}")
        if preferred:
            return " | ".join(preferred)[:3000]
        return json.dumps(value, ensure_ascii=False)[:3000]
    return str(value)[:3000]


def detect_project(payload: dict) -> str:
    """Infer project from campaign/agent/metadata anywhere in the VYORA payload."""
    explicit = find_value(payload, PROJECT_KEYS)
    all_text = (flatten_text(explicit) + " " + json.dumps(payload, ensure_ascii=False, default=str)).lower()
    for key in sorted(PROJECT_BROCHURES.keys(), key=len, reverse=True):
        if key.lower() != "default" and key.lower() in all_text:
            return key
    if explicit:
        return flatten_text(explicit)[:200]
    # Retain campaign metadata in the CRM rather than inventing a project.
    for key, value in walk_items(payload):
        if norm_key(key) in {"campaign", "campaignname", "agentname", "projectname", "propertyname", "assistantname"}:
            text_value = flatten_text(value)
            if text_value:
                return text_value[:200]
    return "Unidentified project"


def get_brochure_link(project: str) -> str:
    low = (project or "").lower()
    for key in sorted(PROJECT_BROCHURES.keys(), key=len, reverse=True):
        if key.lower() in low:
            return str(PROJECT_BROCHURES[key])
    # Scan exact raw project labels are handled in detect_project; no fake link is returned.
    return os.getenv("DEFAULT_BROCHURE_URL", "").strip()


def detect_call_status(payload: dict) -> str:
    raw = flatten_text(find_value(payload, STATUS_KEYS))
    if not raw:
        raw = json.dumps(payload, ensure_ascii=False, default=str)
    low = raw.lower()
    if any(x in low for x in ("voicemail", "voice_mail", "left message", "answering machine")):
        return "voicemail"
    if any(x in low for x in ("screening", "screened", "call screening", "unknown caller")):
        return "screening"
    if any(x in low for x in ("failed", "failure", "no_answer", "no answer", "busy", "unreachable", "not_connected", "not connected", "error")):
        return "failed"
    if any(x in low for x in ("completed", "answered", "connected", "success", "ended")):
        return "completed"
    return raw[:100] or "received"


def detect_source(payload: dict, path: str, default_source: str = "") -> str:
    source = flatten_text(find_value(payload, {"source", "lead_source", "channel", "direction", "call_direction"}))
    low = (source + " " + path + " " + json.dumps(payload, ensure_ascii=False, default=str)).lower()
    if "website" in low or "chat" in low or "widget" in low:
        return "Website AI Chat"
    if "vyora" in low or "campaign" in low or "call" in low or "voicemail" in low or "screening" in low:
        direction = "Incoming" if any(x in low for x in ("incoming", "inbound")) else ("Outgoing" if any(x in low for x in ("outgoing", "outbound")) else "")
        return f"VYORA {direction} Call".strip()
    return source or default_source or f"Webhook {path}"


def get_event_id(payload: dict) -> str:
    value = find_value(payload, EVENT_ID_KEYS)
    if value is None:
        # Do not deduplicate by phone: repeat enquiries/calls must remain separate.
        return ""
    return str(value)[:250]


def get_nested_summary(payload: dict) -> str:
    val = find_value(payload, SUMMARY_KEYS)
    if val:
        return flatten_text(val)
    # Preserve status, direction, campaign metadata in CRM for diagnosis.
    return json.dumps(payload, ensure_ascii=False, default=str)[:3000]


def meta_post(payload: dict) -> Tuple[bool, str]:
    token = os.getenv("META_ACCESS_TOKEN", "").strip()
    phone_number_id = os.getenv("META_PHONE_NUMBER_ID", "").strip()
    if not token or not phone_number_id:
        return False, "missing META_ACCESS_TOKEN or META_PHONE_NUMBER_ID"
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{phone_number_id}/messages"
    try:
        response = requests.post(
            url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
        try:
            body = response.json()
        except ValueError:
            body = {"raw": response.text[:1000]}
        if response.ok and body.get("messages"):
            message_id = body["messages"][0].get("id", "")
            log.info("Meta accepted message id=%s recipient=%s", message_id, payload.get("to"))
            # "accepted" is intentional; delivery is confirmed by Meta status webhook.
            return True, f"accepted:{message_id}"
        log.error("Meta WhatsApp API rejected request status=%s body=%s", response.status_code, body)
        return False, f"http_{response.status_code}:{json.dumps(body, ensure_ascii=False)[:900]}"
    except requests.RequestException as exc:
        log.exception("Meta WhatsApp request failed")
        return False, f"request_error:{exc}"


def template_components(params: list) -> list:
    if not params:
        return []
    return [{"type": "body", "parameters": [{"type": "text", "text": str(x)[:1024]} for x in params]}]


def send_template(
    phone: str, template_name: str, language: str, params: list,
    document_url: str = "", document_filename: str = "brochure.pdf",
    header_type: str = "",
) -> Tuple[bool, str]:
    if not template_name:
        return False, "template name not configured"
    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "template",
        "template": {"name": template_name, "language": {"code": language}},
    }
    components = template_components(params)
    if header_type == "document":
        if not document_url:
            return False, "document header selected but no public brochure URL is mapped"
        components.insert(0, {"type": "header", "parameters": [{
            "type": "document", "document": {"link": document_url, "filename": document_filename[:200]}
        }]})
    if components:
        payload["template"]["components"] = components
    return meta_post(payload)


def send_owner_whatsapp(text: str) -> Tuple[bool, str]:
    owner = clean_phone(OWNER_WHATSAPP)
    if not owner:
        return False, "OWNER_WHATSAPP is invalid"
    # A template is required outside the 24-hour customer-service window.
    # If configured, use it; otherwise a text message is attempted and Meta's exact response is logged.
    if OWNER_TEMPLATE_NAME:
        params = [text] if OWNER_TEMPLATE_BODY_PARAMS == ["lead_message"] else [
            text if str(x) == "lead_message" else str(x) for x in OWNER_TEMPLATE_BODY_PARAMS
        ]
        return send_template(owner, OWNER_TEMPLATE_NAME, OWNER_TEMPLATE_LANGUAGE, params, header_type="")
    return meta_post({
        "messaging_product": "whatsapp",
        "to": owner,
        "type": "text",
        "text": {"preview_url": False, "body": text[:4000]},
    })


def send_customer_brochure(phone: str, name: str, project: str, brochure_url: str) -> Tuple[bool, str]:
    if not phone:
        return False, "no valid customer phone in webhook payload"
    if not brochure_url:
        return False, f"no brochure URL mapped for project '{project}'; configure PROJECT_BROCHURES_JSON"
    # The approved template must have body variables matching BROCHURE_TEMPLATE_BODY_PARAMS_JSON.
    # Supported placeholders: customer_name, project, brochure_url, phone.
    values = {"customer_name": name, "project": project, "brochure_url": brochure_url, "phone": phone}
    params = [values.get(str(item), str(item)) for item in BROCHURE_TEMPLATE_BODY_PARAMS]
    header_type = BROCHURE_TEMPLATE_HEADER_TYPE if BROCHURE_TEMPLATE_HEADER_TYPE in {"document", ""} else ""
    filename = re.sub(r"[^A-Za-z0-9._-]+", "_", (project or "property_brochure"))[:100] + ".pdf"
    return send_template(
        phone, BROCHURE_TEMPLATE_NAME, BROCHURE_TEMPLATE_LANGUAGE, params,
        document_url=brochure_url, document_filename=filename, header_type=header_type,
    )


def send_email(subject: str, body: str) -> Tuple[bool, str]:
    host = os.getenv("SMTP_HOST", "smtp.gmail.com").strip()
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER", "").strip()
    password = os.getenv("SMTP_PASS", "").strip()
    if not user or not password:
        return False, "missing SMTP_USER or SMTP_PASS"
    message = EmailMessage()
    message["Subject"] = subject[:200]
    message["From"] = os.getenv("SMTP_FROM", user)
    message["To"] = OWNER_EMAIL
    message.set_content(body)
    try:
        with smtplib.SMTP(host, port, timeout=REQUEST_TIMEOUT) as server:
            server.starttls()
            server.login(user, password)
            server.send_message(message)
        return True, "sent"
    except Exception as exc:
        log.exception("Email send failed")
        return False, f"email_error:{exc}"


def save_lead(record: dict) -> Tuple[int, bool]:
    """Append-only insert. Repeated events are preserved unless the provider supplies the same event ID."""
    with db_connect() as conn:
        event_id = record.get("event_id") or None
        if event_id:
            existing = conn.execute("SELECT id FROM leads WHERE event_id=?", (event_id,)).fetchone()
            if existing:
                return int(existing["id"]), False
        cur = conn.execute("""
            INSERT INTO leads (
                name, phone, email, project, summary, source, created_at, outcome,
                call_status, event_id, raw_payload, brochure_url,
                owner_whatsapp_status, customer_whatsapp_status, email_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            record["name"], record["phone"], record["email"], record["project"],
            record["summary"], record["source"], record["created_at"], record["outcome"],
            record["call_status"], event_id, record["raw_payload"], record["brochure_url"],
            "pending", "pending", "pending",
        ))
        return int(cur.lastrowid), True


def update_delivery_status(lead_id: int, **fields: str) -> None:
    allowed = {"outcome", "owner_whatsapp_status", "customer_whatsapp_status", "email_status"}
    updates = [(k, v) for k, v in fields.items() if k in allowed]
    if not updates:
        return
    with db_connect() as conn:
        conn.execute(
            "UPDATE leads SET " + ", ".join(f"{k}=?" for k, _ in updates) + " WHERE id=?",
            [v for _, v in updates] + [lead_id],
        )


def process_lead(payload: dict, source: str) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("Webhook JSON must be an object")
    name = flatten_text(find_value(payload, NAME_KEYS)) or "Unknown"
    phone = find_customer_phone(payload, source)
    email = flatten_text(find_value(payload, EMAIL_KEYS))
    project = detect_project(payload)
    summary = get_nested_summary(payload)
    call_status = detect_call_status(payload)
    event_id = get_event_id(payload)
    brochure_url = get_brochure_link(project)
    resolved_source = detect_source(payload, source, source)

    record = {
        "name": name[:200],
        "phone": phone,
        "email": email[:250],
        "project": project[:250],
        "summary": summary[:3000],
        "source": resolved_source[:200],
        "created_at": now_iso(),
        "outcome": "Captured; dispatch pending",
        "call_status": call_status,
        "event_id": event_id,
        "raw_payload": json.dumps(payload, ensure_ascii=False, default=str)[:20000],
        "brochure_url": brochure_url,
    }
    lead_id, inserted = save_lead(record)
    if not inserted:
        log.info("Duplicate webhook event ignored for notifications event_id=%s lead_id=%s", event_id, lead_id)
        return {"status": "duplicate_event", "lead_id": lead_id}

    alert = (
        f"[New Lead #{lead_id}]\n"
        f"Source: {resolved_source}\n"
        f"Name: {name}\n"
        f"Phone: {phone or 'Not present in payload'}\n"
        f"Project/Campaign: {project}\n"
        f"Call status: {call_status}\n"
        f"Details: {summary[:1200]}"
    )

    # All channels are attempted independently; one failure does not stop the others.
    owner_ok, owner_result = send_owner_whatsapp(alert)
    email_ok, email_result = send_email(
        f"New MagicalBoundries lead #{lead_id}: {project}",
        alert + f"\n\nBrochure URL: {brochure_url or 'No mapped brochure'}\nEvent ID: {event_id or 'not provided'}",
    )
    customer_ok, customer_result = send_customer_brochure(phone, name, project, brochure_url)

    update_delivery_status(
        lead_id,
        owner_whatsapp_status=owner_result,
        email_status=email_result,
        customer_whatsapp_status=customer_result,
        outcome="Captured; owner_whatsapp=" + ("accepted" if owner_ok else "failed")
        + "; email=" + ("sent" if email_ok else "failed")
        + "; customer_whatsapp=" + ("accepted" if customer_ok else "failed"),
    )

    log.info(
        "Lead #%s stored source=%s phone_present=%s project=%s call_status=%s owner_wa=%s customer_wa=%s email=%s",
        lead_id, resolved_source, bool(phone), project, call_status, owner_result, customer_result, email_result
    )
    return {
        "status": "processed",
        "lead_id": lead_id,
        "inserted": True,
        "source": resolved_source,
        "project": project,
        "call_status": call_status,
        "phone_found": bool(phone),
        "brochure_mapped": bool(brochure_url),
        "owner_whatsapp": owner_result,
        "customer_whatsapp": customer_result,
        "email": email_result,
    }


def extract_meta_inbound(body: dict) -> list:
    """Convert inbound Meta WhatsApp messages into lead records."""
    output = []
    for entry in body.get("entry", []) if isinstance(body, dict) else []:
        for change in entry.get("changes", []) if isinstance(entry, dict) else []:
            value = change.get("value", {}) if isinstance(change, dict) else {}
            for msg in value.get("messages", []) if isinstance(value, dict) else []:
                sender = clean_phone(msg.get("from"))
                text = msg.get("text", {}).get("body", "") if isinstance(msg.get("text"), dict) else ""
                output.append({
                    "name": "WhatsApp inbound",
                    "phone": sender,
                    "project": "WhatsApp inbound enquiry",
                    "summary": f"Inbound WhatsApp message: {text}",
                    "source": "WhatsApp Inbound",
                    "event_id": msg.get("id", ""),
                })
    return output


@app.get("/health")
async def health():
    with db_connect() as conn:
        count = conn.execute("SELECT COUNT(*) AS n FROM leads").fetchone()["n"]
    return {"status": "ok", "database": DB_FILE, "lead_count": count, "time": now_iso()}


@app.get("/webhook")
async def verify_meta_webhook(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge", "")
    if mode == "subscribe" and VERIFY_TOKEN and token == VERIFY_TOKEN:
        return PlainTextResponse(challenge, status_code=200)
    raise HTTPException(status_code=403, detail="Webhook verification failed")


@app.post("/webhook")
async def receive_meta_webhook(request: Request):
    body = await request.json()
    messages = extract_meta_inbound(body)
    results = []
    for item in messages:
        # Incoming customer messages are stored. Don't automatically blast a brochure
        # unless a project is identified and a matching brochure is configured.
        results.append(process_lead(item, "WhatsApp Inbound"))
    # Meta also sends delivery/read status updates here; acknowledge them to avoid retries.
    log.info("Meta webhook received inbound_messages=%s", len(messages))
    return {"status": "received", "inbound_messages_saved": len(results)}


@app.post("/webhook/website-chat")
async def website_chat(request: Request):
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Expected JSON request body")
    result = process_lead(payload, "Website AI Chat")
    return JSONResponse(result)


@app.post("/webhook/vyora")
@app.post("/webhook/call-lead")
@app.post("/webhook/vyora/incoming")
@app.post("/webhook/vyora/outgoing")
async def vyora_call_webhook(request: Request):
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Expected JSON request body")
    # The endpoint processes all call outcomes, including completed, voicemail,
    # screening, no-answer, busy and failed, when VYORA sends the event to this URL.
    result = process_lead(payload, "VYORA Call")
    return JSONResponse(result)


@app.post("/webhook/test-lead")
async def test_lead(request: Request):
    # Protected diagnostic endpoint; configure TEST_WEBHOOK_KEY before using.
    key = os.getenv("TEST_WEBHOOK_KEY", "")
    if not key or request.headers.get("x-test-key", "") != key:
        raise HTTPException(status_code=403, detail="Test endpoint disabled or key invalid")
    payload = await request.json()
    result = process_lead(payload, "Manual Test")
    return JSONResponse(result)


@app.post("/{path:path}")
async def catch_all_post(path: str, request: Request):
    """
    Diagnostic compatibility route for old website endpoints.
    Only accepts JSON with identifiable lead fields; ignores arbitrary POST bodies.
    This cannot catch a request sent to a different server/domain.
    """
    if path.startswith(("docs", "openapi", "redoc")):
        raise HTTPException(status_code=404)
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=415, detail="Catch-all accepts JSON only")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="JSON body must be an object")
    has_phone = bool(find_value(payload, PHONE_KEYS))
    has_lead_data = bool(find_value(payload, NAME_KEYS) or find_value(payload, PROJECT_KEYS) or find_value(payload, SUMMARY_KEYS))
    if not (has_phone or has_lead_data):
        return {"status": "ignored", "path": path, "reason": "no recognizable lead fields"}
    result = process_lead(payload, f"Catch-all /{path}")
    return JSONResponse(result)


@app.get("/", response_class=HTMLResponse)
@app.get("/leads", response_class=HTMLResponse)
async def dashboard(request: Request):
    search = request.query_params.get("q", "").strip()[:200]
    with db_connect() as conn:
        if search:
            pattern = f"%{search}%"
            rows = conn.execute("""
                SELECT id, created_at, name, phone, email, project, source, call_status,
                       summary, outcome, owner_whatsapp_status, customer_whatsapp_status,
                       email_status, brochure_url
                FROM leads
                WHERE name LIKE ? OR phone LIKE ? OR email LIKE ? OR project LIKE ? OR source LIKE ? OR summary LIKE ?
                ORDER BY id DESC
            """, (pattern, pattern, pattern, pattern, pattern, pattern)).fetchall()
        else:
            rows = conn.execute("""
                SELECT id, created_at, name, phone, email, project, source, call_status,
                       summary, outcome, owner_whatsapp_status, customer_whatsapp_status,
                       email_status, brochure_url
                FROM leads ORDER BY id DESC
            """).fetchall()
    esc = lambda x: html.escape("" if x is None else str(x))
    trs = []
    for r in rows:
        trs.append(
            "<tr>"
            f"<td>{r['id']}</td><td>{esc(r['created_at'])}</td><td>{esc(r['name'])}</td>"
            f"<td>{esc(r['phone'])}</td><td>{esc(r['email'])}</td><td>{esc(r['project'])}</td>"
            f"<td>{esc(r['source'])}</td><td>{esc(r['call_status'])}</td>"
            f"<td>{esc(r['summary'])}</td><td>{esc(r['outcome'])}</td>"
            f"<td>{esc(r['owner_whatsapp_status'])}</td><td>{esc(r['customer_whatsapp_status'])}</td>"
            f"<td>{esc(r['email_status'])}</td>"
            f"<td>{('<a href=\"' + esc(r['brochure_url']) + '\" target=\"_blank\" rel=\"noopener\">Brochure</a>') if r['brochure_url'] else ''}</td>"
            "</tr>"
        )
    table_rows = "".join(trs) or '<tr><td colspan="14">No leads captured yet.</td></tr>'
    return HTMLResponse(f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>MagicalBoundries CRM</title>
<style>
body{{font-family:Arial,sans-serif;margin:20px;background:#f4f7fb;color:#172033}}
h1{{margin-bottom:4px}} .sub{{color:#526078;margin-bottom:18px}}
form{{margin:14px 0}} input{{padding:10px;width:min(420px,70vw);border:1px solid #ccd3df;border-radius:6px}}
button{{padding:10px 14px;border:0;border-radius:6px;background:#173f73;color:white}}
.stats{{margin:10px 0;color:#526078}} .wrap{{overflow:auto;background:white;border:1px solid #dbe1ea;border-radius:8px}}
table{{border-collapse:collapse;width:100%;min-width:1600px;font-size:13px}}
th{{position:sticky;top:0;background:#eaf0f8;text-align:left}}
td,th{{padding:9px 10px;border-bottom:1px solid #e6eaf0;vertical-align:top;max-width:360px;overflow-wrap:anywhere}}
tr:hover{{background:#f8fbff}} a{{color:#075da8}}
</style></head><body>
<h1>MagicalBoundries Lead CRM</h1>
<div class="sub">Append-only lead register · Newest leads first · Refreshing this page does not delete records</div>
<form method="get" action="/leads"><input name="q" value="{esc(search)}" placeholder="Search name, phone, project, source or notes"><button type="submit">Search</button> <a href="/leads">Clear</a></form>
<div class="stats">Showing {len(rows)} matching lead record(s). Health: <a href="/health">/health</a> · CSV export: <a href="/leads.csv">/leads.csv</a></div>
<div class="wrap"><table><thead><tr>
<th>ID</th><th>Created UTC</th><th>Name</th><th>Phone</th><th>Email</th><th>Project / Campaign</th>
<th>Source</th><th>Call status</th><th>Summary / payload details</th><th>Outcome</th>
<th>Owner WhatsApp result</th><th>Customer WhatsApp result</th><th>Email result</th><th>Brochure</th>
</tr></thead><tbody>{table_rows}</tbody></table></div>
</body></html>""")


@app.get("/leads.csv")
async def export_csv():
    import csv
    import io
    from fastapi.responses import StreamingResponse
    with db_connect() as conn:
        rows = conn.execute("SELECT * FROM leads ORDER BY id DESC").fetchall()
        columns = [x["name"] for x in conn.execute("PRAGMA table_info(leads)").fetchall()]
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(columns)
    for row in rows:
        writer.writerow([row[col] for col in columns])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="magicalboundries_leads.csv"'},
    )
