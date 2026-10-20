import os
import sqlite3
from typing import Optional, Any
from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
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
# CENTRAL PROJECT DATABASE (Residential & Commercial Classified)
# ==========================================
PROJECT_DATABASE = {
    # RESIDENTIAL PROJECTS
    "amstoria": {
        "category": "residential",
        "name": "BPTP Amstoria 102 Eden Estate III (Sector 102, Gurugram)",
        "details": "Exclusive ~9.903-acre plotted development within a 143-acre Lutyens-style luxury township on Dwarka Expressway featuring Sanctuary Club and central greens.",
        "offer": "Pre-launch premier plots with world-class township infrastructure and seamless connectivity to Dwarka Golf Course & Yashobhoomi.",
        "brochure_link": "https://real-estate-dy59.onrender.com/brochures/amstoria-102.pdf"
    },
    "eternia": {
        "category": "residential",
        "name": "Mahagun Eternia (Tech Zone IV, Greater Noida West)",
        "details": "Spacious 6-acre residential enclave inspired by the Anthurium flower offering 3 & 4 BHK luxury residences with G+30 floors.",
        "offer": "Facing a 100-meter fully developed green belt on 130-meter wide main road with double-height entrance lobby and ~25,000 sq. ft. clubhouse.",
        "brochure_link": "https://real-estate-dy59.onrender.com/brochures/mahagun-eternia.pdf"
    },
    "godrej miraya": {
        "category": "residential",
        "name": "Godrej Miraya (Sector 43, Golf Course Road, Gurugram)",
        "details": "Ultra-luxury 5.16-acre masterpiece with only 248 exclusive residences, 3-side open towers, no shared walls, and The Crystal Club.",
        "offer": "Legacy luxury living by India's No. 1 Developer with 127 years of trust, private lounges, and elite concierge services.",
        "brochure_link": "https://real-estate-dy59.onrender.com/brochures/godrej-miraya.pdf"
    },
    "arista luxe": {
        "category": "residential",
        "name": "The Arista Luxe (Sector 168, Noida Expressway - Nimbus)",
        "details": "British architectural elegance featuring Ionic columns, 11 ft. floor-to-ceiling height, expansive Yamuna & forest views, and 7 conceptualized pools.",
        "offer": "Limited period pre-launch price advantage before revision. 65% open green spaces and 1.6 lakh sq. ft. Club Aristaire.",
        "brochure_link": "https://real-estate-dy59.onrender.com/brochures/arista-luxe.pdf"
    },
    "twin horizon": {
        "category": "residential",
        "name": "HCBS Twin Horizon (Sector 102, Dwarka Expressway)",
        "details": "Low-density luxury 3 & 4 BHK residences with 70% open green spaces, 1.15 lakh sq. ft. club & recreational space.",
        "offer": "Special payment plan: Pay 10% now, attractive bank loan schemes powered by Bajaj Housing Finance.",
        "brochure_link": "https://real-estate-dy59.onrender.com/brochures/twin-horizon.pdf"
    },
    "hero homes": {
        "category": "residential",
        "name": "Leafsong Retreat / The Palatial (Sector MU, Greater Noida - Hero)",
        "details": "Resort-themed luxury project featuring AQI-controlled apartments, 70,000 sq. ft. ultra-luxury clubhouse, and smart 3 BHK layouts.",
        "offer": "Smart Payment Plan: Pay just 50 Lakhs in 4 months, zero payment till 18 months. First transfer free!",
        "brochure_link": "https://real-estate-dy59.onrender.com/brochures/hero-homes.pdf"
    },
    "eldeco amaya": {
        "category": "residential",
        "name": "Eldeco Amaya (Sector 33, Sonipat)",
        "details": "14 acres of Tuscan-style premium residential plots and villas inspired by European countryside living.",
        "offer": "Features Club Amaya, swimming pool, landscaped greens, and 60-meter wide road access.",
        "brochure_link": "https://real-estate-dy59.onrender.com/brochures/eldeco.pdf"
    },
    "serenity hills": {
        "category": "residential",
        "name": "Emaar Serenity Hills (Sector 86, Gurugram)",
        "details": "IGBC Platinum pre-certified luxury 3 & 4 BHK residences with 8 acres of central greens and a waterfront promenade.",
        "offer": "Resort-styled Club Serenity, EV charging infrastructure, and expansive decks with full-height glazing.",
        "brochure_link": "https://real-estate-dy59.onrender.com/brochures/serenity.pdf"
    },

    # COMMERCIAL PROJECTS
    "mahagun synq": {
        "category": "commercial",
        "name": "Mahagun Synq - IQ Suites & Commercial (Greater Noida West)",
        "details": "AI-optimised 1 & 2 BHK smart suites with high-street commercial retail spaces on Ground to 4th Floor powered by CLEUB home automation.",
        "offer": "High rental yields, fully furnished by IKEA, ideal for smart investors seeking retail and studio spaces.",
        "brochure_link": "https://real-estate-dy59.onrender.com/brochures/mahagun-synq.pdf"
    },
    "m3m commercial": {
        "category": "commercial",
        "name": "M3M Commercial & Retail Avenues (Gurugram)",
        "details": "High-street retail and luxury commercial spaces with assured rental and festive privileges along prime corridors.",
        "offer": "Festive Fortune Offer: Pay 40% now, 60% near possession, plus special electronics/iPhone festive vouchers.",
        "brochure_link": "https://real-estate-dy59.onrender.com/brochures/m3m.pdf"
    }
}

