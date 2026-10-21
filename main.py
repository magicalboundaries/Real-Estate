import os
import sqlite3
import smtplib
from email.message import EmailMessage
from typing import Optional, Any
from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
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

DB_FILE = "leads.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            phone TEXT,
            email TEXT,
            project TEXT,
            summary TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            outcome TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

PROJECT_BROCHURES = {
    "default": "https://example.com/default-brochure.pdf",
    "project_a": "https://example.com/project-a-brochure.pdf"
}

def clean_phone(phone: str) -> str:
    cleaned = "".join(filter(str.isdigit, str(phone)))
    return cleaned

def send_whatsapp_brochure(phone: str, name: str, project: str):
    token = os.getenv("META_ACCESS_TOKEN")
    phone_number_id = os.getenv("META_PHONE_NUMBER_ID")
    
    if not token or not phone_number_id:
        print("Meta credentials missing.")
        return

    recipient_phone = clean_phone(phone)
    url = f"https://graph.facebook.com/v18.0/{phone_number_id}/messages"
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "messaging_product": "whatsapp",
        "to": recipient_phone,
        "type": "template",
        "template": {
            "name": "brochure_dispatch_v3",
            "language": {
                "code": "en"
            }
        }
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        print("--- META WHATSAPP API RESPONSE ---")
        print(f"Status Code: {response.status_code}")
        print(f"Response Body: {response.text}")
        print("---------------------------------")
    except Exception as e:
        print(f"Failed to send WhatsApp message: {e}")

@app.post("/webhook/website-chat")
async def website_chat_lead(request: Request, background_tasks: BackgroundTasks):
    data = await request.json()
    print("Received lead payload from website:", data)
    
    name = data.get("name", "Valued Customer")
    # Check multiple possible key names for the phone number sent by the website
    phone = data.get("phone") or data.get("phone_number") or data.get("mobile") or data.get("whatsapp") or ""
    email = data.get("email", "")
    project = data.get("project", "default")
    summary = data.get("summary", "Website Lead Capture")
    
    # Save to database
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO leads (name, phone, email, project, summary, outcome) VALUES (?, ?, ?, ?, ?, ?)",
        (name, phone, email, project, summary, "Lead Captured & Brochure Dispatched")
    )
    conn.commit()
    conn.close()
    
    # Trigger WhatsApp message in background
    if phone:
        background_tasks.add_task(send_whatsapp_brochure, phone, name, project)
        print(f"Dispatched WhatsApp background task for phone: {phone}")
    else:
        print("WARNING: Lead received, but NO valid phone number field found in payload!")
        
    return {"status": "success", "message": "Lead received and brochure dispatch initiated."}

# ==========================================
# META WHATSAPP WEBHOOK VERIFICATION (GET)
# ==========================================
@app.get("/webhook")
async def verify_webhook(request: Request):
    hub_mode = request.query_params.get("hub.mode")
    hub_challenge = request.query_params.get("hub.challenge")
    hub_verify_token = request.query_params.get("hub.verify_token")
    
    expected_token = os.getenv("VERIFY_TOKEN", "magicalboundries123")
    
    if hub_mode == "subscribe" and hub_verify_token == expected_token:
        return PlainTextResponse(content=str(hub_challenge), status_code=200)
    
    raise HTTPException(status_code=403, detail="Verification token mismatch")

# ==========================================
# META WHATSAPP WEBHOOK EVENTS (POST)
# ==========================================
@app.post("/webhook")
async def receive_webhook(request: Request):
    body = await request.json()
    print("Incoming WhatsApp Webhook Event:", body)
    return {"status": "received"}

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, phone, email, project, summary, created_at, outcome FROM leads ORDER BY id DESC")
    leads = cursor.fetchall()
    conn.close()
    
    html_content = """
    <html>
        <head>
            <title>Real Estate CRM Dashboard</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 40px; background: #f4f7f6; }
                h2 { color: #333; }
                .lead-card { background: white; padding: 15px; margin-bottom: 10px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
                .lead-header { font-weight: bold; font-size: 16px; color: #007bff; }
                .badge { background: #e2e8f0; padding: 3px 8px; border-radius: 4px; font-size: 12px; }
            </style>
        </head>
        <body>
            <h2>Real Estate Leads & WhatsApp Dispatch CRM</h2>
    """
    
    if not leads:
        html_content += "<p>No leads received yet.</p>"
    else:
        for idx, (lead_id, name, phone, email, project, summary, created_at, outcome) in enumerate(leads, 1):
            html_content += f"""
            <div class="lead-card">
                <div class="lead-header">
                    #{idx} - {name} <span class="badge">Phone: {phone}</span> <span class="badge">Project: {project}</span>
                </div>
                <div style="margin-top: 8px;">
                    <b>Email:</b> {email} &nbsp;|&nbsp; <b>Timestamp:</b> {created_at} &nbsp;|&nbsp; <b>Outcome:</b> {outcome}
                </div>
                <div style="margin-top: 8px; color: #555;">
                    <b>Summary:</b> {summary}
                </div>
            </div>
            """
            
    html_content += """
        </body>
    </html>
    """
    return html_content
