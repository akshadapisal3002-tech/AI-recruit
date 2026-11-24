"""Generates FICTIONAL sample resumes (PDF + DOCX), invalid test files and job descriptions into ../sample_data."""
import json, os
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "sample_data"

PEOPLE = [
 dict(file="aarav_mehta.pdf", name="Aarav Mehta", email="aarav.mehta@example.com", phone="+91 98765 43210", loc="Pune, India",
  summary="Backend engineer building scalable Python services and REST APIs.",
  skills="Python, FastAPI, PostgreSQL, Redis, Docker, AWS, REST API, Git, Linux",
  exp=[("Senior Backend Engineer", "Acme Payments", "Jan 2021 - Present", "Designed FastAPI microservices on AWS with PostgreSQL and Redis caching. Containerised services with Docker."),
       ("Software Engineer", "Zenith Systems", "Jul 2019 - Dec 2020", "Built REST APIs in Python and Flask; wrote unit tests with pytest.")],
  proj=[("Order Tracking API", "FastAPI service with PostgreSQL and Docker compose deployment.")],
  edu=[("B.Tech in Computer Science", "Savitribai Phule Pune University", "2015 - 2019")]),
 dict(file="priya_nair.pdf", name="Priya Nair", email="priya.nair@example.com", phone="+91 91234 56780", loc="Bengaluru, India",
  summary="Full-stack developer focused on React front ends and Node.js back ends.",
  skills="JavaScript, TypeScript, React, Node.js, Express, MongoDB, HTML, CSS, Git",
  exp=[("Full Stack Developer", "Brightside Labs", "Mar 2021 - Present", "Built React dashboards and Node.js Express APIs with MongoDB."),
       ("Frontend Developer", "PixelWorks", "Jun 2020 - Feb 2021", "Developed responsive UIs in React and CSS.")],
  proj=[("Team Chat App", "Real-time chat using React, Node.js and websockets.")],
  edu=[("B.E in Information Technology", "Visvesvaraya Technological University", "2016 - 2020")]),
 dict(file="rohan_kulkarni.pdf", name="Rohan Kulkarni", email="rohan.kulkarni@example.com", phone="+91 99887 76655", loc="Pune, India",
  summary="ML engineer working on LLM applications, retrieval augmented generation and embeddings.",
  skills="Python, PyTorch, LLM, RAG, LangChain, Embeddings, FastAPI, Vector Database, Docker, Hugging Face",
  exp=[("Machine Learning Engineer", "Insight AI", "Aug 2022 - Present", "Built RAG pipelines with LangChain, embeddings and a vector database. Served models via FastAPI."),
       ("Data Science Intern", "DataNest", "Jan 2022 - Jul 2022", "Trained PyTorch text classifiers and evaluated them.")],
  proj=[("Policy QA Bot", "RAG chatbot using embeddings, FAISS and an LLM with citations.")],
  edu=[("M.Tech in Artificial Intelligence", "College of Engineering Pune", "2020 - 2022")]),
 dict(file="sneha_iyer.pdf", name="Sneha Iyer", email="sneha.iyer@example.com", phone="+91 90000 11122", loc="Mumbai, India",
  summary="Data analyst turning business data into dashboards and insights.",
  skills="SQL, Excel, Power BI, Tableau, Python, Pandas, Data Analysis",
  exp=[("Data Analyst", "RetailCo", "Jun 2022 - Present", "Built Power BI dashboards and SQL reports; automated Excel reporting with Python and Pandas.")],
  proj=[("Sales Dashboard", "Interactive Tableau dashboard for regional sales.")],
  edu=[("B.Sc in Statistics", "University of Mumbai", "2018 - 2021")]),
 dict(file="karan_desai.pdf", name="Karan Desai", email="karan.desai@example.com", phone="+91 93456 78901", loc="Hyderabad, India",
  summary="DevOps engineer automating cloud infrastructure and CI/CD pipelines.",
  skills="Docker, Kubernetes, AWS, Terraform, Jenkins, Linux, Ansible, CI/CD, Python, Bash",
  exp=[("Senior DevOps Engineer", "CloudNine Tech", "Feb 2020 - Present", "Managed Kubernetes clusters on AWS with Terraform and Jenkins CI/CD pipelines."),
       ("Systems Engineer", "NetCore", "Jul 2017 - Jan 2020", "Administered Linux servers and automated tasks with Bash and Ansible.")],
  proj=[("Infra as Code Library", "Reusable Terraform modules for AWS networking.")],
  edu=[("B.Tech in Electronics", "JNTU Hyderabad", "2013 - 2017")]),
 dict(file="ananya_rao.pdf", name="Ananya Rao", email="ananya.rao@example.com", phone="+91 97000 22233", loc="Pune, India",
  summary="Recent graduate with Java and Spring Boot internship experience.",
  skills="Java, Spring Boot, MySQL, REST API, Git",
  exp=[("Software Intern", "TechSprout", "Jan 2024 - Jun 2024", "Built Spring Boot REST APIs backed by MySQL.")],
  proj=[("Library Management System", "Java and MySQL application with Spring Boot.")],
  edu=[("B.Tech in Computer Engineering", "MIT World Peace University", "2020 - 2024")]),
 dict(file="vikram_singh.docx", name="Vikram Singh", email="vikram.singh@example.com", phone="+91 98111 22334", loc="Pune, India",
  summary="AI engineer with experience in NLP, LLM prompt engineering and Python back ends.",
  skills="Python, NLP, LLM, Prompt Engineering, FastAPI, scikit-learn, PostgreSQL, Docker, Embeddings",
  exp=[("AI Engineer", "Lexicon Labs", "Sep 2021 - Present", "Developed NLP services and LLM-based extraction with FastAPI and PostgreSQL; used embeddings for semantic search."),
       ("Python Developer", "CodeCraft", "Jun 2020 - Aug 2021", "Built backend services in Python and automated testing.")],
  proj=[("Resume Screener", "Semantic search over resumes with embeddings and scikit-learn.")],
  edu=[("B.Tech in Computer Science", "Pune Institute of Computer Technology", "2016 - 2020")]),
 dict(file="aarav_mehta_duplicate.docx", name="Aarav Mehta", email="aarav.mehta@example.com", phone="+91 98765 43210", loc="Pune, India",
  summary="Backend engineer building scalable Python services and REST APIs.",
  skills="Python, FastAPI, PostgreSQL, Redis, Docker, AWS, REST API, Git, Linux",
  exp=[("Senior Backend Engineer", "Acme Payments", "Jan 2021 - Present", "Designed FastAPI microservices on AWS with PostgreSQL and Redis caching.")],
  proj=[], edu=[("B.Tech in Computer Science", "Savitribai Phule Pune University", "2015 - 2019")]),
]

