import os
import sqlite3
from typing import Optional, Any
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
import requests

app = FastAPI(title="Native Real Estate CRM & Dynamic WhatsApp Gateway")

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

# Flexible payload model capturing campaign and call details from Vyora
class AICallWebhookPayload(BaseModel):
    phone: Optional[str] = Field(default="910000000000")
    contact_name: Optional[str] = Field(default="Valued Client")
    outcome: Optional[str] = Field(default="Call Completed")
    interest_confirmation: Optional[str] = Field(default="No")
    ai_summary: Optional[str] = Field(default="")
    recording_url: Optional[str] = Field(default="")
    called_at: Optional[str] = Field(default="")
    campaign: Optional[str] = Field(default="Luxury Real Estate Project")
    event: Optional[Any] = None

def generate_dynamic_message(contact_name: str, ai_summary: str, campaign: str) -> str:
    summary_lower = (ai_summary or "").lower()
    name_lower = (contact_name or "").lower()
    campaign_lower = (campaign or "").lower()
    
    # 1. Detect Audience Type (Doctor, Investor, or General Homebuyer)
    if "dr." in name_lower or "doctor" in name_lower or "medical" in summary_lower:
        audience_tone = "As a medical professional, we understand your requirement for high-ROI, hassle-free real estate assets."
    elif "investor" in summary_lower or "roi" in summary_lower or "rental" in summary_lower:
        audience_tone = "Designed for high capital appreciation and strong rental yields, this asset fits your investment portfolio perfectly."
    else:
        audience_tone = "Thank you for exploring our premium residential offerings."

    # 2. Detect Project Name dynamically from summary or campaign tag
    if "twin horizon" in summary_lower or "twin horizon" in campaign_lower:
        project_name = "HCBS Twin Horizon (Sector 102, Dwarka Expressway)"
        offer_details = "featuring low-density luxury 3 & 4 BHK residences with world-class amenities."
    elif "lansdowne" in summary_lower or "lansdowne" in campaign_lower:
        project_name = "Villas Lansdowne"
        offer_details = "featuring exclusive luxury hill-view villas."
    else:
        # Fallback to whatever campaign tag Vyora passes
        project_name = campaign or "our premium luxury real estate project"
        offer_details = "featuring modern architecture and strategic connectivity."

    # 3. Assemble the dynamic WhatsApp message body
    message = (
        f"Hi {contact_name}, it was great speaking with you regarding {project_name}. "
        f"{audience_tone} {offer_details} "
        f"Here is the official brochure and cost sheet as requested. "
        f"When would you prefer to schedule your private site visit?"
    )
    return message

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
    
    # Generate message dynamically based on lead profile and project
    message_body = generate_dynamic_message(contact_name, ai_summary, campaign)

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
        if payload.event == "test" or not payload.phone or payload.phone == "910000000000":
            return {"status": "success", "message": "Vyora webhook test ping received successfully!"}

        outcome_lower = (payload.outcome or "").lower()
        interest_lower = (payload.interest_confirmation or "").lower()
        
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
            background_tasks.add_task(send_free_meta_whatsapp, payload.phone, payload.contact_name, tier, payload.ai_summary, payload.campaign)

        return {"status": "success", "message": "Lead stored & dynamic WhatsApp queued successfully", "assigned_tier": tier}

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
