import os
import sqlite3
import smtplib
from email.message import EmailMessage
from typing import Optional, Any
from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import requests

app = FastAPI(title="Native Real Estate Multi-Project CRM & WhatsApp Gateway")

# Enable CORS so your GoDaddy website can successfully send leads to Render
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins (GoDaddy website)
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods (POST, GET, etc.)
    allow_headers=["*"],  # Allows all headers
)

DB_FILE = "native_crm_leads.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT UNIQUE,
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

class AICallWebhookPayload(BaseModel):
    phone: Optional[str] = Field(default="910000000000")
    contact_name: Optional[str] = Field(default="Valued Client")
    outcome: Optional[str] = Field(default="Call Completed")
    interest_confirmation: Optional[str] = Field(default="No")
    ai_summary: Optional[str] = Field(default="")
    recording_url: Optional[str] = Field(default="")
    called_at: Optional[str] = Field(default="")
    campaign: Optional[str] = Field(default="Commercial & Industrial Real Estate")
    event: Optional[Any] = None

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
    """Sends lead notification email to info@magicalboundries.com"""
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
                        {"type": "text", "text": "MagicalBoundries Commercial & Industrial Portfolio"}
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
def receive_ai_call_webhook(payload: AICallWebhookPayload, background_tasks: BackgroundTasks):
    try:
        if payload.event == "test" or not payload.phone or payload.phone == "910000000000":
            return {"status": "success", "message": "Webhook test ping received successfully!"}

        tier = "Tier 1: Hot Prospect"
        
        # 1. Save lead to SQLite database
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO leads (phone, contact_name, tier, outcome, interest_confirmed, ai_summary, recording_url, called_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (payload.phone, payload.contact_name, tier, payload.outcome, payload.interest_confirmation, payload.ai_summary, payload.recording_url, payload.called_at))
        conn.commit()
        conn.close()

        # 2. Trigger WhatsApp template to customer
        background_tasks.add_task(send_free_meta_whatsapp, payload.phone, payload.contact_name, tier, payload.ai_summary, payload.campaign)
        
        # 3. Forward WhatsApp notification to business owner: 8851692559
        forward_to_owner_whatsapp(
            f"🚨 [New MagicalBoundries Lead]\n"
            f"Name: {payload.contact_name}\n"
            f"Phone: {payload.phone}\n"
            f"Details: {payload.ai_summary}"
        )

        # 4. Forward lead details to email: info@magicalboundries.com
        send_email_notification(
            subject=f"New Lead: {payload.contact_name} ({payload.phone})",
            content=f"A new lead has been qualified on MagicalBoundries.\n\nName: {payload.contact_name}\nPhone: {payload.phone}\nSummary: {payload.ai_summary}\nCampaign: {payload.campaign}"
        )

        return {"status": "success", "message": "Lead stored, WhatsApp dispatched & notifications forwarded", "assigned_tier": tier}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/leads")
def get_all_leads(x_api_key: Optional[str] = None):
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM leads ORDER BY created_at DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]
