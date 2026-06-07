# Community Pattern Radar

Community Pattern Radar turns messy community feedback into a **living issue tree**.

Instead of showing only a flat list of clusters, it ranks recurring issues by impact, connects related issues into a tree, and lets teams work on issues through shared mains, private workspaces, branches, and status propagation.

The app is designed for communities, SaaS teams, startup founders, moderators, and product teams who need to understand recurring feedback from Discord, Slack, support tickets, app reviews, CSV exports, or pasted notes.

## What it does

Community Pattern Radar helps teams:

* Import messy feedback from pasted text or CSV files
* Clean and normalize feedback text
* Generate embeddings locally by default
* Cluster recurring issues
* Interpret each cluster using deterministic rules or a local LLM
* Build an impact-based issue tree
* Create shared main spaces with unique join codes
* Let users create private workspace trees inside a main
* Copy main trees into a workspace as editable private trees
* Create branches and saved versions
* Track status and progress notes per node
* Propagate status changes across related nodes
* Show propagated nodes with dashed styling
* Remodel the tree after issues are completed
* Search feedback semantically
* Export markdown reports and action backlog CSVs

## MVP scope

Inputs are intentionally simple:

* Paste text from Discord, Slack, support notes, app reviews, or founder feedback dumps
* Upload a CSV export with a text-like column

The core workflow is:

1. Create or join a main space
2. Create a main tree or private workspace tree
3. Import feedback
4. Clean and normalize the text
5. Generate embeddings
6. Cluster recurring issues
7. Interpret each cluster
8. Build an impact-based issue tree
9. Update node statuses and progress notes
10. Push workspace changes back to the main
11. Propagate related status changes across affected trees
12. Export reports or action backlogs

## Key features

### Joinable main spaces

A **main space** is a shared project/community area.

Each main has a unique join code, for example:

```text
MAIN-8K29Q2AB
```

Users can:

* Create a new main
* Join an existing main with a code
* Share a main using a URL such as `/main/MAIN-8K29Q2AB`
* View public main trees when logged out if they have the main code or URL
* Work privately inside their own workspace after logging in

Status propagation is scoped to the same main space, so changes in one main do not affect unrelated mains.

```text
Main A changes → Main A public trees + Main A workspace trees only
Main B is not affected
```

### Authentication and workspaces

Users can create either:

* Normal workspace accounts
* Admin accounts

Logged-out users can:

* Open a shared main by code or URL
* View public main trees read-only

Logged-in normal users can:

* Create private workspace trees
* Join mains
* Copy main trees into their workspace
* Create branches
* Import feedback
* Update node statuses
* Push workspace versions to main
* Delete their own workspace trees and branches

Admin users can:

* Create main trees
* Delete public main trees
* Delete public main branches
* Delete mains they manage

### Main trees and workspace trees

A main tree represents the shared/public version of issues for a main space.

A workspace tree is private to a user and linked to a main space. Users can work on their own copy before pushing changes back.

Typical flow:

```text
Open main
→ Use main tree in workspace
→ Edit private workspace copy
→ Change node statuses
→ Push to main
→ Related nodes update across that main space
```

### Editable main-tree copies

When a user clicks **Use main tree in workspace**, the app creates a real editable copy of the main tree.

The copy includes its own:

* UploadBatch rows
* CommunityPost rows
* IssueCluster rows
* Parent-child relationships
* Status metadata

This prevents workspace copies from accidentally editing public main nodes directly.

### Status propagation

When a workspace version is pushed to main, changed node statuses can propagate to related nodes in:

* Public main trees
* Private workspace trees
* Saved or draft branches
* Merged/unified trees
* Trees created from overlapping or related feedback

The system looks for affected nodes using:

* Same theme/category
* Semantic similarity
* Embedding centroid similarity
* Shared evidence/post overlap
* Subset evidence matching
* Batch/version lineage
* Parent-child relationship bonus
* Local LLM relationship checks for borderline related nodes

### Subset matching

The app supports cases where the main tree contains all posts, but a private tree contains only some of those posts.

Example:

```text
Main tree:
20 posts about confusing billing and usage limits

Private tree:
5 posts about extra seat charges
```

If the private node is marked completed and pushed, the larger main node may become:

```text
partially_resolved
```

instead of fully completed, because only part of the larger issue has been addressed.

### Different-but-related matching

The app can also connect nodes that do not share the same posts but are semantically related.

Example:

```text
Private node:
Users do not understand extra seat charges.

Main node:
Billing limits and usage-based pricing are confusing.
```

If deterministic scoring is borderline, the local LLM can classify the relationship as:

* equivalent
* source subset of target
* target subset of source
* related
* unrelated

The LLM call is configured to be deterministic.

### Status weakening

Status propagation is not a blind copy.

If two nodes are almost equal, the same status can be copied.

If they are only partly related, the target receives a weaker status.

Example:

