# Local model and prompts

The app can use a **local LLM** (e.g. Ollama) to generate:

1. **Resume summary** — 2–4 sentences on strengths and role fit (stored on the resume after upload).
2. **Gap advice** — Short paragraph after “Analyze Skills Gap” on what to learn first and how to frame strengths.
3. **Match advice** — 2–3 sentences when viewing “Match” for a job: fit and what to highlight or improve.

If no local LLM is configured, these features are skipped; the app works as before.

---

## Setup (Ollama)

1. Install [Ollama](https://ollama.com) and start it (e.g. `ollama serve` or run the app).
2. Pull a model: `ollama run llama3.2` (or `llama3.1`, `mistral`, etc.).
3. In the backend `.env`:

   ```env
   LLM_BASE_URL=http://localhost:11434
   LLM_MODEL=llama3.2
   ```

4. Restart the backend. Upload a resume or run gap analysis; you should see AI summary/advice when the LLM is available.

---

## Prompts

Default prompts live in **`backend/data/prompts.json`**. You can edit that file or point to your own with `LLM_PROMPTS_PATH` in `.env`.

| Key | Used for | Placeholders |
|-----|----------|--------------|
| `resume_summary` | Summary after upload | `{resume_text}` |
| `gap_advice` | Advice after Analyze Skills Gap | `{matched_skills}`, `{missing_skills}`, `{high_demand_missing}` |
| `match_advice` | Advice in job Match modal | `{match_score}`, `{semantic}`, `{skill_overlap}`, `{keyword}`, `{matched_skills}`, `{missing_skills}` |

Example override: set `LLM_PROMPTS_PATH=/path/to/my_prompts.json` with a JSON object that has the same keys and your template strings.

---

## API

- **Resume upload:** If LLM is enabled, the created resume may include `ai_summary` in the response and in `GET /resumes/` and `GET /resumes/{id}`.
- **POST /resumes/{id}/generate-summary:** Regenerate AI summary for a resume (requires LLM configured).
- **POST /analysis/resume-gap:** Response includes `ai_advice` when LLM is enabled.
- **GET /analysis/match:** Response includes `ai_advice` when LLM is enabled.

---

## Database

Resumes have an optional **`ai_summary`** column. If you add this after existing tables exist, run:

```sql
ALTER TABLE resumes ADD COLUMN IF NOT EXISTS ai_summary TEXT;
```

(On a fresh DB, tables are created with the column automatically.)
