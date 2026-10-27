    Only accepts JSON with identifiable lead fields; ignores arbitrary POST bodies.
    This cannot catch a request sent to a different server/domain.
    """
    if path.startswith(("docs", "openapi", "redoc")):
        raise HTTPException(status_code=404)
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=415, detail="Catch-all accepts JSON only")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="JSON body must be an object")
    has_phone = bool(find_value(payload, PHONE_KEYS))
    has_lead_data = bool(find_value(payload, NAME_KEYS) or find_value(payload, PROJECT_KEYS) or find_value(payload, SUMMARY_KEYS))
    if not (has_phone or has_lead_data):
        return {"status": "ignored", "path": path, "reason": "no recognizable lead fields"}
    result = process_lead(payload, f"Catch-all /{path}")
    return JSONResponse(result)


@app.get("/", response_class=HTMLResponse)
@app.get("/leads", response_class=HTMLResponse)
async def dashboard(request: Request):
    search = request.query_params.get("q", "").strip()[:200]
    with db_connect() as conn:
        if search:
            pattern = f"%{search}%"
            rows = conn.execute("""
                SELECT id, created_at, name, phone, email, project, source, call_status,
                       summary, outcome, owner_whatsapp_status, customer_whatsapp_status,
                       email_status, brochure_url
                FROM leads
                WHERE name LIKE ? OR phone LIKE ? OR email LIKE ? OR project LIKE ? OR source LIKE ? OR summary LIKE ?
                ORDER BY id DESC
            """, (pattern, pattern, pattern, pattern, pattern, pattern)).fetchall()
        else:
            rows = conn.execute("""
                SELECT id, created_at, name, phone, email, project, source, call_status,
                       summary, outcome, owner_whatsapp_status, customer_whatsapp_status,
                       email_status, brochure_url
                FROM leads ORDER BY id DESC
            """).fetchall()
    esc = lambda x: html.escape("" if x is None else str(x))
    trs = []
    for r in rows:
        trs.append(
            "<tr>"
            f"<td>{r['id']}</td><td>{esc(r['created_at'])}</td><td>{esc(r['name'])}</td>"
            f"<td>{esc(r['phone'])}</td><td>{esc(r['email'])}</td><td>{esc(r['project'])}</td>"
            f"<td>{esc(r['source'])}</td><td>{esc(r['call_status'])}</td>"
            f"<td>{esc(r['summary'])}</td><td>{esc(r['outcome'])}</td>"
            f"<td>{esc(r['owner_whatsapp_status'])}</td><td>{esc(r['customer_whatsapp_status'])}</td>"
            f"<td>{esc(r['email_status'])}</td>"
            f"<td>{('<a href=\"' + esc(r['brochure_url']) + '\" target=\"_blank\" rel=\"noopener\">Brochure</a>') if r['brochure_url'] else ''}</td>"
            "</tr>"
        )
    table_rows = "".join(trs) or '<tr><td colspan="14">No leads captured yet.</td></tr>'
    return HTMLResponse(f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>MagicalBoundries CRM</title>
<style>
body{{font-family:Arial,sans-serif;margin:20px;background:#f4f7fb;color:#172033}}
h1{{margin-bottom:4px}} .sub{{color:#526078;margin-bottom:18px}}
form{{margin:14px 0}} input{{padding:10px;width:min(420px,70vw);border:1px solid #ccd3df;border-radius:6px}}
button{{padding:10px 14px;border:0;border-radius:6px;background:#173f73;color:white}}
.stats{{margin:10px 0;color:#526078}} .wrap{{overflow:auto;background:white;border:1px solid #dbe1ea;border-radius:8px}}
table{{border-collapse:collapse;width:100%;min-width:1600px;font-size:13px}}
th{{position:sticky;top:0;background:#eaf0f8;text-align:left}}
td,th{{padding:9px 10px;border-bottom:1px solid #e6eaf0;vertical-align:top;max-width:360px;overflow-wrap:anywhere}}
tr:hover{{background:#f8fbff}} a{{color:#075da8}}
</style></head><body>
<h1>MagicalBoundries Lead CRM</h1>
<div class="sub">Append-only lead register · Newest leads first · Refreshing this page does not delete records</div>
<form method="get" action="/leads"><input name="q" value="{esc(search)}" placeholder="Search name, phone, project, source or notes"><button type="submit">Search</button> <a href="/leads">Clear</a></form>
<div class="stats">Showing {len(rows)} matching lead record(s). Health: <a href="/health">/health</a> · CSV export: <a href="/leads.csv">/leads.csv</a></div>
<div class="wrap"><table><thead><tr>
<th>ID</th><th>Created UTC</th><th>Name</th><th>Phone</th><th>Email</th><th>Project / Campaign</th>
<th>Source</th><th>Call status</th><th>Summary / payload details</th><th>Outcome</th>
<th>Owner WhatsApp result</th><th>Customer WhatsApp result</th><th>Email result (disabled)</th><th>Brochure</th>
</tr></thead><tbody>{table_rows}</tbody></table></div>
</body></html>""")


@app.get("/leads.csv")
async def export_csv():
    import csv
    import io
    from fastapi.responses import StreamingResponse
    with db_connect() as conn:
        rows = conn.execute("SELECT * FROM leads ORDER BY id DESC").fetchall()
        columns = [x["name"] for x in conn.execute("PRAGMA table_info(leads)").fetchall()]
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(columns)
    for row in rows:
        writer.writerow([row[col] for col in columns])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="magicalboundries_leads.csv"'},
    )

