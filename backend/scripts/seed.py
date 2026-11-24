"""Seeds demo users, jobs and the sample resumes. Usage (from backend/):  python -m scripts.seed"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import services as s
from app.db import init_db

SAMPLES = Path(__file__).resolve().parents[2] / "sample_data"
init_db()
for email, pw, name, role in [("admin@demo.com", "Admin@12345", "Demo Admin", "admin"),
                              ("interviewer@demo.com", "Interviewer@12345", "Demo Interviewer", "interviewer"),
                              ("candidate@demo.com", "Candidate@12345", "Demo Candidate", "candidate")]:
    try: s.create_user(email, pw, name, role); print("created", email)
    except s.Invalid as e: print("skip", email, "-", e)
if not s.list_jobs():
    for j in json.loads((SAMPLES / "jobs.json").read_text()): s.create_job(j)
    print("jobs created")
admin = s.list_users("admin")[0]["id"]
for f in sorted((SAMPLES / "resumes").glob("*")):
    r = s.process_resume(s.create_resume_record(f.name, f.read_bytes(), admin, "seed"))
    print(f.name, "->", r["status"], r.get("error") or "")