```text
Private node: completed
Strong equivalent match → main node: completed
Subset match → main node: partially_resolved
Related match → main node: in_progress or needs_review
Weak match → no update
```

### Manual vs propagated statuses

Manual user decisions are protected.

A propagated update can update:

* untouched nodes
* already propagated nodes if the new confidence is stronger

It should not silently overwrite a node that a user already changed manually.

Visual rules:

```text
Solid node border = manual/direct status
Dashed node border = propagated status
Solid edge = direct/manual relationship
Dashed edge = connected to propagated status
```

If a user manually changes a propagated node, it becomes a manual node and the dashed style is removed.

## Supported statuses

```text
untouched
needs_review
confirmed
planned
in_progress
partially_resolved
completed
blocked
wont_fix
not_affected
legacy
```

Older/simple workflows can still use:

```text
untouched
in_progress
completed
legacy
```

## Tech stack

* Frontend: React + Vite
* Backend: Django + Django REST Framework
* Data processing: Python, Pandas, scikit-learn
* Embeddings: local hashing embeddings by default, optional Cohere
* Cluster interpretation: deterministic rules fallback or local Ollama model
* Local LLM: Ollama
* Storage: SQLite for local development, PostgreSQL/Supabase-ready
* Auth: custom token sessions using Django users
* Tree rendering: responsive React/SVG tree layout

## Project structure

```text
community-pattern-radar-login-workspace/
├── backend/
│   ├── api/
│   │   ├── auth_utils.py
│   │   ├── interpretation.py
│   │   ├── models.py
│   │   ├── serializers.py
│   │   ├── services.py
│   │   ├── urls.py
│   │   └── views.py
│   ├── radar/
│   │   ├── settings.py
│   │   └── urls.py
│   ├── manage.py
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── main.jsx
│   │   └── styles.css
│   ├── package.json
│   └── index.html
├── sample_data/
├── README.md
└── .gitignore
```

## Backend setup

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
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

If your backend is running somewhere else, set the frontend API URL:

```bash
VITE_API_BASE_URL=http://127.0.0.1:8000/api
```

## Environment variables

Create `backend/.env` if your settings load environment variables.

Example:

```bash
DEBUG=True
SECRET_KEY=replace-this-for-production
DATABASE_URL=sqlite:///db.sqlite3

INTERPRETER_MODE=rules
EMBEDDING_BACKEND=local

OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.1:8b

COHERE_API_KEY=
```

Do not commit `.env` to GitHub.

## Optional local LLM interpretation with Ollama

By default, the app can use fast deterministic `rules` mode.

To use a local model with Ollama, set:

```bash
INTERPRETER_MODE=local_llm
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.1:8b
```

Then run:

```bash
ollama pull llama3.1:8b
ollama serve
```

If Ollama is unavailable, the app falls back to rules mode.

## Deterministic local LLM behaviour

The local LLM is configured to be as deterministic as possible.

The app uses:

```text
temperature: 0
top_k: 1
top_p: 1
fixed seed
single thread
stable JSON prompts
```

This helps the same input produce the same output as consistently as possible.

The local LLM may be used for:

* Cluster interpretation
* Relationship checking for borderline related nodes
* Determining whether two nodes are equivalent, subset-related, related, or unrelated

## CSV format

The app auto-detects common text columns, including:

```text
text
body
message
comment
content
post
description
review
ticket_text
feedback
summary
question
answer
```

Optional columns:

```text
created_at
user_id
channel
post_url
report_count
upvotes
moderation_status
```

## Key API endpoints

### Auth

```http
POST /api/auth/register/
POST /api/auth/login/
GET  /api/auth/me/
POST /api/auth/logout/
```

Register payload:

```json
{
  "username": "josh",
  "email": "josh@example.com",
  "password": "password123",
  "workspace_name": "Josh workspace",
  "account_type": "normal"
}
```

Admin account:

```json
{
  "username": "admin",
  "password": "password123",
  "workspace_name": "Admin workspace",
  "account_type": "admin"
}
```

### Main spaces

```http
GET    /api/main-spaces/
POST   /api/main-spaces/create/
GET    /api/main-spaces/:join_code/
POST   /api/main-spaces/:join_code/join/
DELETE /api/main-spaces/:join_code/delete/
GET    /api/main-spaces/:join_code/trees/
```

Create main:

```json
{
  "name": "Focus Feedback Main",
  "description": "Shared main issue space."
}
```

### Trees and versions

```http
GET    /api/trees/?main_space=:join_code
POST   /api/trees/create/
DELETE /api/trees/:tree_id/delete/

GET    /api/trees/:tree_id/versions/
GET    /api/tree-versions/:version_id/
POST   /api/tree-versions/:version_id/branch/
POST   /api/tree-versions/:version_id/save/
POST   /api/tree-versions/:version_id/push-main/
DELETE /api/tree-versions/:version_id/delete/
```

Create workspace tree:

