"""Runs the 12 mandatory scenarios against a RUNNING server over HTTP.
Usage (server started with the demo seed):  python -m scripts.run_api_scenarios [http://localhost:8000]
"""
import sys, time
from pathlib import Path
import requests

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
SAMPLES = Path(__file__).resolve().parents[2] / "sample_data"
results = []


def check(n, name, ok, detail=""):
    results.append(ok); print(f"{'PASS' if ok else 'FAIL'}  #{n:<2} {name}  {detail}")


def login(email, pw):
    r = requests.post(f"{BASE}/auth/login", json={"email": email, "password": pw}); r.raise_for_status()
    return {"Authorization": "Bearer " + r.json()["token"]}


def wait(path, headers, done):
    for _ in range(60):
        d = requests.get(BASE + path, headers=headers).json()
        if done(d): return d
        time.sleep(1)
    return d


adm, iv = login("admin@demo.com", "Admin@12345"), login("interviewer@demo.com", "Interviewer@12345")
tag = str(int(time.time()))
r = requests.post(f"{BASE}/auth/register", json={"email": f"t{tag}@example.com", "password": "Passw0rd!x", "name": "Test Candidate"}); cand = {"Authorization": "Bearer " + r.json()["token"]}
r2 = requests.post(f"{BASE}/auth/register", json={"email": f"u{tag}@example.com", "password": "Passw0rd!x", "name": "Other Candidate"}); other = {"Authorization": "Bearer " + r2.json()["token"]}

# 1
with open(SAMPLES / "resumes/vikram_singh.docx", "rb") as f:
    rid = requests.post(f"{BASE}/me/resume", headers=cand, files={"file": f}).json()["id"]
wait(f"/me/resume/{rid}", cand, lambda d: d["status"] != "Processing")
prof = requests.get(f"{BASE}/me/profile", headers=cand).json()
check(1, "Candidate uploads a resume", bool(prof["skills"]) and bool(prof["experience"]), f"skills={prof['skills'][:4]}")
# 2
files = [("files", (p.name, p.read_bytes())) for p in sorted((SAMPLES / "resumes").glob("*.pdf"))[:5]]
b = requests.post(f"{BASE}/admin/resumes/bulk", headers=adm, files=files).json()
lst = wait(f"/admin/resumes?batch_id={b['batch_id']}", adm, lambda d: all(x["status"] != "Processing" for x in d))
check(2, "Admin uploads 5 resumes", len(lst) == 5 and all(x["status"] == "Completed" for x in lst), str([x["status"] for x in lst]))
# 3
files = [("files", ("not_a_resume.txt", b"hello")), ("files", ("corrupted.pdf", (SAMPLES / "invalid/corrupted.pdf").read_bytes())), ("files", ("karan_desai.pdf", (SAMPLES / "resumes/karan_desai.pdf").read_bytes()))]
b = requests.post(f"{BASE}/admin/resumes/bulk", headers=adm, files=files).json()
lst = wait(f"/admin/resumes?batch_id={b['batch_id']}", adm, lambda d: all(x["status"] != "Processing" for x in d))
st = {x["filename"]: x["status"] for x in lst}
check(3, "Invalid file handled without affecting others", st.get("not_a_resume.txt") == "Failed" and st.get("corrupted.pdf") == "Failed" and st.get("karan_desai.pdf") == "Completed", str(st))
# 4
job = requests.post(f"{BASE}/admin/jobs", headers=adm, json={"title": f"Test AI Engineer {tag}", "description": "Build LLM apps with Python, RAG and embeddings.", "required_skills": ["python", "llm", "rag"], "preferred_skills": ["docker"], "min_experience": 2, "max_experience": 6, "education": "Bachelor's degree", "location": "Pune", "last_date": "2030-01-01"}).json()
check(4, "Admin creates a job", "id" in job and job["required_skills"] == ["python", "llm", "rag"])
# 5
ms = requests.post(f"{BASE}/admin/jobs/{job['id']}/match", headers=adm).json()
check(5, "Matching ranks candidates with scores", len(ms) > 1 and ms[0]["score"] >= ms[-1]["score"], f"top={ms[0]['candidate_name']} {ms[0]['score']}")
# 6
sr = requests.post(f"{BASE}/admin/search", headers=adm, json={"query": "python developer with LLM and embeddings experience"}).json()
check(6, "Natural-language semantic search", bool(sr["results"]), f"top={sr['results'][0]['name']}")
# 7
cid = ms[0]["candidate_id"]; d = requests.get(f"{BASE}/candidates/{cid}", headers=adm).json()
check(7, "Candidate profile + matching explanation", bool(d.get("skills")) and any(a.get("detail") for a in d["applications"]))
# 8
sl = requests.post(f"{BASE}/admin/shortlist", headers=adm, json={"job_id": job["id"], "candidate_ids": [m["candidate_id"] for m in ms[:2]]}).json()
check(8, "Shortlist is job-specific", len(sl) == 2 and all(x["status"] == "Shortlisted" for x in sl))
# 9
aid = sl[0]["id"]; ap = requests.post(f"{BASE}/admin/applications/{aid}/approve", headers=adm).json()
check(9, "Approve -> notification (outbox/SMTP)", ap["status"] == "Approved for Interview")
# 10
iv_id = requests.get(f"{BASE}/admin/users?role=interviewer", headers=adm).json()[0]["id"]
when = (time.strftime("%Y") and "2030-03-01T10:00")
i = requests.post(f"{BASE}/admin/interviews", headers=adm, json={"application_id": aid, "interviewer_id": iv_id, "scheduled_at": when, "duration_min": 45}).json()
check(10, "Schedule interview", i.get("status") == "Scheduled", str(i)[:80])
# 11
fb = requests.post(f"{BASE}/interviewer/interviews/{i['id']}/feedback", headers=iv, json={"technical": 4, "communication": 4, "problem_solving": 5, "remarks": "Good", "recommendation": "Hire"})
allfb = requests.get(f"{BASE}/admin/feedback", headers=adm).json()
check(11, "Interviewer feedback stored & visible to admin", fb.status_code == 200 and any(x["interview_id"] == i["id"] for x in allfb))
# 12
me = requests.get(f"{BASE}/me/profile", headers=cand).json()
r = requests.get(f"{BASE}/candidates/{me['id']}", headers=other)
check(12, "Candidate cannot access another candidate's profile", r.status_code == 403, f"HTTP {r.status_code}")
print(f"\n{sum(results)}/{len(results)} scenarios passed"); sys.exit(0 if all(results) else 1)
