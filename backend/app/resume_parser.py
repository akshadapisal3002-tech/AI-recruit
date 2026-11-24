"""Resume text extraction + structured parsing.

Pipeline: extract text (PDF/DOCX) -> LLM JSON extraction (or heuristic fallback) -> GROUNDING (every
extracted fact must be present in the source text, else dropped & logged) -> experience years computed
in code from dates (never taken from the LLM).
"""
import datetime as dt, io, re
from . import llm
from .skills import extract_skills, canonical

class ResumeError(Exception):
    pass

MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
DATE_TOKEN = r"(?:[A-Za-z]{3,9}\.?,?\s+\d{4}|\d{1,2}/\d{4}|\d{4})"
RANGE_RE = re.compile(rf"(?P<s>{DATE_TOKEN})\s*(?:-|–|—|to)\s*(?P<e>present|current|now|till date|{DATE_TOKEN})", re.I)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?:\+?\d{1,3}[\s-]?)?(?:\(?\d{3,5}\)?[\s-]?)\d{3,5}[\s-]?\d{3,5}")
HEADINGS = {
    "summary": r"(professional )?summary|profile|objective|about me",
    "experience": r"(work |professional )?experience|employment( history)?|work history",
    "education": r"education|academic.*|qualifications?",
    "projects": r"(academic |personal |key )?projects",
    "skills": r"(technical |key )?skills|technologies|tech stack",
    "other": r"certifications?|achievements|awards|languages|interests|references",
}
DEGREE_RE = re.compile(r"\b(ph\.?d|doctorate|m\.?\s?tech|m\.?\s?e\b|m\.?\s?sc|m\.?\s?s\b|mca|mba|master[’']?s?|b\.?\s?tech|b\.?\s?e\b|b\.?\s?sc|bca|b\.?\s?s\b|bachelor[’']?s?|diploma)\b", re.I)


# ---------- text extraction ----------
def extract_text(data: bytes, filename: str) -> str:
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if ext == "pdf":
        if not data.startswith(b"%PDF"):
            raise ResumeError("File is not a valid PDF (bad header)")
        try:
            from pypdf import PdfReader
            text = "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages)
        except Exception as e:
            raise ResumeError(f"Corrupted or unreadable PDF: {e}")
    elif ext == "docx":
        if not data.startswith(b"PK"):
            raise ResumeError("File is not a valid DOCX (bad header)")
        try:
            import docx
            d = docx.Document(io.BytesIO(data))
            lines = [p.text for p in d.paragraphs]
            for t in d.tables:
                for r in t.rows:
                    lines.append(" | ".join(c.text for c in r.cells))
            text = "\n".join(lines)
        except Exception as e:
            raise ResumeError(f"Corrupted or unreadable DOCX: {e}")
    else:
        raise ResumeError(f"Unsupported file type '.{ext}'. Only PDF and DOCX are accepted")
    text = re.sub(r"[ \t]+", " ", text).strip()
    if len(text) < 40:
        raise ResumeError("No readable text found (empty or scanned/image-only document)")
    return text


# ---------- dates / experience ----------
def _parse_date(s: str, end=False):
    s = s.strip().lower()
    if s in ("present", "current", "now", "till date"):
        t = dt.date.today()
        return t.year * 12 + t.month
    m = re.match(r"([a-z]{3})[a-z]*\.?,?\s+(\d{4})", s)
    if m and m.group(1) in MONTHS:
        return int(m.group(2)) * 12 + MONTHS[m.group(1)]
    m = re.match(r"(\d{1,2})/(\d{4})", s)
    if m:
        return int(m.group(2)) * 12 + int(m.group(1))
    m = re.match(r"(\d{4})", s)
    if m:
        return int(m.group(1)) * 12 + (12 if end else 1)
    return None


def entry_months(e: dict):
    a, b = _parse_date(str(e.get("start") or "")), _parse_date(str(e.get("end") or "present"), end=True)
    if a is None or b is None or b < a:
        return None
    return a, b


def entry_years(e: dict) -> float:
    m = entry_months(e)
    return round((m[1] - m[0] + 1) / 12, 1) if m else 0