```json
{
  "name": "June Community Feedback Tree",
  "description": "Named community issue tree",
  "created_by_name": "Josh",
  "version_name": "Initial version",
  "main_space": "MAIN-8K29Q2AB",
  "as_main_tree": false,
  "is_public": false
}
```

Create public main tree as a main owner/admin:

```json
{
  "name": "Public Main Feedback Tree",
  "description": "Main shared tree",
  "created_by_name": "Josh",
  "version_name": "Initial version",
  "main_space": "MAIN-8K29Q2AB",
  "as_main_tree": true,
  "is_public": true
}
```

Branch or copy main tree into workspace:

```json
{
  "branch_name": "working-branch",
  "created_by_name": "Josh",
  "notes": "Created from frontend workspace."
}
```

### Import

```http
POST /api/import/paste/
POST /api/upload/
POST /api/import/sample/
```

Paste import:

```json
{
  "text": "Users are confused about billing limits...",
  "tree_version_id": 1,
  "merge_with_existing": true
}
```

CSV upload uses form data:

```text
file=<csv file>
tree_version_id=1
merge_with_existing=true
```

### Dashboard and tree

```http
GET   /api/batches/:batch_id/dashboard/
GET   /api/batches/:batch_id/tree/
PATCH /api/batches/:batch_id/tree/nodes/:cluster_id/status/
POST  /api/batches/:batch_id/tree/remodel/
```

Update node status:

```json
{
  "status": "in_progress",
  "progress_note": "Product is rewriting the pricing FAQ this week."
}
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

## Pattern Tree logic

The tree is intentionally explainable:

* The root is the highest-impact visible issue
* Impact score comes from cluster size, reports, moderation signals, and related metadata
* Child nodes are lower-impact clusters that are semantically similar to a higher-impact cluster
* Completed nodes can be hidden and the tree remodelled
* Completed nodes can also be kept as muted legacy nodes for historical context
* Related issues are labelled cautiously as `related_to`, `contributes_to`, or `likely_upstream`

The app avoids overclaiming perfect causality. Relationships are meant to guide investigation and prioritisation.

## Status propagation logic

When a version is pushed to main, the app searches for changed source nodes.

A node counts as changed if:

```text
status is not untouched
or progress_note exists
or completed_at exists
```

Then the app compares changed nodes against candidate nodes in the same main space.

Matching signals include:

* Exact theme/category match
* Semantic signature similarity
* Embedding centroid similarity
* Exact evidence overlap
* Subset evidence overlap
* Token overlap
* Batch lineage
* Version ancestry
* Parent/child connection
* Optional local LLM relationship classification

Propagation result depends on match strength:

```text
Very high confidence → same status
Strong related match → one-step weaker status
Medium related match → two-step weaker status
Weak related match → needs_review
Low confidence → no update
```

Manual user decisions are not silently overwritten.

## Frontend behaviour

The frontend includes:

* Auth panel
* Main-space panel
* Open-main-by-code flow for logged-out users
* Workspace tree controls
* Import panel for pasted text and CSVs
* Responsive tree renderer
* Focus mode with scrollbars
* Status-coloured nodes
* Dashed propagated nodes and edges
* Node detail panel with evidence and status controls
* Version report
* Semantic search

## Git setup notes

Recommended `.gitignore` entries:

```gitignore
# Python / Django
__pycache__/
*.py[cod]
*.sqlite3
db.sqlite3
.env
.env.*
*.log

# Virtual environments
.venv/
venv/
env/

# Django static/media
staticfiles/
media/

# Node / React
node_modules/
frontend/node_modules/
dist/
frontend/dist/
.vite/

# OS/editor
.DS_Store
Thumbs.db
.vscode/
.idea/

# Windows metadata
*:Zone.Identifier

# Archives
*.zip
*.tar
*.gz
```

Check that sensitive/local files are not tracked:

```bash
git ls-files | grep -E "(\.env|db\.sqlite3|node_modules|\.venv|Zone.Identifier)"
```

Ideally this returns nothing.

## Portfolio positioning

> Community Pattern Radar turns pasted or CSV community feedback into a living issue tree, helping teams see what to fix first, how issues relate, and what progress has been made.

It demonstrates:

* Full-stack React and Django development
* Authentication and workspace logic
* Versioned workflows
* Data processing with Pandas and scikit-learn
* Embeddings and semantic similarity
* Local LLM integration
* Deterministic AI-assisted analysis
* Explainable issue relationships
* Status propagation across related entities
* Practical product thinking for community and SaaS feedback workflows

## Future improvements

Potential next steps:

* Invite users to a main by email
* Role management inside each main
* Push review/approval workflow
* Comments on nodes
* Activity log for status changes
* Better conflict handling when multiple users change related nodes
* Background jobs for large CSV imports
* PostgreSQL production deployment
* More advanced graph layout
* Export/import whole main spaces
* Richer LLM explanations for relationship reasoning
