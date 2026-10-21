import os
import sqlite3
import smtplib
from email.message import EmailMessage
from typing import Optional, Any
from fastapi import FastAPI, HTTPException, Request
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
    "default": "https://real-estate-dy59.onrender.com/brochures/commercial-portfolio.pdf",
    "hcbs twin horizon": "https://real-estate-dy59.onrender.com/brochures/commercial-portfolio.pdf"
}

def get_brochure_link(project_name: Optional[str]) -> str:
    if project_name:
        p_lower = project_name.lower()
        for key in PROJECT_BROCHURES:
            if key in p_lower:
                return PROJECT_BROCHURES[key]
    return PROJECT_BROCHURES["default"]

def clean_phone(phone: str) -> str:
    return "".join(filter(str.isdigit, str(phone)))

def send_email_notification(subject: str, body: str):
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASS", "")
    if not smtp_user or not smtp_pass:
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
    except Exception as e:
        print(f"Email error: {e}")

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
        response = requests.post(url, headers=headers, json=payload)
        print(f"--- OWNER WHATSAPP ALERT Status: {response.status_code} Body: {response.text} ---")
    except Exception as e:
        print(f"Owner WhatsApp error: {e}")

def send_whatsapp_brochure(phone: str, name: str, project: str):
    token = os.getenv("META_ACCESS_TOKEN")
    phone_number_id = os.getenv("META_PHONE_NUMBER_ID")
    if not token or not phone_number_id:
        print("Meta credentials missing.")
        return

    recipient_phone = clean_phone(phone)
    url = f"https://graph.facebook.com/v18.0/{phone_number_id}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    
    # 1. Try sending via Meta Template `brochure_dispatch_v3`
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
        print(f"--- TEMPLATE DISPATCH ({recipient_phone}) Status: {response.status_code} Body: {response.text} ---")
        
        # 2. Fallback to direct text if template fails
        if response.status_code != 200:
            brochure_link = get_brochure_link(project)
            fallback_text = f"Dear {name}, thank you for your interest with MagicalBoundries! Here is your project brochure link: {brochure_link} - please click to download."
            payload_text = {
                "messaging_product": "whatsapp",
                "to": recipient_phone,
                "type": "text",
                "text": {"body": fallback_text}
            }
            res_text = requests.post(url, headers=headers, json=payload_text)
            print(f"--- FALLBACK TEXT DISPATCH Status: {res_text.status_code} Body: {res_text.text} ---")
    except Exception as e:
        print(f"Brochure dispatch exception: {e}")

def handle_lead_submission(data: dict, source: str):
    print(f"Processing lead from {source} with data:", data)
    name = data.get("contact_name") or data.get("name") or data.get("customer_name") or "Valued Customer"
    phone = data.get("phone") or data.get("phone_number") or data.get("mobile") or data.get("whatsapp") or data.get("customer_phone") or ""
    email = data.get("email", "")
    project = data.get("project") or data.get("property_type") or data.get("campaign") or data.get("agent_name") or "default"
    
    summary = "Lead Capture"
    if "analysis" in data and isinstance(data["analysis"], dict):
        summary = data["analysis"].get("summary", "Call Completed")
    else:
        summary = data.get("ai_summary") or data.get("summary") or data.get("call_summary") or "Lead Capture"
    
    # Save to database
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO leads (name, phone, email, project, summary, source, outcome) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (name, phone, email, project, summary, source, "Captured & Dispatched")
    )
    conn.commit()
    conn.close()
    
    # 1. Email Owner (info@magicalboundaries.com)
    send_email_notification(f"New Lead: {name} ({project})", f"Source: {source}\nName: {name}\nPhone: {phone}\nEmail: {email}\nProject: {project}\nSummary: {summary}")
    
    # 2. Owner WhatsApp Notification (to 8851692559 formatted exactly like your successful screenshot)
    owner_msg = f"🔴 *[New Website Lead]*\nName: {name}\nPhone: {phone}\nDetails: Project: {project} | Summary: {summary}"
    send_whatsapp_message("8851692559", owner_msg)
    
    # 3. Customer Brochure Dispatch
    if phone:
        send_whatsapp_brochure(phone, name, project)

@app.post("/webhook/website-chat")
async def website_chat(request: Request):
    try:
        data = await request.json()
    except:
        data = {}
    handle_lead_submission(data, "Website AI Chat")
    return {"status": "success"}

@app.post("/webhook/vyora")
@app.post("/webhook/call-lead")
async def vyora_lead(request: Request):
    try:
        data = await request.json()
    except:
        data = {}
    handle_lead_submission(data, "VYORA Call")
    return {"status": "success"}

@app.get("/webhook")
async def verify(request: Request):
    if request.query_params.get("hub.mode") == "subscribe" and request.query_params.get("hub.verify_token") == os.getenv("VERIFY_TOKEN", "magicalboundries123"):
        return PlainTextResponse(content=str(request.query_params.get("hub.challenge")), status_code=200)
    raise HTTPException(status_code=403)

@app.post("/webhook")
async def webhook_post(request: Request):
    return {"status": "received"}

@app.post("/{path:path}")
async def catch_all_post(path: str, request: Request):
    try:
        data = await request.json()
    except:
        data = {}
    if data and any(k in data for k in ["phone", "phone_number", "mobile", "whatsapp", "contact_name", "name", "event"]):
        handle_lead_submission(data, f"Catch-All (/{path})")
    return {"status": "success", "path": path}

@app.get("/leads", response_class=HTMLResponse)
@app.get("/", response_class=HTMLResponse)
async def dash():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT id, name, phone, email, project, summary, source, created_at, outcome FROM leads ORDER BY id DESC")
    leads = c.fetchall()
    conn.close()
    html = "<html><head><title>Real Estate CRM Dashboard</title></head><body style='font-family:Arial; margin:40px; background:#f4f7f6;'><h2>Real Estate CRM Dashboard</h2>"
    if not leads:
        html += "<p>No leads captured yet.</p>"
    for l in leads:
        html += f"<div style='background:#fff; border:1px solid #ddd; padding:15px; margin-bottom:10px; border-radius:6px;'><b>#{l[0]} - {l[1]}</b> | <span style='background:#e2e8f0; padding:2px 6px; border-radius:4px;'>Source: {l[6]}</span> | Phone: {l[2]} | Project: {l[4]}<br><div style='margin-top:6px; color:#555;'><b>Summary:</b> {l[5]}</div></div>"
    html += "</body></html>"
    return html
