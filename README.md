# EduGuide Agent v2 — Deployable Multi-Agent Tutor

A free, multi-agent AI tutoring system — upgraded from a Kaggle notebook
prototype into a real, deployable web app.

## What's new vs. the notebook version

| Feature | Notebook v1 | This version (v2) |
|---|---|---|
| Interface | Kaggle notebook only | Live web app (FastAPI + chat UI) |
| Memory | Resets every restart | Persisted in SQLite (topics, quiz scores) |
| Content source | Wikipedia only | RAG over user-uploaded PDFs/notes, falls back to Wikipedia |
| Progress tracking | None | `/progress` endpoint + in-chat "show my progress" |

## Architecture

```
OrchestratorAgent
 ├── safety_check()              — blocks unsafe queries before anything runs
 ├── ExplainerAgent path
 │     ├── retrieve_relevant_chunks()  — RAG over uploaded docs (keyword retrieval)
 │     ├── fetch_wikipedia_content()   — fallback if no doc uploaded
 │     └── skill_simplify_topic()      — Gemini rewrites content simply
 ├── QuizAgent path
 │     ├── skill_generate_quiz()
 │     └── skill_evaluate_answer()
 └── SQLite persistence — sessions, topics_learned, quiz_results, documents
```

## Run locally

```bash
pip install -r requirements.txt
export GOOGLE_API_KEY="your-key-here"
uvicorn main:app --reload
```

Visit `http://localhost:8000`

## Deploy free (Render.com)

1. Push this folder to a GitHub repo
2. Go to render.com → New → Web Service → connect your repo
3. Build command: `pip install -r requirements.txt`
4. Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
5. Add environment variable: `GOOGLE_API_KEY` = your Gemini key
6. Deploy — Render gives you a public URL

## Cost

$0 — Gemini free tier, Wikipedia API, SQLite (local file), Render free tier.
🔗 **Live Demo:** https://eduguide-app.onrender.com

## Author

Janvi Jaiswal
