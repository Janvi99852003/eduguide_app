"""
EduGuide Agent v2 - Deployable multi-agent tutoring system
Upgrades over the Kaggle notebook version:
  1. Real web app (FastAPI + simple chat UI) instead of notebook-only
  2. SQLite persistence - session history, quiz scores survive restarts
  3. RAG pipeline - users can upload their own material (PDF/text) instead
     of being limited to Wikipedia; falls back to Wikipedia if no upload
"""

import os
import re
import sqlite3
import requests
from datetime import datetime
from contextlib import contextmanager

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import google.generativeai as genai

# ── Config ──
genai.configure(api_key=os.environ.get("GOOGLE_API_KEY", ""))
MODEL_NAME = "gemini-2.5-flash-lite"
model = genai.GenerativeModel(MODEL_NAME)
DB_PATH = "eduguide.db"

app = FastAPI(title="EduGuide Agent")


# ── Persistence layer ──
@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                created_at TEXT
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS topics_learned (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                topic TEXT,
                explanation TEXT,
                source TEXT,
                created_at TEXT
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS quiz_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                topic TEXT,
                question TEXT,
                user_answer TEXT,
                correct INTEGER,
                created_at TEXT
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                filename TEXT,
                chunk_text TEXT,
                chunk_index INTEGER
            )
        """)


init_db()


def ensure_session(session_id: str):
    with get_db() as db:
        existing = db.execute("SELECT id FROM sessions WHERE id=?", (session_id,)).fetchone()
        if not existing:
            db.execute("INSERT INTO sessions (id, created_at) VALUES (?, ?)",
                       (session_id, datetime.utcnow().isoformat()))


def save_topic(session_id: str, topic: str, explanation: str, source: str):
    with get_db() as db:
        db.execute(
            "INSERT INTO topics_learned (session_id, topic, explanation, source, created_at) VALUES (?,?,?,?,?)",
            (session_id, topic, explanation, source, datetime.utcnow().isoformat())
        )


def save_quiz_result(session_id: str, topic: str, question: str, user_answer: str, correct: bool):
    with get_db() as db:
        db.execute(
            "INSERT INTO quiz_results (session_id, topic, question, user_answer, correct, created_at) VALUES (?,?,?,?,?,?)",
            (session_id, topic, question, user_answer, int(correct), datetime.utcnow().isoformat())
        )


def get_progress(session_id: str):
    with get_db() as db:
        topics = db.execute(
            "SELECT topic, source, created_at FROM topics_learned WHERE session_id=? ORDER BY created_at DESC",
            (session_id,)
        ).fetchall()
        quizzes = db.execute(
            "SELECT topic, correct FROM quiz_results WHERE session_id=?", (session_id,)
        ).fetchall()
        total = len(quizzes)
        correct = sum(q["correct"] for q in quizzes)
        return {
            "topics_learned": [dict(t) for t in topics],
            "quiz_accuracy": f"{correct}/{total}" if total else "No quizzes yet",
        }


# ── RAG: chunking + retrieval over uploaded documents ──
def chunk_text(text: str, chunk_size: int = 800):
    text = re.sub(r"\s+", " ", text).strip()
    return [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]


def save_document(session_id: str, filename: str, text: str):
    chunks = chunk_text(text)
    with get_db() as db:
        # Replace any previous doc for this session (keep it simple: one doc context per session)
        db.execute("DELETE FROM documents WHERE session_id=?", (session_id,))
        for i, chunk in enumerate(chunks):
            db.execute(
                "INSERT INTO documents (session_id, filename, chunk_text, chunk_index) VALUES (?,?,?,?)",
                (session_id, filename, chunk, i)
            )
    return len(chunks)


def retrieve_relevant_chunks(session_id: str, query: str, top_k: int = 3):
    """Simple keyword-overlap retrieval - no extra embedding API calls needed,
    keeps this fast and free. Good enough for short uploaded documents."""
    with get_db() as db:
        rows = db.execute(
            "SELECT chunk_text FROM documents WHERE session_id=? ORDER BY chunk_index",
            (session_id,)
        ).fetchall()
    if not rows:
        return None

    query_words = set(re.findall(r"\w+", query.lower()))
    scored = []
    for r in rows:
        chunk_words = set(re.findall(r"\w+", r["chunk_text"].lower()))
        overlap = len(query_words & chunk_words)
        scored.append((overlap, r["chunk_text"]))
    scored.sort(key=lambda x: x[0], reverse=True)
    top_chunks = [c for score, c in scored[:top_k] if score > 0]
    if not top_chunks:
        # No real keyword match found - don't guess, let caller fall back
        # to Wikipedia or report no match, instead of feeding Gemini
        # unrelated content that invites hallucination.
        return None
    return "\n\n".join(top_chunks)


# ── MCP-style tools ──
def fetch_wikipedia_content(topic: str) -> dict:
    headers = {"User-Agent": "EduGuideAgent/2.0 (educational-project)"}
    try:
        # Step 1: search for the best-matching article title (handles typos,
        # casual phrasing, partial names) instead of requiring an exact match
        search_url = "https://en.wikipedia.org/w/api.php"
        params = {
            "action": "query",
            "list": "search",
            "srsearch": topic,
            "format": "json",
            "srlimit": 1,
        }
        search_resp = requests.get(search_url, params=params, headers=headers, timeout=10)
        search_data = search_resp.json()
        results = search_data.get("query", {}).get("search", [])
        if not results:
            return {"status": "error", "summary": f"Could not find '{topic}' on Wikipedia."}

        best_title = results[0]["title"]

        # Step 2: fetch the summary for that resolved title
        summary_url = "https://en.wikipedia.org/api/rest_v1/page/summary/" + best_title.replace(" ", "_")
        response = requests.get(summary_url, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            return {
                "status": "success",
                "title": data.get("title", best_title),
                "summary": data.get("extract", "")[:1500],
            }
        return {"status": "error", "summary": f"Could not find '{topic}' on Wikipedia."}
    except Exception as e:
        return {"status": "error", "summary": str(e)}


def safety_check(query: str) -> dict:
    unsafe_keywords = ["bomb", "weapon", "kill", "suicide", "self-harm", "drug synthesis", "hack into"]
    lowered = query.lower()
    for kw in unsafe_keywords:
        if kw in lowered:
            return {"safe": False, "reason": "This topic isn't appropriate for an educational tutor."}
    return {"safe": True, "reason": ""}


# ── Agent skills ──
def skill_simplify_topic(topic: str, raw_content: str) -> str:
    prompt = f"""You are a friendly tutor explaining '{topic}' to a curious student.

