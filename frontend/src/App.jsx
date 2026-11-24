import React, { useEffect, useState, useCallback } from "react";
import { api, auth } from "./api.js";

const Err = ({ e }) => (e ? <div className="err">{e}</div> : null);
const Ok = ({ m }) => (m ? <div className="okmsg">{m}</div> : null);
const csv = (s) => s.split(",").map((x) => x.trim()).filter(Boolean);
const fmt = (d) => (d ? new Date(d).toLocaleString() : "");
const statusPill = (s) => <span className={"pill " + (["Completed", "Selected", "Approved for Interview"].includes(s) ? "ok" : ["Failed", "Rejected"].includes(s) ? "bad" : "warn")}>{s}</span>;

function useLoad(fn, deps = []) {
  const [data, setData] = useState(null); const [err, setErr] = useState("");
  const reload = useCallback(() => fn().then(setData).catch((e) => setErr(e.message)), deps); // eslint-disable-line
  useEffect(() => { reload(); }, [reload]);
  return [data, reload, err];
}

/* ---------------- Login ---------------- */
function Login({ onDone }) {
  const [mode, setMode] = useState("login"); const [f, setF] = useState({ name: "", email: "", password: "" }); const [err, setErr] = useState("");
  const submit = async (e) => {
    e.preventDefault(); setErr("");
    try { const r = await api.post(mode === "login" ? "/auth/login" : "/auth/register", f); auth.set(r.token, r.user); onDone(r.user); }
    catch (x) { setErr(x.message); }
  };
  return (
    <div className="card center"><h2>AI Recruitment Platform</h2><Err e={err} />
      <form onSubmit={submit}>
        {mode === "register" && <><label>Full name</label><input required value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></>}
        <label>Email</label><input type="email" required value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} />
        <label>Password (min 8 chars)</label><input type="password" required minLength={8} value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} />
        <p><button className="btn">{mode === "login" ? "Log in" : "Create candidate account"}</button></p>
      </form>
      <button className="btn sec" onClick={() => setMode(mode === "login" ? "register" : "login")}>{mode === "login" ? "New candidate? Register" : "Have an account? Log in"}</button>
      <p className="muted">Demo: admin@demo.com / Admin@12345 · interviewer@demo.com / Interviewer@12345 · candidate@demo.com / Candidate@12345</p>
    </div>
  );
}

/* ---------------- Candidate portal ---------------- */
function CandidateProfile() {
  const [p, reload, err] = useLoad(() => api.get("/me/profile"));
  const [msg, setMsg] = useState(""); const [e2, setE2] = useState(""); const [form, setForm] = useState(null); const [busy, setBusy] = useState(false);
  useEffect(() => { if (p) setForm({ name: p.name || "", phone: p.phone || "", location: p.location || "", summary: p.summary || "", skills: (p.skills || []).join(", ") }); }, [p]);
  const upload = async (file) => {
    if (!file) return; setBusy(true); setE2(""); setMsg("");
    try {
      const r = await api.upload("/me/resume", file);
      for (let i = 0; i < 40; i++) { const s = await api.get(`/me/resume/${r.id}`); if (s.status !== "Processing") { if (s.status === "Failed") throw new Error(s.error); break; } await new Promise((x) => setTimeout(x, 1500)); }
      setMsg("Resume parsed. Please review the extracted information below."); reload();
    } catch (x) { setE2(x.message); } finally { setBusy(false); }
  };
  const save = async () => { setE2(""); try { await api.put("/me/profile", { ...form, skills: csv(form.skills) }); setMsg("Profile saved"); reload(); } catch (x) { setE2(x.message); } };
  if (!p || !form) return <Err e={err} />;
  return (<>
    <div className="card"><h2>Resume</h2><Err e={e2} /><Ok m={msg} />
      <input type="file" accept=".pdf,.docx" disabled={busy} onChange={(e) => upload(e.target.files[0])} />
      <p className="muted">{busy ? "Uploading and parsing with AI…" : p.parse_method ? `Parsed using ${p.parse_method} extraction.` : "Upload a PDF or DOCX resume (max 5 MB)."}</p>
      {(p.parse_warnings || []).length > 0 && <details><summary className="muted">{p.parse_warnings.length} item(s) the AI could not verify were removed</summary><ul>{p.parse_warnings.map((w, i) => <li key={i} className="muted">{w}</li>)}</ul></details>}
    </div>
    <div className="card"><h2>My profile</h2>
      <div className="row"><div><label>Name</label><input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></div>
        <div><label>Email</label><input value={p.email} disabled /></div></div>
      <div className="row"><div><label>Phone</label><input value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} /></div>
        <div><label>Location</label><input value={form.location} onChange={(e) => setForm({ ...form, location: e.target.value })} /></div></div>
      <label>Summary</label><textarea value={form.summary} onChange={(e) => setForm({ ...form, summary: e.target.value })} />
      <label>Skills (comma separated)</label><input value={form.skills} onChange={(e) => setForm({ ...form, skills: e.target.value })} />
      <p><button className="btn" onClick={save}>Confirm & save profile</button></p>
      <ProfileDetails p={p} />
    </div></>);
}

