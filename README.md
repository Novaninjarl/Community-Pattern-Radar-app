# Community Pattern Radar

Community Pattern Radar turns messy community feedback into a **living issue tree**.

Instead of showing only a flat list of clusters, it ranks recurring issues by impact, connects related issues into a tree, and lets a team mark each issue as **untouched**, **in progress**, **completed**, or **legacy**. When completed issues are removed, the tree can be remodelled around the next highest-impact unresolved issue.

## MVP scope

Inputs are intentionally simple:

- Paste text from Discord, Slack, support notes, app reviews, or founder feedback dumps
- Upload a CSV export with a text-like column

The standout feature is the Pattern Tree workflow:

1. Import feedback
2. Clean and normalize the text
3. Generate embeddings
4. Cluster recurring issues
5. Interpret each cluster with rules or a local LLM
6. Build an impact-based tree
7. Track status and progress notes per node
8. Remodel the tree after issues are completed
9. Export weekly reports and action backlog CSVs

## Tech stack

- Frontend: React + Vite
- Backend: Django REST Framework
- Data processing: Python, Pandas, scikit-learn
- Embeddings: local hashing embeddings by default, optional Cohere
- Cluster interpretation: rules fallback or local Ollama model
- Storage: SQLite for local development, PostgreSQL/Supabase-ready

## Backend setup

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp ../.env.example .env
python manage.py makemigrations api
python manage.py migrate
python manage.py runserver
```

The API runs at:

```text
http://localhost:8000/api
```

## Frontend setup

```bash
cd frontend
npm install
npm run dev
```

The UI runs at:

```text
http://localhost:5173
```

## Optional local LLM interpretation with Ollama

By default, the app uses fast deterministic `rules` mode. To make cluster labels and actions more generic, run a local model with Ollama.

In `backend/.env`:

```bash
INTERPRETER_MODE=local_llm
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.1:8b
```

Then:

```bash
ollama pull llama3.1:8b
ollama serve
```

If Ollama is unavailable, the app automatically falls back to rules mode.

## Key API endpoints

### Import

```http
POST /api/import/paste/
POST /api/upload/
```

### Dashboard and tree

```http
GET /api/batches/:batch_id/dashboard/
GET /api/batches/:batch_id/tree/
PATCH /api/batches/:batch_id/tree/nodes/:cluster_id/status/
POST /api/batches/:batch_id/tree/remodel/
```

Update node status:

```json
{
  "status": "in_progress",
  "progress_note": "Product is rewriting the pricing FAQ this week."
}
```

Supported statuses:

```text
untouched
in_progress
completed
legacy
```

Remodel tree:

```json
{
  "remove_completed": true,
  "keep_legacy": false
}
```

Or keep completed issues visible as legacy:

```json
{
  "remove_completed": false,
  "keep_legacy": true
}
```

### Search and export

```http
GET /api/batches/:batch_id/search/?q=pricing%20complaints
GET /api/batches/:batch_id/export/
GET /api/batches/:batch_id/export/markdown/
GET /api/batches/:batch_id/export/actions/
```

## CSV format

The app auto-detects common text columns, including:

```text
text, body, message, comment, content, post, description, review, ticket_text, feedback
```

Optional columns:

```text
created_at, user_id, channel, post_url, report_count, upvotes, moderation_status
```

## Pattern Tree logic

The tree is intentionally explainable:

- The root is the highest-impact visible issue
- Impact score comes from cluster size, reports, moderation signals, and related metadata
- Child nodes are lower-impact clusters that are semantically similar to a higher-impact cluster
- Completed nodes can be hidden and the tree remodelled
- Completed nodes can also be kept as muted legacy nodes for historical context

Relationship labels are cautious by design. The app says an issue is `related_to`, `contributes_to`, or `likely_upstream`; it does not overclaim perfect causality.

## Portfolio positioning

> Community Pattern Radar turns pasted or CSV community feedback into a living issue tree, helping early-stage teams see what to fix first, how issues relate, and what progress has been made.
