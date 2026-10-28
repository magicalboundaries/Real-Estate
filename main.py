    source=str(source_override or first_value(flat,{"source","lead_source","campaign_source","provider","platform"}) or "Website AI Chat").strip()
    transcript=str(first_value(flat,{"transcript","call_transcript","conversation","summary","call_summary","recording_transcript"}) or "")
    project_hint=str(first_value(flat,{"project","project_name","campaign_name","campaign","campaign_id","property_name","agent_name","assistant_name","property_id"}) or "")
    project=detect_project(flat,project_hint)
    project_name=(project or {}).get("Project Name", project_hint or "Unmatched project")
    property_type=str(first_value(flat,{"property_type","property_category","type"}) or (project or {}).get("Property Type", ""))
    budget=str(first_value(flat,{"budget","budget_range","investment_budget","price_range"}) or "")
    intent=str(first_value(flat,{"intent","lead_intent","disposition","call_outcome","qualification_status","lead_status"}) or "")
    call_status=str(first_value(flat,{"call_status","status","call_result","result","disposition","end_reason"}) or "")
    vyora=is_vyora(source,flat)
    explicit_request=lead_requested_brochure(transcript,intent,flat)
    negative=bool(NEGATIVE_RE.search(" ".join([intent,transcript,call_status])))
    qualified=(bool(QUALIFIED_RE.search(" ".join([intent,transcript,call_status]))) or explicit_request) and not negative
    # Website enquiries always notify the owner; Vyora alerts only for qualified leads.
    owner_should_send=(not vyora) or qualified
    url=brochure_url(project)
    # Website chat leads get the matching brief when a project can be identified. Vyora gets it only on explicit request.
    customer_should_send=bool(url and phone and ((not vyora) or explicit_request))
    summary=safe_text(str(first_value(flat,{"summary","message","query","enquiry","requirement","notes"}) or ""),1800)
    owner_status="not_sent"
    if owner_should_send:
        owner_msg=(f"MagicalBoundries lead\nSource: {source}\nName: {name or 'Not provided'}\nPhone: {phone or 'Not provided'}\nProject: {project_name}\nType: {property_type or 'Not provided'}\nBudget: {budget or 'Not provided'}\nStatus: {call_status or intent or 'Not provided'}\nQualified: {'Yes' if qualified else 'No'}\nBrochure: {url or 'No matched clean brochure'}\nEnquiry: {summary or 'Not provided'}")
        owner_status=send_text(OWNER_WA,owner_msg)
    customer_status="not_sent"
    if customer_should_send:
        customer_status=send_document(phone,url,project_name)
    elif phone and (not project):
        customer_status="skipped_no_exact_project_match"
    elif phone and vyora and not explicit_request:
        customer_status="skipped_vyora_no_explicit_brochure_request"
    elif phone and project and not url:
        customer_status="skipped_no_clean_brochure_file"
    now=datetime.now(timezone.utc).isoformat()
    row={"name":safe_text(name,200),"phone":phone,"email":str(email)[:250], "project":safe_text(project_name,250),"summary":summary,"source":safe_text(source,100),"created_at":now,"outcome":safe_text(call_status or intent,250),"property_type":safe_text(property_type,100),"budget":safe_text(budget,100),"intent":safe_text(intent,250),"call_status":safe_text(call_status,250),"transcript":safe_text(transcript,4000),"brochure_url":url,"owner_whatsapp_status":owner_status,"customer_whatsapp_status":customer_status,"qualified":1 if qualified else 0,"raw_payload":json.dumps(payload,ensure_ascii=False)[:20000]}
    lead_id=insert_lead(row)
    log.info("Lead #%s stored source=%s project=%s qualified=%s owner=%s customer=%s",lead_id,source,project_name,qualified,owner_status,customer_status)
    return {"ok":True,"lead_id":lead_id,"project":project_name,"matched_project":bool(project),"brochure_url":url,"qualified":qualified,"owner_whatsapp_status":owner_status,"customer_whatsapp_status":customer_status,"email_status":"disabled"}

@app.get("/")
def root():
    return {"service":"MagicalBoundries Lead CRM","status":"ok","routes":["/health","/lead","/chatbot/lead","/vyora/webhook","/leads","/leads.csv","/brochures/{slug}.pdf"]}

@app.get("/health")
def health(): return {"ok":True,"registry_count":len(REGISTRY),"brochure_dir_exists":BROCHURE_DIR.exists(),"db_path":str(DB_PATH)}

def verify_meta_challenge(request: Request):
    mode=request.query_params.get("hub.mode"); token=request.query_params.get("hub.verify_token"); challenge=request.query_params.get("hub.challenge")
    if mode=="subscribe" and token and token==VERIFY_TOKEN: return PlainTextResponse(challenge or "")
    raise HTTPException(status_code=403,detail="Verification failed")

