"""Business logic. main.py stays a thin HTTP layer so this can be unit-tested without a web server."""
import csv, io, json, os, re, secrets, uuid
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from . import config, embeddings, matching, resume_parser
from .db import CANDIDATE_JSON, JOB_JSON, db, row, rows
from .mailer import send_email
from .security import hash_password, verify_password
from .skills import canonical, extract_skills

class NotFound(Exception): pass
class Forbidden(Exception): pass
class Invalid(Exception): pass

STATUSES = ["Matched", "Applied", "Shortlisted", "Approved for Interview", "Interview Scheduled", "Selected", "On Hold", "Rejected"]


def _now(): return datetime.utcnow().isoformat(timespec="seconds")


# ---------------- users ----------------
def create_user(email, password, name, role="candidate"):
    email = email.strip().lower()
    if len(password) < 8:
        raise Invalid("Password must be at least 8 characters")
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise Invalid("Invalid email address")
    with db() as c:
        if c.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            raise Invalid("Email already registered")
        uid = c.execute("INSERT INTO users(email,password_hash,name,role) VALUES(?,?,?,?)",
                        (email, hash_password(password), name.strip(), role)).lastrowid
        if role == "candidate":
            c.execute("INSERT INTO candidates(user_id,name,email) VALUES(?,?,?)", (uid, name.strip(), email))
    return get_user(uid)


def get_user(uid):
    with db() as c:
        r = c.execute("SELECT id,email,name,role,created_at FROM users WHERE id=?", (uid,)).fetchone()
    if not r: raise NotFound("User not found")
    return row(r)


def authenticate(email, password):
    with db() as c:
        r = c.execute("SELECT * FROM users WHERE email=?", (email.strip().lower(),)).fetchone()
    if not r or not verify_password(password, r["password_hash"]):
        return None
    return get_user(r["id"])


def list_users(role=None):
    with db() as c:
        q, a = "SELECT id,email,name,role FROM users", ()
        if role: q, a = q + " WHERE role=?", (role,)
        return rows(c.execute(q + " ORDER BY name", a).fetchall())


# ---------------- candidates ----------------
def get_candidate(cid):
    with db() as c:
        r = c.execute("SELECT * FROM candidates WHERE id=?", (cid,)).fetchone()
    if not r: raise NotFound("Candidate not found")
    d = row(r, CANDIDATE_JSON); d.pop("embedding", None)
    return d


def candidate_for_user(uid):
    with db() as c:
        r = c.execute("SELECT id FROM candidates WHERE user_id=?", (uid,)).fetchone()
    if not r: raise NotFound("Candidate profile not found")
    return get_candidate(r["id"])


def assert_can_view_candidate(user: dict, cid: int):
    """Scenario 12: a candidate may only read their own profile."""
    if user["role"] == "admin":
        return
    if user["role"] == "candidate":
        if get_candidate(cid).get("user_id") != user["id"]:
            raise Forbidden("You can only access your own profile")
        return
    if user["role"] == "interviewer":  # only candidates they are assigned to interview
        with db() as c:
            ok = c.execute("""SELECT 1 FROM interviews i JOIN applications a ON a.id=i.application_id
                              WHERE i.interviewer_id=? AND a.candidate_id=?""", (user["id"], cid)).fetchone()
        if not ok: raise Forbidden("Not assigned to this candidate")
        return
    raise Forbidden("Access denied")


def _persist_embedding(conn, cid):
    r = conn.execute("SELECT * FROM candidates WHERE id=?", (cid,)).fetchone()
    cand = row(r, CANDIDATE_JSON)
    conn.execute("UPDATE candidates SET embedding=? WHERE id=?", (json.dumps(embeddings.embed(embeddings.candidate_text(cand))), cid))


