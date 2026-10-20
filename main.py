import os
import sqlite3
import smtplib
from email.message import EmailMessage
from typing import Optional, Any
from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import requests

app = FastAPI(title="Native Real Estate Multi-Project CRM & WhatsApp Gateway")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_FILE = "native_crm_leads.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT,
            contact_name TEXT,
            tier TEXT,
            outcome TEXT,
            interest_confirmed TEXT,
            ai_summary TEXT,
            recording_url TEXT,
            called_at TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

init_db()

PROJECT_BROCHURES = {
    "residential": "https://real-estate-dy59.onrender.com/brochures/residential-portfolio.pdf",
    "commercial": "https://real-estate-dy59.onrender.com/brochures/commercial-portfolio.pdf",
    "industrial": "https://real-estate-dy59.onrender.com/brochures/industrial-portfolio.pdf",
    "m3m": "https://real-estate-dy59.onrender.com/brochures/m3m-commercial.pdf",
    "amstoria": "https://real-estate-dy59.onrender.com/brochures/amstoria-102.pdf",
    "default": "https://real-estate-dy59.onrender.com/brochures/magicalboundries-master-portfolio.pdf"
}

def get_brochure_link(text_context: str) -> str:
    lower = text_context.lower()
    for key, link in PROJECT_BROCHURES.items():
        if key in lower:
            return link
    return PROJECT_BROCHURES["default"]

def clean_phone(raw_phone: str) -> str:
    digits = "".join([c for c in str(raw_phone) if c.isdigit()])
    if len(digits) == 10:
        return "91" + digits
    return digits

def clean_transcript(raw_summary: Any) -> str:
    if not raw_summary:
        return "Call Completed Successfully - Brochure Dispatched"
    summary_str = str(raw_summary)
    if "[" in summary_str and "]" in summary_str and "timestamp" in summary_str:
        return "Voice Call Completed - Visit Scheduled & Brochure Triggered"
    return summary_str

def forward_to_owner_whatsapp(notification_text: str):
    owner_phone = "918851692559"
    phone_number_id = os.getenv("META_PHONE_NUMBER_ID")
    access_token = os.getenv("META_ACCESS_TOKEN")
    
    if not phone_number_id or not access_token:
        return

    url = f"https://graph.facebook.com/v17.0/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": owner_phone,
        "type": "text",
        "text": {"body": notification_text}
    }
    try:
        requests.post(url, json=payload, headers=headers)
    except Exception as e:
        print(f"[Error forwarding to owner]: {e}")

def send_email_notification(subject: str, content: str):
    recipient = "info@magicalboundries.com"
    smtp_server = os.getenv("SMTP_SERVER")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")

    if not smtp_server or not smtp_user or not smtp_password:
        return

    try:
        msg = EmailMessage()
        msg.set_content(content)
        msg['Subject'] = subject
        msg['From'] = smtp_user
        msg['To'] = recipient

        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(msg)
    except Exception as e:
        print(f"[Error sending email]: {e}")

def send_free_meta_whatsapp(phone: str, contact_name: str, project_context: str):
    phone_number_id = os.getenv("META_PHONE_NUMBER_ID")
    access_token = os.getenv("META_ACCESS_TOKEN")
    
    formatted_phone = clean_phone(phone)
    brochure_url = get_brochure_link(project_context)

    if not phone_number_id or not access_token:
        print(f"[WhatsApp Mock] Credentials missing. Target: {formatted_phone} | Link: {brochure_url}")
        return

    url = f"https://graph.facebook.com/v17.0/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "messaging_product": "whatsapp",
        "to": formatted_phone,
        "type": "template",
        "template": {
            "name": "brochure_dispatch_v3",
            "language": { "code": "en" },
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": contact_name if contact_name.strip() else "Valued Client"},
                        {"type": "text", "text": brochure_url}
                    ]
                }
            ]
        }
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        print("--- META WHATSAPP API RESPONSE ---")
        print(f"Status Code: {response.status_code}")
        print(f"Response Body: {response.text}")
        print("---------------------------------")
    except Exception as e:
        print(f"[Error] Failed to send WhatsApp template: {e}")

@app.get("/")
def read_root():
    return {"status": "online", "system": "MagicalBoundries CRM & WhatsApp Gateway is active"}

@app.post("/webhook/website-chat")
async def receive_website_chat_webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        body = await request.json()
    except Exception:
        body = {}

    phone = clean_phone(body.get("phone", "910000000000"))
    contact_name = body.get("contact_name", "Valued Client").strip()
    if not contact_name:
        contact_name = "Valued Client"
        
    property_type = body.get("property_type", "Residential / Commercial / Industrial")
    raw_summary = body.get("ai_summary", "")
    
    clean_sum = clean_transcript(raw_summary)
    full_summary = f"[🌐 Website Chatbot Lead (www.magicalboundaries.com)] {clean_sum}"

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO leads (phone, contact_name, tier, outcome, interest_confirmed, ai_summary, recording_url, called_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (phone, contact_name, "Tier 1: Hot Prospect", "Visit Scheduled", "Yes", full_summary, "", ""))
    conn.commit()
    conn.close()

    background_tasks.add_task(send_free_meta_whatsapp, phone, contact_name, property_type + " " + str(raw_summary))
    forward_to_owner_whatsapp(f"🚨 [New Website Lead]\nName: {contact_name}\nPhone: {phone}\nDetails: {clean_sum}")
    send_email_notification(f"New Website Lead: {contact_name} ({phone})", f"Name: {contact_name}\nPhone: {phone}\nSummary: {clean_sum}")

    return {"status": "success", "message": "Website lead stored and brochure WhatsApp dispatched"}