def total_years(experience: list) -> float:
    spans = sorted(s for s in (entry_months(e) for e in experience) if s)
    merged = []
    for a, b in spans:
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return round(sum(b - a + 1 for a, b in merged) / 12, 1)  # inclusive months


# ---------- heuristic parser (fallback when no LLM) ----------
def _split_sections(text: str):
    sections, cur = {"header": []}, "header"
    for line in text.splitlines():
        stripped = line.strip().strip(":").strip()
        hit = next((k for k, pat in HEADINGS.items() if re.fullmatch(pat, stripped, re.I)), None)
        if hit and len(stripped) < 40:
            cur = hit
            sections.setdefault(cur, [])
            continue
        sections.setdefault(cur, []).append(line.strip())
    return sections


def heuristic_parse(text: str) -> dict:
    sec = _split_sections(text)
    header = [l for l in sec["header"] if l]
    email = (EMAIL_RE.search(text) or [None])[0] if EMAIL_RE.search(text) else None
    phone = None
    for m in PHONE_RE.finditer(text):
        if len(re.sub(r"\D", "", m.group(0))) >= 10 and not RANGE_RE.search(m.group(0)):
            phone = m.group(0).strip()
            break
    name = next((l for l in header if "@" not in l and not re.search(r"\d", l) and 1 < len(l.split()) <= 5), None)
    location = None
    for l in header[:6]:
        m = re.search(r"(?:Location|Address)\s*:\s*(.+)", l, re.I)
        if m:
            location = m.group(1).strip()
    if not location:
        for l in header[:6]:
            parts = [p.strip() for p in re.split(r"[|•·]", l)]
            for p in parts:
                if re.fullmatch(r"[A-Z][a-zA-Z .]+,\s*[A-Z][a-zA-Z .]+", p) and "@" not in p:
                    location = p
    # experience
    experience, cur = [], None
    for line in sec.get("experience", []):
        if not line:
            continue
        m = RANGE_RE.search(line)
        if m:
            head = (line[:m.start()] + line[m.end():]).strip(" |-–—,()")
            parts = [p.strip() for p in re.split(r"\s+\|\s+|\s+at\s+|\s+[-–—]\s+|,\s+(?=[A-Z])", head) if p.strip()]
            cur = {"title": parts[0] if parts else "", "company": parts[1] if len(parts) > 1 else "",
                   "start": m.group("s"), "end": m.group("e"), "description": ""}
            experience.append(cur)
        elif cur is not None:
            cur["description"] = (cur["description"] + " " + line.lstrip("•-* ")).strip()
    # education
    education = []
    for line in sec.get("education", []):
        if DEGREE_RE.search(line):
            yr = re.findall(r"(?:19|20)\d{2}", line)
            parts = [p.strip() for p in re.split(r"\s+\|\s+|\s+[-–—]\s+|,\s+", line) if p.strip()]
            degree = next((p for p in parts if DEGREE_RE.search(p)), line)
            inst = next((p for p in parts if re.search(r"universit|institute|college|school|iit|nit", p, re.I)), "")
            education.append({"degree": degree, "institution": inst, "field": "", "year": yr[-1] if yr else ""})
    # projects
    projects, cur = [], None
    for line in sec.get("projects", []):
        if not line:
            continue
        if not line.startswith(("•", "-", "*")) and len(line) < 90:
            cur = {"name": line.split(" - ")[0].strip(), "description": "", "technologies": []}
            projects.append(cur)
            rest = line.split(" - ", 1)[1] if " - " in line else ""
            cur["description"] = rest
        elif cur is not None:
            cur["description"] = (cur["description"] + " " + line.lstrip("•-* ")).strip()
    for p in projects:
        p["technologies"] = extract_skills(p["name"] + " " + p["description"])
    skills_text = " ".join(sec.get("skills", []))
    skills = extract_skills(skills_text) or extract_skills(text)
    return {"name": name, "email": email, "phone": phone, "location": location,
            "summary": " ".join(sec.get("summary", [])).strip(), "education": education,
            "experience": experience, "skills": skills, "projects": projects}


