import json
import os
from datetime import date
from pathlib import Path
from uuid import uuid4

import aiosqlite
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import UploadFile


STATIC = Path(__file__).with_name("static")
ROOT = STATIC.parents[1]
DATA = ROOT / os.getenv("WEBMORPH_DATA_DIR", ".data")
MAX_FILE = 10 * 1024 * 1024
app = FastAPI(title="CivicGrid 2008", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


@app.post("/applications")
async def issue_receipt(request: Request):
    async with request.form(max_fields=40, max_files=1, max_part_size=16384) as form:
        expected = {"full_name", "email", "phone", "date_of_birth", "country", "tax_cadence", "applicant_type",
                    "delivery", "own_work", "contact_permission", "legal_certification"}
        if form.get("applicant_type") == "startup":
            expected |= {"project_url", "annual_revenue"}
            if form.get("co_applicant"):
                expected |= {"co_applicant", "co_applicant_name", "co_applicant_email"}
        else:
            expected.add("organization_name")
        values = {key: form.get(key) for key in expected}
        if any(not isinstance(value, str) or not value.strip() for value in values.values()):
            raise HTTPException(422, "Required application details are missing.")
        if any(values[key] != "on" for key in ("own_work", "contact_permission", "legal_certification")):
            raise HTTPException(422, "Accept the required declarations before submitting.")
        file = form.get("proposal")
        filename = file.filename if isinstance(file, UploadFile) else None
        if not filename or Path(filename).suffix.lower() not in {".pdf", ".txt"}:
            raise HTTPException(422, "Attach a PDF or TXT proposal.")
        data = await file.read(MAX_FILE + 1)
        if not data or len(data) > MAX_FILE:
            raise HTTPException(422, "Attach a file up to 10 MB.")
    today = date.today()
    reference = f"CG-{today.year}-{uuid4().hex[:8].upper()}"
    DATA.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DATA / "civicgrid.sqlite3") as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS applications (
                reference TEXT PRIMARY KEY, received TEXT NOT NULL, fields TEXT NOT NULL,
                proposal_name TEXT NOT NULL, proposal BLOB NOT NULL
            )
        """)
        await db.execute("INSERT INTO applications VALUES (?, ?, ?, ?, ?)",
                         (reference, today.isoformat(), json.dumps(values), filename, data))
        await db.commit()
    return {"reference": reference, "received": today.isoformat()}
