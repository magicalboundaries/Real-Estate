import os
import sqlite3
from typing import Optional, Any
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
import requests

app = FastAPI(title="Native Real Estate Multi-Project CRM & WhatsApp Gateway")

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
    campaign: Optional[str] = Field(default="Luxury Real Estate")
    event: Optional[Any] = None

# ==========================================
# CENTRAL PROJECT DATABASE (Add new projects here easily!)
# ==========================================
PROJECT_DATABASE = {
    "twin horizon": {
        "name": "HCBS Twin Horizon (Sector 102, Dwarka Expressway)",
        "details": "Low-density luxury 3 & 4 BHK residences with 70% open green spaces, 1.15 lakh sq. ft. club & recreational space.",
        "offer": "Special payment plan: Pay 10% now, attractive bank loan schemes powered by Bajaj Housing Finance & Bank of Maharashtra.",
        "brochure_link": "https://your-public-link-to-twin-horizon-brochure.pdf"
    },
    "eldeco amaya": {
        "name": "Eldeco Amaya (Sector 33, Sonipat)",
        "details": "14 acres of Tuscan-style premium residential plots and villas inspired by European countryside living.",
        "offer": "Features Club Amaya, swimming pool, landscaped greens, and 60-meter wide road access.",
        "brochure_link": "https://your-public-link-to-eldeco-amaya-brochure.pdf"
    },
    "serenity hills": {
        "name": "Emaar Serenity Hills (Sector 86, Gurugram)",
        "details": "IGBC Platinum pre-certified luxury 3 & 4 BHK residences with 8 acres of central greens and a waterfront promenade.",
        "offer": "Resort-styled Club Serenity, EV charging infrastructure, and expansive decks with full-height glazing.",
        "brochure_link": "https://your-public-link-to-serenity-hills-brochure.pdf"
    },
    "m3m": {
        "name": "M3M Commercial (Cullinan, Line & Jewel Crest Avenue)",
        "details": "High-street retail and luxury commercial spaces with assured rental and festive privileges.",
        "offer": "Festive Fortune Offer: Pay 40% now, 60% near possession, plus special electronics/iPhone festive vouchers.",
        "brochure_link": "https://your-public-link-to-m3m-brochure.pdf"
    },
    "elan ramada": {
        "name": "Ramada Encore by Wyndham (Elan)",
        "details": "Premium managed hospitality suites and luxury commercial spaces offering high rental yields.",
        "offer": "Fully serviced branded hospitality suites with assured returns.",
        "brochure_link": "https://your-public-link-to-elan-ramada-brochure.pdf"
    }
}

def generate_dynamic_message(contact_name: str, ai_summary: str, campaign: str) -> str:
    summary_lower = (ai_summary or "").lower()
    name_lower = (contact_name or "").lower()
    campaign_lower = (campaign or "").lower()
    
    # Detect Audience Persona
    if "dr." in name_lower or "doctor" in name_lower or "medical" in summary_lower:
        audience_tone = "As a medical professional, we understand your preference for secure, high-yield real estate assets."
    elif "investor" in summary_lower or "roi" in summary_lower or "rental" in summary_lower:
        audience_tone = "Tailored for strong capital appreciation and consistent rental income."
    else:
        audience_tone = "Thank you for connecting with our advisory team."

    # Match Project from database based on call summary or campaign
    matched_project = None
    for key, proj in PROJECT_DATABASE.items():
        if key in summary_lower or key in campaign_lower:
            matched_project = proj
            break
            
    # Default fallback if no specific keyword matched
    if not matched_project:
        matched_project = {
            "name": campaign or "our featured luxury real estate project",
            "details": "premium architecture, world-class amenities, and strategic connectivity.",
            "offer": "Special pre-launch benefits and flexible payment plans available.",
            "brochure_link": "https://your-portfolio-link.pdf"
        }

    message = (
        f"Hi {contact_name}, it was a pleasure speaking with you regarding {matched_project['name']}. "
        f"{audience_tone} {matched_project['details']} "
        f"Key Highlight: {matched_project['offer']} "
        f"You can view the official project brochure and cost sheet here: {matched_project['brochure_link']} "
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
    
    message_body = generate_dynamic_message(contact_name, ai_summary, campaign)

   payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "template",
        "template": {
            "name": "3p_direct_integration_test_template",
            "language": {
                "code": "en_US"
            },
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": contact_name},
                        {"type": "text", "text": matched_project_name}
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

        return {"status": "success", "message": "Lead stored & dynamic multi-project WhatsApp queued successfully", "assigned_tier": tier}

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