def update_candidate(cid, data: dict, reviewed=True):
    allowed = {"name", "phone", "location", "summary", "education", "experience", "skills", "projects"}
    sets, vals = [], []
    data = dict(data)
    if "experience" in data:
        for e in data["experience"]:
            e["years"] = resume_parser.entry_years(e)
        sets.append("total_experience_years=?"); vals.append(resume_parser.total_years(data["experience"]))
    if "skills" in data:
        data["skills"] = [canonical(s) for s in data["skills"] if str(s).strip()]
    for k, v in data.items():
        if k in allowed:
            sets.append(f"{k}=?"); vals.append(json.dumps(v) if k in CANDIDATE_JSON else v)
    if not sets: raise Invalid("No editable fields supplied")
    with db() as c:
        if not c.execute("SELECT 1 FROM candidates WHERE id=?", (cid,)).fetchone(): raise NotFound("Candidate not found")
        c.execute(f"UPDATE candidates SET {','.join(sets)}, reviewed=?, updated_at=? WHERE id=?", (*vals, int(reviewed), _now(), cid))
        _persist_embedding(c, cid)
    return get_candidate(cid)


def find_duplicate(parsed: dict, exclude_id=None):
    with db() as c:
        cands = rows(c.execute("SELECT id,name,email,phone,skills FROM candidates WHERE parse_method IS NOT NULL").fetchall(), ("skills",))
    phone = re.sub(r"\D", "", parsed.get("phone") or "")[-10:]
    for x in cands:
        if x["id"] == exclude_id: continue
        if parsed.get("email") and x["email"] and parsed["email"].lower() == x["email"].lower(): return x["id"]
        if phone and len(phone) >= 10 and phone == re.sub(r"\D", "", x["phone"] or "")[-10:]: return x["id"]
        if parsed.get("name") and x["name"] and SequenceMatcher(None, parsed["name"].lower(), x["name"].lower()).ratio() > 0.95:
            a, b = set(parsed.get("skills") or []), set(x["skills"] or [])
            if a and b and len(a & b) / len(a | b) > 0.7: return x["id"]
    return None