def forward_to_owner_whatsapp(notification_text: str):
    owner_phone = "918851692559"
    phone_number_id = os.getenv("META_PHONE_NUMBER_ID")
    access_token = os.getenv("META_ACCESS_TOKEN")
    
    if not phone_number_id or not access_token:
        print("[Error]: Meta credentials missing for owner forwarding.")
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
        print("Owner Forwarding Response:", res.json())
    except Exception as e:
        print(f"[Error forwarding to owner]: {e}")

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
    
    summary_lower = (ai_summary or "").lower()
    campaign_lower = (campaign or "").lower()
    matched_project_name = campaign or "our premium luxury property"
    
    for key, proj in PROJECT_DATABASE.items():
        if key in summary_lower or key in campaign_lower:
            matched_project_name = proj["name"]
            break

    # Meta Template Payload (using pre-approved integration test template)
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
                        {"type": "text", "text": matched_project_name}
                    ]
                }
            ]
        }
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        print("Meta WhatsApp API Response:", response.json())
        
        # Mirroring out to 8851692559
        forward_to_owner_whatsapp(
            f"📤 [Outbound CRM Log]\n"
            f"Project: {matched_project_name}\n"
            f"Sent To Customer: {contact_name} ({phone})\n"
            f"Status: Automated WhatsApp template dispatched successfully."
        )
    except Exception as e:
        print(f"[Error] Failed to send WhatsApp message to {phone}: {e}")

@app.post("/webhook/ai-caller")
def receive_ai_call_webhook(payload: AICallWebhookPayload, background_tasks: BackgroundTasks):
    try:
        if payload.event == "test" or not payload.phone or payload.phone == "910000000000":
            return {"status": "success", "message": "Webhook test ping received successfully!"}

        outcome_lower = (payload.outcome or "").lower()
        interest_lower = (payload.interest_confirmation or "").lower()
        
        is_missed_or_voicemail = any(keyword in outcome_lower for keyword in ["voicemail", "failed", "busy", "no answer", "screening", "missed"])

        if is_missed_or_voicemail:
            tier = "Tier 4: Voicemail / Missed Call"
        elif "visit scheduled" in outcome_lower or interest_lower == "yes" or "follow up requested" in outcome_lower:
            tier = "Tier 1: Hot Prospect"
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

        # Trigger WhatsApp and owner forwarding for leads
        background_tasks.add_task(send_free_meta_whatsapp, payload.phone, payload.contact_name, tier, payload.ai_summary, payload.campaign)
        
        # Direct owner mirror alert
        forward_to_owner_whatsapp(
            f"🚨 [New Qualified Lead Captured]\n"
            f"Name: {payload.contact_name}\n"
            f"Phone: {payload.phone}\n"
            f"Details: {payload.ai_summary}"
        )

        return {"status": "success", "message": "Lead stored & automated WhatsApp dispatched", "assigned_tier": tier}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/webhook/whatsapp-inbound")
def verify_whatsapp_webhook(request: Request):
    verify_token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")
    if challenge:
        return int(challenge)
    return "Verification failed", 400

@app.post("/webhook/whatsapp-inbound")
async def receive_whatsapp_reply(request: Request):
    body = await request.json()
    try:
        entries = body.get("entry", [])
        for entry in entries:
            changes = entry.get("changes", [])
            for change in changes:
                value = change.get("value", {})
                messages = value.get("messages", [])
                for msg in messages:
                    customer_phone = msg.get("from")
                    message_body = msg.get("text", {}).get("body", "[Media/Attachment]")
                    
                    forward_to_owner_whatsapp(
                        f"💬 [Incoming Customer Reply]\n"
                        f"From: {customer_phone}\n"
                        f"Message: {message_body}\n\n"
                        f"*(Reply directly to this customer)*"
                    )
    except Exception as e:
        print(f"[Error processing incoming whatsapp reply]: {e}")
        
    return {"status": "received"}

@app.get("/leads")
def get_all_leads(x_api_key: Optional[str] = None):
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM leads ORDER BY created_at DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]