Source material (this is your ONLY source of truth — do not use outside knowledge,
do not invent unrelated content):
\"\"\"
{raw_content}
\"\"\"

If the source material above does NOT actually contain information relevant to
'{topic}', respond with exactly: "I couldn't find content about that specific
topic in the provided material. Try asking about a specific item mentioned in it."

Otherwise, explain it in simple, friendly language using ONLY the source material.
Use one relatable analogy. End with one interesting fact. Keep it under 200 words."""
    response = model.generate_content(prompt)
    return response.text


def skill_generate_quiz(topic: str, explanation: str) -> str:
    prompt = f"""Based on this explanation of '{topic}':
{explanation}

Generate exactly 3 multiple-choice questions (A/B/C/D) testing understanding.
Mark the correct answer clearly at the end of each question like: [Correct: B]"""
    response = model.generate_content(prompt)
    return response.text


def skill_evaluate_answer(question: str, user_answer: str, correct_answer: str) -> str:
    prompt = f"""Question: {question}
Student's answer: {user_answer}
Correct answer: {correct_answer}

Give brief, encouraging feedback (2-3 sentences). If wrong, explain why simply."""
    response = model.generate_content(prompt)
    return response.text


# ── Orchestrator ──
class OrchestratorAgent:
    def process(self, session_id: str, user_input: str) -> dict:
        ensure_session(session_id)

        safety = safety_check(user_input)
        if not safety["safe"]:
            return {"type": "blocked", "message": f"⚠️ {safety['reason']}"}

        lowered = user_input.lower()

        if any(kw in lowered for kw in ["explain", "what is", "what are", "tell me about", "learn about", "who is", "who are"]):
            topic = self._extract_topic(user_input)

            # RAG first: check if user uploaded their own material
            rag_content = retrieve_relevant_chunks(session_id, topic)
            if rag_content:
                explanation = skill_simplify_topic(topic, rag_content)
                source = "uploaded document"
            else:
                wiki = fetch_wikipedia_content(topic)
                if wiki["status"] != "success":
                    return {"type": "error", "message": f"❌ Couldn't find info on '{topic}'."}
                explanation = skill_simplify_topic(topic, wiki["summary"])
                source = "Wikipedia"

            save_topic(session_id, topic, explanation, source)
            return {
                "type": "explanation",
                "topic": topic,
                "message": explanation,
                "source": source,
            }

        elif "quiz" in lowered:
            with get_db() as db:
                last = db.execute(
                    "SELECT topic, explanation FROM topics_learned WHERE session_id=? ORDER BY created_at DESC LIMIT 1",
                    (session_id,)
                ).fetchone()
            if not last:
                return {"type": "error", "message": "📖 Ask me to explain a topic first!"}
            quiz = skill_generate_quiz(last["topic"], last["explanation"])
            return {"type": "quiz", "topic": last["topic"], "message": quiz}

        elif "progress" in lowered:
            return {"type": "progress", "data": get_progress(session_id)}

        else:
            return {
                "type": "help",
                "message": ("👋 Try: 'Explain photosynthesis', 'quiz me', "
                             "'show my progress', or upload your own notes!")
            }

    def _extract_topic(self, query: str) -> str:
        """Strip filler/question words from both ends of the query until
        only the core topic remains. More robust than fixed prefix matching
        because it handles words in any combination (e.g. 'hi can you
        explain who are the homo sapiens')."""
        FILLERS = {
            "hi", "hey", "hello", "please", "can", "could", "would", "you",
            "explain", "what", "is", "are", "the", "a", "an", "to", "me",
            "for", "who", "tell", "about", "learn", "of", "in", "terms",
            "simple", "do", "ya", "give", "i", "want", "know", "and", "so"
        }

        # Strip punctuation, lowercase a working copy for comparison only
        cleaned = query.strip().rstrip("?!.").strip()
        words = cleaned.split()

        # Strip filler words from the FRONT
        start = 0
        while start < len(words) and words[start].lower().strip(",") in FILLERS:
            start += 1

        # Strip filler words from the BACK
        end = len(words)
        while end > start and words[end - 1].lower().strip(",") in FILLERS:
            end -= 1

        topic_words = words[start:end]
        topic = " ".join(topic_words).strip()

        # Safety net: if we stripped everything (e.g. query was all filler),
        # fall back to the original cleaned query
        if not topic:
            topic = cleaned

        return topic


agent = OrchestratorAgent()


# ── API routes ──
@app.post("/chat")
async def chat(session_id: str = Form(...), message: str = Form(...)):
    try:
        result = agent.process(session_id, message)
        return JSONResponse(result)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse(
            {"type": "error", "message": f"⚠️ Server error: {str(e)}"},
            status_code=500
        )


@app.post("/upload")
async def upload(session_id: str = Form(...), file: UploadFile = File(...)):
    try:
        content = await file.read()
        if file.filename.endswith(".pdf"):
            from pypdf import PdfReader
            import io
            reader = PdfReader(io.BytesIO(content))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        else:
            text = content.decode("utf-8", errors="ignore")

        if not text.strip():
            return JSONResponse(
                {"status": "error", "message": "No extractable text found in this file."},
                status_code=400
            )

        ensure_session(session_id)
        n_chunks = save_document(session_id, file.filename, text)
        return JSONResponse({"status": "ok", "chunks_stored": n_chunks, "filename": file.filename})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse(
            {"status": "error", "message": f"Upload failed: {str(e)}"},
            status_code=500
        )


@app.get("/debug/documents/{session_id}")
async def debug_documents(session_id: str):
    with get_db() as db:
        rows = db.execute(
            "SELECT filename, chunk_index, chunk_text FROM documents WHERE session_id=? ORDER BY chunk_index",
            (session_id,)
        ).fetchall()
    return JSONResponse([dict(r) for r in rows])


@app.get("/progress/{session_id}")
async def progress(session_id: str):
    return JSONResponse(get_progress(session_id))


@app.get("/", response_class=HTMLResponse)
async def home():
    with open("static/index.html", encoding="utf-8") as f:
        return f.read()