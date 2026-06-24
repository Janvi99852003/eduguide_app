# 🎓 EduGuide Agent v2 — Deployable Multi-Agent Tutor

A free, multi-agent AI tutoring system that explains topics, generates quizzes, and tracks progress — built for the Google × Kaggle "AI Agents Intensive" Capstone, then upgraded from a notebook prototype into a real, deployed web app.

🔗 **Live Demo:** [eduguide-app.onrender.com](https://eduguide-app.onrender.com)
📓 **Original Capstone Notebook:** [Kaggle](#) *(add your notebook link)*
🎥 **Video Walkthrough:** [YouTube](https://youtu.be/lfc-avDWf7U)

> Free tier note: the live demo sleeps after inactivity — the first request may take 30–50s to wake up.

---

## What's New vs. the Notebook Prototype

| Feature | Notebook v1 (Kaggle) | This Version (v2) |
|---|---|---|
| Interface | Kaggle notebook only | Live web app (FastAPI + chat UI) |
| Memory | Resets every restart | Persisted in SQLite (topics, quiz scores) |
| Content source | Wikipedia only | RAG over user-uploaded PDFs/notes, falls back to Wikipedia |
| Progress tracking | None | `/progress` endpoint + in-chat "show my progress" |
| Reliability | — | Error surfacing end-to-end (no silent failures) |

---

## Architecture

```
OrchestratorAgent
 ├── safety_check()                    — blocks unsafe queries before anything runs
 ├── ExplainerAgent path
 │     ├── retrieve_relevant_chunks()  — RAG over uploaded docs (keyword retrieval)
 │     ├── fetch_wikipedia_content()   — Wikipedia search + fallback if no doc uploaded
 │     └── skill_simplify_topic()      — Gemini rewrites content simply, grounded in source
 ├── QuizAgent path
 │     ├── skill_generate_quiz()
 │     └── skill_evaluate_answer()
 └── SQLite persistence — sessions, topics_learned, quiz_results, documents
```

**Gen AI concepts demonstrated:** multi-agent orchestration, RAG (retrieval-augmented generation), reusable agent skills, safety guardrails.

---

## Try It

```
explain photosynthesis
explain Find the Duplicate Number          # after uploading your own notes
quiz me
show my progress
```

Upload a `.txt` or `.pdf` to have EduGuide answer from *your* material instead of Wikipedia.

---

## Engineering Notes — Bugs Found & Fixed

This wasn't a one-shot build — getting it production-ready surfaced real issues:

- **Wikipedia 403 errors** → Wikipedia now requires a `User-Agent` header on all requests; added one.
- **Model deprecation** → `gemini-1.5-flash` was retired mid-build; migrated to a current model.
- **Free-tier quota (`limit: 0`)** → resolved via fresh API key provisioning across projects/accounts.
- **Query parsing failures** → casual phrasing ("hi can you explain who are X") broke prefix-based extraction; replaced with a generic filler-word-stripping approach, tested against 8+ phrasings.
- **RAG hallucination** → traced an apparent model hallucination back to a missing `pypdf` dependency causing silent upload failures — no content was ever stored, so the model had nothing to ground on and invented unrelated answers. Fixed by adding error handling end-to-end (backend + frontend) so failures are never silent again, plus a stricter retrieval threshold and explicit grounding instructions in the generation prompt.

---

## Run Locally

```bash
git clone https://github.com/Janvi99852003/eduguide_app.git
cd eduguide_app
pip install -r requirements.txt
export GOOGLE_API_KEY="your-key-here"      # PowerShell: $env:GOOGLE_API_KEY="your-key"
uvicorn main:app --reload
```

Visit `http://localhost:8000`

---

## Deploy Free (Render.com)

1. Push this repo to GitHub
2. [render.com](https://render.com) → **New → Web Service** → connect your repo
3. **Build command:** `pip install -r requirements.txt`
4. **Start command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
5. **Environment variable:** `GOOGLE_API_KEY` = your Gemini key
6. Deploy — Render gives you a public URL

---

## Known Limitations

- Retrieval uses simple keyword overlap, not semantic embeddings — works well for short uploaded documents, less precise for large/dense ones (a vector DB like Qdrant or Chroma would be the natural next step)
- Wikipedia content depends on close title matches via its search API
- Free-tier Gemini API quota (~20 requests/day per key) limits heavy testing

## Possible Next Steps

- Swap keyword retrieval for embedding-based semantic search
- Multi-user auth + per-user document libraries
- WhatsApp/Telegram bot front-end for broader, low-bandwidth access

---

## Cost

**$0** — Gemini free tier, Wikipedia API, SQLite (local file), Render free tier.

## Author

Janvi Jaiswal