@app.get("/webhook")
def verify_webhook(request: Request):
    return verify_meta_challenge(request)

@app.get("/meta/webhook")
def meta_verify(request: Request):
    return verify_meta_challenge(request)

@app.post("/lead")
@app.post("/chatbot/lead")
@app.post("/api/lead")
async def website_lead(request: Request):
    try: payload=await request.json()
    except Exception: raise HTTPException(status_code=400,detail="Expected JSON object")
    if not isinstance(payload,dict): raise HTTPException(status_code=400,detail="Expected JSON object")
    return await process_payload(payload,"Website AI Chat")

@app.post("/vyora/webhook")
@app.post("/webhook/vyora")
@app.post("/api/vyora")
async def vyora_webhook(request: Request):
    if VYORA_SECRET and request.headers.get("X-Webhook-Secret","")!=VYORA_SECRET:
        raise HTTPException(status_code=401,detail="Invalid webhook secret")
    try: payload=await request.json()
    except Exception: raise HTTPException(status_code=400,detail="Expected JSON object")
    if not isinstance(payload,dict): raise HTTPException(status_code=400,detail="Expected JSON object")
    return await process_payload(payload,"Vyora AI")

@app.get("/brochures/{slug}.pdf")
def get_brochure(slug:str):
    # Only the clean, generated PDFs are served; original uploaded source brochures are never exposed by this route.
    if not re.fullmatch(r"[a-z0-9-]{1,120}",slug): raise HTTPException(status_code=404,detail="Not found")
    path=(BROCHURE_DIR/f"{slug}.pdf").resolve()
    if BROCHURE_DIR.resolve() not in path.parents or not path.is_file(): raise HTTPException(status_code=404,detail="Clean brochure not found")
    return FileResponse(path,media_type="application/pdf",filename=path.name)

@app.get("/leads",response_class=HTMLResponse)
def leads_dashboard():
    with sqlite3.connect(DB_PATH) as con:
        con.row_factory=sqlite3.Row
        rows=con.execute("SELECT * FROM leads ORDER BY id DESC LIMIT 500").fetchall()
    cols=["id","created_at","source","name","phone","project","property_type","budget","qualified","outcome","owner_whatsapp_status","customer_whatsapp_status","brochure_url"]
    def cell(v):
        s=safe_text(v or "",500).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
        return s
    html=['<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>MagicalBoundries Leads</title><style>body{font:14px Arial;margin:20px;color:#173c3a}h2{color:#07564f}table{border-collapse:collapse;width:100%;font-size:12px}th,td{border:1px solid #d6e1df;padding:7px;text-align:left;vertical-align:top}th{background:#e9f4f2;position:sticky;top:0}tr:nth-child(even){background:#f8fbfa}.wrap{overflow:auto}a{color:#08796f}</style></head><body><h2>MagicalBoundries Lead CRM</h2><p>Append-only lead log · email notifications disabled · <a href="/leads.csv">Export CSV</a></p><div class="wrap"><table><thead><tr>']
    html.extend('<th>'+c+'</th>' for c in cols); html.append('</tr></thead><tbody>')
    for r in rows:
        html.append('<tr>')
        for c in cols:
            rawval=r[c] if c in r.keys() else ''
            val=str(rawval or '').replace('&','&amp;').replace('<','&lt;').replace('>','&gt;') if c in {'phone','email'} else cell(rawval)
            if c=='brochure_url' and val.startswith('https://'): val=f'<a href="{val}">clean brochure</a>'
            html.append('<td>'+val+'</td>')
        html.append('</tr>')
    html.append('</tbody></table></div></body></html>')
    return ''.join(html)

@app.get("/leads.csv")
def export_csv():
    with sqlite3.connect(DB_PATH) as con:
        con.row_factory=sqlite3.Row
        rows=con.execute("SELECT * FROM leads ORDER BY id DESC").fetchall()
    import io
    buf=io.StringIO(); writer=csv.writer(buf)
    if rows:
        writer.writerow(rows[0].keys())
        for r in rows: writer.writerow([r[k] for k in r.keys()])
    else: writer.writerow(["id","created_at","source","name","phone","project"])
    return StreamingResponse(iter([buf.getvalue()]),media_type="text/csv",headers={"Content-Disposition":"attachment; filename=magicalboundries_leads.csv"})

@app.post("/webhook")
@app.post("/meta/webhook")
@app.post("/whatsapp/inbound")
async def whatsapp_inbound(request: Request):
    # Meta delivery/status events are acknowledged here; lead creation is handled by website/Vyora endpoints.
    try: payload=await request.json()
    except Exception: raise HTTPException(status_code=400,detail="Expected JSON object")
