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
    return {"status": "online", "system": "MagicalBoundries CRM & WhatsApp Gateway is active (Vyora Number: 7971413799)"}

@app.post("/webhook/ai-caller")
async def receive_ai_call_webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        body = await request.json()
        print("Incoming Vyora Call Webhook Body:", body)
    except Exception:
        body = {}

    # Extract fields supporting incoming vs outgoing Vyora calls
    phone = body.get("phone") or body.get("customer_phone") or body.get("caller_id") or body.get("from") or "910000000000"
    contact_name = body.get("contact_name") or body.get("name") or body.get("customer_name") or "Valued Client"
    outcome = body.get("outcome") or body.get("status") or body.get("call_status") or "Call Completed"
    ai_summary = body.get("ai_summary") or body.get("summary") or body.get("transcript") or "Vyora Call Interaction"
    recording_url = body.get("recording_url") or body.get("recording") or ""
    called_at = body.get("called_at") or body.get("timestamp") or ""
    
    # Detect if call was Incoming or Outgoing on number 7971413799
    direction = (body.get("direction") or body.get("call_type") or body.get("type") or "outbound").lower()
    call_direction_label = "📥 Incoming Call (Customer Dialed 7971413799)" if "in" in direction else "📤 Outgoing Call (Vyora Dialed Lead)"

    if body.get("event") == "test" or phone == "910000000000":
        return {"status": "success", "message": "Webhook test ping received successfully!"}

    tier = "Tier 1: Hot Prospect"

    # Save lead to SQLite database
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO leads (phone, contact_name, tier, outcome, interest_confirmed, ai_summary, recording_url, called_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (phone, contact_name, tier, outcome, "Yes", f"[{call_direction_label}] {ai_summary}", recording_url, called_at))
    conn.commit()
    conn.close()

    # 1. Trigger WhatsApp template to customer
    background_tasks.add_task(send_free_meta_whatsapp, phone, contact_name, tier, ai_summary, "Commercial & Industrial Real Estate")
    
    # 2. Forward WhatsApp notification to business owner: 8851692559
    forward_to_owner_whatsapp(
        f"📞 [{call_direction_label}]\n"
        f"Vyora Number: 7971413799\n"
        f"Name: {contact_name}\n"
        f"Phone: {phone}\n"
        f"Outcome: {outcome}\n"
        f"Summary: {ai_summary}"
    )

    # 3. Forward lead details to email: info@magicalboundries.com
    send_email_notification(
        subject=f"[{call_direction_label}] {contact_name} ({phone})",
        content=f"Call Interaction on Vyora Number 7971413799.\n\nDirection: {call_direction_label}\nName: {contact_name}\nPhone: {phone}\nOutcome: {outcome}\nSummary: {ai_summary}"
    )

    return {"status": "success", "message": "Call logged successfully, WhatsApp & email notifications triggered", "direction": call_direction_label}

@app.get("/leads")
def get_all_leads(x_api_key: Optional[str] = None):
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM leads ORDER BY created_at DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]
