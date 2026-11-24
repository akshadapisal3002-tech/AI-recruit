"""Hybrid, explainable candidate<->job scoring (0-100).

score = 40% skills (30 required + 10 preferred) + 20% experience + 10% education + 30% semantic similarity
All parts except semantic similarity are deterministic functions of grounded structured data. The LLM is NOT
used to produce the score; explanations are generated from the computed facts so they cannot invent anything.
"""
import re
from . import embeddings
from .skills import canonical, extract_skills

W_SKILLS_REQ, W_SKILLS_PREF, W_EXP, W_EDU, W_SEM = 30, 10, 20, 10, 30
EDU_LEVELS = [(4, r"ph\.?d|doctorate"), (3, r"master|m\.?\s?tech|m\.?\s?sc|\bm\.?s\b|mca|mba|\bm\.?e\b"),
              (2, r"bachelor|b\.?\s?tech|b\.?\s?sc|\bbca\b|\bb\.?e\b|\bb\.?s\b|undergraduate|graduate"), (1, r"diploma")]


def edu_level(text: str) -> int:
    for lvl, pat in EDU_LEVELS:
        if re.search(pat, text or "", re.I):
            return lvl
    return 0


def candidate_skill_set(c: dict) -> set:
    s = {canonical(x) for x in c.get("skills") or []}
    blob = " ".join([(e.get("title", "") + " " + e.get("description", "")) for e in c.get("experience") or []] +
                    [(p.get("name", "") + " " + p.get("description", "")) for p in c.get("projects") or []])
    s.update(extract_skills(blob))  # skills evidenced in experience/projects text
    return s


def score_candidate(c: dict, job: dict, semantic_cos: float) -> dict:
    cand = candidate_skill_set(c)
    req = [canonical(s) for s in job.get("required_skills") or []]
    pref = [canonical(s) for s in job.get("preferred_skills") or []]
    matched_req, missing_req = [s for s in req if s in cand], [s for s in req if s not in cand]
    matched_pref, missing_pref = [s for s in pref if s in cand], [s for s in pref if s not in cand]
    req_ratio = len(matched_req) / len(req) if req else 1.0
    pref_ratio = len(matched_pref) / len(pref) if pref else req_ratio

    years = float(c.get("total_experience_years") or 0)
    mn, mx = float(job.get("min_experience") or 0), job.get("max_experience")
    years_score = 1.0 if years >= mn else (years / mn if mn else 1.0)
    note = ""
    if mx is not None and years > float(mx) + 3:
        years_score *= 0.85; note = " (notably above the maximum range)"
    relevant = sum(e.get("years", 0) for e in c.get("experience") or []
                   if set(extract_skills((e.get("title") or "") + " " + (e.get("description") or ""))) & set(req + pref))
    rel_ratio = min(1.0, relevant / mn) if mn else (1.0 if relevant else 0.5)
    exp_ratio = 0.6 * years_score + 0.4 * rel_ratio

    need = edu_level(job.get("education") or "")
    have = max([edu_level((e.get("degree") or "") + " " + (e.get("field") or "")) for e in c.get("education") or []] or [0])
    edu_ratio = 1.0 if need == 0 or have >= need else (0.5 if have == need - 1 and have > 0 else 0.0)

    sem = embeddings.calibrate(semantic_cos)
    parts = {
        "required_skills": round(W_SKILLS_REQ * req_ratio, 1), "preferred_skills": round(W_SKILLS_PREF * pref_ratio, 1),
        "experience": round(W_EXP * exp_ratio, 1), "education": round(W_EDU * edu_ratio, 1),
        "semantic": round(W_SEM * sem, 1)}
    total = round(min(100.0, sum(parts.values())), 1)
    label = "Strong match" if total >= 75 else "Good match" if total >= 55 else "Partial match" if total >= 35 else "Weak match"
    jr = f"{mn:g}" + (f"-{float(mx):g}" if mx is not None else "+")
    reasons = [f"Matches {len(matched_req)}/{len(req)} required skills" + (f" ({', '.join(matched_req)})" if matched_req else "") + "."]
    if missing_req:
        reasons.append(f"Missing required: {', '.join(missing_req)}.")
    if pref:
        reasons.append(f"Matches {len(matched_pref)}/{len(pref)} preferred skills.")
    reasons.append(f"Has {years:g} years of experience vs {jr} requested{note}; {relevant:g} years in roles using the job's skills.")
    if need:
        reasons.append("Education meets the requirement." if edu_ratio == 1 else "Education is below the stated requirement.")
    reasons.append(f"Profile/job-description semantic similarity: {round(sem * 100)}%.")
    return {"score": total, "label": label, "breakdown": parts, "matched_skills": matched_req + matched_pref,
            "missing_skills": missing_req + missing_pref, "matched_required": matched_req, "missing_required": missing_req,
            "matched_preferred": matched_pref, "missing_preferred": missing_pref,
            "experience": {"candidate_years": years, "required_min": mn, "required_max": mx, "relevant_years": round(relevant, 1)},
            "semantic_similarity": round(sem, 3), "raw_cosine": round(semantic_cos, 3), "reason": " ".join(reasons)}
