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

# Multi-Project Brochure mapping
PROJECT_BROCHURES = {
    "default": "https://real-estate-dy59.onrender.com/brochures/commercial-portfolio.pdf",
    "hcbs twin horizon": "https://real-estate-dy59.onrender.com/brochures/hcbs-twin-horizon-brochure.pdf",
    "pushpanjali": "https://real-estate-dy59.onrender.com/brochures/pushpanjali-portfolio.pdf",
    "gurugram": "https://real-estate-dy59.onrender.com/brochures/gurugram-residential.pdf"
}

def detect_project(data: dict) -> str:
    payload_str = str(data).lower()
    if "hcbs" in payload_str or "twin horizon" in payload_str or "vamika" in payload_str:
        return "HCBS Twin Horizon"
    elif "pushpanjali" in payload_str:
        return "Pushpanjali"
    elif "gurugram" in payload_str or "sector 102" in payload_str:
        return "Gurugram Residential"
    
    explicit = data.get("project") or data.get("property_type") or data.get("campaign") or data.get("agent_name") or ""
    if explicit:
        return str(explicit)
    return "HCBS Twin Horizon"

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
        print("Email notification sent to info@magicalboundaries.com")
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
    
    brochure_link = get_brochure_link(project)
    text_msg = f"Dear {name}, thank you for your interaction with MagicalBoundries regarding {project}! Here is your relevant project brochure link: {brochure_link} - please click to download."
    
    payload = {
        "messaging_product": "whatsapp",
        "to": recipient_phone,
        "type": "text",
        "text": {"body": text_msg}
    }
    
    try:
        res = requests.post(url, headers=headers, json=payload)
        print(f"--- CUSTOMER BROCHURE DISPATCH ({recipient_phone}) Status: {res.status_code} Body: {res.text} ---")
    except Exception as e:
        print(f"Brochure dispatch exception: {e}")

def handle_lead_submission(data: dict, source: str):
    print(f"Processing lead from {source} with data:", data)
    
    name = (
        data.get("contact_name") or 
        data.get("name") or 
        data.get("customer_name") or 
        data.get("custom_args", {}).get("callee_name") or 
        data.get("custom_args", {}).get("callee_first_name") or 
        "Valued Customer"
    )
    
    phone = (
        data.get("phone") or 
        data.get("phone_number") or 
        data.get("mobile") or 
        data.get("whatsapp") or 
        data.get("customer_phone") or 
        data.get("custom_args", {}).get("mobile_number") or 
        ""
    )
    
    email = data.get("email", "")
    project = detect_project(data)
    
    status = data.get("status", "completed")
    voicemail = data.get("voicemail", False)
    call_note = f"Status: {status} | Voicemail: {voicemail}"
    
    if "analysis" in data and isinstance(data["analysis"], dict):
        summary = data["analysis"].get("summary", call_note)
    else:
        summary = data.get("ai_summary") or data.get("summary") or data.get("call_summary") or call_note
        
    summary = f"{summary} ({call_note})"

    # Save to SQLite CRM permanently (prevents overwriting)
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO leads (name, phone, email, project, summary, source, outcome) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (name, phone, email, project, summary, source, "Captured & Brochure Dispatched")
    )
    conn.commit()
    conn.close()
    
    # 1. Email Owner (info@magicalboundaries.com)
    send_email_notification(
        f"New Lead: {name} ({project})", 
        f"Source: {source}\nName: {name}\nPhone: {phone}\nEmail: {email}\nProject: {project}\nSummary: {summary}"
    )
    
    # 2. Owner WhatsApp Notification (to 8851692559)
    owner_msg = f"🔴 *[New Lead - {source}]*\nName: {name}\nPhone: {phone}\nProject: {project}\nDetails: {summary}"
    send_whatsapp_message("8851692559", owner_msg)
    
    # 3. Customer Brochure Dispatch (Instant text message)
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
    handle_lead_submission(data, "VYORA Call Campaign")
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
    if data and any(k in data for k in ["phone", "phone_number", "mobile", "whatsapp", "contact_name", "name", "event", "call_id", "custom_args"]):
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
    
    html = """
    <html>
        <head>
            <title>Real Estate CRM Dashboard</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 30px; background: #f8fafc; color: #334155; }
                h2 { color: #1e293b; margin-bottom: 5px; }
                p.subtitle { color: #64748b; margin-top: 0; margin-bottom: 20px; }
                table { width: 100%; border-collapse: collapse; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); }
                th, td { padding: 12px 16px; text-align: left; border-bottom: 1px solid #e2e8f0; font-size: 14px; }
                th { background: #0f172a; color: white; font-weight: 600; text-transform: uppercase; font-size: 12px; letter-spacing: 0.5px; }
                tr:hover { background: #f1f5f9; }
                .badge { background: #e0f2fe; color: #0369a1; padding: 4px 8px; border-radius: 4px; font-size: 12px; font-weight: 600; }
                .badge-vyora { background: #fef3c7; color: #b45309; }
                .no-leads { text-align: center; padding: 40px; color: #64748b; font-size: 16px; }
            </style>
        </head>
        <body>
            <h2>Real Estate CRM Dashboard</h2>
            <p class="subtitle">Live Multi-Project Lead Management & WhatsApp Gateway</p>
            <table>
                <thead>
                    <tr>
                        <th>#ID</th>
                        <th>Timestamp</th>
                        <th>Name</th>
                        <th>Phone</th>
                        <th>Email</th>
                        <th>Project</th>
                        <th>Source</th>
                        <th>Summary / Details</th>
                        <th>Outcome</th>
                    </tr>
                </thead>
                <tbody>
    """
    
    if not leads:
        html += '<tr><td colspan="9" class="no-leads">No leads captured yet. Submit a test lead or trigger a VYORA call to populate data.</td></tr>'
    else:
        for l in leads:
            source_badge = f'<span class="badge badge-vyora">{l[6]}</span>' if "VYORA" in l[6] else f'<span class="badge">{l[6]}</span>'
            html += f"""
                <tr>
                    <td><b>#{l[0]}</b></td>
                    <td style="white-space: nowrap; color: #64748b;">{l[7]}</td>
                    <td><b>{l[1]}</b></td>
                    <td style="color: #0284c7; font-weight: 600;">{l[2]}</td>
                    <td>{l[3]}</td>
                    <td><b>{l[4]}</b></td>
                    <td>{source_badge}</td>
                    <td style="color: #475569; max-width: 300px; word-break: break-word;">{l[5]}</td>
                    <td><span style="color: #16a34a; font-weight: 600;">{l[8]}</span></td>
                </tr>
            """
            
    html += """
                </tbody>
            </table>
        </body>
    </html>
    """
    return html