function ProfileDetails({ p }) {
  return (<>
    <h3>Experience ({p.total_experience_years} years)</h3>
    {(p.experience || []).map((e, i) => <p key={i}><b>{e.title}</b> · {e.company} <span className="muted">({e.start} – {e.end})</span><br /><span className="muted">{e.description}</span></p>)}
    <h3>Education</h3>{(p.education || []).map((e, i) => <p key={i}>{e.degree} · {e.institution} <span className="muted">{e.year}</span></p>)}
    <h3>Projects</h3>{(p.projects || []).map((e, i) => <p key={i}><b>{e.name}</b> <span className="muted">{e.description}</span></p>)}
  </>);
}

function CandidateJobs() {
  const [jobs, , err] = useLoad(() => api.get("/jobs")); const [apps, reloadApps] = useLoad(() => api.get("/me/applications")); const [m, setM] = useState(""); const [e, setE] = useState("");
  const apply = async (id) => { setE(""); setM(""); try { await api.post(`/jobs/${id}/apply`); setM("Application submitted"); reloadApps(); } catch (x) { setE(x.message); } };
  const applied = new Set((apps || []).map((a) => a.job_id));
  return (<div className="card"><h2>Open jobs</h2><Err e={err || e} /><Ok m={m} />
    <table><tbody>{(jobs || []).map((j) => <tr key={j.id}><td><b>{j.title}</b><br /><span className="muted">{j.location} · {j.employment_type} · {j.min_experience}-{j.max_experience ?? "+"} yrs · apply by {j.last_date || "open"}</span><p>{j.description}</p>
      {[...j.required_skills.map((s) => [s, 1]), ...j.preferred_skills.map((s) => [s, 0])].map(([s, r]) => <span key={s} className={"pill" + (r ? " warn" : "")}>{s}</span>)}</td>
      <td style={{ width: 120 }}><button className="btn" disabled={applied.has(j.id)} onClick={() => apply(j.id)}>{applied.has(j.id) ? "Applied" : "Apply"}</button></td></tr>)}</tbody></table></div>);
}

function CandidateApplications() {
  const [apps] = useLoad(() => api.get("/me/applications")); const [iv] = useLoad(() => api.get("/me/interviews"));
  return (<><div className="card"><h2>My applications</h2><table><thead><tr><th>Job</th><th>Status</th><th>Updated</th></tr></thead>
    <tbody>{(apps || []).map((a) => <tr key={a.id}><td>{a.job_title}</td><td>{statusPill(a.status)}</td><td>{fmt(a.updated_at)}</td></tr>)}</tbody></table></div>
    <div className="card"><h2>My interviews</h2><table><thead><tr><th>Job</th><th>When</th><th>Duration</th><th>Mode</th><th>Status</th></tr></thead>
      <tbody>{(iv || []).map((i) => <tr key={i.id}><td>{i.job_title}</td><td>{fmt(i.scheduled_at)}</td><td>{i.duration_min} min</td><td>{i.mode} {i.meeting_link && <a href={i.meeting_link}>link</a>}</td><td>{statusPill(i.status)}</td></tr>)}</tbody></table></div></>);
}

