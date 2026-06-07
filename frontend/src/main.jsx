import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  AlertTriangle,
  CheckCircle2,
  Clipboard,
  FileUp,
  GitBranch,
  LogIn,
  LogOut,
  Plus,
  Trash2,
  Radar,
  Search,
  Sparkles,
} from 'lucide-react';
import './styles.css';

const API_BASE =
  import.meta.env.VITE_API_BASE_URL ||
  import.meta.env.VITE_API_BASE ||
  'http://127.0.0.1:8000/api';

const AUTH_TOKEN_KEY = 'community-pattern-radar-token';
const SELECTED_MAIN_KEY = 'community-pattern-radar-main-code';

const STATUS_META = {
  untouched: { label: 'Untouched', tone: 'status-untouched', pillTone: 'neutral' },
  needs_review: { label: 'Needs review', tone: 'status-needs-review', pillTone: 'amber' },
  confirmed: { label: 'Confirmed', tone: 'status-confirmed', pillTone: 'purple' },
  planned: { label: 'Planned', tone: 'status-planned', pillTone: 'blue' },
  in_progress: { label: 'In progress', tone: 'status-in-progress', pillTone: 'blue' },
  partially_resolved: { label: 'Partially resolved', tone: 'status-partially-resolved', pillTone: 'teal' },
  completed: { label: 'Resolved', tone: 'status-completed', pillTone: 'green' },
  blocked: { label: 'Blocked', tone: 'status-blocked', pillTone: 'red' },
  wont_fix: { label: "Won't fix", tone: 'status-wont-fix', pillTone: 'neutral' },
  not_affected: { label: 'Not affected', tone: 'status-not-affected', pillTone: 'neutral' },
  legacy: { label: 'Legacy', tone: 'status-legacy', pillTone: 'neutral' },
};

const STATUS_BUTTONS = [
  ['untouched', 'Untouched', 'secondary'],
  ['needs_review', 'Needs review', 'warning-btn'],
  ['confirmed', 'Confirmed', 'secondary'],
  ['planned', 'Planned', 'secondary'],
  ['in_progress', 'In progress', 'warning-btn'],
  ['partially_resolved', 'Partially resolved', 'secondary'],
  ['completed', 'Resolved', 'success-btn'],
  ['blocked', 'Blocked', 'danger-btn'],
  ['wont_fix', "Won't fix", 'secondary'],
  ['not_affected', 'Not affected', 'secondary'],
  ['legacy', 'Legacy', 'secondary'],
];

function isPropagatedStatus(node) {
  return node?.status_source === 'propagated';
}

async function api(path, options = {}) {
  const token = localStorage.getItem(AUTH_TOKEN_KEY);

  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      ...(options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers || {}),
    },
    ...options,
  });

  let data = null;

  try {
    data = await response.json();
  } catch {
    data = null;
  }

  if (!response.ok) {
    throw new Error(data?.error || data?.detail || `Request failed: ${response.status}`);
  }

  return data;
}

function Pill({ children, tone = 'neutral' }) {
  return <span className={`pill ${tone}`}>{children}</span>;
}