JOBS = [
 dict(title="AI / LLM Engineer", description="Build LLM-powered products: retrieval augmented generation, embeddings, semantic search and FastAPI services. Work with Python and vector databases to ship reliable AI features.",
      required_skills=["python", "llm", "rag", "embeddings", "fastapi"], preferred_skills=["pytorch", "docker", "vector database", "langchain"],
      min_experience=2, max_experience=5, education="Bachelor's degree in Computer Science or related field", location="Pune", employment_type="Full-time", last_date="2027-12-31", status="Open"),
 dict(title="Backend Engineer (Python)", description="Design and maintain REST APIs and microservices using Python, FastAPI and PostgreSQL. Deploy with Docker on AWS.",
      required_skills=["python", "fastapi", "postgresql", "docker", "rest api"], preferred_skills=["aws", "redis", "kubernetes"],
      min_experience=3, max_experience=7, education="Bachelor's degree in Engineering", location="Pune", employment_type="Full-time", last_date="2027-12-31", status="Open"),
 dict(title="Data Analyst", description="Analyse business data with SQL and Python, build dashboards in Power BI or Tableau and present insights.",
      required_skills=["sql", "excel", "power bi"], preferred_skills=["python", "tableau", "pandas"],
      min_experience=1, max_experience=4, education="Bachelor's degree", location="Mumbai", employment_type="Full-time", last_date="2027-12-31", status="Open"),
]


def pdf(p, path):
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    ss = getSampleStyleSheet(); story = []
    for kind, text in lines(p):
        story.append(Paragraph(text, ss["Title"] if kind == "t" else ss["Heading3"] if kind == "h" else ss["BodyText"]))
        story.append(Spacer(1, 3))
    SimpleDocTemplate(str(path)).build(story)


def docx(p, path):
    import docx as d
    doc = d.Document()
    for kind, text in lines(p):
        if kind == "t": doc.add_heading(text, 0)
        elif kind == "h": doc.add_heading(text, 2)
        else: doc.add_paragraph(text)
    doc.save(path)


def lines(p):
    L = [("t", p["name"]), ("p", f"{p['email']} | {p['phone']} | {p['loc']}"), ("h", "SUMMARY"), ("p", p["summary"]), ("h", "SKILLS"), ("p", p["skills"]), ("h", "EXPERIENCE")]
    for t, c, dts, desc in p["exp"]: L += [("p", f"<b>{t} | {c} | {dts}</b>".replace("<b>", "").replace("</b>", "")), ("p", "- " + desc)]
    if p["proj"]:
        L.append(("h", "PROJECTS"))
        for n, desc in p["proj"]: L += [("p", f"{n} - {desc}")]
    L.append(("h", "EDUCATION"))
    for deg, inst, yrs in p["edu"]: L.append(("p", f"{deg} | {inst} | {yrs}"))
    return L


if __name__ == "__main__":
    (OUT / "resumes").mkdir(parents=True, exist_ok=True); (OUT / "invalid").mkdir(parents=True, exist_ok=True)
    for p in PEOPLE:
        (docx if p["file"].endswith("docx") else pdf)(p, OUT / "resumes" / p["file"])
    (OUT / "invalid" / "not_a_resume.txt").write_text("This is just a text file, not a resume.")
    (OUT / "invalid" / "corrupted.pdf").write_bytes(b"%PDF-1.4\n" + os.urandom(300))
    (OUT / "invalid" / "empty.docx").write_bytes(b"")
    (OUT / "jobs.json").write_text(json.dumps(JOBS, indent=2))
    print("Sample data written to", OUT)
