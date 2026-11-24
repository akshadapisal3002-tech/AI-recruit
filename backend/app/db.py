import json, sqlite3
from contextlib import contextmanager
from pathlib import Path
from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
  name TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('candidate','admin','interviewer')),
  created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS candidates(
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER UNIQUE REFERENCES users(id),
  name TEXT, email TEXT, phone TEXT, location TEXT, summary TEXT,
  education TEXT DEFAULT '[]', experience TEXT DEFAULT '[]', skills TEXT DEFAULT '[]', projects TEXT DEFAULT '[]',
  total_experience_years REAL DEFAULT 0, parse_warnings TEXT DEFAULT '[]', parse_method TEXT,
  reviewed INTEGER DEFAULT 0, embedding TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS resumes(
  id INTEGER PRIMARY KEY AUTOINCREMENT, candidate_id INTEGER REFERENCES candidates(id),
  uploaded_by INTEGER REFERENCES users(id), filename TEXT, path TEXT, batch_id TEXT,
  status TEXT DEFAULT 'Processing' CHECK(status IN ('Processing','Completed','Failed')),
  error TEXT, duplicate_of INTEGER REFERENCES candidates(id), created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS jobs(
  id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, description TEXT NOT NULL,
  required_skills TEXT DEFAULT '[]', preferred_skills TEXT DEFAULT '[]', min_experience REAL DEFAULT 0, max_experience REAL,
  education TEXT, location TEXT, employment_type TEXT DEFAULT 'Full-time', last_date TEXT,
  status TEXT DEFAULT 'Open' CHECK(status IN ('Draft','Open','Closed')), embedding TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS applications(
  id INTEGER PRIMARY KEY AUTOINCREMENT, job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
  status TEXT DEFAULT 'Matched', applied INTEGER DEFAULT 0, shortlisted INTEGER DEFAULT 0,
  score REAL, detail TEXT, ai_recommendation TEXT,
  override_decision TEXT, override_reason TEXT, override_by INTEGER REFERENCES users(id),
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(job_id, candidate_id));
CREATE TABLE IF NOT EXISTS notes(
  id INTEGER PRIMARY KEY AUTOINCREMENT, candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
  author_id INTEGER REFERENCES users(id), text TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS interviews(
  id INTEGER PRIMARY KEY AUTOINCREMENT, application_id INTEGER NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
  interviewer_id INTEGER NOT NULL REFERENCES users(id), scheduled_at TEXT NOT NULL, duration_min INTEGER DEFAULT 45,
  mode TEXT DEFAULT 'Online', meeting_link TEXT, status TEXT DEFAULT 'Scheduled' CHECK(status IN ('Scheduled','Cancelled','Completed')),
  created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS feedback(
  id INTEGER PRIMARY KEY AUTOINCREMENT, interview_id INTEGER UNIQUE NOT NULL REFERENCES interviews(id) ON DELETE CASCADE,
  technical INTEGER, communication INTEGER, problem_solving INTEGER, remarks TEXT,
  recommendation TEXT, submitted_by INTEGER REFERENCES users(id), created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS share_links(
  token TEXT PRIMARY KEY, job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  expires_at TEXT NOT NULL, created_by INTEGER REFERENCES users(id));
CREATE TABLE IF NOT EXISTS outbox(
  id INTEGER PRIMARY KEY AUTOINCREMENT, to_email TEXT, subject TEXT, body TEXT, sent INTEGER DEFAULT 0, error TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS idx_app_job ON applications(job_id);
CREATE INDEX IF NOT EXISTS idx_resume_cand ON resumes(candidate_id);
"""

CANDIDATE_JSON = ("education", "experience", "skills", "projects", "parse_warnings")
JOB_JSON = ("required_skills", "preferred_skills")


def connect():
    Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


@contextmanager
def db():
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with db() as c:
        c.executescript(SCHEMA)


def row(r, json_fields=()):
    if r is None:
        return None
    d = dict(r)
    for f in json_fields:
        if f in d and isinstance(d[f], str):
            try:
                d[f] = json.loads(d[f])
            except ValueError:
                d[f] = []
    return d


def rows(rs, json_fields=()):
    return [row(r, json_fields) for r in rs]
