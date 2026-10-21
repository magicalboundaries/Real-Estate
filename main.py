import os
import sqlite3
import smtplib
from email.message import EmailMessage
from typing import Optional, Any
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
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
            source TEXT,
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

def send_email_notification(subject: str, body: str):
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASS", "")
    
    if not smtp_user or not smtp_pass:
        print("SMTP credentials not configured. Skipping email notification.")
        return

    try:
        msg = EmailMessage()
        msg.set_content(body)
        msg["Subject"] = subject
        msg["From"] = smtp_user
        msg["To"] = "info@magicalboundaries.com"
        
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        print("Email notification sent successfully to info@magicalboundaries.com")
    except Exception as e:
        print(f"Failed to send email notification: {e}")

def send_whatsapp_message(recipient_phone: str, message_text: str):
    token = os.getenv("META_ACCESS_TOKEN")
    phone_number_id = os.getenv("META_PHONE_NUMBER_ID")
    if not token or not phone_number_id:
        return
    
    url = f"https://graph.facebook.com/v18.0/{phone_number_id}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "to": clean_phone(recipient_phone),
        "type": "text",
        "text": {"body": message_text}
    }
    try:
        requests.post(url, headers=headers, json=payload)
    except Exception as e:
        print(f"Failed to send owner WhatsApp text: {e}")

def send_whatsapp_brochure(phone: str, name: str, project: str):
    token = os.getenv("META_ACCESS_TOKEN")
    phone_number_id = os.getenv("META_PHONE_NUMBER_ID")
    
    if not token or not phone_number_id:
        print("Meta credentials missing.")
        return

    recipient_phone = clean_phone(phone)
    url = f"https://graph.facebook.com/v18.0/{phone_number_id}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    
    payload = {
        "messaging_product": "whatsapp",
        "to": recipient_phone,
        "type": "template",
        "template": {
            "name": "brochure_dispatch_v3",
            "language": {"code": "en"}
        }
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        print(f"--- BROCHURE DISPATCH RESPONSE ({recipient_phone}) ---")
        print(f"Status Code: {response.status_code}")
        print(f"Response Body: {response.text}")
    except Exception as e:
        print(f"Failed to send WhatsApp brochure: {e}")

def process_lead(name: str, phone: str, email: str, project: str, summary: str, source: str):
    # 1. Save to CRM Database
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO leads (name, phone, email, project, summary, source, outcome) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (name, phone, email, project, summary, source, "Lead Captured & Notifications Dispatched")
    )
    conn.commit()
    conn.close()
    
    # 2. Email Owner (info@magicalboundaries.com)
    email_subject = f"New Lead Generated: {name} ({project})"
    email_body = f"Source: {source}\nName: {name}\nPhone: {phone}\nEmail: {email}\nProject: {project}\nSummary: {summary}"
    send_email_notification(email_subject, email_body)
    
    # 3. WhatsApp Owner Notification (to 8851692559)
    owner_msg = f"🔔 *New Lead Captured!*\nSource: {source}\nName: {name}\nPhone: {phone}\nProject: {project}\nSummary: {summary}"
    send_whatsapp_message("8851692559", owner_msg)
    
    # 4. Dispatch Brochure to Customer
    if phone:
        send_whatsapp_brochure(phone, name, project)

@app.post("/webhook/website-chat")
async def website_chat_lead(request: Request, background_tasks: BackgroundTasks):
    data = await request.json()
    print("Website Lead Payload:", data)
    name = data.get("contact_name") or data.get("name") or "Valued Customer"
    phone = data.get("phone") or data.get("phone_number") or data.get("mobile") or data.get("whatsapp") or ""
    email = data.get("email", "")
    project = data.get("project") or data.get("property_type") or "default"
    summary = data.get("ai_summary") or data.get("summary") or "Website Lead Capture"
    
    background_tasks.add_task(process_lead, name, phone, email, project, summary, "Website AI Chat")
    return {"status": "success", "message": "Lead processed successfully"}

@app.post("/webhook/vyora")
@app.post("/webhook/call-lead")
async def vyora_call_lead(request: Request, background_tasks: BackgroundTasks):
    data = await request.json()
    print("VYORA / Call Lead Payload:", data)
    name = data.get("contact_name") or data.get("name") or data.get("customer_name") or "Call Lead"
    phone = data.get("phone") or data.get("phone_number") or data.get("customer_phone") or ""
    email = data.get("email", "")
    project = data.get("project") or data.get("campaign") or data.get("property") or "default"
    summary = data.get("summary") or data.get("call_summary") or "VYORA Call Campaign Lead"
    source = data.get("source", "VYORA Call")
    
    background_tasks.add_task(process_lead, name, phone, email, project, summary, source)
    return {"status": "success", "message": "Call lead processed successfully"}

@app.get("/webhook")
async def verify_webhook(request: Request):
    hub_mode = request.query_params.get("hub.mode")
    hub_challenge = request.query_params.get("hub.challenge")
    hub_verify_token = request.query_params.get("hub.verify_token")
    expected_token = os.getenv("VERIFY_TOKEN", "magicalboundries123")
    
    if hub_mode == "subscribe" and hub_verify_token == expected_token:
        return PlainTextResponse(content=str(hub_challenge), status_code=200)
    raise HTTPException(status_code=403, detail="Verification token mismatch")

@app.post("/webhook")
async def receive_webhook(request: Request):
    body = await request.json()
    print("Inbound Meta Webhook Event:", body)
    return {"status": "received"}

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, phone, email, project, summary, source, created_at, outcome FROM leads ORDER BY id DESC")
    leads = cursor.fetchall()
    conn.close()
    
    html = '''
    <html>
        <head>
            <title>Real Estate CRM Dashboard</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 40px; background: #f4f7f6; }
                .card { background: white; padding: 15px; margin-bottom: 12px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
                .badge { background: #e2e8f0; padding: 3px 8px; border-radius: 4px; font-size: 12px; font-weight: bold; color: #333; }
            </style>
        </head>
        <body>
            <h2>Real Estate Multi-Project CRM & WhatsApp Gateway</h2>
    '''
    if not leads:
        html += "<p>No leads captured yet.</p>"
    else:
        for idx, (lid, name, phone, email, project, summary, source, created_at, outcome) in enumerate(leads, 1):
            html += f'''
            <div class="card">
                <b>#{idx} - {name}</b> <span class="badge">Source: {source}</span> <span class="badge">Phone: {phone}</span> <span class="badge">Project: {project}</span>
                <div style="margin-top: 6px; font-size: 14px; color: #444;">
                    <b>Email:</b> {email} &nbsp;|&nbsp; <b>Time:</b> {created_at}
                </div>
                <div style="margin-top: 6px; color: #666; font-size: 13px;">
                    <b>Summary:</b> {summary}
                </div>
            </div>
            '''
    html += "</body></html>"
    return html