function AuthPanel({ user, onAuthChanged, setError }) {
  const [mode, setMode] = useState('login');
  const [username, setUsername] = useState('josh');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('password123');
  const [workspaceName, setWorkspaceName] = useState('Josh workspace');
  const [accountType, setAccountType] = useState('normal');
  const [loading, setLoading] = useState(false);

  async function submit(event) {
    event.preventDefault();
    setLoading(true);
    setError('');

    try {
      const path = mode === 'register' ? '/auth/register/' : '/auth/login/';
      const payload = mode === 'register'
        ? { username, email, password, workspace_name: workspaceName, account_type: accountType }
        : { username, password };

      const data = await api(path, {
        method: 'POST',
        body: JSON.stringify(payload),
      });

      localStorage.setItem(AUTH_TOKEN_KEY, data.token);
      await onAuthChanged(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function logout() {
    setLoading(true);
    setError('');

    try {
      await api('/auth/logout/', { method: 'POST', body: JSON.stringify({}) });
    } catch {
      // Still clear local state if the token has already expired server-side.
    } finally {
      localStorage.removeItem(AUTH_TOKEN_KEY);
      await onAuthChanged(null);
      setLoading(false);
    }
  }

  if (user) {
    return (
      <section className="panel auth-panel">
        <div className="section-title">
          <LogIn size={18} />
          <h2>{user.workspace?.name || `${user.username} workspace`}</h2>
        </div>

        <p className="hint">
          Logged in as <strong>{user.username}</strong> <Pill tone={user.is_admin ? 'green' : 'neutral'}>{user.is_admin ? 'Admin' : 'Normal'}</Pill>. Admin accounts can delete public main trees/branches. Normal accounts can delete their own workspace trees/branches.
        </p>

        <button type="button" className="secondary" onClick={logout} disabled={loading}>
          <LogOut size={16} /> Log out
        </button>
      </section>
    );
  }

  return (
    <section className="panel auth-panel">
      <div className="section-title">
        <LogIn size={18} />
        <h2>Public view / workspace login</h2>
      </div>

      <p className="hint">
        Without logging in you can view a main if you have its code or URL. Log in to create/join mains, work in your workspace, and push changes back to that main.
      </p>

      <div className="import-tabs two-tabs">
        <button
          type="button"
          className={`import-tab ${mode === 'login' ? 'active' : ''}`}
          onClick={() => setMode('login')}
        >
          Log in
        </button>
        <button
          type="button"
          className={`import-tab ${mode === 'register' ? 'active' : ''}`}
          onClick={() => setMode('register')}
        >
          Create workspace
        </button>
      </div>

      <form onSubmit={submit} className="workspace-form auth-form">
        <input value={username} onChange={e => setUsername(e.target.value)} placeholder="Username" />
        {mode === 'register' && (
          <input value={email} onChange={e => setEmail(e.target.value)} placeholder="Email optional" />
        )}
        <input
          value={password}
          onChange={e => setPassword(e.target.value)}
          placeholder="Password"
          type="password"
        />
        {mode === 'register' && (
          <input
            value={workspaceName}
            onChange={e => setWorkspaceName(e.target.value)}
            placeholder="Workspace name"
          />
        )}
        {mode === 'register' && (
          <label className="inline-field">
            Account type
            <select value={accountType} onChange={e => setAccountType(e.target.value)}>
              <option value="normal">Normal workspace account</option>
              <option value="admin">Admin account</option>
            </select>
          </label>
        )}
        <button disabled={loading || !username.trim() || !password.trim()}>
          {loading ? 'Working...' : mode === 'register' ? 'Create workspace' : 'Log in'}
        </button>
      </form>
    </section>
  );
}


function MainSpacePanel({ user, mainSpaces, selectedMainCode, onSelectMain, onCreateMain, onJoinMain, onOpenMain, onDeleteMain, loading }) {
  const [mainName, setMainName] = useState('Focus Feedback Main');
  const [joinCode, setJoinCode] = useState('');

  const selectedMain = mainSpaces.find(space => space.join_code === selectedMainCode);

  async function createMain(event) {
    event.preventDefault();
    await onCreateMain({ name: mainName, description: 'Shared main issue space.' });
  }

  async function joinMain(event) {
    event.preventDefault();
    await onJoinMain(joinCode);
  }

  async function openMain(event) {
    event.preventDefault();
    await onOpenMain(joinCode);
  }

  function copyLink() {
    if (!selectedMainCode) return;
    const url = `${window.location.origin}/main/${selectedMainCode}`;
    navigator.clipboard?.writeText(url);
  }

  return (
    <section className="panel main-space-panel">
      <div className="section-title">
        <GitBranch size={18} />
        <h2>Main space</h2>
      </div>

      <p className="hint">
        A main is now a separate shared project/community space. Only people with its code or URL can view or join that main.
      </p>

      <div className="main-space-actions">
        {user && (
          <form onSubmit={createMain} className="workspace-form">
            <input
              value={mainName}
              onChange={e => setMainName(e.target.value)}
              placeholder="New main name"
            />
            <button type="submit" disabled={loading || !mainName.trim()}>
              <Plus size={16} /> Create main
            </button>
          </form>
        )}

        <form onSubmit={user ? joinMain : openMain} className="workspace-form">
          <input
            value={joinCode}
            onChange={e => setJoinCode(e.target.value.toUpperCase())}
            placeholder="Main code, e.g. MAIN-8K29Q"
          />
          <button type="submit" className="secondary" disabled={loading || !joinCode.trim()}>
            {user ? 'Join main' : 'Open main read-only'}
          </button>
        </form>
      </div>

      <div className="selector-grid">
        <label>
          Current main
          <select value={selectedMainCode || ''} onChange={e => onSelectMain(e.target.value)}>
            <option value="">{user ? 'Choose a main' : 'Open a main by code or URL'}</option>
            {mainSpaces.map(space => (
              <option key={space.join_code} value={space.join_code}>
                {space.name} — {space.join_code}
              </option>
            ))}
          </select>
        </label>
      </div>

      {selectedMain && (
        <div className="metrics-row">
          <span>Main: {selectedMain.name}</span>
          <span>Code: {selectedMain.join_code}</span>
          <span>Role: {selectedMain.current_user_role || 'viewer'}</span>
          <span>{selectedMain.member_count || 0} members</span>
        </div>
      )}

      {selectedMainCode && (
        <div className="export-row">
          <button type="button" className="secondary" onClick={copyLink}>
            <Clipboard size={16} /> Copy main link
          </button>
          {selectedMain?.can_admin && (
            <button type="button" className="secondary danger-btn" onClick={onDeleteMain} disabled={loading}>
              <Trash2 size={16} /> Delete main
            </button>
          )}
        </div>
      )}
    </section>
  );
}

function WorkspacePanel({
  user,
  mainSpace,
  selectedMainCode,
  trees,
  versions,
  selectedTreeId,
  onSelectTree,
  selectedVersionId,
  setSelectedVersionId,
  onCreateTree,
  onCreateBranch,
  onSaveVersion,
  onPushMain,
  onDeleteTree,
  onDeleteVersion,
  onDeleteWorkspace,
  loading,
}) {
  const [treeName, setTreeName] = useState('June Community Feedback Tree');
  const [createdByName, setCreatedByName] = useState('Josh');
  const [branchName, setBranchName] = useState('working-branch');
  const [treeScope, setTreeScope] = useState('workspace');

  const selectedTree = trees.find(tree => String(tree.id) === String(selectedTreeId));
  const selectedVersion = versions.find(version => String(version.id) === String(selectedVersionId));
  const canEditSelectedTree = Boolean(user && selectedTree?.can_edit);
  const selectedTreeScope = selectedTree?.scope === 'workspace' ? 'Your workspace' : 'Main';
  const canDeleteSelectedTree = Boolean(user && selectedTree?.can_delete);
  const canDeleteSelectedVersion = Boolean(user && selectedVersion && canDeleteSelectedTree);
  const canCreateMainTree = Boolean(user && mainSpace?.can_admin);

  async function createTree(event) {
    event.preventDefault();

    await onCreateTree({
      name: treeName,
      description: 'Named community issue tree',
      created_by_name: createdByName,
      version_name: 'Initial version',
      main_space: selectedMainCode,
      as_main_tree: treeScope === 'main',
      is_public: treeScope === 'main',
    });
  }

  async function createBranch(event) {
    event.preventDefault();

    await onCreateBranch({
      branch_name: branchName,
      created_by_name: createdByName,
      notes: 'Created from frontend workspace.',
    });
  }

  return (
    <section className="panel workspace-panel">
      <div className="section-title">
        <GitBranch size={18} />
        <h2>Tree workspace</h2>
      </div>

      <p className="hint">
        {user
          ? 'Choose a main, then create private workspace trees inside it or copy a main tree into your workspace before editing.'
          : 'Public mode: open a main by code or URL to view its public issue trees. Log in to join, edit, or create branches.'}
      </p>

      {!selectedMainCode && (
        <div className="empty-main-state">
          <GitBranch size={26} />
          <h3>No main selected</h3>
          <p>
            {user
              ? 'Create a new main or join one with a code before creating trees.'
              : 'Enter a main code above or open a shared /main/CODE link to view public trees read-only.'}
          </p>
        </div>
      )}

      {selectedMainCode && user && (
      <form onSubmit={createTree} className="workspace-form">
        <input
          value={createdByName}
          onChange={e => setCreatedByName(e.target.value)}
          placeholder="Your display name"
        />

        <input
          value={treeName}
          onChange={e => setTreeName(e.target.value)}
          placeholder="New tree name"
        />

        <label className="inline-field">
          Tree type
          <select
            value={treeScope}
            onChange={e => setTreeScope(e.target.value)}
            disabled={!selectedMainCode}
          >
            <option value="workspace">Private workspace tree</option>
            <option value="main" disabled={!canCreateMainTree}>Public main tree {canCreateMainTree ? '' : '(owner/admin only)'}</option>
          </select>
        </label>

        <button type="submit" disabled={loading || !treeName.trim() || !selectedMainCode}>
          <Plus size={16} /> Create tree
        </button>
      </form>
      )}

      {selectedMainCode && (
      <>
      <div className="selector-grid">
        <label>
          Existing trees
          <select
            value={selectedTreeId}
            onChange={e => onSelectTree(e.target.value)}
          >
            <option value="">Choose a tree</option>
            {trees.map(tree => (
              <option key={tree.id} value={String(tree.id)}>
                {tree.scope === 'workspace' ? 'Workspace' : 'Main'} — {tree.name}
              </option>
            ))}
          </select>
        </label>

        <label>
          Versions / branches
          <select
            value={selectedVersionId}
            onChange={e => setSelectedVersionId(e.target.value)}
            disabled={!selectedTreeId}
          >
            <option value="">Choose a version</option>
            {versions.map(version => (
              <option key={version.id} value={String(version.id)}>
                {version.name} — {version.branch_name} [{version.status}]
              </option>
            ))}
          </select>
        </label>
      </div>

      {selectedTree && (
        <div className="metrics-row">
          <span>{selectedTreeScope}: {selectedTree.name}</span>
          <span>Main: {selectedTree.main_version_name || 'None'}</span>
          <span>{selectedTree.version_count || versions.length} versions</span>
        </div>
      )}

      {selectedVersion && (
        <div className="metrics-row">
          <span>Current: {selectedVersion.name}</span>
          <span>Branch: {selectedVersion.branch_name}</span>
          <span>Status: {selectedVersion.status}</span>
        </div>
      )}

      {user && (
      <form onSubmit={createBranch} className="workspace-form">
        <input
          value={branchName}
          onChange={e => setBranchName(e.target.value)}
          placeholder={canEditSelectedTree ? 'Branch name' : 'Workspace copy name'}
          disabled={!selectedVersionId}
        />

        <button
          type="submit"
          className="secondary"
          disabled={loading || !selectedVersionId}
        >
          <GitBranch size={16} /> {canEditSelectedTree ? 'Create branch' : 'Use main tree in workspace'}
        </button>
      </form>
      )}

      {user && (
      <div className="export-row">
        <button
          type="button"
          className="secondary"
          onClick={onSaveVersion}
          disabled={loading || !selectedVersionId || !canEditSelectedTree}
        >
          Save version
        </button>

        <button
          type="button"
          className="secondary"
          onClick={onPushMain}
          disabled={loading || !selectedVersionId || !canEditSelectedTree}
        >
          Push to main
        </button>
      </div>
      )}

      {user && (
      <div className="export-row">
        <button
          type="button"
          className="secondary danger-btn"
          onClick={onDeleteVersion}
          disabled={loading || !selectedVersionId || !canDeleteSelectedVersion}
          title={canDeleteSelectedVersion ? 'Delete the selected branch/version' : 'You do not have permission to delete this branch/version'}
        >
          <Trash2 size={16} /> Delete branch/version
        </button>

        <button
          type="button"
          className="secondary danger-btn"
          onClick={onDeleteTree}
          disabled={loading || !selectedTreeId || !canDeleteSelectedTree}
          title={canDeleteSelectedTree ? 'Delete the selected tree' : 'Only admins can delete public main trees. Normal users can delete their own workspace trees.'}
        >
          <Trash2 size={16} /> Delete selected tree
        </button>

        <button
          type="button"
          className="secondary danger-btn"
          onClick={onDeleteWorkspace}
          disabled={loading}
          title="Delete all trees in your current workspace. Your account stays active."
        >
          <Trash2 size={16} /> Delete my workspace
        </button>
      </div>
      )}
      </>
      )}
    </section>
  );
}

function ImportPanel({ user, selectedVersionId, canEditSelectedTree, onImported, loading, setLoading, error, setError }) {
  const [active, setActive] = useState('paste');
  const [file, setFile] = useState(null);
  const [pasteText, setPasteText] = useState(
    'user123: The trial limits are confusing and people do not understand when billing starts.\ncommunity_mod: We keep seeing spam DMs from fake investment accounts.\n[2026-06-01] Jess: New members are confused by the onboarding checklist and permissions setup.\nMorgan: People keep asking for a clearer cancellation flow because billing settings are hard to find.'
  );

  async function importPaste(event) {
    event.preventDefault();
    setError('');

    if (!selectedVersionId) {
      setError('Choose or create a tree version first.');
      return;
    }

    setLoading(true);

    try {
      await api('/import/paste/', {
        method: 'POST',
        body: JSON.stringify({
          text: pasteText,
          tree_version_id: selectedVersionId,
          merge_with_existing: true,
        }),
      });

      await onImported();
      setPasteText('');
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function uploadCsv(event) {
    event.preventDefault();

    if (!file) return;

    setError('');

    if (!selectedVersionId) {
      setError('Choose or create a tree version first.');
      return;
    }

    setLoading(true);

    try {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('tree_version_id', selectedVersionId);
      formData.append('merge_with_existing', 'true');

      await api('/upload/', {
        method: 'POST',
        body: formData,
      });

      await onImported();
      setFile(null);
      event.target.reset();
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  if (!user) {
    return null;
  }

  if (selectedVersionId && !canEditSelectedTree) {
    return (
      <section className="panel import-panel">
        <div className="section-title">
          <FileUp size={18} />
          <h2>Add feedback to this version</h2>
        </div>

        <p className="hint">
          This is a public main tree. Click “Use main tree in workspace” first, then import feedback or update node statuses in your workspace copy.
        </p>
      </section>
    );
  }

  return (
    <section className="panel import-panel">
      <div className="section-title">
        <Sparkles size={18} />
        <h2>Add feedback to this version</h2>
      </div>

      <p className="hint">
        Paste messy feedback or upload a CSV. The import is attached to the selected tree version, not automatically pushed to main.
      </p>

      <div className="import-tabs two-tabs">
        <button
          type="button"
          className={`import-tab ${active === 'paste' ? 'active' : ''}`}
          onClick={() => setActive('paste')}
        >
          <Clipboard size={16} /> Paste text
        </button>

        <button
          type="button"
          className={`import-tab ${active === 'csv' ? 'active' : ''}`}
          onClick={() => setActive('csv')}
        >
          <FileUp size={16} /> Upload CSV
        </button>
      </div>

      {active === 'paste' && (
        <form onSubmit={importPaste} className="stack-form">
          <textarea
            value={pasteText}
            onChange={e => setPasteText(e.target.value)}
            rows={8}
            placeholder="Paste Discord messages, support notes, app reviews, Slack snippets, or founder feedback dumps..."
          />

          <button disabled={loading || !pasteText.trim() || !selectedVersionId}>
            {loading ? 'Adding to tree...' : 'Import into selected version'}
          </button>
        </form>
      )}

      {active === 'csv' && (
        <form onSubmit={uploadCsv} className="upload-form">
          <input
            type="file"
            accept=".csv,text/csv"
            onChange={e => setFile(e.target.files?.[0] || null)}
          />

          <button disabled={!file || loading || !selectedVersionId}>
            {loading ? 'Adding to tree...' : 'Upload into selected version'}
          </button>

          <p className="hint full-width">
            Auto-detects text-like columns including text, body, message, comment, content, review, feedback, and ticket_text.
          </p>
        </form>
      )}

      {error && (
        <div className="error">
          <AlertTriangle size={16} /> {error}
        </div>
      )}
    </section>
  );
}

function PatternTree({ tree, selectedNode, onSelect }) {
  const scrollRef = useRef(null);
  const [viewportSize, setViewportSize] = useState({ width: 0, height: 0 });

  useEffect(() => {
    const element = scrollRef.current;
    if (!element || typeof ResizeObserver === 'undefined') return undefined;

    const observer = new ResizeObserver(entries => {
      const entry = entries[0];
      if (!entry) return;

      const nextWidth = Math.floor(entry.contentRect.width);
      const nextHeight = Math.floor(entry.contentRect.height);

      setViewportSize(current => {
        if (current.width === nextWidth && current.height === nextHeight) {
          return current;
        }

        return { width: nextWidth, height: nextHeight };
      });
    });

    observer.observe(element);

    return () => observer.disconnect();
  }, []);

  const layout = useMemo(() => {
    const nodes = tree?.nodes || [];
    const edges = tree?.edges || [];

    if (!nodes.length) {
      return {
        nodes: [],
        edges: [],
        positions: {},
        width: Math.max(900, viewportSize.width || 0),
        height: Math.max(620, viewportSize.height || 0),
      };
    }

    const nodeKey = node => `${node.batch_id || 'v'}-${node.id}`;

    const childCountByNodeId = new Map();

    edges.forEach(edge => {
      const parentId = String(edge.source);
      childCountByNodeId.set(parentId, (childCountByNodeId.get(parentId) || 0) + 1);
    });

    const byDepth = new Map();

    nodes.forEach(node => {
      const depth = node.tree_depth ?? node.depth ?? 0;

      if (!byDepth.has(depth)) {
        byDepth.set(depth, []);
      }

      byDepth.get(depth).push(node);
    });

    byDepth.forEach(list => {
      list.sort((a, b) => {
        const orderDiff = (a.tree_order || 0) - (b.tree_order || 0);

        if (orderDiff !== 0) return orderDiff;

        return (b.impact_score || b.priority_score || 0) - (a.impact_score || a.priority_score || 0);
      });
    });

    const maxDepth = Math.max(0, ...nodes.map(n => n.tree_depth ?? n.depth ?? 0));
    const maxNodesInLevel = Math.max(1, ...Array.from(byDepth.values()).map(list => list.length));

    const cardW = 280;
    const cardH = 116;
    const horizontalGap = 90;
    const verticalGap = 170;
    const canvasPaddingX = 160;
    const canvasPaddingY = 110;

    const width = Math.max(
      viewportSize.width || 0,
      900,
      maxNodesInLevel * cardW + Math.max(0, maxNodesInLevel - 1) * horizontalGap + canvasPaddingX * 2
    );

    const height = Math.max(
      viewportSize.height || 0,
      620,
      (maxDepth + 1) * cardH + maxDepth * verticalGap + canvasPaddingY * 2
    );

    const centerX = width / 2;
    const positions = {};

    byDepth.forEach((list, depth) => {
      const rowWidth =
        list.length * cardW + Math.max(0, list.length - 1) * horizontalGap;

      const startX = centerX - rowWidth / 2;
      const y = canvasPaddingY + depth * (cardH + verticalGap);

      list.forEach((node, index) => {
        const key = nodeKey(node);
        const hasChildren = childCountByNodeId.get(String(node.id)) > 0;

        positions[key] = {
          x: startX + index * (cardW + horizontalGap),
          y,
          w: cardW,
          h: cardH,
          depth,
          kind: depth === 0 ? 'root' : hasChildren ? 'branch' : 'leaf',
        };
      });
    });

    /*
      Collision safety pass.
      This keeps same-level cards separated if text/card sizing changes.
    */
    const keys = Object.keys(positions);
    const paddingX = 36;
    const paddingY = 28;

    for (let pass = 0; pass < 8; pass += 1) {
      let moved = false;

      for (let i = 0; i < keys.length; i += 1) {
        for (let j = i + 1; j < keys.length; j += 1) {
          const a = positions[keys[i]];
          const b = positions[keys[j]];

          const overlapX =
            Math.min(a.x + a.w + paddingX, b.x + b.w + paddingX) -
            Math.max(a.x - paddingX, b.x - paddingX);

          const overlapY =
            Math.min(a.y + a.h + paddingY, b.y + b.h + paddingY) -
            Math.max(a.y - paddingY, b.y - paddingY);

          if (overlapX > 0 && overlapY > 0) {
            moved = true;

            if (a.depth === b.depth || overlapX < overlapY) {
              const push = overlapX / 2 + 20;

              if (a.x <= b.x) {
                a.x -= push;
                b.x += push;
              } else {
                a.x += push;
                b.x -= push;
              }
            } else {
              const push = overlapY / 2 + 18;

              if (a.y <= b.y) {
                a.y -= push;
                b.y += push;
              } else {
                a.y += push;
                b.y -= push;
              }
            }
          }
        }
      }

      if (!moved) break;
    }

    /*
      Shift all cards into positive canvas space if collision pass moved them left/up.
    */
    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;

    Object.values(positions).forEach(pos => {
      minX = Math.min(minX, pos.x);
      minY = Math.min(minY, pos.y);
      maxX = Math.max(maxX, pos.x + pos.w);
      maxY = Math.max(maxY, pos.y + pos.h);
    });

    const safePad = 120;

    if (minX < safePad) {
      const shift = safePad - minX;
      Object.values(positions).forEach(pos => {
        pos.x += shift;
      });
      maxX += shift;
    }

    if (minY < safePad) {
      const shift = safePad - minY;
      Object.values(positions).forEach(pos => {
        pos.y += shift;
      });
      maxY += shift;
    }

    return {
      nodes,
      edges,
      positions,
      width: Math.max(width, maxX + safePad, viewportSize.width || 0),
      height: Math.max(height, maxY + safePad, viewportSize.height || 0),
    };
  }, [tree, viewportSize.width, viewportSize.height]);

  if (!layout.nodes.length) {
    return (
      <div className="empty-tree">
        No issue nodes yet. Import feedback to build this version’s decision tree.
      </div>
    );
  }

  function getPositionForEdgeNode(edgeNodeId, batchId) {
    const batchKey = batchId ? `${batchId}-${edgeNodeId}` : null;

    if (batchKey && layout.positions[batchKey]) {
      return layout.positions[batchKey];
    }

    const fallbackKey = Object.keys(layout.positions).find(key => key.endsWith(`-${edgeNodeId}`));

    return fallbackKey ? layout.positions[fallbackKey] : null;
  }

  const nodesById = new Map(layout.nodes.map(node => [String(node.id), node]));

  return (
    <div className="tree-scroll" ref={scrollRef}>
      <div
        className="tree-canvas decision-canvas"
        style={{ width: layout.width, height: layout.height }}
      >
        <svg className="edge-layer decision-layer" width={layout.width} height={layout.height}>
          <defs>
            <marker
              id="decisionArrow"
              markerWidth="12"
              markerHeight="12"
              refX="10"
              refY="6"
              orient="auto"
              markerUnits="strokeWidth"
            >
              <path d="M2,2 L10,6 L2,10 Z" className="decision-arrow-head" />
            </marker>

            <filter id="decisionGlow">
              <feGaussianBlur stdDeviation="1.6" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
          </defs>

          {layout.edges.map(edge => {
            const source = getPositionForEdgeNode(edge.source, edge.source_batch_id || edge.batch_id);
            const target = getPositionForEdgeNode(edge.target, edge.target_batch_id || edge.batch_id);

            if (!source || !target) return null;

            const x1 = source.x + source.w / 2;
            const y1 = source.y + source.h;
            const x2 = target.x + target.w / 2;
            const y2 = target.y;

            const midY = y1 + (y2 - y1) / 2;

            const sourceNode = nodesById.get(String(edge.source));
            const targetNode = nodesById.get(String(edge.target));
            const propagatedEdge = isPropagatedStatus(sourceNode) || isPropagatedStatus(targetNode);

            return (
              <path
                key={edge.id || `${edge.source}-${edge.target}`}
                d={`M ${x1} ${y1}
                    C ${x1} ${midY}, ${x2} ${midY}, ${x2} ${y2}`}
                className={`decision-edge ${propagatedEdge ? 'edge-propagated' : 'edge-direct'}`}
                markerEnd="url(#decisionArrow)"
              />
            );
          })}
        </svg>

        <div className="decision-guide decision-guide-main" />
        <div className="decision-guide decision-guide-horizontal" />

        {layout.nodes.map(node => {
          const key = `${node.batch_id || 'v'}-${node.id}`;
          const pos = layout.positions[key];
          const meta = STATUS_META[node.status] || STATUS_META.untouched;
          const score = node.impact_score ?? node.priority_score ?? 0;
          const propagatedClass = isPropagatedStatus(node) ? 'status-propagated' : 'status-direct';

          return (
            <button
              key={key}
              type="button"
              className={`tree-node decision-node decision-${pos.kind} ${meta.tone} ${propagatedClass} ${
                selectedNode?.id === node.id && selectedNode?.batch_id === node.batch_id
                  ? 'selected'
                  : ''
              }`}
              style={{
                left: pos.x,
                top: pos.y,
                width: pos.w,
                height: pos.h,
              }}
              onClick={() => onSelect(node)}
            >
              <span className="node-score">{Math.round(score)}</span>

              <span className="decision-copy">
                <strong>{node.theme}</strong>
                <span>
                  {node.post_count || 0} posts · {meta.label}
                  {isPropagatedStatus(node) ? ` · auto ${Math.round((node.status_confidence || 0) * 100)}%` : ''}
                </span>
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function NodeDetails({ node, user, canEditSelectedTree, onUpdated }) {
  const [note, setNote] = useState(node?.progress_note || '');
  const [saving, setSaving] = useState(false);

  React.useEffect(() => {
    setNote(node?.progress_note || '');
  }, [node?.id, node?.batch_id]);

  if (!node) {
    return (
      <aside className="node-panel empty-node">
        <GitBranch size={28} />
        <h3>Select a node</h3>
        <p>
          Click any issue in the Pattern Tree to see evidence, suggested action,
          relationship context, and update its status.
        </p>
      </aside>
    );
  }

  async function setStatus(status) {
    if (!node.batch_id) {
      throw new Error('This node is missing batch_id. Check tree_version_payload().');
    }

    setSaving(true);

    try {
      await api(`/batches/${node.batch_id}/tree/nodes/${node.id}/status/`, {
        method: 'PATCH',
        body: JSON.stringify({ status, progress_note: note }),
      });

      await onUpdated();
    } finally {
      setSaving(false);
    }
  }

  const meta = STATUS_META[node.status] || STATUS_META.untouched;
  const score = node.impact_score ?? node.priority_score ?? 0;

  return (
    <aside className="node-panel">
      <div className="node-detail-head">
        <Pill tone={meta.pillTone || 'neutral'}>{meta.label}</Pill>
        <Pill>{Math.round(score)} impact</Pill>
        <Pill tone={isPropagatedStatus(node) ? 'amber' : 'green'}>
          {isPropagatedStatus(node)
            ? `Propagated · ${Math.round((node.status_confidence || 0) * 100)}%`
            : 'Manual'}
        </Pill>
      </div>

      <h2>{node.theme}</h2>

      <p className="muted">
        {node.category} · {node.post_count} related posts · {node.severity} priority
        {node.assigned_to_username ? ` · assigned to ${node.assigned_to_username}` : ''}
      </p>

      <div className="action-box">
        <strong>Suggested action</strong>
        <p>{node.suggested_action}</p>
      </div>

      {node.relationship_reason && node.relationship_type !== 'root_highest_impact' && (
        <div className="relationship-box">
          <strong>Relationship to parent</strong>
          <p>{node.relationship_reason}</p>
          <span>Relation score: {node.relationship_score}</span>
        </div>
      )}

      {isPropagatedStatus(node) && node.status_reason && (
        <div className="relationship-box propagated-box">
          <strong>Propagated status</strong>
          <p>{node.status_reason}</p>
          <span>
            If you change this node directly, it becomes a manual status and the dashed style is removed.
          </span>
        </div>
      )}

      {user && canEditSelectedTree ? (
      <>
      <label className="note-label">Progress note</label>

      <textarea
        value={note}
        onChange={e => setNote(e.target.value)}
        rows={3}
        placeholder="Example: Product is rewriting the pricing FAQ this week."
      />

      <div className="status-grid">
        {STATUS_BUTTONS.map(([value, label, className]) => (
          <button
            key={value}
            disabled={saving}
            type="button"
            className={className}
            onClick={() => setStatus(value)}
          >
            {value === 'completed' ? <CheckCircle2 size={16} /> : null}
            {label}
          </button>
        ))}
      </div>

      </>
      ) : (
        <div className="relationship-box">
          <strong>Public view only</strong>
          <p>Log in to create a workspace branch and update the status of this node.</p>
        </div>
      )}

      <h3>Evidence</h3>

      <div className="examples">
        {(node.examples || []).map((example, index) => (
          <blockquote key={index}>
            {typeof example === 'string' ? example : example.text}
          </blockquote>
        ))}
      </div>
    </aside>
  );
}

function TreeWorkspace({ versionPayload, user, canEditSelectedTree, onReload }) {
  const [selectedKey, setSelectedKey] = useState(null);
  const [focusMode, setFocusMode] = useState(false);

  const nodes = versionPayload?.nodes || [];
  const tree = useMemo(() => ({
    nodes: versionPayload?.nodes || [],
    edges: versionPayload?.edges || [],
  }), [versionPayload]);

  const selectedNode = useMemo(() => {
    if (!nodes.length) return null;
    if (!selectedKey) return nodes[0];

    return nodes.find(node => `${node.batch_id || 'v'}-${node.id}` === selectedKey) || nodes[0];
  }, [nodes, selectedKey]);

  React.useEffect(() => {
    if (nodes[0]) {
      setSelectedKey(`${nodes[0].batch_id || 'v'}-${nodes[0].id}`);
    } else {
      setSelectedKey(null);
    }
  }, [versionPayload?.version?.id, nodes.length]);

  return (
    <section className={`panel tree-panel ${focusMode ? 'tree-panel-focus' : ''}`}>
      <div className="tree-header">
        <div>
          <div className="section-title">
            <GitBranch size={18} />
            <h2>Pattern Tree</h2>
          </div>

          <p className="hint">
            Root = highest-impact visible issue. Branches show related downstream issues.
          </p>
        </div>

        <div className="tree-header-actions">
          {versionPayload?.version && (
            <div className="metrics-row">
              <span>{versionPayload.tree?.name}</span>
              <span>{versionPayload.version.name}</span>
              <span>{versionPayload.version.branch_name}</span>
              <span>{versionPayload.version.status}</span>
            </div>
          )}

          <button
            type="button"
            className="secondary"
            onClick={() => setFocusMode(current => !current)}
          >
            {focusMode ? 'Exit focus' : 'Focus tree'}
          </button>
        </div>
      </div>

      <div className="tree-layout">
        <PatternTree
          tree={tree}
          selectedNode={selectedNode}
          onSelect={node => setSelectedKey(`${node.batch_id || 'v'}-${node.id}`)}
        />

        {!focusMode && (
          <NodeDetails
            node={selectedNode}
            user={user}
            canEditSelectedTree={canEditSelectedTree}
            onUpdated={onReload}
          />
        )}
      </div>
    </section>
  );
}


function VersionReport({ versionPayload }) {
  const nodes = versionPayload?.nodes || [];
  if (!nodes.length) return null;

  const topNodes = [...nodes]
    .sort((a, b) => (b.impact_score ?? b.priority_score ?? 0) - (a.impact_score ?? a.priority_score ?? 0))
    .slice(0, 5);

  async function copyReport() {
    const lines = [
      `${versionPayload.tree.name} / ${versionPayload.version.name}`,
      '',
      'Top recurring issues:',
      ...topNodes.map((node, index) => {
        const score = Math.round(node.impact_score ?? node.priority_score ?? 0);

        return `${index + 1}. ${node.theme} — ${node.post_count} posts, impact ${score}. ${node.suggested_action}`;
      }),
      '',
      'Next steps:',
      ...topNodes.map(node => `- ${node.suggested_action}`),
    ];

    await navigator.clipboard.writeText(lines.join('\n'));
  }

  return (
    <section className="panel report-panel">
      <div className="section-title report-title">
        <div>
          <Sparkles size={18} />
          <h2>Version report</h2>
        </div>

        <div className="export-row">
          <button type="button" className="secondary" onClick={copyReport}>
            <Clipboard size={16} /> Copy report
          </button>
        </div>
      </div>

      <ol className="report-list">
        {topNodes.map(node => (
          <li key={`${node.batch_id || 'v'}-${node.id}`}>
            <strong>{node.theme}</strong> — {node.post_count} posts. {node.suggested_action}
          </li>
        ))}
      </ol>
    </section>
  );
}

function SearchPanel({ versionPayload }) {
  const [query, setQuery] = useState('pricing complaints');
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);

  const latestBatchId = versionPayload?.batches?.[versionPayload.batches.length - 1]?.id;

  async function runSearch(event) {
    event?.preventDefault();

    if (!latestBatchId || !query.trim()) return;

    setLoading(true);

    try {
      const data = await api(`/batches/${latestBatchId}/search/?q=${encodeURIComponent(query)}`);
      setResults(data.results || []);
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="panel">
      <div className="section-title">
        <Search size={18} />
        <h2>Semantic search</h2>
      </div>

      <p className="hint">
        For now, search runs against the latest imported batch in this version.
      </p>

      <form className="search-form" onSubmit={runSearch}>
        <input
          value={query}
          onChange={e => setQuery(e.target.value)}
          placeholder="Try: pricing complaints, possible spam, onboarding confusion"
        />

        <button type="submit" disabled={loading || !latestBatchId}>
          {loading ? 'Searching...' : 'Search latest batch'}
        </button>
      </form>

      <div className="search-results">
        {results.map(result => (
          <div className="search-result" key={result.id}>
            <div className="metrics-row">
              <span>Similarity {result.score}</span>
              {result.channel && <span>{result.channel}</span>}
            </div>

            <p>{result.text}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

function App() {
  const [mainSpaces, setMainSpaces] = useState([]);
  const [selectedMainCode, setSelectedMainCode] = useState(() => {
    const pathMatch = window.location.pathname.match(/^\/main\/([^/]+)/);
    return pathMatch?.[1]?.toUpperCase() || localStorage.getItem(SELECTED_MAIN_KEY) || '';
  });
  const [trees, setTrees] = useState([]);
  const [versions, setVersions] = useState([]);
  const [selectedTreeId, setSelectedTreeId] = useState('');
  const [selectedVersionId, setSelectedVersionId] = useState('');
  const [versionPayload, setVersionPayload] = useState(null);
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const nodes = versionPayload?.nodes || [];
  const selectedTree = trees.find(tree => String(tree.id) === String(selectedTreeId));
  const selectedMainSpace = mainSpaces.find(space => space.join_code === selectedMainCode);
  const canEditSelectedTree = Boolean(user && selectedTree?.can_edit);

  const stats = useMemo(() => {
    const unresolved = nodes.filter(n => !['completed', 'legacy'].includes(n.status)).length;
    const inProgress = nodes.filter(n => n.status === 'in_progress').length;
    const completed = nodes.filter(n => ['completed', 'legacy'].includes(n.status)).length;

    return {
      unresolved,
      inProgress,
      completed,
      total: nodes.length,
    };
  }, [nodes]);

  async function loadMainSpaces(preferredCode = selectedMainCode) {
    let data = await api('/main-spaces/');

    if (preferredCode && !data.some(space => space.join_code === preferredCode)) {
      try {
        const sharedSpace = await api(`/main-spaces/${encodeURIComponent(preferredCode)}/`);
        data = [sharedSpace, ...data.filter(space => space.join_code !== sharedSpace.join_code)];
      } catch {
        // Keep the normal list if the shared code is invalid or unavailable.
      }
    }

    setMainSpaces(data);

    if (preferredCode && data.some(space => space.join_code === preferredCode)) {
      setSelectedMainCode(preferredCode);
      localStorage.setItem(SELECTED_MAIN_KEY, preferredCode);
      return data;
    }

    if (!selectedMainCode && data[0]) {
      setSelectedMainCode(data[0].join_code);
      localStorage.setItem(SELECTED_MAIN_KEY, data[0].join_code);
    }

    return data;
  }

  async function loadTrees(preferredTreeId = null, mainCodeArg = selectedMainCode) {
    const query = mainCodeArg ? `?main_space=${encodeURIComponent(mainCodeArg)}` : '';
    const data = await api(`/trees/${query}`);
    setTrees(data);

    if (!data.length) {
      setSelectedTreeId('');
      setSelectedVersionId('');
      setVersionPayload(null);
      return data;
    }

    const preferredStillExists =
      preferredTreeId &&
      data.some(tree => String(tree.id) === String(preferredTreeId));

    if (preferredStillExists) {
      setSelectedTreeId(String(preferredTreeId));
      return data;
    }

    const currentStillExists =
      selectedTreeId &&
      data.some(tree => String(tree.id) === String(selectedTreeId));

    if (currentStillExists) {
      return data;
    }

    if (!user && data[0]) {
      setSelectedTreeId(String(data[0].id));
      return data;
    }

    setSelectedTreeId('');
    setSelectedVersionId('');
    setVersionPayload(null);

    return data;
  }

  async function loadVersions(
    treeId = selectedTreeId,
    preferredVersionId = null,
    treeList = trees
  ) {
    if (!treeId) {
      setVersions([]);
      setSelectedVersionId('');
      setVersionPayload(null);
      return [];
    }

    const data = await api(`/trees/${treeId}/versions/`);
    setVersions(data);

    if (!data.length) {
      setSelectedVersionId('');
      setVersionPayload(null);
      return data;
    }

    const preferredStillExists =
      preferredVersionId &&
      data.some(version => String(version.id) === String(preferredVersionId));

    if (preferredStillExists) {
      setSelectedVersionId(String(preferredVersionId));
      return data;
    }

    const currentStillExists =
      selectedVersionId &&
      data.some(version => String(version.id) === String(selectedVersionId));

    if (currentStillExists) {
      return data;
    }

    const selectedTree = treeList.find(tree => String(tree.id) === String(treeId));
    const mainVersionId = selectedTree?.main_version;

    const mainVersion = data.find(
      version => String(version.id) === String(mainVersionId)
    );

    if (mainVersion) {
      setSelectedVersionId(String(mainVersion.id));
      return data;
    }

    // Last resort only if no main version is found.
    setSelectedVersionId(String(data[0].id));

    return data;
  }

  async function loadVersionPayload(versionId = selectedVersionId) {
    if (!versionId) {
      setVersionPayload(null);
      return null;
    }

    const data = await api(`/tree-versions/${versionId}/`);
    setVersionPayload(data);

    return data;
  }

  function handleSelectTree(treeId) {
    setSelectedTreeId(String(treeId));
    setSelectedVersionId('');
    setVersionPayload(null);
  }

  async function refreshCurrentVersion() {
    if (!selectedVersionId) return;

    await loadVersionPayload(selectedVersionId);
    await loadVersions(selectedTreeId, selectedVersionId);
  }

  async function handleSelectMain(code) {
    const nextCode = (code || '').toUpperCase();
    setSelectedMainCode(nextCode);
    if (nextCode) {
      localStorage.setItem(SELECTED_MAIN_KEY, nextCode);
      window.history.replaceState(null, '', `/main/${nextCode}`);
    }
    setSelectedTreeId('');
    setSelectedVersionId('');
    setVersionPayload(null);
    await loadTrees(null, nextCode);
  }

  async function handleCreateMain(payload) {
    setLoading(true);
    setError('');
    try {
      const space = await api('/main-spaces/create/', {
        method: 'POST',
        body: JSON.stringify(payload),
      });
      setSelectedMainCode(space.join_code);
      localStorage.setItem(SELECTED_MAIN_KEY, space.join_code);
      window.history.replaceState(null, '', `/main/${space.join_code}`);
      await loadMainSpaces(space.join_code);
      await loadTrees(null, space.join_code);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleJoinMain(code) {
    const cleanCode = (code || '').trim().toUpperCase();
    if (!cleanCode) return;
    setLoading(true);
    setError('');
    try {
      const space = await api(`/main-spaces/${encodeURIComponent(cleanCode)}/join/`, {
        method: 'POST',
        body: JSON.stringify({}),
      });
      setSelectedMainCode(space.join_code);
      localStorage.setItem(SELECTED_MAIN_KEY, space.join_code);
      window.history.replaceState(null, '', `/main/${space.join_code}`);
      await loadMainSpaces(space.join_code);
      await loadTrees(null, space.join_code);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleOpenMain(code) {
    const cleanCode = (code || '').trim().toUpperCase();
    if (!cleanCode) return;

    setLoading(true);
    setError('');

    try {
      const space = await api(`/main-spaces/${encodeURIComponent(cleanCode)}/`);
      setSelectedMainCode(space.join_code);
      localStorage.setItem(SELECTED_MAIN_KEY, space.join_code);
      window.history.replaceState(null, '', `/main/${space.join_code}`);
      await loadMainSpaces(space.join_code);
      await loadTrees(null, space.join_code);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleDeleteMain() {
    if (!selectedMainCode) return;
    const selected = mainSpaces.find(space => space.join_code === selectedMainCode);
    const confirmed = window.confirm(
      `Delete main “${selected?.name || selectedMainCode}”? This deletes its public main trees and linked workspace trees.`
    );
    if (!confirmed) return;
    setLoading(true);
    setError('');
    try {
      await api(`/main-spaces/${encodeURIComponent(selectedMainCode)}/delete/`, { method: 'DELETE' });
      localStorage.removeItem(SELECTED_MAIN_KEY);
      window.history.replaceState(null, '', '/');
      setSelectedMainCode('');
      setSelectedTreeId('');
      setSelectedVersionId('');
      setVersionPayload(null);
      await loadMainSpaces('');
      await loadTrees(null, '');
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleCreateTree(payload) {
    setLoading(true);
    setError('');

    try {
      const version = await api('/trees/create/', {
        method: 'POST',
        body: JSON.stringify({ ...payload, main_space: payload.main_space || selectedMainCode }),
      });

      const treeId = String(version.tree);
      const versionId = String(version.id);

      const freshTrees = await loadTrees(treeId);

      setSelectedTreeId(treeId);
      await loadVersions(treeId, versionId, freshTrees);
      setSelectedVersionId(versionId);
      await loadVersionPayload(versionId);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleCreateBranch(payload) {
    if (!selectedVersionId) return;

    const currentTreeId = selectedTreeId;

    setLoading(true);
    setError('');

    try {
      const version = await api(`/tree-versions/${selectedVersionId}/branch/`, {
        method: 'POST',
        body: JSON.stringify(payload),
      });

      const versionId = String(version.id);
      const nextTreeId = String(version.tree || currentTreeId);

      if (nextTreeId !== String(currentTreeId)) {
        const freshTrees = await loadTrees(nextTreeId);
        setSelectedTreeId(nextTreeId);
        await loadVersions(nextTreeId, versionId, freshTrees);
      } else {
        await loadVersions(currentTreeId, versionId);
      }

      setSelectedVersionId(versionId);
      await loadVersionPayload(versionId);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleSaveVersion() {
    if (!selectedVersionId) return;

    const currentTreeId = selectedTreeId;
    const currentVersionId = selectedVersionId;

    setLoading(true);
    setError('');

    try {
      await api(`/tree-versions/${currentVersionId}/save/`, {
        method: 'POST',
        body: JSON.stringify({
          notes: 'Saved manually from frontend.',
        }),
      });

      await loadVersions(currentTreeId, currentVersionId);
      await loadVersionPayload(currentVersionId);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function handlePushMain() {
    if (!selectedVersionId) return;

    const pushedVersionId = selectedVersionId;
    const currentTreeId = selectedTreeId;

    setLoading(true);
    setError('');

    try {
      await api(`/tree-versions/${pushedVersionId}/push-main/`, {
        method: 'POST',
        body: JSON.stringify({}),
      });

      const query = selectedMainCode ? `?main_space=${encodeURIComponent(selectedMainCode)}` : '';
      const freshTrees = await api(`/trees/${query}`);
      setTrees(freshTrees);

      await loadVersions(currentTreeId, pushedVersionId, freshTrees);

      setSelectedTreeId(String(currentTreeId));
      setSelectedVersionId(String(pushedVersionId));
      await loadVersionPayload(String(pushedVersionId));
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleDeleteTree() {
    if (!selectedTreeId) return;

    const selected = trees.find(tree => String(tree.id) === String(selectedTreeId));
    const confirmed = window.confirm(
      `Delete tree “${selected?.name || selectedTreeId}”? This will delete all its branches and nodes.`
    );

    if (!confirmed) return;

    setLoading(true);
    setError('');

    try {
      await api(`/trees/${selectedTreeId}/delete/`, {
        method: 'DELETE',
      });

      setSelectedTreeId('');
      setSelectedVersionId('');
      setVersionPayload(null);
      await loadTrees();
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleDeleteVersion() {
    if (!selectedVersionId) return;

    const selected = versions.find(version => String(version.id) === String(selectedVersionId));
    const confirmed = window.confirm(
      `Delete branch/version “${selected?.name || selectedVersionId}”?`
    );

    if (!confirmed) return;

    const currentTreeId = selectedTreeId;

    setLoading(true);
    setError('');

    try {
      const result = await api(`/tree-versions/${selectedVersionId}/delete/`, {
        method: 'DELETE',
      });

      setSelectedVersionId('');
      setVersionPayload(null);
      const freshTrees = await loadTrees(currentTreeId);
      await loadVersions(currentTreeId, result.main_version ? String(result.main_version) : null, freshTrees);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleDeleteWorkspace() {
    if (!user) return;

    const confirmed = window.confirm(
      'Delete your workspace? This deletes all trees and branches inside your workspace, but keeps your login account.'
    );

    if (!confirmed) return;

    setLoading(true);
    setError('');

    try {
      await api('/workspace/delete/', {
        method: 'DELETE',
      });

      const currentUser = await loadMe();
      setUser(currentUser);
      setSelectedTreeId('');
      setSelectedVersionId('');
      setVersionPayload(null);
      await loadTrees();
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function loadMe() {
    const data = await api('/auth/me/');
    setUser(data.user || null);
    return data.user || null;
  }

  async function handleAuthChanged(data) {
    const nextUser = data?.username ? data : await loadMe().catch(() => null);
    setUser(nextUser || null);
    setMainSpaces([]);
    setTrees([]);
    setVersions([]);
    setSelectedTreeId('');
    setSelectedVersionId('');
    setVersionPayload(null);
    await loadMainSpaces();
    await loadTrees();
  }

  React.useEffect(() => {
    loadMe()
      .then(() => loadMainSpaces())
      .finally(() => loadTrees())
      .catch(err => setError(err.message));
  }, []);

  React.useEffect(() => {
    loadTrees().catch(err => setError(err.message));
  }, [selectedMainCode]);

  React.useEffect(() => {
    if (!selectedTreeId) {
      setVersions([]);
      setSelectedVersionId('');
      setVersionPayload(null);
      return;
    }

    loadVersions(selectedTreeId).catch(err => setError(err.message));
  }, [selectedTreeId]);

  React.useEffect(() => {
    if (!selectedVersionId) {
      setVersionPayload(null);
      return;
    }

    loadVersionPayload(selectedVersionId).catch(err => setError(err.message));
  }, [selectedVersionId]);

  return (
    <main>
      <header className="hero">
        <div className="brand">
          <Radar /> Community Pattern Radar
        </div>

        <h1>Turn recurring feedback into a living issue tree.</h1>

        <p>
          Create or join a main by code/URL, then work privately in your workspace and push related status changes back to that main only.
        </p>
      </header>

      {error && (
        <div className="panel error">
          <AlertTriangle size={16} /> {error}
        </div>
      )}

      <AuthPanel
        user={user}
        onAuthChanged={handleAuthChanged}
        setError={setError}
      />

      <MainSpacePanel
        user={user}
        mainSpaces={mainSpaces}
        selectedMainCode={selectedMainCode}
        onSelectMain={handleSelectMain}
        onCreateMain={handleCreateMain}
        onJoinMain={handleJoinMain}
        onOpenMain={handleOpenMain}
        onDeleteMain={handleDeleteMain}
        loading={loading}
      />

      <WorkspacePanel
        user={user}
        mainSpace={selectedMainSpace}
        selectedMainCode={selectedMainCode}
        trees={trees}
        versions={versions}
        selectedTreeId={selectedTreeId}
        onSelectTree={handleSelectTree}
        selectedVersionId={selectedVersionId}
        setSelectedVersionId={setSelectedVersionId}
        onCreateTree={handleCreateTree}
        onCreateBranch={handleCreateBranch}
        onSaveVersion={handleSaveVersion}
        onPushMain={handlePushMain}
        onDeleteTree={handleDeleteTree}
        onDeleteVersion={handleDeleteVersion}
        onDeleteWorkspace={handleDeleteWorkspace}
        loading={loading}
      />

      <ImportPanel
        user={user}
        selectedVersionId={selectedVersionId}
        canEditSelectedTree={canEditSelectedTree}
        onImported={refreshCurrentVersion}
        loading={loading}
        setLoading={setLoading}
        error=""
        setError={setError}
      />

      {versionPayload && (
        <>
          <section className="stats-grid">
            <div className="stat">
              <span>Total nodes</span>
              <strong>{stats.total}</strong>
            </div>

            <div className="stat">
              <span>Unresolved</span>
              <strong>{stats.unresolved}</strong>
            </div>

            <div className="stat">
              <span>In progress</span>
              <strong>{stats.inProgress}</strong>
            </div>

            <div className="stat">
              <span>Completed/legacy</span>
              <strong>{stats.completed}</strong>
            </div>
          </section>

          {versionPayload.batches?.length > 0 && (
            <section className="panel import-summary">
              <h2>Version batches</h2>

              <div className="metrics-row">
                {versionPayload.batches.map(batch => (
                  <span key={batch.id}>
                    #{batch.id} {batch.filename} · {batch.total_posts} posts
                  </span>
                ))}
              </div>
            </section>
          )}

          <TreeWorkspace
            versionPayload={versionPayload}
            user={user}
            canEditSelectedTree={canEditSelectedTree}
            onReload={refreshCurrentVersion}
          />

          <VersionReport versionPayload={versionPayload} />

          <SearchPanel versionPayload={versionPayload} />
        </>
      )}
    </main>
  );
}

createRoot(document.getElementById('root')).render(<App />);