/* ---------------- Admin ---------------- */
function Dashboard() {
  const [s, , err] = useLoad(() => api.get("/admin/stats"));
  const L = { total_candidates: "Candidates", total_resumes: "Resumes", active_jobs: "Active jobs", total_applications: "Applications", shortlisted: "Shortlisted", interviews_scheduled: "Interviews scheduled", selected: "Selected" };
  return <div><Err e={err} /><div className="grid">{s && Object.entries(L).map(([k, l]) => <div className="card stat" key={k}><div className="n">{s[k]}</div><div className="l">{l}</div></div>)}</div></div>;
}

const emptyJob = { title: "", description: "", required_skills: "", preferred_skills: "", min_experience: 0, max_experience: "", education: "", location: "", employment_type: "Full-time", last_date: "", status: "Open" };
function Jobs() {
  const [jobs, reload, err] = useLoad(() => api.get("/admin/jobs")); const [f, setF] = useState(emptyJob); const [id, setId] = useState(null); const [e, setE] = useState(""); const [m, setM] = useState("");
  const save = async (ev) => {
    ev.preventDefault(); setE(""); setM("");
    const body = { ...f, required_skills: csv(f.required_skills), preferred_skills: csv(f.preferred_skills), min_experience: +f.min_experience || 0, max_experience: f.max_experience === "" ? null : +f.max_experience, last_date: f.last_date || null };
    try { id ? await api.put(`/admin/jobs/${id}`, body) : await api.post("/admin/jobs", body); setM("Job saved"); setF(emptyJob); setId(null); reload(); } catch (x) { setE(x.message); }
  };
  const edit = (j) => { setId(j.id); setF({ ...j, required_skills: j.required_skills.join(", "), preferred_skills: j.preferred_skills.join(", "), max_experience: j.max_experience ?? "", last_date: j.last_date || "", education: j.education || "", location: j.location || "" }); window.scrollTo(0, 0); };
  const set = (k) => (ev) => setF({ ...f, [k]: ev.target.value });
  return (<><div className="card"><h2>{id ? `Edit job #${id}` : "Create job"}</h2><Err e={e || err} /><Ok m={m} />
    <form onSubmit={save}>
      <div className="row"><div><label>Title</label><input required value={f.title} onChange={set("title")} /></div><div><label>Location</label><input value={f.location} onChange={set("location")} /></div>
        <div><label>Employment type</label><select value={f.employment_type} onChange={set("employment_type")}>{["Full-time", "Part-time", "Contract", "Internship"].map((x) => <option key={x}>{x}</option>)}</select></div></div>
      <label>Description</label><textarea required minLength={10} value={f.description} onChange={set("description")} />
      <div className="row"><div><label>Required skills (comma separated)</label><input value={f.required_skills} onChange={set("required_skills")} /></div><div><label>Preferred skills</label><input value={f.preferred_skills} onChange={set("preferred_skills")} /></div></div>
      <div className="row"><div><label>Min exp (yrs)</label><input type="number" min="0" step="0.5" value={f.min_experience} onChange={set("min_experience")} /></div><div><label>Max exp (yrs)</label><input type="number" min="0" step="0.5" value={f.max_experience} onChange={set("max_experience")} /></div>
        <div><label>Education requirement</label><input value={f.education} onChange={set("education")} /></div><div><label>Last application date</label><input type="date" value={f.last_date} onChange={set("last_date")} /></div>
        <div><label>Status</label><select value={f.status} onChange={set("status")}>{["Draft", "Open", "Closed"].map((x) => <option key={x}>{x}</option>)}</select></div></div>
      <p><button className="btn">{id ? "Update job" : "Create job"}</button> {id && <button type="button" className="btn sec" onClick={() => { setId(null); setF(emptyJob); }}>Cancel</button>}</p></form></div>
    <div className="card"><h2>Jobs</h2><table><thead><tr><th>Title</th><th>Location</th><th>Exp</th><th>Status</th><th></th></tr></thead><tbody>{(jobs || []).map((j) =>
      <tr key={j.id}><td>{j.title}<br />{j.required_skills.map((s) => <span className="pill" key={s}>{s}</span>)}</td><td>{j.location}</td><td>{j.min_experience}-{j.max_experience ?? "+"}</td><td>{statusPill(j.status)}</td>
        <td><button className="btn sec" onClick={() => edit(j)}>Edit</button> <button className="btn danger" onClick={async () => { if (confirm("Delete this job and its applications?")) { await api.del(`/admin/jobs/${j.id}`); reload(); } }}>Delete</button></td></tr>)}</tbody></table></div></>);
}

