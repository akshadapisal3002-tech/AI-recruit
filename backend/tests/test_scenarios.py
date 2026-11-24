"""End-to-end tests of the 12 mandatory scenarios at the service layer (no web server needed).
Run:  pytest -q      or      python -m tests.test_scenarios
"""
import json, os, tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_PATH=f"{_tmp}/t.db", UPLOAD_DIR=f"{_tmp}/up", LLM_API_KEY="", EMBEDDING_BACKEND="hash")

from app import db, services as s  

SAMPLES = Path(__file__).resolve().parents[2] / "sample_data"
S = {}


def setup_module(_=None):
    db.init_db()
    S["admin"] = s.create_user("admin@example.com", "Admin#12345", "Admin", "admin")
    S["iv"] = s.create_user("iv@example.com", "Interv#12345", "Ivy Interviewer", "interviewer")
    S["c1"] = s.create_user("cand1@example.com", "Cand#12345", "Cand One", "candidate")
    S["c2"] = s.create_user("cand2@example.com", "Cand#12345", "Cand Two", "candidate")
    for j in json.loads((SAMPLES / "jobs.json").read_text()):
        S.setdefault("jobs", []).append(s.create_job(j))


def _upload(path, uploader, batch=None, candidate_id=None):
    rid = s.create_resume_record(path.name, path.read_bytes(), uploader, batch, candidate_id)
    return s.process_resume(rid)


def test_01_candidate_uploads_resume():
    cand = s.candidate_for_user(S["c1"]["id"])
    r = _upload(SAMPLES / "resumes" / "priya_nair.pdf", S["c1"]["id"], candidate_id=cand["id"])
    assert r["status"] == "Completed", r
    p = s.get_candidate(cand["id"])
    assert p["email"] == "cand1@example.com"            # account email is preserved
    assert "react" in p["skills"] and "node.js" in p["skills"] and p["experience"] and p["education"]
    assert p["total_experience_years"] > 3
    S["cand1_id"] = cand["id"]


def test_02_admin_uploads_five_resumes_individually():
    names = ["aarav_mehta.pdf", "rohan_kulkarni.pdf", "sneha_iyer.pdf", "karan_desai.pdf", "ananya_rao.pdf"]
    res = [_upload(SAMPLES / "resumes" / n, S["admin"]["id"], "batch1") for n in names]
    assert [r["status"] for r in res] == ["Completed"] * 5
    assert len({r["candidate_id"] for r in res}) == 5       # five distinct profiles
    assert _upload(SAMPLES / "resumes" / "vikram_singh.docx", S["admin"]["id"], "batch1")["status"] == "Completed"  # DOCX works


def test_03_invalid_files_do_not_affect_others():
    before = s.stats()["total_candidates"]
    bad = [_upload(SAMPLES / "invalid" / n, S["admin"]["id"], "batch2") for n in ("not_a_resume.txt", "corrupted.pdf", "empty.docx")]
    good = _upload(SAMPLES / "resumes" / "aarav_mehta_duplicate.docx", S["admin"]["id"], "batch2")
    assert [b["status"] for b in bad] == ["Failed"] * 3 and all(b["error"] for b in bad)
    assert good["status"] == "Completed"
    assert good["duplicate_of"] is not None                   # duplicate detected (same email/phone), no new profile
    assert s.stats()["total_candidates"] == before


def test_04_admin_creates_job():
    j = S["jobs"][0]
    assert j["title"] == "AI / LLM Engineer" and j["required_skills"] and j["min_experience"] == 2 and j["location"] == "Pune" and j["last_date"]


def test_05_matching_ranks_candidates():
    ms = s.run_matching(S["jobs"][0]["id"])
    top = ms[0]
    assert top["candidate_name"] in ("Rohan Kulkarni", "Vikram Singh"), [m["candidate_name"] for m in ms]
    assert top["score"] > ms[-1]["score"] and all(0 <= m["score"] <= 100 for m in ms)
    d = top["detail"]
    assert d["matched_skills"] and "reason" in d and d["experience"]["candidate_years"] > 0
    assert d["breakdown"]["semantic"] >= 0
    S["match"] = ms
    names = [m["candidate_name"] for m in ms]
    assert names.index("Sneha Iyer") > names.index("Rohan Kulkarni")        


def test_06_natural_language_search():
    r = s.search_candidates("python developer with LLM and embeddings experience in Pune")
    assert r["interpreted"]["skills"] and r["results"]
    assert r["results"][0]["name"] in ("Rohan Kulkarni", "Vikram Singh")
    assert "Has" in r["results"][0]["why"]


