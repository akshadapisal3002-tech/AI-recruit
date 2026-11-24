"""Skill vocabulary + alias normalisation shared by parsing, matching and search."""
import re

# canonical skill -> aliases (lowercase)
SKILLS = {
    "python": ["python3", "py"], "java": [], "javascript": ["js", "es6", "ecmascript"],
    "typescript": ["ts"], "c++": ["cpp"], "c#": ["csharp"], ".net": ["dotnet", ".net core", "asp.net"],
    "golang": ["go lang"], "rust": [], "php": [], "ruby": [], "kotlin": [], "swift": [], "scala": [],
    "sql": [], "html": ["html5"], "css": ["css3"], "bash": ["shell scripting"],
    "react": ["reactjs", "react.js"], "angular": ["angularjs"], "vue": ["vue.js", "vuejs"],
    "next.js": ["nextjs"], "redux": [], "tailwind": ["tailwindcss"], "node.js": ["nodejs", "node"],
    "express": ["express.js", "expressjs"], "django": [], "flask": [], "fastapi": [],
    "spring boot": ["springboot", "spring"], "graphql": [], "rest api": ["rest", "restful", "restful api", "rest apis"],
    "postgresql": ["postgres", "psql"], "mysql": [], "sqlite": [], "mongodb": ["mongo"],
    "redis": [], "elasticsearch": ["elastic search"], "kafka": ["apache kafka"], "rabbitmq": [],
    "docker": ["containers", "containerization"], "kubernetes": ["k8s"], "aws": ["amazon web services"],
    "azure": [], "gcp": ["google cloud", "google cloud platform"], "terraform": [], "ansible": [],
    "ci/cd": ["cicd", "ci cd", "continuous integration"], "jenkins": [], "github actions": [],
    "git": ["github", "gitlab"], "linux": [], "nginx": [], "microservices": ["microservice"],
    "machine learning": ["ml"], "deep learning": ["dl"], "nlp": ["natural language processing"],
    "computer vision": ["opencv"], "pytorch": ["torch"], "tensorflow": [], "keras": [],
    "scikit-learn": ["sklearn", "scikit learn"], "pandas": [], "numpy": [], "llm": ["llms", "large language models"],
    "langchain": [], "rag": ["retrieval augmented generation", "retrieval-augmented generation"],
    "embeddings": ["embedding", "vector embeddings"],
    "vector database": ["vector db", "vector store", "pgvector", "faiss", "chromadb", "qdrant", "pinecone"],
    "prompt engineering": [], "hugging face": ["huggingface", "transformers"],
    "data analysis": ["data analytics"], "power bi": ["powerbi"], "tableau": [], "excel": [],
    "spark": ["pyspark", "apache spark"], "airflow": [], "etl": [], "data engineering": [],
    "react native": [], "flutter": [], "android": [], "ios": [],
    "selenium": [], "pytest": [], "jest": [], "unit testing": ["unit tests"], "agile": ["scrum"],
    "jira": [], "figma": [], "ui/ux": ["ux design", "ui design"], "system design": [],
    "oauth": ["oauth2"], "jwt": [], "websockets": ["websocket"], "webrtc": [],
    "communication": [], "leadership": [], "project management": [],
}

ALIAS_TO_CANON = {}
for _canon, _aliases in SKILLS.items():
    ALIAS_TO_CANON[_canon] = _canon
    for _a in _aliases:
        ALIAS_TO_CANON[_a] = _canon

_TERMS = sorted(ALIAS_TO_CANON, key=len, reverse=True)
_PATTERNS = [(t, re.compile(r"(?<![A-Za-z0-9+#.])" + re.escape(t) + r"(?![A-Za-z0-9+#])", re.I)) for t in _TERMS]
# short/ambiguous aliases are only accepted when written exactly like this
_CASE_SENSITIVE = {"py", "ts", "js", "ml", "dl"}


def canonical(skill: str) -> str:
    s = (skill or "").strip().lower()
    return ALIAS_TO_CANON.get(s, s)


def extract_skills(text: str) -> list:
    """Canonical skills literally mentioned in `text` (never inferred)."""
    found = []
    for term, pat in _PATTERNS:
        m = pat.search(text or "")
        if not m:
            continue
        if term in _CASE_SENSITIVE and m.group(0) != term:
            continue
        c = ALIAS_TO_CANON[term]
        if c not in found:
            found.append(c)
    return found


def mentions(text: str, skill: str) -> bool:
    """True if `skill` (or an alias) literally appears in text."""
    c = canonical(skill)
    if c in extract_skills(text):
        return True
    return bool(re.search(r"(?<![A-Za-z0-9])" + re.escape((skill or "").lower()) + r"(?![A-Za-z0-9])", (text or "").lower()))