function Resumes() {
  const [list, reload, err] = useLoad(() => api.get("/admin/resumes")); const [e, setE] = useState(""); const [busy, setBusy] = useState(false);
  useEffect(() => { const t = setInterval(() => { if ((list || []).some((r) => r.status === "Processing")) reload(); }, 2000); return () => clearInterval(t); }, [list, reload]);
  const upload = async (files) => { if (!files.length) return; setBusy(true); setE(""); try { await api.upload("/admin/resumes/bulk", [...files], "files"); reload(); } catch (x) { setE(x.message); } finally { setBusy(false); } };
  return (<div className="card"><h2>Bulk resume upload</h2><Err e={e || err} />
    <input type="file" multiple disabled={busy} onChange={(ev) => upload(ev.target.files)} /><p className="muted">PDF/DOCX. Each file is parsed individually; failures don't affect other files.</p>
    <table><thead><tr><th>File</th><th>Status</th><th>Candidate</th><th>Details</th></tr></thead><tbody>{(list || []).map((r) =>
      <tr key={r.id}><td>{r.filename}</td><td>{statusPill(r.status)}</td><td>{r.candidate_name}</td><td className="muted">{r.error}{r.duplicate_of && <span className="pill warn">duplicate of #{r.duplicate_of}</span>}</td></tr>)}</tbody></table></div>);
}

function CandidateModal({ id, onClose, jobId }) {
  const [c, reload, err] = useLoad(() => api.get(`/candidates/${id}`), [id]); const [note, setNote] = useState(""); const [skills, setSkills] = useState(null); const [m, setM] = useState("");
  useEffect(() => { if (c) setSkills(c.skills.join(", ")); }, [c]);
  if (!c) return <div className="modal"><div className="card"><Err e={err} /></div></div>;
  const mine = (c.applications || []).filter((a) => !jobId || a.job_id === jobId);
  return (<div className="modal" onClick={onClose}><div className="card" onClick={(e) => e.stopPropagation()}>
    <p style={{ float: "right" }}><button className="btn sec" onClick={onClose}>Close</button></p>
    <h2>{c.name}</h2><p className="muted">{c.email} · {c.phone} · {c.location} · parsed via {c.parse_method} {c.reviewed ? <span className="pill ok">reviewed</span> : <span className="pill warn">unreviewed</span>}</p>
    <p>{c.summary}</p><Ok m={m} />
    <label>Skills (edit to correct AI extraction)</label><div className="row"><input value={skills || ""} onChange={(e) => setSkills(e.target.value)} />
      <button className="btn" onClick={async () => { await api.put(`/admin/candidates/${id}`, { skills: csv(skills) }); setM("Corrections saved; embedding refreshed"); reload(); }}>Save</button></div>
    <ProfileDetails p={c} />
    {(c.parse_warnings || []).length > 0 && <details><summary className="muted">AI extraction warnings ({c.parse_warnings.length})</summary><ul>{c.parse_warnings.map((w, i) => <li className="muted" key={i}>{w}</li>)}</ul></details>}
    {mine.map((a) => <div key={a.id} className="card"><b>{a.job_title || `Job #${a.job_id}`}</b> — score <b>{a.score}</b> {statusPill(a.status)}
      <p>{a.detail?.reason}</p>
      <p>{(a.detail?.matched_skills || []).map((s) => <span className="pill ok" key={s}>{s}</span>)}{(a.detail?.missing_skills || []).map((s) => <span className="pill bad" key={s}>{s}</span>)}</p></div>)}
    <h3>Internal notes</h3>{(c.notes || []).map((n) => <p key={n.id}><span className="muted">{n.author} · {fmt(n.created_at)}</span><br />{n.text}</p>)}
    <div className="row"><input placeholder="Add an internal note" value={note} onChange={(e) => setNote(e.target.value)} />
      <button className="btn" onClick={async () => { if (note.trim()) { await api.post(`/admin/candidates/${id}/notes`, { text: note }); setNote(""); reload(); } }}>Add</button></div>
  </div></div>);
}

function Candidates() {
  const [f, setF] = useState({ skill: "", min_exp: "", location: "", q: "" }); const [list, setList] = useState([]); const [open, setOpen] = useState(null);
  const [nl, setNl] = useState(""); const [sr, setSr] = useState(null); const [e, setE] = useState("");
  const load = useCallback(async () => { const p = new URLSearchParams(Object.entries(f).filter(([, v]) => v)); try { setList(await api.get("/admin/candidates?" + p)); } catch (x) { setE(x.message); } }, [f]);
  useEffect(() => { load(); }, []); // eslint-disable-line
  return (<><div className="card"><h2>Semantic search</h2><Err e={e} />
    <div className="row"><input placeholder='e.g. "Python developer with LLM and embeddings experience in Pune"' value={nl} onChange={(x) => setNl(x.target.value)} onKeyDown={(x) => x.key === "Enter" && document.getElementById("go").click()} />
      <button id="go" className="btn" onClick={async () => { try { setSr(await api.post("/admin/search", { query: nl })); setE(""); } catch (x) { setE(x.message); } }}>Search</button></div>
    {sr && <><p className="muted">Understood: skills {sr.interpreted.skills.join(", ") || "—"} · min years {sr.interpreted.min_years ?? "—"} · location {sr.interpreted.location ?? "—"}</p>
      <table><tbody>{sr.results.map((r) => <tr key={r.candidate_id}><td><a href="#" onClick={(x) => { x.preventDefault(); setOpen(r.candidate_id); }}>{r.name}</a><br /><span className="muted">{r.why}</span></td><td>{r.years} yrs</td><td style={{ width: 120 }}><div className="bar"><i style={{ width: r.score + "%" }} /></div>{r.score}</td></tr>)}</tbody></table></>}</div>
    <div className="card"><h2>Candidates</h2>
      <div className="row"><input placeholder="Skills (comma sep.)" value={f.skill} onChange={(x) => setF({ ...f, skill: x.target.value })} /><input placeholder="Min years" type="number" value={f.min_exp} onChange={(x) => setF({ ...f, min_exp: x.target.value })} />
        <input placeholder="Location" value={f.location} onChange={(x) => setF({ ...f, location: x.target.value })} /><input placeholder="Name/email" value={f.q} onChange={(x) => setF({ ...f, q: x.target.value })} /><button className="btn" onClick={load}>Filter</button></div>
      <table><thead><tr><th>Name</th><th>Location</th><th>Exp</th><th>Skills</th></tr></thead><tbody>{list.map((c) => <tr key={c.id}><td><a href="#" onClick={(x) => { x.preventDefault(); setOpen(c.id); }}>{c.name}</a><br /><span className="muted">{c.email}</span></td><td>{c.location}</td><td>{c.total_experience_years}</td>
        <td>{c.skills.slice(0, 8).map((s) => <span className="pill" key={s}>{s}</span>)}</td></tr>)}</tbody></table></div>
    {open && <CandidateModal id={open} onClose={() => setOpen(null)} />}</>);
}

function Matching() {
  const [jobs] = useLoad(() => api.get("/admin/jobs")); const [jid, setJid] = useState(""); const [ms, setMs] = useState([]); const [sel, setSel] = useState(new Set()); const [open, setOpen] = useState(null);
  const [e, setE] = useState(""); const [m, setM] = useState(""); const [busy, setBusy] = useState(false); const [exp, setExp] = useState(null);
  const run = async () => { setBusy(true); setE(""); try { setMs(await api.post(`/admin/jobs/${jid}/match`)); } catch (x) { setE(x.message); } setBusy(false); };
  const refresh = async () => setMs(await api.get(`/admin/jobs/${jid}/matches`));
  const act = async (fn, msg) => { setE(""); setM(""); try { await fn(); setM(msg); await refresh(); } catch (x) { setE(x.message); } };
  const interviewers = useLoad(() => api.get("/admin/users?role=interviewer"))[0] || [];
  const [sch, setSch] = useState({ interviewer_id: "", scheduled_at: "", duration_min: 45, meeting_link: "" });
  return (<div className="card"><h2>AI candidate matching</h2><Err e={e} /><Ok m={m} />
    <div className="row"><select value={jid} onChange={(x) => { setJid(x.target.value); setMs([]); setSel(new Set()); if (x.target.value) api.get(`/admin/jobs/${x.target.value}/matches`).then(setMs).catch(() => {}); }}><option value="">Select a job…</option>{(jobs || []).map((j) => <option key={j.id} value={j.id}>{j.title}</option>)}</select>
      <button className="btn" disabled={!jid || busy} onClick={run}>{busy ? "Matching…" : "Run matching"}</button>
      <button className="btn sec" disabled={!sel.size} onClick={() => act(() => api.post("/admin/shortlist", { job_id: +jid, candidate_ids: [...sel] }), `${sel.size} candidate(s) shortlisted`)}>Shortlist selected</button>
      <button className="btn sec" disabled={!jid} onClick={() => api.download(`/admin/jobs/${jid}/shortlist/export?format=csv`, "shortlist.csv").catch((x) => setE(x.message))}>Export CSV</button>
      <button className="btn sec" disabled={!jid} onClick={() => api.download(`/admin/jobs/${jid}/shortlist/export?format=xlsx`, "shortlist.xlsx").catch((x) => setE(x.message))}>Export Excel</button>
      <button className="btn sec" disabled={!jid} onClick={async () => { try { const r = await api.post(`/admin/jobs/${jid}/share`); setM("Share link (expires in 72h): " + location.origin.replace("5173", "8000") + r.path); } catch (x) { setE(x.message); } }}>Share shortlist</button></div>
    <table><thead><tr><th></th><th>Candidate</th><th>Score</th><th>Exp</th><th>AI recommendation</th><th>Status</th><th></th></tr></thead><tbody>{ms.map((a) => <React.Fragment key={a.id}><tr>
      <td><input type="checkbox" style={{ width: "auto" }} checked={sel.has(a.candidate_id)} onChange={() => { const n = new Set(sel); n.has(a.candidate_id) ? n.delete(a.candidate_id) : n.add(a.candidate_id); setSel(n); }} /></td>
      <td><a href="#" onClick={(x) => { x.preventDefault(); setOpen(a.candidate_id); }}>{a.candidate_name}</a>{a.applied ? <span className="pill">applied</span> : null}<br />
        {(a.detail?.matched_skills || []).map((s) => <span className="pill ok" key={s}>{s}</span>)}{(a.detail?.missing_skills || []).map((s) => <span className="pill bad" key={s}>{s}</span>)}</td>
      <td style={{ width: 110 }}><b>{a.score}</b><div className="bar"><i style={{ width: a.score + "%" }} /></div></td><td>{a.total_experience_years} yrs</td>
      <td>{a.ai_recommendation}{a.override_decision && <div><span className="pill warn">Admin: {a.override_decision}</span><br /><span className="muted">{a.override_reason}</span></div>}</td><td>{statusPill(a.status)}</td>
      <td><button className="btn sec" onClick={() => setExp(exp === a.id ? null : a.id)}>Why?</button></td></tr>
      {exp === a.id && <tr><td colSpan="7" className="muted"><p>{a.detail.reason}</p><p>Breakdown: {Object.entries(a.detail.breakdown).map(([k, v]) => `${k}: ${v}`).join(" · ")}</p>
        <div className="row"><button className="btn" onClick={() => act(() => api.post(`/admin/applications/${a.id}/approve`), "Approved; candidate notified by email")}>Approve for interview</button>
          <button className="btn sec" onClick={() => { const r = prompt("Reason for overriding the AI recommendation:"); if (r) act(() => api.post(`/admin/applications/${a.id}/override`, { decision: a.ai_recommendation?.startsWith("Weak") || a.ai_recommendation?.startsWith("Partial") ? "Recommend" : "Do not recommend", reason: r }), "Override recorded"); }}>Override AI</button>
          <button className="btn sec" onClick={() => act(() => api.post(`/admin/applications/${a.id}/override`, { decision: "Clear" }), "Override cleared")}>Clear override</button>
          <button className="btn sec" onClick={() => act(() => api.put(`/admin/applications/${a.id}/status`, { status: "Selected" }), "Marked as Selected")}>Select</button>
          <button className="btn danger" onClick={() => act(() => api.put(`/admin/applications/${a.id}/status`, { status: "Rejected" }), "Marked as Rejected")}>Reject</button></div>
        {["Approved for Interview", "Interview Scheduled"].includes(a.status) && <div className="row"><select value={sch.interviewer_id} onChange={(x) => setSch({ ...sch, interviewer_id: x.target.value })}><option value="">Interviewer…</option>{interviewers.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}</select>
          <input type="datetime-local" value={sch.scheduled_at} onChange={(x) => setSch({ ...sch, scheduled_at: x.target.value })} /><input type="number" value={sch.duration_min} onChange={(x) => setSch({ ...sch, duration_min: +x.target.value })} /><input placeholder="Meeting link (optional)" value={sch.meeting_link} onChange={(x) => setSch({ ...sch, meeting_link: x.target.value })} />
          <button className="btn" onClick={() => act(() => api.post("/admin/interviews", { application_id: a.id, interviewer_id: +sch.interviewer_id, scheduled_at: sch.scheduled_at, duration_min: sch.duration_min, meeting_link: sch.meeting_link || null }), "Interview scheduled; candidate notified")}>Schedule</button></div>}
      </td></tr>}</React.Fragment>)}</tbody></table>
    {open && <CandidateModal id={open} jobId={+jid} onClose={() => setOpen(null)} />}</div>);
}

function AdminInterviews() {
  const [list, reload, err] = useLoad(() => api.get("/admin/interviews")); const [fb] = useLoad(() => api.get("/admin/feedback")); const [e, setE] = useState("");
  const [staff, setStaff] = useState({ name: "", email: "", password: "", role: "interviewer" }); const [m, setM] = useState("");
  const act = async (fn) => { setE(""); try { await fn(); reload(); } catch (x) { setE(x.message); } };
  return (<><div className="card"><h2>Interviews</h2><Err e={e || err} />
    <table><thead><tr><th>Candidate</th><th>Job</th><th>Interviewer</th><th>When</th><th>Status</th><th></th></tr></thead><tbody>{(list || []).map((i) => <tr key={i.id}><td>{i.candidate_name}</td><td>{i.job_title}</td><td>{i.interviewer_name}</td><td>{fmt(i.scheduled_at)} ({i.duration_min}m)</td><td>{statusPill(i.status)}</td>
      <td>{i.status === "Scheduled" && <><button className="btn sec" onClick={() => { const v = prompt("New date/time (YYYY-MM-DDTHH:MM):", i.scheduled_at); if (v) act(() => api.put(`/admin/interviews/${i.id}`, { scheduled_at: v })); }}>Reschedule</button> <button className="btn danger" onClick={() => confirm("Cancel interview?") && act(() => api.put(`/admin/interviews/${i.id}`, { cancel: true }))}>Cancel</button></>}</td></tr>)}</tbody></table></div>
    <div className="card"><h2>Interview feedback</h2><table><thead><tr><th>Candidate</th><th>By</th><th>Tech</th><th>Comm</th><th>Problem solving</th><th>Recommendation</th><th>Remarks</th></tr></thead><tbody>{(fb || []).map((f) => <tr key={f.id}><td>{f.candidate_name}<br /><span className="muted">{f.job_title}</span></td><td>{f.interviewer}</td><td>{f.technical}/5</td><td>{f.communication}/5</td><td>{f.problem_solving}/5</td><td>{f.recommendation}</td><td>{f.remarks}</td></tr>)}</tbody></table></div>
    <div className="card"><h2>Add interviewer / admin</h2><Ok m={m} /><div className="row"><input placeholder="Name" value={staff.name} onChange={(x) => setStaff({ ...staff, name: x.target.value })} /><input placeholder="Email" value={staff.email} onChange={(x) => setStaff({ ...staff, email: x.target.value })} /><input placeholder="Password (min 8)" type="password" value={staff.password} onChange={(x) => setStaff({ ...staff, password: x.target.value })} />
      <select value={staff.role} onChange={(x) => setStaff({ ...staff, role: x.target.value })}><option>interviewer</option><option>admin</option></select><button className="btn" onClick={async () => { try { await api.post("/admin/users", staff); setM("User created"); setStaff({ name: "", email: "", password: "", role: "interviewer" }); } catch (x) { setE(x.message); } }}>Create</button></div></div></>);
}

/* ---------------- Interviewer ---------------- */
function InterviewerHome() {
  const [list, reload, err] = useLoad(() => api.get("/interviewer/interviews")); const [open, setOpen] = useState(null); const [fb, setFb] = useState(null); const [e, setE] = useState(""); const [m, setM] = useState("");
  const blank = { technical: 3, communication: 3, problem_solving: 3, remarks: "", recommendation: "Hire" };
  return (<><div className="card"><h2>My interviews</h2><Err e={e || err} /><Ok m={m} />
    <table><thead><tr><th>Candidate</th><th>Job</th><th>When</th><th>Status</th><th></th></tr></thead><tbody>{(list || []).map((i) => <tr key={i.id}><td><a href="#" onClick={(x) => { x.preventDefault(); setOpen(i.candidate_id); }}>{i.candidate_name}</a></td><td>{i.job_title}</td><td>{fmt(i.scheduled_at)}</td><td>{statusPill(i.status)}</td>
      <td>{i.status !== "Cancelled" && !i.has_feedback && <button className="btn" onClick={() => setFb({ id: i.id, ...blank })}>Give feedback</button>}{i.has_feedback ? <span className="pill ok">feedback submitted</span> : null}</td></tr>)}</tbody></table></div>
    {fb && <div className="card"><h2>Feedback</h2><div className="row">{["technical", "communication", "problem_solving"].map((k) => <div key={k}><label>{k.replace("_", " ")} (1-5)</label><input type="number" min="1" max="5" value={fb[k]} onChange={(x) => setFb({ ...fb, [k]: +x.target.value })} /></div>)}
      <div><label>Recommendation</label><select value={fb.recommendation} onChange={(x) => setFb({ ...fb, recommendation: x.target.value })}>{["Strong Hire", "Hire", "No Hire", "Strong No Hire"].map((x) => <option key={x}>{x}</option>)}</select></div></div>
      <label>Remarks</label><textarea value={fb.remarks} onChange={(x) => setFb({ ...fb, remarks: x.target.value })} />
      <p><button className="btn" onClick={async () => { try { const { id, ...b } = fb; await api.post(`/interviewer/interviews/${id}/feedback`, b); setFb(null); setM("Feedback submitted"); reload(); } catch (x) { setE(x.message); } }}>Submit</button> <button className="btn sec" onClick={() => setFb(null)}>Cancel</button></p></div>}
    {open && <InterviewerCandidate id={open} onClose={() => setOpen(null)} />}</>);
}
function InterviewerCandidate({ id, onClose }) {
  const [c, , err] = useLoad(() => api.get(`/candidates/${id}`), [id]);
  return (<div className="modal" onClick={onClose}><div className="card" onClick={(x) => x.stopPropagation()}><p style={{ float: "right" }}><button className="btn sec" onClick={onClose}>Close</button></p><Err e={err} />{c && <><h2>{c.name}</h2><p className="muted">{c.email} · {c.location}</p><p>{c.summary}</p><p>{c.skills.map((s) => <span className="pill" key={s}>{s}</span>)}</p><ProfileDetails p={c} /></>}</div></div>);
}

/* ---------------- Shell ---------------- */
const TABS = {
  candidate: { Profile: CandidateProfile, Jobs: CandidateJobs, "Applications & interviews": CandidateApplications },
  admin: { Dashboard, Jobs, Resumes, Candidates, Matching, Interviews: AdminInterviews },
  interviewer: { "My interviews": InterviewerHome },
};

export default function App() {
  const [user, setUser] = useState(auth.user); const tabs = user && TABS[user.role]; const [tab, setTab] = useState(null);
  if (!user) return <Login onDone={(u) => { setUser(u); setTab(null); }} />;
  const cur = tab && tabs[tab] ? tab : Object.keys(tabs)[0]; const View = tabs[cur];
  return (<><header><b>AI Recruitment</b><nav>{Object.keys(tabs).map((t) => <button key={t} className={t === cur ? "active" : ""} onClick={() => setTab(t)}>{t}</button>)}</nav>
    <span className="muted" style={{ color: "#cfd5e6" }}>{user.name} ({user.role})</span><button className="btn sec" onClick={() => { auth.clear(); setUser(null); }}>Log out</button></header>
    <main><View key={cur} /></main></>);
}