def test_07_candidate_profile_and_explanation():
    top = S["match"][0]
    prof = s.get_candidate(top["candidate_id"])
    assert prof["skills"] and prof["parse_method"] == "heuristic"
    assert top["detail"]["reason"] and "required skills" in top["detail"]["reason"]


def test_08_shortlist_job_specific():
    jid, top2 = S["jobs"][0]["id"], [m["candidate_id"] for m in S["match"][:2]]
    sl = s.shortlist(jid, top2)
    assert {m["candidate_id"] for m in sl} == set(top2) and all(m["status"] == "Shortlisted" for m in sl)
    assert not any(m["shortlisted"] for m in s.list_matches(S["jobs"][1]["id"]))      
    data, name = s.export_shortlist(jid, "csv")
    assert b"Candidate" in data and name.endswith(".csv")
    S["app"] = sl[0]["id"]


def test_09_approve_sends_notification():
    a = s.approve_for_interview(S["app"])
    assert a["status"] == "Approved for Interview"
    with db.db() as c:
        mail = c.execute("SELECT * FROM outbox WHERE to_email=? ORDER BY id DESC", (a["candidate_email"],)).fetchone()
    assert mail and "approved for an interview" in mail["subject"]


def test_10_schedule_interview_visible_to_candidate():
    a = s.get_application(S["app"])
    i = s.schedule_interview(a["id"], S["iv"]["id"], "2030-01-15T10:30", 45)
    assert i["status"] == "Scheduled"
    seen = s.candidate_interviews(a["candidate_id"])
    assert any(x["id"] == i["id"] for x in seen)
    try:
        s.schedule_interview(a["id"], S["iv"]["id"], "2030-01-15T10:45", 30); assert False, "clash not detected"
    except s.Invalid:
        pass
    S["iid"] = i["id"]


def test_11_interviewer_feedback():
    try:
        s.submit_feedback(S["iid"], S["admin"]["id"], 4, 4, 4, "x", "Hire"); assert False
    except s.Forbidden:
        pass
    f = s.submit_feedback(S["iid"], S["iv"]["id"], 4, 5, 4, "Strong fundamentals", "Hire")
    assert f["technical"] == 4 and f["recommendation"] == "Hire"
    assert any(x["interview_id"] == S["iid"] for x in s.all_feedback())


def test_12_candidate_cannot_access_other_profile():
    other = s.get_candidate(S["match"][0]["candidate_id"])
    me = s.candidate_for_user(S["c1"]["id"])
    s.assert_can_view_candidate(S["c1"], me["id"])             # own profile OK
    try:
        s.assert_can_view_candidate(S["c1"], other["id"]); assert False, "should be denied"
    except s.Forbidden:
        pass


# ---- extra: hallucination guard & human-in-the-loop ----
def test_hallucination_guard_drops_ungrounded_facts():
    from app.resume_parser import ground
    text = "Jane Doe\njane@example.com\nSKILLS\nPython, SQL\nEXPERIENCE\nData Analyst | Initech | Jan 2020 - Dec 2022\nBuilt reports in SQL."
    fake = {"name": "Jane Doe", "email": "jane@example.com", "phone": "+91 99999 99999", "skills": ["python", "Kubernetes", "SQL"],
            "experience": [{"title": "Data Analyst", "company": "Initech", "start": "Jan 2020", "end": "Dec 2022", "description": ""},
                           {"title": "CTO", "company": "Google", "start": "2015", "end": "2019", "description": ""}],
            "education": [{"degree": "PhD Physics", "institution": "MIT", "year": "2010"}], "projects": []}
    clean, warns = ground(fake, text)
    assert "kubernetes" not in clean["skills"] and clean["phone"] is None
    assert len(clean["experience"]) == 1 and not clean["education"] and clean["total_experience_years"] == 3.0
    assert len(warns) >= 4


def test_override_requires_reason():
    app = s.get_application(S["app"])
    try:
        s.override(app["id"], "Do not recommend", "", S["admin"]["id"]); assert False
    except s.Invalid:
        pass
    a = s.override(app["id"], "Do not recommend", "Salary expectation mismatch", S["admin"]["id"])
    assert a["override_decision"] == "Do not recommend" and a["ai_recommendation"]       # AI output preserved alongside override


if __name__ == "__main__":
    setup_module()
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print("PASS", name)
            except Exception as e:
                fails += 1; print("FAIL", name, "->", repr(e))
    raise SystemExit(1 if fails else 0)