@app.post("/webhook/ai-caller")
async def receive_ai_call_webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        body = await request.json()
    except Exception:
        body = {}

    raw_phone = (
        body.get("phone") or 
        body.get("customer_phone") or 
        body.get("phone_number") or 
        body.get("caller_id") or 
        body.get("to") or 
        body.get("from") or 
        (body.get("customer") or {}).get("phone") or 
        (body.get("lead") or {}).get("phone") or 
        "910000000000"
    )
    phone = clean_phone(raw_phone)

    contact_name = (
        body.get("contact_name") or 
        body.get("name") or 
        body.get("customer_name") or 
        (body.get("customer") or {}).get("name") or 
        "Valued Client"
    ).strip()
    if not contact_name:
        contact_name = "Valued Client"

    outcome = body.get("outcome") or body.get("status") or body.get("call_status") or "Call Completed"
    raw_summary = body.get("ai_summary") or body.get("summary") or body.get("transcript") or "Vyora Voice Interaction"
    recording_url = body.get("recording_url") or body.get("recording") or ""
    called_at = body.get("called_at") or body.get("timestamp") or ""
    
    direction = (body.get("direction") or body.get("call_type") or body.get("type") or "outbound").lower()
    source_label = "📥 Vyora Inbound Call (7971413799)" if "in" in direction else "📤 Vyora Outbound Call Agent"
    
    clean_sum = clean_transcript(raw_summary)
    full_summary = f"[{source_label}] {clean_sum}"

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO leads (phone, contact_name, tier, outcome, interest_confirmed, ai_summary, recording_url, called_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (phone, contact_name, "Tier 1: Hot Prospect", outcome, "Yes", full_summary, recording_url, called_at))
    conn.commit()
    conn.close()

    background_tasks.add_task(send_free_meta_whatsapp, phone, contact_name, str(raw_summary))
    forward_to_owner_whatsapp(f"📞 [{source_label}]\nName: {contact_name}\nPhone: {phone}\nOutcome: {outcome}\nSummary: {clean_sum}")
    send_email_notification(f"New Vyora Lead: {contact_name} ({phone})", f"Source: {source_label}\nName: {contact_name}\nPhone: {phone}\nOutcome: {outcome}\nSummary: {clean_sum}")

    return {"status": "success", "message": "Call logged and brochure WhatsApp dispatched"}

@app.get("/leads", response_class=HTMLResponse)
def get_all_leads(x_api_key: Optional[str] = None):
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM leads ORDER BY created_at DESC")
    rows = cursor.fetchall()
    conn.close()

    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>MagicalBoundries CRM - Lead Dashboard</title>
        <style>
            body { font-family: Arial, sans-serif; background: #f4f6f9; margin: 0; padding: 30px; color: #333; }
            .container { max-width: 950px; margin: auto; background: white; padding: 40px; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.08); }
            h2 { color: #075E54; margin-top: 0; border-bottom: 2px solid #25D366; padding-bottom: 12px; }
            .lead-card { background: #fafafa; border-left: 6px solid #075E54; padding: 22px; margin-bottom: 25px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.04); line-height: 1.6; }
            .lead-header { display: flex; justify-content: space-between; font-weight: bold; color: #075E54; font-size: 16px; margin-bottom: 10px; }
            .lead-meta { font-size: 13px; color: #666; margin-bottom: 12px; }
            .lead-summary { background: #e1ffc7; padding: 12px 16px; border-radius: 6px; font-size: 14px; color: #111; word-break: break-word; }
            .badge { background: #25D366; color: white; padding: 4px 10px; border-radius: 4px; font-size: 12px; }
        </style>
    </head>
    <body>
        <div class="container">
            <h2>🏢 MagicalBoundries Centralized CRM Leads</h2>
            <p>Showing all qualified website chatbot and Vyora voice call leads, organized chronologically.</p>
            <hr style="border: 0; border-top: 1px solid #ddd; margin-bottom: 30px;">
    """

    if not rows:
        html_content += "<p style='text-align: center; color: #777;'>No leads captured yet.</p>"
    else:
        for idx, row in enumerate(rows, start=1):
            created_at = row["created_at"] or "N/A"
            phone = row["phone"] or "N/A"
            name = row["contact_name"] or "N/A"
            outcome = row["outcome"] or "N/A"
            summary = row["ai_summary"] or "N/A"
            
            html_content += f"""
            <div class="lead-card">
                <div class="lead-header">
                    <span>#{idx} — {name}</span>
                    <span class="badge">Phone: {phone}</span>
                </div>
                <div class="lead-meta">
                    📅 <b>Timestamp:</b> {created_at} &nbsp;|&nbsp; 🎯 <b>Outcome:</b> {outcome}
                </div>
                <div class="lead-summary">
                    <b>Summary / Source:</b> {summary}
                </div>
            </div>
            """

    html_content += """
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)
