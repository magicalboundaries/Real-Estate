import os
import sqlite3
from typing import Optional
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
import requests

app = FastAPI(title="Native Real Estate CRM & WhatsApp Webhook Gateway")

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
    phone: str
    contact_name: Optional[str] = "Doctor"
    outcome: str
    interest_confirmation: Optional[str] = "No"
    ai_summary: Optional[str] = ""
    recording_url: Optional[str] = ""
    called_at: Optional[str] = ""

def send_free_meta_whatsapp(phone: str, contact_name: str, tier: str):
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
    
    if "Tier 1" in tier:
        message_body = f"Hi {contact_name}, thanks for speaking with our team regarding HCBS Twin Horizon, Sector 102 (Dwarka Expressway). Here is the official project brochure and cost sheet as requested. When would you prefer to schedule your site visit?"
    else:
        message_body = f"Hi {contact_name}, great connecting earlier regarding Gurugram luxury real estate. Sharing a quick overview of our low-density 3 & 4 BHK project in Sector 102. Let me know if you have any questions!"

    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "text",
        "text": {"body": message_body}
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        print("Meta WhatsApp API Response:", response.json())
    except Exception as e:
        print(f"[Error] Failed to send WhatsApp message to {phone}: {e}")

@app.post("/webhook/ai-caller")
def receive_ai_call_webhook(payload: AICallWebhookPayload, background_tasks: BackgroundTasks):
    try:
        outcome_lower = payload.outcome.lower()
        interest_lower = payload.interest_confirmation.lower()
        
        if "visit scheduled" in outcome_lower or interest_lower == "yes" or "follow up requested" in outcome_lower:
            tier = "Tier 1: Hot Prospect"
        elif "hesitated" in outcome_lower or "postponed" in outcome_lower:
            tier = "Tier 2: Hesitant / Reluctant"
        else:
            tier = "Tier 3: Cautious Listener"
        
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO leads (phone, contact_name, tier, outcome, interest_confirmed, ai_summary, recording_url, called_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (payload.phone, payload.contact_name, tier, payload.outcome, payload.interest_confirmation, payload.ai_summary, payload.recording_url, payload.called_at))
        conn.commit()
        conn.close()

        if "Tier 1" in tier or "Tier 2" in tier:
            background_tasks.add_task(send_free_meta_whatsapp, payload.phone, payload.contact_name, tier)

        return {"status": "success", "message": "Lead stored in Native CRM & WhatsApp queued successfully", "assigned_tier": tier}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/leads")
def get_all_leads():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM leads ORDER BY created_at DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]
