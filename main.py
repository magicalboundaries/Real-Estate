import os
import sqlite3
import smtplib
from email.message import EmailMessage
from typing import Optional, Any, Dict
from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
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

def forward_to_owner_whatsapp(notification_text: str):
    owner_phone = "918851692559"
    phone_number_id = os.getenv("META_PHONE_NUMBER_ID")
    access_token = os.getenv("META_ACCESS_TOKEN")
    
    if not phone_number_id or not access_token:
        print("[Error]: Meta credentials missing for owner WhatsApp forwarding.")
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
        res = requests.post(url, json=payload, headers=headers)
        print("Owner WhatsApp Forwarding Response:", res.json())
    except Exception as e:
        print(f"[Error forwarding to owner whatsapp]: {e}")

def send_email_notification(subject: str, content: str):
    recipient = "info@magicalboundries.com"
    smtp_server = os.getenv("SMTP_SERVER")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")

    if not smtp_server or not smtp_user or not smtp_password:
        print(f"[Email Mock] SMTP settings not configured. Target: {recipient} | Subject: {subject} | Content: {content}")
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
        print(f"[Email Success] Lead sent to {recipient}")
    except Exception as e:
        print(f"[Error sending email to {recipient}]: {e}")

def send_free_meta_whatsapp(phone: str, contact_name: str, tier: str, ai_summary: str, campaign: str):
    phone_number_id = os.getenv("META_PHONE_NUMBER_ID")
    access_token = os.getenv("META_ACCESS_TOKEN")
    
    if not phone_number_id or not access_token:
        print("[WhatsApp Mock] Meta credentials not set. Skipping WhatsApp dispatch.")
        return

    url = f"https://graph.facebook.com/v17.0/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "template",
        "template": {
            "name": "3p_direct_integration_test_template",
            "language": { "code": "en_US" },
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": contact_name},
                        {"type": "text", "text": "MagicalBoundries Real Estate Portfolio"}
                    ]
                }
            ]
        }
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        print("Meta WhatsApp API Response:", response.json())
    except Exception as e:
        print(f"[Error] Failed to send WhatsApp message to {phone}: {e}")

@app.get("/")
def read_root():
    return {"status": "online", "system": "MagicalBoundries CRM & WhatsApp Gateway is active"}

@app.post("/webhook/ai-caller")
async def receive_ai_call_webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        body = await request.json()
        print("Incoming Webhook Body:", body)
    except Exception:
        body = {}

    phone = body.get("phone") or body.get("customer_phone") or body.get("caller_id") or body.get("from") or "910000000000"
    contact_name = body.get("contact_name") or body.get("name") or body.get("customer_name") or "Valued Client"
    outcome = body.get("outcome") or body.get("status") or body.get("call_status") or "Visit Scheduled"
    ai_summary = body.get("ai_summary") or body.get("summary") or body.get("transcript") or ""
    recording_url = body.get("recording_url") or body.get("recording") or ""
    called_at = body.get("called_at") or body.get("timestamp") or ""
    
    # Intelligently detect if this is from Website Chatbot vs Vyora Voice Call
    incoming_source = str(body.get("source") or "").lower()
    summary_lower = ai_summary.lower()
    
    if "website" in incoming_source or "website" in summary_lower or "chat" in summary_lower:
        source_label = "🌐 Website Chatbot Lead (www.magicalboundaries.com)"
    else:
        direction = (body.get("direction") or body.get("call_type") or body.get("type") or "outbound").lower()
        if "in" in direction:
            source_label = "📥 Vyora Inbound Call (Dialed 7971413799)"
        else:
            source_label = "📤 Vyora Outbound Call Agent"

    if body.get("event") == "test" or phone == "910000000000":
        return {"status": "success", "message": "Webhook test ping received successfully!"}

    tier = "Tier 1: Hot Prospect"
    final_summary = f"[{source_label}] {ai_summary}"

    # Save lead to SQLite database
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO leads (phone, contact_name, tier, outcome, interest_confirmed, ai_summary, recording_url, called_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (phone, contact_name, tier, outcome, "Yes", final_summary, recording_url, called_at))
    conn.commit()
    conn.close()

    # 1. Trigger WhatsApp template to customer
    background_tasks.add_task(send_free_meta_whatsapp, phone, contact_name, tier, final_summary, "Commercial & Industrial Real Estate")
    
    # 2. Forward WhatsApp notification to business owner: 8851692559
    forward_to_owner_whatsapp(
        f"🚨 [New Lead Captured]\n"
        f"Source: {source_label}\n"
        f"Name: {contact_name}\n"
        f"Phone: {phone}\n"
        f"Details: {ai_summary}"
    )

    # 3. Forward lead details to email: info@magicalboundries.com
    send_email_notification(
        subject=f"New Lead: {contact_name} ({phone}) via {source_label}",
        content=f"A new lead has been captured.\n\nSource: {source_label}\nName: {contact_name}\nPhone: {phone}\nOutcome: {outcome}\nSummary: {ai_summary}"
    )

    return {"status": "success", "message": "Lead stored successfully", "source": source_label}

@app.get("/leads")
def get_all_leads(x_api_key: Optional[str] = None):
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM leads ORDER BY created_at DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]