# ---------------- resumes ----------------
def create_resume_record(filename, data: bytes, uploaded_by, batch_id=None, candidate_id=None):
    """Store the file and a Processing row. Validation failures are recorded as Failed (never raised) so a
    bad file in a batch cannot affect the others."""
    Path(config.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", os.path.basename(filename or "resume"))
    path, status, err = os.path.join(config.UPLOAD_DIR, f"{uuid.uuid4().hex}_{safe}"), "Processing", None
    ext = safe.lower().rsplit(".", 1)[-1] if "." in safe else ""
    if ext not in ("pdf", "docx"): status, err = "Failed", f"Unsupported file type '.{ext}'. Only PDF and DOCX are accepted"
    elif not data: status, err = "Failed", "Empty file"
    elif len(data) > config.MAX_UPLOAD_BYTES: status, err = "Failed", "File larger than 5 MB"
    if status != "Failed":
        with open(path, "wb") as f: f.write(data)
    with db() as c:
        rid = c.execute("INSERT INTO resumes(candidate_id,uploaded_by,filename,path,batch_id,status,error) VALUES(?,?,?,?,?,?,?)",
                        (candidate_id, uploaded_by, safe, path if status != "Failed" else None, batch_id, status, err)).lastrowid
    return rid


def get_resume(rid):
    with db() as c:
        r = c.execute("SELECT * FROM resumes WHERE id=?", (rid,)).fetchone()
    if not r: raise NotFound("Resume not found")
    return row(r)


def process_resume(rid):
    """Parse one resume. Always ends in Completed or Failed; never raises."""
    r = get_resume(rid)
    if r["status"] == "Failed": return r
    try:
        data = open(r["path"], "rb").read()
        text = resume_parser.extract_text(data, r["filename"])
        parsed, warnings, method = resume_parser.parse_resume(text)
        own = r["candidate_id"]  # set when a candidate uploads their own resume
        dup = find_duplicate(parsed, exclude_id=own)
        if own is None and dup:
            with db() as c:
                c.execute("UPDATE resumes SET status='Completed', candidate_id=?, duplicate_of=?, error=? WHERE id=?",
                          (dup, dup, f"Duplicate of candidate #{dup}; no new profile created", rid))
            return get_resume(rid)
        with db() as c:
            if own is None:
                if not parsed.get("email") and not parsed.get("name"):
                    raise resume_parser.ResumeError("Could not identify a candidate (no name or email found)")
                own = c.execute("INSERT INTO candidates(name,email) VALUES(?,?)", (parsed.get("name"), parsed.get("email"))).lastrowid
            existing = c.execute("SELECT email,name,user_id FROM candidates WHERE id=?", (own,)).fetchone()
            email = existing["email"] if existing["user_id"] else (parsed.get("email") or existing["email"])
            name = parsed.get("name") or existing["name"]
            c.execute("""UPDATE candidates SET name=?,email=?,phone=?,location=?,summary=?,education=?,experience=?,skills=?,projects=?,
                         total_experience_years=?,parse_warnings=?,parse_method=?,reviewed=0,updated_at=? WHERE id=?""",
                      (name, email, parsed.get("phone"), parsed.get("location"), parsed.get("summary"),
                       json.dumps(parsed["education"]), json.dumps(parsed["experience"]), json.dumps(parsed["skills"]),
                       json.dumps(parsed["projects"]), parsed["total_experience_years"], json.dumps(warnings), method, _now(), own))
            _persist_embedding(c, own)
            c.execute("UPDATE resumes SET status='Completed', candidate_id=?, error=NULL WHERE id=?", (own, rid))
        return get_resume(rid)
    except Exception as e:
        with db() as c:
            c.execute("UPDATE resumes SET status='Failed', error=? WHERE id=?", (str(e)[:500], rid))
    return get_resume(rid)


def list_resumes(batch_id=None):
    with db() as c:
        q = """SELECT r.*, c.name AS candidate_name FROM resumes r LEFT JOIN candidates c ON c.id=r.candidate_id"""
        rs = c.execute(q + (" WHERE r.batch_id=?" if batch_id else "") + " ORDER BY r.id DESC", (batch_id,) if batch_id else ()).fetchall()
    return rows(rs)


# ---------------- jobs ----------------
def _job_fields(d):
    out = dict(d)
    for k in JOB_JSON: out[k] = [canonical(s) for s in out.get(k, []) if str(s).strip()]
    return out


def get_job(jid):
    with db() as c:
        r = c.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
    if not r: raise NotFound("Job not found")
    d = row(r, JOB_JSON); d.pop("embedding", None)
    return d


def _job_with_vec(jid):
    with db() as c:
        r = c.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
    if not r: raise NotFound("Job not found")
    d = row(r, JOB_JSON)
    d["embedding"] = json.loads(d["embedding"]) if d.get("embedding") else None
    return d


def create_job(d):
    d = _job_fields(d)
    if d.get("max_experience") is not None and d["max_experience"] < d.get("min_experience", 0):
        raise Invalid("max_experience cannot be less than min_experience")
    vec = json.dumps(embeddings.embed(embeddings.job_text(d)))
    with db() as c:
        jid = c.execute("""INSERT INTO jobs(title,description,required_skills,preferred_skills,min_experience,max_experience,education,
                           location,employment_type,last_date,status,embedding) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (d["title"], d["description"], json.dumps(d["required_skills"]), json.dumps(d["preferred_skills"]),
                         d.get("min_experience", 0), d.get("max_experience"), d.get("education"), d.get("location"),
                         d.get("employment_type", "Full-time"), d.get("last_date"), d.get("status", "Open"), vec)).lastrowid
    return get_job(jid)


def update_job(jid, d):
    cur = get_job(jid); cur.update({k: v for k, v in _job_fields(d).items() if v is not None or k == "max_experience"})
    with db() as c:
        c.execute("""UPDATE jobs SET title=?,description=?,required_skills=?,preferred_skills=?,min_experience=?,max_experience=?,education=?,
                     location=?,employment_type=?,last_date=?,status=?,embedding=? WHERE id=?""",
                  (cur["title"], cur["description"], json.dumps(cur["required_skills"]), json.dumps(cur["preferred_skills"]),
                   cur["min_experience"], cur["max_experience"], cur["education"], cur["location"], cur["employment_type"],
                   cur["last_date"], cur["status"], json.dumps(embeddings.embed(embeddings.job_text(cur))), jid))
    return get_job(jid)


def delete_job(jid):
    get_job(jid)
    with db() as c: c.execute("DELETE FROM jobs WHERE id=?", (jid,))


def list_jobs(open_only=False):
    with db() as c:
        q = "SELECT * FROM jobs" + (" WHERE status='Open' AND (last_date IS NULL OR last_date='' OR last_date>=date('now'))" if open_only else "") + " ORDER BY id DESC"
        out = rows(c.execute(q).fetchall(), JOB_JSON)
    for j in out: j.pop("embedding", None)
    return out


# ---------------- matching ----------------
def _all_candidates_with_vec():
    with db() as c:
        rs = c.execute("SELECT * FROM candidates WHERE parse_method IS NOT NULL").fetchall()
    out = []
    for r in rs:
        d = row(r, CANDIDATE_JSON); d["embedding"] = json.loads(d["embedding"]) if d.get("embedding") else None; out.append(d)
    return out


def run_matching(jid):
    job = _job_with_vec(jid)
    qv = job["embedding"] or embeddings.embed(embeddings.job_text(job))
    results = []
    with db() as c:
        for cand in _all_candidates_with_vec():
            cos = embeddings.cosine(qv, cand["embedding"]) if cand["embedding"] else 0.0
            m = matching.score_candidate(cand, job, cos)
            ex = c.execute("SELECT id FROM applications WHERE job_id=? AND candidate_id=?", (jid, cand["id"])).fetchone()
            if ex:
                c.execute("UPDATE applications SET score=?,detail=?,ai_recommendation=?,updated_at=? WHERE id=?",
                          (m["score"], json.dumps(m), m["label"], _now(), ex["id"]))
            else:
                c.execute("INSERT INTO applications(job_id,candidate_id,status,score,detail,ai_recommendation) VALUES(?,?,?,?,?,?)",
                          (jid, cand["id"], "Matched", m["score"], json.dumps(m), m["label"]))
    return list_matches(jid)


def list_matches(jid, min_score=0):
    get_job(jid)
    with db() as c:
        rs = c.execute("""SELECT a.*, c.name AS candidate_name, c.email AS candidate_email, c.location, c.skills, c.total_experience_years
                          FROM applications a JOIN candidates c ON c.id=a.candidate_id
                          WHERE a.job_id=? AND IFNULL(a.score,0)>=? ORDER BY a.score DESC""", (jid, min_score)).fetchall()
    out = rows(rs, ("detail", "skills"))
    return out


def get_application(aid):
    with db() as c:
        r = c.execute("""SELECT a.*, c.name AS candidate_name, c.email AS candidate_email, j.title AS job_title
                         FROM applications a JOIN candidates c ON c.id=a.candidate_id JOIN jobs j ON j.id=a.job_id WHERE a.id=?""", (aid,)).fetchone()
    if not r: raise NotFound("Application not found")
    return row(r, ("detail",))


def candidate_application_for_job(cid, jid):
    with db() as c:
        r = c.execute("SELECT id FROM applications WHERE candidate_id=? AND job_id=?", (cid, jid)).fetchone()
    return get_application(r["id"]) if r else None


def apply_to_job(cid, jid):
    job = get_job(jid)
    if job["status"] != "Open" or (job.get("last_date") and job["last_date"] < datetime.utcnow().date().isoformat()):
        raise Invalid("This job is not open for applications")
    cand = get_candidate(cid)
    if not cand.get("parse_method"): raise Invalid("Upload your resume before applying")
    with db() as c:
        ex = c.execute("SELECT id,status,applied FROM applications WHERE job_id=? AND candidate_id=?", (jid, cid)).fetchone()
        if ex and ex["applied"]: raise Invalid("You have already applied to this job")
        if ex: c.execute("UPDATE applications SET applied=1,status=CASE WHEN status='Matched' THEN 'Applied' ELSE status END,updated_at=? WHERE id=?", (_now(), ex["id"]))
        else: c.execute("INSERT INTO applications(job_id,candidate_id,status,applied) VALUES(?,?,'Applied',1)", (jid, cid))
    run_matching(jid)  # scores the new application (and refreshes others)
    return candidate_application_for_job(cid, jid)


def candidate_applications(cid):
    with db() as c:
        rs = c.execute("""SELECT a.id,a.job_id,a.status,a.applied,a.updated_at,j.title AS job_title,j.location FROM applications a
                          JOIN jobs j ON j.id=a.job_id WHERE a.candidate_id=? AND a.status!='Matched' ORDER BY a.updated_at DESC""", (cid,)).fetchall()
    return rows(rs)


# ---------------- NL search ----------------
LOC_RE = re.compile(r"\b(?:in|from|based in|located in)\s+([A-Z][a-zA-Z]+(?:\s[A-Z][a-zA-Z]+)?)")


def search_candidates(query: str, limit=20):
    if not query.strip(): raise Invalid("Query is empty")
    qskills = extract_skills(query)
    m = re.search(r"(\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?)", query, re.I)
    min_years = float(m.group(1)) if m else None
    loc = (LOC_RE.search(query) or [None, None])[1]
    qv = embeddings.embed(query)
    cands = {c["id"]: c for c in _all_candidates_with_vec()}
    hits = embeddings.top_k(qv, [(i, c["embedding"]) for i, c in cands.items() if c["embedding"]], k=len(cands))
    out = []
    for cid, cos in hits:
        c = cands[cid]; have = matching.candidate_skill_set(c)
        sem = embeddings.calibrate(cos)
        overlap = [s for s in qskills if s in have]
        score = 0.55 * sem + 0.45 * (len(overlap) / len(qskills) if qskills else sem)
        reasons = []
        if overlap: reasons.append("Has " + ", ".join(overlap))
        miss = [s for s in qskills if s not in have]
        if miss: reasons.append("No evidence of " + ", ".join(miss))
        if min_years is not None:
            if c["total_experience_years"] >= min_years: reasons.append(f"{c['total_experience_years']:g} yrs experience (>= {min_years:g})")
            else: score *= 0.7; reasons.append(f"{c['total_experience_years']:g} yrs experience (< {min_years:g})")
        if loc:
            if loc.lower() in (c.get("location") or "").lower(): reasons.append(f"Located in {loc}"); score += 0.05
            else: score *= 0.85
        out.append({"candidate_id": cid, "name": c["name"], "email": c["email"], "location": c["location"],
                    "skills": c["skills"], "years": c["total_experience_years"], "score": round(min(score, 1) * 100, 1),
                    "semantic_similarity": round(sem, 3), "why": "; ".join(reasons) or "Semantic similarity to query"})
    out.sort(key=lambda x: -x["score"])
    return {"interpreted": {"skills": qskills, "min_years": min_years, "location": loc}, "results": [o for o in out if o["score"] > 5][:limit]}


def filter_candidates(skill=None, min_exp=None, location=None, q=None, sort="name"):
    cands = _all_candidates_with_vec()
    out = []
    for c in cands:
        if skill and not all(canonical(s) in matching.candidate_skill_set(c) for s in skill.split(",") if s.strip()): continue
        if min_exp is not None and c["total_experience_years"] < min_exp: continue
        if location and location.lower() not in (c.get("location") or "").lower(): continue
        if q and q.lower() not in f"{c['name']} {c['email']}".lower(): continue
        c.pop("embedding", None); out.append(c)
    out.sort(key=lambda c: (-c["total_experience_years"]) if sort == "experience" else (c["name"] or "").lower())
    return out


# ---------------- notes / shortlisting / approvals ----------------
def add_note(cid, author_id, text):
    get_candidate(cid)
    if not text.strip(): raise Invalid("Note is empty")
    with db() as c: c.execute("INSERT INTO notes(candidate_id,author_id,text) VALUES(?,?,?)", (cid, author_id, text.strip()))
    return list_notes(cid)


def list_notes(cid):
    with db() as c:
        return rows(c.execute("SELECT n.*,u.name AS author FROM notes n LEFT JOIN users u ON u.id=n.author_id WHERE candidate_id=? ORDER BY n.id DESC", (cid,)).fetchall())


def set_status(aid, status):
    if status not in STATUSES: raise Invalid(f"Status must be one of {STATUSES}")
    a = get_application(aid)
    with db() as c: c.execute("UPDATE applications SET status=?,updated_at=? WHERE id=?", (status, _now(), aid))
    if status in ("Selected", "Rejected"):
        send_email(a["candidate_email"], f"Application update: {a['job_title']}",
                   f"Hello {a['candidate_name']},\n\nYour application for {a['job_title']} has been updated to: {status}.\n")
    return get_application(aid)


def shortlist(jid, candidate_ids):
    get_job(jid)
    if not candidate_ids: raise Invalid("Select at least one candidate")
    run = False
    with db() as c:
        for cid in candidate_ids:
            ex = c.execute("SELECT id,status FROM applications WHERE job_id=? AND candidate_id=?", (jid, cid)).fetchone()
            if not ex: c.execute("INSERT INTO applications(job_id,candidate_id,status,shortlisted) VALUES(?,?,'Shortlisted',1)", (jid, cid)); run = True
            else: c.execute("UPDATE applications SET shortlisted=1,status=CASE WHEN status IN ('Matched','Applied') THEN 'Shortlisted' ELSE status END,updated_at=? WHERE id=?", (_now(), ex["id"]))
    if run: run_matching(jid)
    return [m for m in list_matches(jid) if m["shortlisted"]]


def approve_for_interview(aid):
    a = get_application(aid)
    if a["status"] not in ("Shortlisted", "Applied", "Matched", "On Hold"):
        raise Invalid(f"Cannot approve an application in status '{a['status']}'")
    set_status(aid, "Approved for Interview")
    send_email(a["candidate_email"], f"You've been approved for an interview: {a['job_title']}",
               f"Hello {a['candidate_name']},\n\nGood news - you have been approved for an interview for {a['job_title']}. "
               "We will send the schedule shortly. You can track your status in the candidate portal.\n")
    return get_application(aid)


def override(aid, decision, reason, admin_id):
    """Human-in-the-loop: admin overrides the AI recommendation, with a mandatory reason."""
    if decision not in ("Recommend", "Do not recommend", "Clear"): raise Invalid("Decision must be Recommend, Do not recommend or Clear")
    if decision != "Clear" and not (reason or "").strip(): raise Invalid("A reason is required to override the AI recommendation")
    get_application(aid)
    with db() as c:
        if decision == "Clear": c.execute("UPDATE applications SET override_decision=NULL,override_reason=NULL,override_by=NULL WHERE id=?", (aid,))
        else: c.execute("UPDATE applications SET override_decision=?,override_reason=?,override_by=?,updated_at=? WHERE id=?", (decision, reason.strip(), admin_id, _now(), aid))
    return get_application(aid)


def export_shortlist(jid, fmt="csv"):
    job, ms = get_job(jid), [m for m in list_matches(jid) if m["shortlisted"]]
    header = ["Candidate", "Email", "Location", "Experience (yrs)", "Score", "AI Recommendation", "Admin Override", "Matched skills", "Missing skills", "Status"]
    data = [[m["candidate_name"], m["candidate_email"], m["location"], m["total_experience_years"], m["score"], m["ai_recommendation"],
             m["override_decision"] or "", ", ".join((m["detail"] or {}).get("matched_skills", [])), ", ".join((m["detail"] or {}).get("missing_skills", [])), m["status"]] for m in ms]
    if fmt == "xlsx":
        import openpyxl
        wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Shortlist"; ws.append(header)
        for r in data: ws.append(r)
        buf = io.BytesIO(); wb.save(buf); return buf.getvalue(), f"shortlist_job{jid}.xlsx"
    buf = io.StringIO(); w = csv.writer(buf); w.writerow(header); w.writerows(data)
    return buf.getvalue().encode(), f"shortlist_job{jid}.csv"


def create_share_link(jid, admin_id, hours=72):
    get_job(jid); token = secrets.token_urlsafe(24)
    with db() as c: c.execute("INSERT INTO share_links(token,job_id,expires_at,created_by) VALUES(?,?,?,?)", (token, jid, (datetime.utcnow() + timedelta(hours=hours)).isoformat(), admin_id))
    return {"token": token, "path": f"/shared/{token}", "expires_in_hours": hours}


def shared_shortlist(token):
    with db() as c: r = c.execute("SELECT * FROM share_links WHERE token=?", (token,)).fetchone()
    if not r or r["expires_at"] < datetime.utcnow().isoformat(): raise NotFound("Link is invalid or has expired")
    # read-only, minimised view: no contact details
    return {"job": get_job(r["job_id"])["title"], "candidates": [
        {"name": m["candidate_name"], "score": m["score"], "experience_years": m["total_experience_years"],
         "skills": m["skills"], "recommendation": m["ai_recommendation"], "reason": (m["detail"] or {}).get("reason")}
        for m in list_matches(r["job_id"]) if m["shortlisted"]]}


# ---------------- interviews ----------------
def _interview_view(r): return row(r)


def interview_rows(where="", args=()):
    with db() as c:
        rs = c.execute(f"""SELECT i.*, a.candidate_id, a.job_id, cd.name AS candidate_name, cd.email AS candidate_email,
                           j.title AS job_title, u.name AS interviewer_name, (SELECT 1 FROM feedback f WHERE f.interview_id=i.id) AS has_feedback
                           FROM interviews i JOIN applications a ON a.id=i.application_id JOIN candidates cd ON cd.id=a.candidate_id
                           JOIN jobs j ON j.id=a.job_id JOIN users u ON u.id=i.interviewer_id {where} ORDER BY i.scheduled_at""", args).fetchall()
    return rows(rs)


def schedule_interview(aid, interviewer_id, scheduled_at, duration_min=45, mode="Online", meeting_link=None):
    a = get_application(aid)
    try: when = datetime.fromisoformat(scheduled_at)
    except ValueError: raise Invalid("scheduled_at must be an ISO datetime, e.g. 2026-12-01T10:30")
    if when < datetime.now(): raise Invalid("Interview time must be in the future")
    if get_user(interviewer_id)["role"] != "interviewer": raise Invalid("Selected user is not an interviewer")
    with db() as c:
        clash = c.execute("""SELECT 1 FROM interviews WHERE interviewer_id=? AND status='Scheduled' AND
                             datetime(scheduled_at) < datetime(?, '+' || ? || ' minutes') AND datetime(scheduled_at, '+' || duration_min || ' minutes') > datetime(?)""",
                          (interviewer_id, scheduled_at, duration_min, scheduled_at)).fetchone()
        if clash: raise Invalid("Interviewer already has an interview in that time slot")
        iid = c.execute("INSERT INTO interviews(application_id,interviewer_id,scheduled_at,duration_min,mode,meeting_link) VALUES(?,?,?,?,?,?)",
                        (aid, interviewer_id, scheduled_at, duration_min, mode, meeting_link)).lastrowid
        c.execute("UPDATE applications SET status='Interview Scheduled',updated_at=? WHERE id=?", (_now(), aid))
    send_email(a["candidate_email"], f"Interview scheduled: {a['job_title']}",
               f"Hello {a['candidate_name']},\n\nYour interview for {a['job_title']} is scheduled for {scheduled_at} ({duration_min} minutes, {mode})."
               + (f"\nLink: {meeting_link}" if meeting_link else "") + "\n")
    return interview_rows("WHERE i.id=?", (iid,))[0]


def update_interview(iid, scheduled_at=None, duration_min=None, cancel=False):
    cur = interview_rows("WHERE i.id=?", (iid,))
    if not cur: raise NotFound("Interview not found")
    cur = cur[0]
    if cur["status"] != "Scheduled": raise Invalid(f"Interview is {cur['status']} and cannot be changed")
    with db() as c:
        if cancel:
            c.execute("UPDATE interviews SET status='Cancelled' WHERE id=?", (iid,))
            c.execute("UPDATE applications SET status='Approved for Interview',updated_at=? WHERE id=?", (_now(), cur["application_id"]))
            subj, body = f"Interview cancelled: {cur['job_title']}", "Your interview has been cancelled. We will contact you about a new time."
        else:
            if scheduled_at:
                try: datetime.fromisoformat(scheduled_at)
                except ValueError: raise Invalid("scheduled_at must be an ISO datetime")
            c.execute("UPDATE interviews SET scheduled_at=?,duration_min=? WHERE id=?", (scheduled_at or cur["scheduled_at"], duration_min or cur["duration_min"], iid))
            subj, body = f"Interview rescheduled: {cur['job_title']}", f"Your interview is now scheduled for {scheduled_at or cur['scheduled_at']}."
    send_email(cur["candidate_email"], subj, f"Hello {cur['candidate_name']},\n\n{body}\n")
    return interview_rows("WHERE i.id=?", (iid,))[0]


def submit_feedback(iid, interviewer_id, technical, communication, problem_solving, remarks, recommendation):
    rs = interview_rows("WHERE i.id=?", (iid,))
    if not rs: raise NotFound("Interview not found")
    if rs[0]["interviewer_id"] != interviewer_id: raise Forbidden("This interview is not assigned to you")
    if rs[0]["status"] == "Cancelled": raise Invalid("Cannot submit feedback for a cancelled interview")
    for n, v in (("technical", technical), ("communication", communication), ("problem_solving", problem_solving)):
        if not isinstance(v, int) or not 1 <= v <= 5: raise Invalid(f"{n} must be an integer from 1 to 5")
    if recommendation not in ("Strong Hire", "Hire", "No Hire", "Strong No Hire"): raise Invalid("Invalid recommendation")
    with db() as c:
        if c.execute("SELECT 1 FROM feedback WHERE interview_id=?", (iid,)).fetchone(): raise Invalid("Feedback already submitted")
        c.execute("INSERT INTO feedback(interview_id,technical,communication,problem_solving,remarks,recommendation,submitted_by) VALUES(?,?,?,?,?,?,?)",
                  (iid, technical, communication, problem_solving, remarks, recommendation, interviewer_id))
        c.execute("UPDATE interviews SET status='Completed' WHERE id=?", (iid,))
    return get_feedback(iid)


def get_feedback(iid):
    with db() as c: r = c.execute("SELECT f.*, u.name AS interviewer FROM feedback f JOIN users u ON u.id=f.submitted_by WHERE interview_id=?", (iid,)).fetchone()
    return row(r)


def all_feedback():
    with db() as c:
        return rows(c.execute("""SELECT f.*, u.name AS interviewer, cd.name AS candidate_name, j.title AS job_title
            FROM feedback f JOIN users u ON u.id=f.submitted_by JOIN interviews i ON i.id=f.interview_id JOIN applications a ON a.id=i.application_id
            JOIN candidates cd ON cd.id=a.candidate_id JOIN jobs j ON j.id=a.job_id ORDER BY f.id DESC""").fetchall())


def candidate_interviews(cid):
    return [i for i in interview_rows("WHERE a.candidate_id=?", (cid,))]  # feedback is never exposed to candidates


# ---------------- dashboard ----------------
def stats():
    with db() as c:
        q = lambda s: c.execute(s).fetchone()[0]
        return {"total_candidates": q("SELECT COUNT(*) FROM candidates WHERE parse_method IS NOT NULL"),
                "total_resumes": q("SELECT COUNT(*) FROM resumes"),
                "active_jobs": q("SELECT COUNT(*) FROM jobs WHERE status='Open'"),
                "total_applications": q("SELECT COUNT(*) FROM applications WHERE status!='Matched'"),
                "shortlisted": q("SELECT COUNT(DISTINCT candidate_id) FROM applications WHERE shortlisted=1"),
                "interviews_scheduled": q("SELECT COUNT(*) FROM interviews WHERE status='Scheduled'"),
                "selected": q("SELECT COUNT(*) FROM applications WHERE status='Selected'")}