# ---------- LLM parser ----------
LLM_SYSTEM = """You extract structured data from resumes. Return ONLY a JSON object. STRICT RULES:
- Use ONLY information explicitly present in the resume text. Never infer, guess or add skills, employers,
  degrees, dates or contact details. If something is missing use null (or [] for lists).
- Copy names, companies, institutions and skills as written in the resume.
Schema: {"name":str|null,"email":str|null,"phone":str|null,"location":str|null,"summary":str|null,
"education":[{"degree":str,"field":str|null,"institution":str,"year":str|null}],
"experience":[{"title":str,"company":str,"start":"Mon YYYY"|"YYYY"|null,"end":"Mon YYYY"|"YYYY"|"Present"|null,"description":str}],
"skills":[str],"projects":[{"name":str,"description":str,"technologies":[str]}]}"""


def llm_parse(text: str) -> dict:
    return llm.chat_json(LLM_SYSTEM, "Resume text:\n\"\"\"\n" + text[:15000] + "\n\"\"\"")


# ---------- grounding / hallucination guard ----------
def _flat(s): return re.sub(r"[^a-z0-9+#]+", " ", (s or "").lower()).strip()


def ground(parsed: dict, text: str):
    """Drop anything not literally supported by the resume text. Returns (clean, warnings)."""
    warnings, ft, digits = [], " " + _flat(text) + " ", re.sub(r"\D", "", text)
    def present(s): return bool(s) and (" " + _flat(s) + " ") in ft
    out = {k: parsed.get(k) for k in ("name", "email", "phone", "location", "summary")}
    for k in ("name", "location"):
        if out[k] and not present(out[k]):
            warnings.append(f"Dropped {k} '{out[k]}': not found in resume text"); out[k] = None
    if out["email"] and out["email"].lower() not in text.lower():
        warnings.append("Dropped email: not found in resume text"); out["email"] = None
    if out["phone"] and re.sub(r"\D", "", out["phone"])[-10:] not in digits:
        warnings.append("Dropped phone: not found in resume text"); out["phone"] = None
    out["summary"] = out["summary"] if (out["summary"] and len(out["summary"]) < 1500) else (out["summary"] or "")[:1500]
    skills = []
    for s in parsed.get("skills") or []:
        if not isinstance(s, str):
            continue
        c = canonical(s)
        if present(s) or present(c) or c in extract_skills(text):
            if c not in skills:
                skills.append(c)
        else:
            warnings.append(f"Dropped skill '{s}': not found in resume text")
    out["skills"] = skills
    exp = []
    for e in parsed.get("experience") or []:
        if not isinstance(e, dict):
            continue
        if present(e.get("company")) or present(e.get("title")):
            exp.append({"title": e.get("title") or "", "company": e.get("company") or "", "start": e.get("start"),
                        "end": e.get("end"), "description": (e.get("description") or "")[:1500]})
        else:
            warnings.append(f"Dropped experience '{e.get('title')} @ {e.get('company')}': not found in resume text")
    for e in exp:
        e["years"] = entry_years(e)
    out["experience"] = exp
    edu = []
    for e in parsed.get("education") or []:
        if isinstance(e, dict) and (present(e.get("institution")) or present(e.get("degree"))):
            edu.append({"degree": e.get("degree") or "", "field": e.get("field") or "",
                        "institution": e.get("institution") or "", "year": str(e.get("year") or "")})
        else:
            warnings.append(f"Dropped education entry '{(e or {}).get('degree')}': not found in resume text")
    out["education"] = edu
    projs = []
    for p in parsed.get("projects") or []:
        if isinstance(p, dict) and present(p.get("name")):
            techs = [canonical(t) for t in (p.get("technologies") or []) if isinstance(t, str) and (present(t) or canonical(t) in extract_skills(text))]
            projs.append({"name": p["name"], "description": (p.get("description") or "")[:1000], "technologies": techs})
    out["projects"] = projs
    out["total_experience_years"] = total_years(exp)
    return out, warnings


def parse_resume(text: str):
    """Returns (parsed_clean, warnings, method)."""
    warnings, method = [], "heuristic"
    parsed = None
    if llm.configured():
        try:
            parsed, method = llm_parse(text), "llm"
        except llm.LLMError as e:
            warnings.append(f"LLM parsing failed ({e}); used heuristic parser instead")
    if parsed is None:
        parsed = heuristic_parse(text)
    clean, w = ground(parsed, text)
    return clean, warnings + w, method
