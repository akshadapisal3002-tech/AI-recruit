"""FastAPI HTTP layer. Business logic lives in services.py. Interactive docs: /docs (Swagger) and /redoc."""
import uuid
from typing import List, Optional
from fastapi import BackgroundTasks, Depends, FastAPI, File, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field
from . import config, llm, services as s
from .db import init_db
from .security import create_token, decode_token

app = FastAPI(title="AI Recruitment & Interview Platform", version="1.0.0",
              description="Candidate portal, admin recruitment portal and interview management with AI resume parsing, hybrid matching and semantic search.")
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
def _startup():
    init_db()


@app.exception_handler(s.NotFound)
async def _nf(_, e): return Response(content=f'{{"detail":"{e}"}}', status_code=404, media_type="application/json")
@app.exception_handler(s.Forbidden)
async def _fb(_, e): return Response(content=f'{{"detail":"{e}"}}', status_code=403, media_type="application/json")
@app.exception_handler(s.Invalid)
async def _iv(_, e): return Response(content=f'{{"detail":"{str(e)}"}}', status_code=400, media_type="application/json")


# ---------- auth ----------
def current_user(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Missing bearer token")
    data = decode_token(authorization.split(" ", 1)[1])
    if not data:
        raise HTTPException(401, "Invalid or expired token")
    try:
        return s.get_user(data["sub"])
    except s.NotFound:
        raise HTTPException(401, "User no longer exists")


def require(*roles):
    def dep(user=Depends(current_user)):
        if user["role"] not in roles:
            raise HTTPException(403, f"Requires role: {', '.join(roles)}")
        return user
    return dep


admin_only, candidate_only, interviewer_only = require("admin"), require("candidate"), require("interviewer")


class RegisterIn(BaseModel):
    email: str
    password: str = Field(min_length=8)
    name: str = Field(min_length=1)


class LoginIn(BaseModel):
    email: str
    password: str


class UserIn(RegisterIn):
    role: str = Field(pattern="^(admin|interviewer)$")


@app.post("/auth/register", tags=["Auth"])
def register(b: RegisterIn):
    u = s.create_user(b.email, b.password, b.name, "candidate")
    return {"token": create_token(u["id"], u["role"]), "user": u}


@app.post("/auth/login", tags=["Auth"])
def login(b: LoginIn):
    u = s.authenticate(b.email, b.password)
    if not u:
        raise HTTPException(401, "Invalid email or password")
    return {"token": create_token(u["id"], u["role"]), "user": u}


@app.get("/auth/me", tags=["Auth"])
def me(user=Depends(current_user)):
    return user


@app.get("/health", tags=["System"])
def health():
    return {"status": "ok", "llm_configured": llm.configured(), "embedding_backend": config.EMBEDDING_BACKEND}


# ---------- candidate portal ----------
class ProfileIn(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    summary: Optional[str] = None
    education: Optional[list] = None
    experience: Optional[list] = None
    skills: Optional[List[str]] = None
    projects: Optional[list] = None


@app.get("/me/profile", tags=["Candidate"])
def my_profile(user=Depends(candidate_only)):
    return s.candidate_for_user(user["id"])


@app.put("/me/profile", tags=["Candidate"])
def update_my_profile(b: ProfileIn, user=Depends(candidate_only)):
    cand = s.candidate_for_user(user["id"])
    return s.update_candidate(cand["id"], b.model_dump(exclude_none=True), reviewed=True)


def _process(rid):  # background wrapper
    s.process_resume(rid)


@app.post("/me/resume", tags=["Candidate"])
async def upload_my_resume(bg: BackgroundTasks, file: UploadFile = File(...), user=Depends(candidate_only)):
    cand = s.candidate_for_user(user["id"])
    rid = s.create_resume_record(file.filename, await file.read(), user["id"], None, cand["id"])
    if config.SYNC_PROCESSING:
        s.process_resume(rid)
    else:
        bg.add_task(_process, rid)
    return s.get_resume(rid)


@app.get("/me/resume/{rid}", tags=["Candidate"])
def my_resume_status(rid: int, user=Depends(candidate_only)):
    r, cand = s.get_resume(rid), s.candidate_for_user(user["id"])
    if r["candidate_id"] != cand["id"]:
        raise HTTPException(403, "Not your resume")
    return {k: r[k] for k in ("id", "filename", "status", "error")}


@app.get("/jobs", tags=["Candidate"])
def open_jobs(user=Depends(current_user)):
    return s.list_jobs(open_only=True)


@app.post("/jobs/{job_id}/apply", tags=["Candidate"])
def apply(job_id: int, user=Depends(candidate_only)):
    cand = s.candidate_for_user(user["id"])
    a = s.apply_to_job(cand["id"], job_id)
    return {"id": a["id"], "status": a["status"], "job_title": a["job_title"]}


@app.get("/me/applications", tags=["Candidate"])
def my_applications(user=Depends(candidate_only)):
    return s.candidate_applications(s.candidate_for_user(user["id"])["id"])


@app.get("/me/interviews", tags=["Candidate"])
def my_interviews(user=Depends(candidate_only)):
    keep = ("id", "job_title", "scheduled_at", "duration_min", "mode", "meeting_link", "status", "interviewer_name")
    return [{k: i[k] for k in keep} for i in s.candidate_interviews(s.candidate_for_user(user["id"])["id"])]


@app.get("/candidates/{cid}", tags=["Candidates"])
def candidate_detail(cid: int, user=Depends(current_user)):
    """Admins: any profile. Candidates: only their own (403 otherwise). Interviewers: only assigned candidates."""
    s.assert_can_view_candidate(user, cid)
    out = s.get_candidate(cid)
    if user["role"] == "admin":
        out["notes"] = s.list_notes(cid)
        out["applications"] = [m for j in s.list_jobs() for m in s.list_matches(j["id"]) if m["candidate_id"] == cid]
        out["resumes"] = [r for r in s.list_resumes() if r["candidate_id"] == cid]
    return out


# ---------- admin: dashboard, users ----------
@app.get("/admin/stats", tags=["Admin"])
def stats(user=Depends(admin_only)):
    return s.stats()


@app.post("/admin/users", tags=["Admin"])
def create_staff(b: UserIn, user=Depends(admin_only)):
    return s.create_user(b.email, b.password, b.name, b.role)


@app.get("/admin/users", tags=["Admin"])
def users(role: Optional[str] = None, user=Depends(admin_only)):
    return s.list_users(role)


# ---------- admin: bulk upload ----------
@app.post("/admin/resumes/bulk", tags=["Admin: Resumes"])
async def bulk_upload(bg: BackgroundTasks, files: List[UploadFile] = File(...), user=Depends(admin_only)):
    """Each file becomes its own record and is processed independently; a bad file never affects the others."""
    batch, out = uuid.uuid4().hex[:8], []
    for f in files:
        try:
            rid = s.create_resume_record(f.filename, await f.read(), user["id"], batch)
        except Exception as e:  # unreadable upload stream
            out.append({"filename": f.filename, "status": "Failed", "error": str(e)}); continue
        if config.SYNC_PROCESSING:
            s.process_resume(rid)
        else:
            bg.add_task(_process, rid)
        out.append(s.get_resume(rid))
    return {"batch_id": batch, "resumes": out}


@app.get("/admin/resumes", tags=["Admin: Resumes"])
def resumes(batch_id: Optional[str] = None, user=Depends(admin_only)):
    return [{k: v for k, v in r.items() if k != "path"} for r in s.list_resumes(batch_id)]


# ---------- admin: jobs ----------
class JobIn(BaseModel):
    title: str = Field(min_length=2)
    description: str = Field(min_length=10)
    required_skills: List[str] = []
    preferred_skills: List[str] = []
    min_experience: float = Field(0, ge=0)
    max_experience: Optional[float] = Field(None, ge=0)
    education: Optional[str] = None
    location: Optional[str] = None
    employment_type: str = "Full-time"
    last_date: Optional[str] = None
    status: str = Field("Open", pattern="^(Draft|Open|Closed)$")


@app.post("/admin/jobs", tags=["Admin: Jobs"])
def create_job(b: JobIn, user=Depends(admin_only)): return s.create_job(b.model_dump())


@app.get("/admin/jobs", tags=["Admin: Jobs"])
def all_jobs(user=Depends(admin_only)): return s.list_jobs()


@app.get("/admin/jobs/{jid}", tags=["Admin: Jobs"])
def job(jid: int, user=Depends(admin_only)): return s.get_job(jid)


@app.put("/admin/jobs/{jid}", tags=["Admin: Jobs"])
def edit_job(jid: int, b: JobIn, user=Depends(admin_only)): return s.update_job(jid, b.model_dump())


@app.delete("/admin/jobs/{jid}", tags=["Admin: Jobs"])
def remove_job(jid: int, user=Depends(admin_only)):
    s.delete_job(jid); return {"deleted": jid}


# ---------- admin: matching, search, candidates ----------
@app.post("/admin/jobs/{jid}/match", tags=["Admin: Matching"])
def match(jid: int, user=Depends(admin_only)):
    """Scores every candidate against the job (hybrid: skills + experience + education + embeddings)."""
    return s.run_matching(jid)


@app.get("/admin/jobs/{jid}/matches", tags=["Admin: Matching"])
def matches(jid: int, min_score: float = 0, user=Depends(admin_only)): return s.list_matches(jid, min_score)


class SearchIn(BaseModel):
    query: str = Field(min_length=2)
    limit: int = Field(20, ge=1, le=100)


@app.post("/admin/search", tags=["Admin: Matching"])
def search(b: SearchIn, user=Depends(admin_only)): return s.search_candidates(b.query, b.limit)


@app.get("/admin/candidates", tags=["Admin: Candidates"])
def candidates(skill: Optional[str] = Query(None, description="comma separated"), min_exp: Optional[float] = None,
               location: Optional[str] = None, q: Optional[str] = None, sort: str = "name", user=Depends(admin_only)):
    return s.filter_candidates(skill, min_exp, location, q, sort)


@app.put("/admin/candidates/{cid}", tags=["Admin: Candidates"])
def correct_candidate(cid: int, b: ProfileIn, user=Depends(admin_only)):
    """Human-in-the-loop correction of AI-extracted data. Embedding is regenerated."""
    return s.update_candidate(cid, b.model_dump(exclude_none=True), reviewed=True)


class NoteIn(BaseModel):
    text: str = Field(min_length=1)


@app.post("/admin/candidates/{cid}/notes", tags=["Admin: Candidates"])
def note(cid: int, b: NoteIn, user=Depends(admin_only)): return s.add_note(cid, user["id"], b.text)


# ---------- admin: shortlist / approvals ----------
class ShortlistIn(BaseModel):
    job_id: int
    candidate_ids: List[int]


@app.post("/admin/shortlist", tags=["Admin: Shortlist"])
def shortlist(b: ShortlistIn, user=Depends(admin_only)): return s.shortlist(b.job_id, b.candidate_ids)


@app.get("/admin/jobs/{jid}/shortlist/export", tags=["Admin: Shortlist"])
def export(jid: int, format: str = Query("csv", pattern="^(csv|xlsx)$"), user=Depends(admin_only)):
    data, name = s.export_shortlist(jid, format)
    mt = "text/csv" if format == "csv" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return Response(data, media_type=mt, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.post("/admin/jobs/{jid}/share", tags=["Admin: Shortlist"])
def share(jid: int, hours: int = Query(72, ge=1, le=720), user=Depends(admin_only)): return s.create_share_link(jid, user["id"], hours)


@app.get("/shared/{token}", tags=["Shared"])
def shared(token: str):
    """Public, expiring, read-only shortlist (no contact details)."""
    return s.shared_shortlist(token)


@app.post("/admin/applications/{aid}/approve", tags=["Admin: Shortlist"])
def approve(aid: int, user=Depends(admin_only)): return s.approve_for_interview(aid)


class StatusIn(BaseModel):
    status: str


@app.put("/admin/applications/{aid}/status", tags=["Admin: Shortlist"])
def status(aid: int, b: StatusIn, user=Depends(admin_only)): return s.set_status(aid, b.status)


class OverrideIn(BaseModel):
    decision: str
    reason: Optional[str] = None


@app.post("/admin/applications/{aid}/override", tags=["Admin: Shortlist"])
def override(aid: int, b: OverrideIn, user=Depends(admin_only)): return s.override(aid, b.decision, b.reason or "", user["id"])


# ---------- interviews ----------
class InterviewIn(BaseModel):
    application_id: int
    interviewer_id: int
    scheduled_at: str = Field(description="ISO datetime, e.g. 2026-12-01T10:30")
    duration_min: int = Field(45, ge=10, le=480)
    mode: str = "Online"
    meeting_link: Optional[str] = None


class InterviewUpdate(BaseModel):
    scheduled_at: Optional[str] = None
    duration_min: Optional[int] = None
    cancel: bool = False


@app.post("/admin/interviews", tags=["Interviews"])
def schedule(b: InterviewIn, user=Depends(admin_only)):
    return s.schedule_interview(b.application_id, b.interviewer_id, b.scheduled_at, b.duration_min, b.mode, b.meeting_link)


@app.put("/admin/interviews/{iid}", tags=["Interviews"])
def reschedule(iid: int, b: InterviewUpdate, user=Depends(admin_only)): return s.update_interview(iid, b.scheduled_at, b.duration_min, b.cancel)


@app.get("/admin/interviews", tags=["Interviews"])
def all_interviews(upcoming: bool = False, user=Depends(admin_only)):
    return s.interview_rows("WHERE i.status='Scheduled' AND datetime(i.scheduled_at)>=datetime('now')") if upcoming else s.interview_rows()


@app.get("/admin/feedback", tags=["Interviews"])
def feedback_all(user=Depends(admin_only)): return s.all_feedback()


@app.get("/interviewer/interviews", tags=["Interviews"])
def my_assigned(user=Depends(interviewer_only)): return s.interview_rows("WHERE i.interviewer_id=?", (user["id"],))


class FeedbackIn(BaseModel):
    technical: int = Field(ge=1, le=5)
    communication: int = Field(ge=1, le=5)
    problem_solving: int = Field(ge=1, le=5)
    remarks: str = ""
    recommendation: str = Field(pattern="^(Strong Hire|Hire|No Hire|Strong No Hire)$")


@app.post("/interviewer/interviews/{iid}/feedback", tags=["Interviews"])
def feedback(iid: int, b: FeedbackIn, user=Depends(interviewer_only)):
    return s.submit_feedback(iid, user["id"], b.technical, b.communication, b.problem_solving, b.remarks, b.recommendation)
