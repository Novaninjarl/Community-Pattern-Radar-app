import csv
from copy import deepcopy
import io
import json
import math
import re
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import (
    ENGLISH_STOP_WORDS,
    HashingVectorizer,
    TfidfVectorizer,
)
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.preprocessing import normalize

from .interpretation import (
    build_cluster_evidence,
    deterministic_json,
    interpret_cluster,
    ollama_deterministic_options,
    weekly_report_summary,
)
from .models import (
    CommunityPost,
    IssueCluster,
    MainSpace,
    PatternTree,
    TreeVersion,
    UploadBatch,
    WeeklyReport,
    Workspace,
)


@dataclass
class PostRecord:
    text: str
    created_at: str = ''
    user_id: str = ''
    channel: str = ''
    post_url: str = ''
    report_count: int = 0
    upvotes: int = 0
    moderation_status: str = ''
    source: str = ''
    external_id: str = ''
    raw_metadata: Dict[str, Any] | None = None


TEXT_COLUMN_CANDIDATES = [
    'text',
    'body',
    'message',
    'comment',
    'content',
    'post',
    'description',
    'review',
    'ticket_text',
    'feedback',
    'summary',
    'question',
    'answer',
]


def clean_text(text: Any) -> str:
    text = '' if pd.isna(text) else str(text)
    text = re.sub(r'https?://\S+', ' ', text)
    text = re.sub(r'@[\w_]+', ' ', text)
    text = re.sub(r'#[\w_]+', ' ', text)
    text = re.sub(r'[^a-zA-Z0-9£$%!?.,\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip().lower()
    return text


def safe_int(value: Any) -> int:
    try:
        if pd.isna(value) or value == '':
            return 0
        return int(float(value))
    except Exception:
        return 0


def guess_text_column(columns: List[str]) -> str | None:
    lowered = {c.lower().strip(): c for c in columns}

    for candidate in TEXT_COLUMN_CANDIDATES:
        if candidate in lowered:
            return lowered[candidate]

    return None


def guess_text_column_from_dataframe(df: pd.DataFrame) -> str | None:
    exact = guess_text_column(list(df.columns))
    if exact:
        return exact

    best_col = None
    best_score = 0

    for col in df.columns:
        series = df[col].dropna().astype(str)
        if series.empty:
            continue

        avg_len = series.str.len().mean()
        longish_ratio = (series.str.len() > 20).mean()
        score = avg_len * longish_ratio

        if score > best_score:
            best_score = score
            best_col = col

    return best_col if best_score >= 20 else None


def local_embeddings(texts: List[str]) -> np.ndarray:
    vectorizer = HashingVectorizer(
        n_features=384,
        alternate_sign=False,
        stop_words='english',
        norm='l2',
    )
    matrix = vectorizer.transform(texts).toarray().astype(float)
    return normalize(matrix)


def cohere_embeddings(texts: List[str]) -> np.ndarray:
    import cohere

    client = cohere.Client(settings.COHERE_API_KEY)
    response = client.embed(
        texts=texts,
        model='embed-english-v3.0',
        input_type='clustering',
    )
    return normalize(np.array(response.embeddings, dtype=float))


def embed_texts(texts: List[str]) -> np.ndarray:
    if settings.EMBEDDING_BACKEND == 'cohere' and settings.COHERE_API_KEY:
        try:
            return cohere_embeddings(texts)
        except Exception:
            pass

    return local_embeddings(texts)


def choose_cluster_count(n: int) -> int:
    if n < 8:
        return max(1, min(3, n))
    return max(2, min(8, int(math.sqrt(n))))


def cluster_embeddings(embeddings: np.ndarray) -> np.ndarray:
    n = len(embeddings)

    if n <= 1:
        return np.zeros(n, dtype=int)

    k = choose_cluster_count(n)
    model = KMeans(n_clusters=k, random_state=42, n_init=10)
    return model.fit_predict(embeddings)


def top_terms(texts: List[str], limit: int = 5) -> List[str]:
    if not texts:
        return []

    vectorizer = TfidfVectorizer(
        stop_words='english',
        max_features=80,
        ngram_range=(1, 2),
    )

    try:
        matrix = vectorizer.fit_transform(texts)
        scores = np.asarray(matrix.sum(axis=0)).ravel()
        terms = vectorizer.get_feature_names_out()
        return [terms[i] for i in scores.argsort()[::-1][:limit]]
    except Exception:
        words = [
            word
            for text in texts
            for word in re.findall(r'[a-z]{3,}', text)
            if word not in ENGLISH_STOP_WORDS
        ]
        return [word for word, _ in Counter(words).most_common(limit)]


def create_weekly_report(batch: UploadBatch) -> WeeklyReport:
    clusters = list(batch.clusters.order_by('-priority_score')[:5])

    top_issues = [
        {
            'theme': cluster.theme,
            'category': cluster.category,
            'severity': cluster.severity,
            'post_count': cluster.post_count,
            'recommended_next_step': cluster.suggested_action,
        }
        for cluster in clusters
    ]

    summary = weekly_report_summary(batch.total_posts, top_issues)

    return WeeklyReport.objects.create(batch=batch, summary=summary)


def _dedupe_records(records: List[PostRecord]) -> Tuple[List[PostRecord], int, int]:
    seen = set()
    deduped: List[PostRecord] = []
    skipped_short = 0
    skipped_duplicates = 0

    for record in records:
        cleaned = clean_text(record.text)

        if len(cleaned) < 3:
            skipped_short += 1
            continue

        key = re.sub(r'\s+', ' ', cleaned)[:240]

        if key in seen:
            skipped_duplicates += 1
            continue

        seen.add(key)
        deduped.append(record)

    return deduped, skipped_short, skipped_duplicates


def _process_records(
    records: List[PostRecord],
    filename: str,
    source_type: str,
    column_map: Dict[str, Any] | None = None,
    tree_version: TreeVersion | None = None,
    merge_with_existing: bool = False,
    is_unified_tree_batch: bool = False,
    inherited_batch_ids: List[int] | None = None,
) -> UploadBatch:
    records, skipped_short, skipped_duplicates = _dedupe_records(records)

    if not records:
        raise ValueError('No usable feedback items were found after cleaning.')

    batch = UploadBatch.objects.create(
        filename=filename,
        total_posts=len(records),
        status='processing',
        tree_version=tree_version,
        column_map={
            **(column_map or {}),
            'source_type': source_type,
            'skipped_short_or_empty': skipped_short,
            'skipped_duplicates': skipped_duplicates,
            'merge_with_existing_tree': merge_with_existing,
            'tree_version_id': tree_version.id if tree_version else None,
            'is_unified_tree_batch': is_unified_tree_batch,
            'inherited_batch_ids': inherited_batch_ids or [],
        },
    )

    cleaned_texts = [clean_text(record.text) for record in records]
    embeddings = embed_texts(cleaned_texts)
    labels = cluster_embeddings(embeddings)

    created_posts = []

    for pos, record in enumerate(records):
        post = CommunityPost.objects.create(
            batch=batch,
            text=str(record.text),
            cleaned_text=cleaned_texts[pos],
            created_at_raw=str(record.created_at or ''),
            user_id=str(record.user_id or ''),
            channel=str(record.channel or record.source or source_type or ''),
            post_url=str(record.post_url or ''),
            report_count=safe_int(record.report_count),
            upvotes=safe_int(record.upvotes),
            moderation_status=str(record.moderation_status or ''),
            embedding=embeddings[pos].round(6).tolist(),
            cluster_label=int(labels[pos]),
        )
        created_posts.append(post)

    grouped = defaultdict(list)

    for post in created_posts:
        grouped[post.cluster_label].append(post)

    for label, posts in grouped.items():
        cluster_texts = [post.cleaned_text for post in posts]
        terms = top_terms(cluster_texts)
        evidence = build_cluster_evidence(posts, terms)
        interpretation = interpret_cluster(evidence)
        examples = [post.text[:300] for post in posts[:3]]

        IssueCluster.objects.create(
            batch=batch,
            source_version=tree_version,
            label=label,
            theme=interpretation['theme'],
            category=interpretation['category'],
            severity=interpretation['severity'],
            priority_score=interpretation['priority_score'],
            suggested_action=interpretation['suggested_action'],
            post_count=len(posts),
            examples=examples,
        )

    batch.status = 'complete'
    batch.total_posts = len(created_posts)
    batch.save(update_fields=['status', 'total_posts'])

    create_weekly_report(batch)
    rebuild_issue_tree(batch.id, remove_completed=False, keep_legacy=True)

    return batch


def records_from_dataframe(
    df: pd.DataFrame,
    source_type: str = 'csv',
    source_url: str = '',
) -> Tuple[List[PostRecord], Dict[str, Any]]:
    text_col = guess_text_column_from_dataframe(df)

    if not text_col:
        raise ValueError(
            'Could not find a text-like column. Try columns such as text, body, '
            'message, comment, content, review, or feedback.'
        )

    records: List[PostRecord] = []

    for idx, row in df.iterrows():
        records.append(PostRecord(
            text=str(row.get(text_col, '')),
            created_at=str(row.get('created_at', row.get('date', row.get('timestamp', '')))),
            user_id=str(row.get('user_id', row.get('author', row.get('username', '')))),
            channel=str(row.get('channel', row.get('source', source_type))),
            post_url=str(row.get('post_url', row.get('url', source_url))),
            report_count=safe_int(row.get('report_count', row.get('reports', 0))),
            upvotes=safe_int(row.get('upvotes', row.get('likes', row.get('score', 0)))),
            moderation_status=str(row.get('moderation_status', row.get('status', ''))),
            source=source_type,
            external_id=str(row.get('id', idx)),
            raw_metadata={
                column: str(row.get(column, ''))
                for column in df.columns
                if column != text_col
            },
        ))

    return records, {
        'text': text_col,
        'detected_columns': list(df.columns),
    }


def parse_pasted_text(raw_text: str) -> List[PostRecord]:
    if not raw_text or not raw_text.strip():
        raise ValueError('Paste some community feedback, comments, tickets, or notes first.')

    lines = [
        line.strip()
        for line in raw_text.replace('\r\n', '\n').split('\n')
    ]

    records: List[PostRecord] = []
    current = ''

    for line in lines:
        if not line:
            if current:
                records.append(_record_from_pasted_line(current))
                current = ''
            continue

        starts_new = bool(
            re.match(
                r'^(?:[-*•]|\d+[.)]|\[?\d{4}-\d{2}-\d{2}|[\w .@-]{1,40}:)',
                line,
            )
        )

        if starts_new and current:
            records.append(_record_from_pasted_line(current))
            current = line
        else:
            current = f'{current} {line}'.strip() if current else line

    if current:
        records.append(_record_from_pasted_line(current))

    if len(records) == 1 and len(records[0].text) > 800:
        chunks = re.split(r'(?<=[.!?])\s+(?=[A-Z0-9])', records[0].text)
        records = [
            PostRecord(
                text=chunk.strip(),
                source='pasted_text',
                channel='pasted_text',
            )
            for chunk in chunks
            if len(chunk.strip()) > 20
        ]

    return records


def _record_from_pasted_line(line: str) -> PostRecord:
    original = line.strip()
    line = re.sub(r'^(?:[-*•]|\d+[.)])\s*', '', original)

    created_at = ''
    user_id = ''

    date_match = re.match(
        r'^\[?(\d{4}-\d{2}-\d{2}|\w{3,9}\s+\d{1,2})\]?\s*[-–:]?\s*(.*)$',
        line,
    )

    if date_match:
        created_at = date_match.group(1)
        line = date_match.group(2).strip()

    user_match = re.match(r'^([A-Za-z0-9_. @-]{1,40})\s*[:–-]\s+(.+)$', line)

    if user_match:
        user_id = user_match.group(1).strip()
        line = user_match.group(2).strip()

    return PostRecord(
        text=line,
        created_at=created_at,
        user_id=user_id,
        channel='pasted_text',
        source='pasted_text',
    )


def _is_unified_batch(batch: UploadBatch) -> bool:
    return bool((batch.column_map or {}).get('is_unified_tree_batch'))


def _latest_unified_batch_for_version(version: TreeVersion) -> UploadBatch | None:
    return (
        UploadBatch.objects
        .filter(tree_version=version, column_map__is_unified_tree_batch=True)
        .exclude(column_map__superseded=True)
        .order_by('-created_at', '-id')
        .first()
    )


def _version_lineage(version: TreeVersion) -> List[TreeVersion]:
    lineage = []
    current = version

    while current:
        lineage.append(current)
        current = current.parent_version

    return list(reversed(lineage))


def _display_batches_for_version(version):
    current_unified = _latest_unified_batch_for_version(version)
    if current_unified:
        return [current_unified]

    current_normal_batches = UploadBatch.objects.filter(tree_version=version)

    if current_normal_batches:
        return current_normal_batches

    if version.parent_version_id:
        return _display_batches_for_version(version.parent_version)

    return []


def _record_from_existing_post(post: CommunityPost) -> PostRecord:
    return PostRecord(
        text=post.text,
        created_at=post.created_at_raw or '',
        user_id=post.user_id or '',
        channel=post.channel or '',
        post_url=post.post_url or '',
        report_count=post.report_count or 0,
        upvotes=post.upvotes or 0,
        moderation_status=post.moderation_status or '',
        source='inherited_tree',
        external_id=f'post:{post.id}',
        raw_metadata={
            'inherited_from_batch_id': post.batch_id,
            'original_post_id': post.id,
        },
    )


def _records_from_batch(batch: UploadBatch) -> List[PostRecord]:
    posts = CommunityPost.objects.filter(batch=batch).order_by('id')
    return [_record_from_existing_post(post) for post in posts]


def inherited_records_for_version(version: TreeVersion) -> List[PostRecord]:
    records: List[PostRecord] = []

    for batch in _display_batches_for_version(version):
        records.extend(_records_from_batch(batch))

    return records


def mark_old_unified_batches_superseded(version: TreeVersion) -> None:
    old_unified_batches = UploadBatch.objects.filter(
        tree_version=version,
        column_map__is_unified_tree_batch=True,
    )

    for batch in old_unified_batches:
        batch.status = 'superseded'
        column_map = batch.column_map or {}
        column_map['superseded'] = True
        batch.column_map = column_map
        batch.save(update_fields=['status', 'column_map'])


@transaction.atomic
def process_records_into_unified_version(
    new_records: List[PostRecord],
    filename: str,
    source_type: str,
    column_map: Dict[str, Any] | None,
    tree_version: TreeVersion,
) -> UploadBatch:
    inherited_batches = _display_batches_for_version(tree_version)
    inherited_batch_ids = [batch.id for batch in inherited_batches]
    inherited_records = inherited_records_for_version(tree_version)

    combined_records = inherited_records + new_records

    if not combined_records:
        raise ValueError('No usable records found for unified tree processing.')

    mark_old_unified_batches_superseded(tree_version)

    unified_column_map = {
        **(column_map or {}),
        'unified_from_existing_tree': True,
        'new_source_type': source_type,
        'new_record_count_before_dedupe': len(new_records),
        'inherited_record_count_before_dedupe': len(inherited_records),
    }

    return _process_records(
        combined_records,
        filename=f'unified-{filename}',
        source_type='unified_tree',
        column_map=unified_column_map,
        tree_version=tree_version,
        merge_with_existing=True,
        is_unified_tree_batch=True,
        inherited_batch_ids=inherited_batch_ids,
    )


def process_csv(
    file_obj,
    tree_version_id: int | None = None,
    merge_with_existing: bool = False,
) -> UploadBatch:
    raw = file_obj.read().decode('utf-8-sig')
    dialect = csv.Sniffer().sniff(raw[:2048]) if raw.strip() else csv.excel
    df = pd.read_csv(io.StringIO(raw), dialect=dialect)

    records, column_map = records_from_dataframe(df, source_type='csv')
    tree_version = TreeVersion.objects.get(id=tree_version_id) if tree_version_id else None
    filename = getattr(file_obj, 'name', 'community-upload.csv')

    if tree_version and merge_with_existing:
        return process_records_into_unified_version(
            new_records=records,
            filename=filename,
            source_type='csv',
            column_map=column_map,
            tree_version=tree_version,
        )

    return _process_records(
        records,
        filename,
        'csv',
        column_map,
        tree_version=tree_version,
        merge_with_existing=merge_with_existing,
    )


def process_pasted_text(
    raw_text: str,
    tree_version_id: int | None = None,
    merge_with_existing: bool = False,
) -> UploadBatch:
    records = parse_pasted_text(raw_text)
    tree_version = TreeVersion.objects.get(id=tree_version_id) if tree_version_id else None

    if tree_version and merge_with_existing:
        return process_records_into_unified_version(
            new_records=records,
            filename='pasted-feedback',
            source_type='pasted_text',
            column_map={'input_mode': 'paste'},
            tree_version=tree_version,
        )

    return _process_records(
        records,
        'pasted-feedback',
        'pasted_text',
        {'input_mode': 'paste'},
        tree_version=tree_version,
        merge_with_existing=merge_with_existing,
    )


def process_sample_data(
    tree_version_id: int | None = None,
    merge_with_existing: bool = False,
) -> UploadBatch:
    sample_path = Path(__file__).resolve().parents[2] / 'sample_data' / 'community_posts.csv'

    with sample_path.open('rb') as file_handle:
        class NamedBytes:
            name = 'sample-community-posts.csv'

            def read(self):
                return file_handle.read()

        return process_csv(
            NamedBytes(),
            tree_version_id=tree_version_id,
            merge_with_existing=merge_with_existing,
        )


def semantic_search(batch_id: int, query: str, limit: int = 10) -> List[Dict[str, Any]]:
    posts = list(
        CommunityPost.objects
        .filter(batch_id=batch_id)
        .exclude(embedding=[])
    )

    if not posts:
        return []

    query_vec = embed_texts([clean_text(query) or query])[0].reshape(1, -1)
    matrix = np.array([post.embedding for post in posts], dtype=float)
    scores = cosine_similarity(query_vec, matrix)[0]
    ranked_idx = scores.argsort()[::-1][:limit]

    results = []

    for idx in ranked_idx:
        post = posts[idx]
        results.append({
            'id': post.id,
            'score': round(float(scores[idx]), 4),
            'text': post.text,
            'channel': post.channel,
            'post_url': post.post_url,
            'report_count': post.report_count,
            'moderation_status': post.moderation_status,
            'cluster_label': post.cluster_label,
        })

    return results


def _cluster_centroid(cluster: IssueCluster) -> np.ndarray | None:
    posts = list(
        CommunityPost.objects
        .filter(batch=cluster.batch, cluster_label=cluster.label)
        .exclude(embedding=[])
    )

    vectors = [post.embedding for post in posts if post.embedding]

    if not vectors:
        return None

    matrix = np.array(vectors, dtype=float)
    centroid = matrix.mean(axis=0)
    norm = np.linalg.norm(centroid)

    return centroid / norm if norm else centroid


def _relationship_type(score: float) -> str:
    if score >= 0.72:
        return 'likely_upstream'
    if score >= 0.52:
        return 'contributes_to'
    return 'related_to'


def _relationship_reason(parent: IssueCluster, child: IssueCluster, score: float) -> str:
    relation = _relationship_type(score).replace('_', ' ')

    return (
        f'“{parent.theme}” is a higher-impact issue with similar evidence to '
        f'“{child.theme}”. Treat it as {relation}; investigating it first may '
        f'reduce or clarify the child issue.'
    )


def rebuild_issue_tree(
    batch_id: int,
    remove_completed: bool = False,
    keep_legacy: bool = True,
) -> Dict[str, Any]:
    batch = UploadBatch.objects.get(id=batch_id)
    clusters = list(
        IssueCluster.objects
        .filter(batch=batch)
        .order_by('-priority_score', '-post_count', 'id')
    )

    if keep_legacy:
        for cluster in clusters:
            if cluster.status == IssueCluster.STATUS_COMPLETED:
                cluster.status = IssueCluster.STATUS_LEGACY
                cluster.save(update_fields=['status'])

    visible = []

    for cluster in clusters:
        if remove_completed and cluster.status in {
            IssueCluster.STATUS_COMPLETED,
            IssueCluster.STATUS_LEGACY,
        }:
            cluster.parent_cluster = None
            cluster.tree_depth = 0
            cluster.tree_order = 0
            cluster.save(update_fields=['parent_cluster', 'tree_depth', 'tree_order'])
            continue

        visible.append(cluster)

    if not visible:
        return issue_tree_payload(batch_id, hide_completed=remove_completed)

    centroids = {
        cluster.id: _cluster_centroid(cluster)
        for cluster in visible
    }

    root = visible[0]
    root.parent_cluster = None
    root.relationship_type = 'root_highest_impact'
    root.relationship_score = 1
    root.relationship_reason = 'Highest-impact visible issue in this batch.'
    root.tree_depth = 0
    root.tree_order = 0
    root.save(update_fields=[
        'parent_cluster',
        'relationship_type',
        'relationship_score',
        'relationship_reason',
        'tree_depth',
        'tree_order',
    ])

    placed = [root]

    for order, cluster in enumerate(visible[1:], start=1):
        child_vec = centroids.get(cluster.id)
        best_parent = root
        best_score = -1.0

        for candidate in placed:
            parent_vec = centroids.get(candidate.id)

            if child_vec is None or parent_vec is None:
                score = 0.0
            else:
                score = float(np.dot(child_vec, parent_vec))

            child_channels = set(
                CommunityPost.objects
                .filter(batch=batch, cluster_label=cluster.label)
                .values_list('channel', flat=True)
            )
            parent_channels = set(
                CommunityPost.objects
                .filter(batch=batch, cluster_label=candidate.label)
                .values_list('channel', flat=True)
            )

            if child_channels and parent_channels and child_channels.intersection(parent_channels):
                score += 0.05

            if score > best_score:
                best_score = score
                best_parent = candidate

        if best_score < 0.34:
            best_parent = root
            best_score = max(best_score, 0.0)

        cluster.parent_cluster = best_parent
        cluster.relationship_type = _relationship_type(best_score)
        cluster.relationship_score = round(float(best_score), 3)
        cluster.relationship_reason = _relationship_reason(best_parent, cluster, best_score)
        cluster.tree_depth = min((best_parent.tree_depth or 0) + 1, 5)
        cluster.tree_order = order
        cluster.save(update_fields=[
            'parent_cluster',
            'relationship_type',
            'relationship_score',
            'relationship_reason',
            'tree_depth',
            'tree_order',
        ])

        placed.append(cluster)

    return issue_tree_payload(batch_id, hide_completed=remove_completed)


def issue_tree_payload(batch_id: int, hide_completed: bool = False) -> Dict[str, Any]:
    batch = UploadBatch.objects.get(id=batch_id)
    clusters = list(
        IssueCluster.objects
        .filter(batch=batch)
        .order_by('tree_order', '-priority_score')
    )

    if hide_completed:
        clusters = [
            cluster
            for cluster in clusters
            if cluster.status not in {
                IssueCluster.STATUS_COMPLETED,
                IssueCluster.STATUS_LEGACY,
            }
        ]

    nodes = []
    edges = []
    visible_ids = {cluster.id for cluster in clusters}

    for cluster in clusters:
        parent_id = (
            cluster.parent_cluster_id
            if cluster.parent_cluster_id in visible_ids
            else None
        )

        nodes.append({
            'id': cluster.id,
            'label': cluster.label,
            'theme': cluster.theme,
            'category': cluster.category,
            'severity': cluster.severity,
            'impact_score': round(cluster.priority_score, 1),
            'priority_score': round(cluster.priority_score, 1),
            'status': cluster.status,
            'status_source': getattr(cluster, 'status_source', IssueCluster.STATUS_SOURCE_MANUAL),
            'status_confidence': round(float(getattr(cluster, 'status_confidence', 1.0) or 0), 3),
            'status_source_cluster': cluster.status_source_cluster_id,
            'status_reason': getattr(cluster, 'status_reason', ''),
            'progress_note': cluster.progress_note,
            'assigned_to': cluster.assigned_to_id,
            'assigned_to_username': cluster.assigned_to.username if cluster.assigned_to else '',
            'post_count': cluster.post_count,
            'examples': cluster.examples,
            'suggested_action': cluster.suggested_action,
            'parent_id': parent_id,
            'relationship_type': cluster.relationship_type,
            'relationship_score': cluster.relationship_score,
            'relationship_reason': cluster.relationship_reason,
            'tree_depth': cluster.tree_depth,
            'tree_order': cluster.tree_order,
        })

        if parent_id:
            edges.append({
                'id': f'{parent_id}-{cluster.id}',
                'source': parent_id,
                'target': cluster.id,
                'relationship_type': cluster.relationship_type,
                'relationship_score': cluster.relationship_score,
                'relationship_reason': cluster.relationship_reason,
            })

    return {
        'batch_id': batch.id,
        'nodes': nodes,
        'edges': edges,
    }


def update_cluster_status(
    cluster_id: int,
    status_value: str,
    progress_note: str = '',
) -> IssueCluster:
    cluster = IssueCluster.objects.get(id=cluster_id)

    allowed = {choice[0] for choice in IssueCluster.STATUS_CHOICES}

    if status_value not in allowed:
        raise ValueError(f'Status must be one of: {", ".join(sorted(allowed))}.')

    cluster.status = status_value
    cluster.status_source = IssueCluster.STATUS_SOURCE_MANUAL
    cluster.status_confidence = 1.0
    cluster.status_source_cluster = None
    cluster.status_reason = ''

    if progress_note is not None:
        cluster.progress_note = progress_note

    if status_value in {
        IssueCluster.STATUS_COMPLETED,
        IssueCluster.STATUS_PARTIALLY_RESOLVED,
        IssueCluster.STATUS_NOT_AFFECTED,
        IssueCluster.STATUS_WONT_FIX,
        IssueCluster.STATUS_LEGACY,
    } and not cluster.completed_at:
        cluster.completed_at = timezone.now()

    if status_value in {
        IssueCluster.STATUS_UNTOUCHED,
        IssueCluster.STATUS_NEEDS_REVIEW,
        IssueCluster.STATUS_CONFIRMED,
        IssueCluster.STATUS_PLANNED,
        IssueCluster.STATUS_IN_PROGRESS,
        IssueCluster.STATUS_BLOCKED,
    }:
        cluster.completed_at = None

    cluster.save()

    return cluster


def get_default_workspace() -> Workspace:
    workspace, _ = Workspace.objects.get_or_create(name='Default workspace')
    return workspace


def tree_version_payload(version_id: int, hide_completed: bool = False) -> Dict[str, Any]:
    version = TreeVersion.objects.select_related('tree', 'parent_version').get(id=version_id)
    batches = _display_batches_for_version(version)

    # Important fix:
    # A newly created branch may have no direct batches yet,
    # but it has a snapshot copied from the parent version.
    # Show that snapshot so the existing tree is visible before adding new feedback.
    if not batches and version.snapshot:
        snapshot = dict(version.snapshot)

        snapshot['tree'] = {
            'id': version.tree.id,
            'name': version.tree.name,
        }

        snapshot['version'] = {
            'id': version.id,
            'name': version.name,
            'branch_name': version.branch_name,
            'status': version.status,
            'parent_version_id': version.parent_version_id,
            'created_by_name': version.created_by_name,
            'notes': version.notes,
        }

        for node in snapshot.get('nodes', []):
            node['version_id'] = version.id
            node['source_version_id'] = node.get('source_version_id') or version.parent_version_id
            node['is_inherited'] = True

        for edge in snapshot.get('edges', []):
            edge['version_id'] = version.id
            edge['source_version_id'] = edge.get('source_version_id') or version.parent_version_id

        for batch in snapshot.get('batches', []):
            batch['is_inherited'] = True

        return snapshot

    nodes = []
    edges = []

    for batch in batches:
        payload = issue_tree_payload(batch.id, hide_completed=hide_completed)

        for node in payload['nodes']:
            node['batch_id'] = batch.id
            node['version_id'] = version.id
            node['source_version_id'] = batch.tree_version_id
            node['is_inherited'] = batch.tree_version_id != version.id
            nodes.append(node)

        for edge in payload['edges']:
            edge['batch_id'] = batch.id
            edge['version_id'] = version.id
            edge['source_version_id'] = batch.tree_version_id
            edge['source_batch_id'] = batch.id
            edge['target_batch_id'] = batch.id
            edge['is_inherited'] = batch.tree_version_id != version.id
            edges.append(edge)

    return {
        'tree': {
            'id': version.tree.id,
            'name': version.tree.name,
        },
        'version': {
            'id': version.id,
            'name': version.name,
            'branch_name': version.branch_name,
            'status': version.status,
            'parent_version_id': version.parent_version_id,
            'created_by_name': version.created_by_name,
            'notes': version.notes,
        },
        'nodes': nodes,
        'edges': edges,
        'batches': [
            {
                'id': batch.id,
                'filename': batch.filename,
                'created_at': batch.created_at.isoformat() if batch.created_at else None,
                'total_posts': batch.total_posts,
                'status': batch.status,
                'source_version_id': batch.tree_version_id,
                'is_inherited': batch.tree_version_id != version.id,
                'is_unified_tree_batch': bool(
                    (batch.column_map or {}).get('is_unified_tree_batch')
                ),
                'inherited_batch_ids': (
                    batch.column_map or {}
                ).get('inherited_batch_ids', []),
            }
            for batch in batches
        ],
    }

@transaction.atomic
def create_pattern_tree(
    name: str,
    description: str = '',
    created_by_name: str = '',
    version_name: str = 'Initial version',
    workspace: Workspace | None = None,
    main_space: MainSpace | None = None,
    is_public: bool = True,
) -> TreeVersion:
    workspace = workspace or get_default_workspace()

    tree = PatternTree.objects.create(
        workspace=workspace,
        main_space=main_space,
        name=name.strip() or 'Untitled tree',
        description=description,
        created_by_name=created_by_name,
        is_public=is_public,
    )

    version = TreeVersion.objects.create(
        tree=tree,
        name=version_name.strip() or 'Initial version',
        branch_name='main',
        created_by_name=created_by_name,
        status=TreeVersion.STATUS_DRAFT,
    )

    tree.main_version = version
    tree.save(update_fields=['main_version'])

    return version


@transaction.atomic
def create_branch_version(
    source_version_id: int,
    branch_name: str,
    created_by_name: str = '',
    notes: str = '',
) -> TreeVersion:
    source = TreeVersion.objects.select_related('tree', 'tree__main_space').get(id=source_version_id)

    new_version = TreeVersion.objects.create(
        tree=source.tree,
        name=f'{branch_name.strip() or "Branch"} from {source.name}',
        branch_name=branch_name.strip() or 'branch',
        parent_version=source,
        created_by_name=created_by_name,
        status=TreeVersion.STATUS_DRAFT,
        notes=notes,
        snapshot=tree_version_payload(source.id),
    )

    return new_version


def _clone_batches_for_workspace_version(source_version: TreeVersion, target_version: TreeVersion) -> int:
    """Create real editable copies of the source version's batches/nodes.

    A workspace copy must not point its nodes at the public main batch IDs,
    otherwise the status endpoint correctly treats those nodes as public-main
    nodes and blocks editing. This clone gives the workspace version its own
    UploadBatch, CommunityPost, and IssueCluster rows while preserving enough
    lineage metadata for related-node sync.
    """
    source_batches = list(
        UploadBatch.objects
        .filter(tree_version=source_version)
        .prefetch_related('posts', 'clusters')
        .order_by('id')
    )

    copied_batches = 0

    for source_batch in source_batches:
        column_map = deepcopy(source_batch.column_map or {})
        inherited_batch_ids = set(column_map.get('inherited_batch_ids') or [])
        inherited_batch_ids.add(source_batch.id)
        column_map.update({
            'copied_from_batch_id': source_batch.id,
            'copied_from_tree_version_id': source_version.id,
            'inherited_batch_ids': sorted(inherited_batch_ids),
        })

        new_batch = UploadBatch.objects.create(
            filename=f'workspace-copy-of-{source_batch.filename}',
            total_posts=source_batch.total_posts,
            status=source_batch.status,
            column_map=column_map,
            tree_version=target_version,
        )
        copied_batches += 1

        for post in source_batch.posts.all().order_by('id'):
            CommunityPost.objects.create(
                batch=new_batch,
                text=post.text,
                cleaned_text=post.cleaned_text,
                created_at_raw=post.created_at_raw,
                user_id=post.user_id,
                channel=post.channel,
                post_url=post.post_url,
                report_count=post.report_count,
                upvotes=post.upvotes,
                moderation_status=post.moderation_status,
                embedding=deepcopy(post.embedding or []),
                cluster_label=post.cluster_label,
            )

        cluster_map = {}
        source_clusters = list(source_batch.clusters.all().order_by('id'))

        for cluster in source_clusters:
            new_cluster = IssueCluster.objects.create(
                batch=new_batch,
                source_version=target_version,
                label=cluster.label,
                theme=cluster.theme,
                category=cluster.category,
                severity=cluster.severity,
                priority_score=cluster.priority_score,
                suggested_action=cluster.suggested_action,
                post_count=cluster.post_count,
                examples=deepcopy(cluster.examples or []),
                status=cluster.status,
                progress_note=cluster.progress_note,
                status_source=IssueCluster.STATUS_SOURCE_SYSTEM,
                status_confidence=cluster.status_confidence,
                status_reason=(
                    f'Copied from main node #{cluster.id}. Change this status directly '
                    'to make it a manual workspace decision.'
                ),
                assigned_to=cluster.assigned_to,
                completed_at=cluster.completed_at,
                relationship_type=cluster.relationship_type,
                relationship_score=cluster.relationship_score,
                relationship_reason=cluster.relationship_reason,
                tree_depth=cluster.tree_depth,
                tree_order=cluster.tree_order,
            )
            cluster_map[cluster.id] = new_cluster

        for cluster in source_clusters:
            new_cluster = cluster_map.get(cluster.id)
            if not new_cluster:
                continue

            update_fields = []

            if cluster.parent_cluster_id and cluster.parent_cluster_id in cluster_map:
                new_cluster.parent_cluster = cluster_map[cluster.parent_cluster_id]
                update_fields.append('parent_cluster')

            if cluster.status_source_cluster_id and cluster.status_source_cluster_id in cluster_map:
                new_cluster.status_source_cluster = cluster_map[cluster.status_source_cluster_id]
                update_fields.append('status_source_cluster')

            if update_fields:
                new_cluster.save(update_fields=update_fields)

        if hasattr(source_batch, 'weekly_report'):
            WeeklyReport.objects.create(
                batch=new_batch,
                summary=deepcopy(source_batch.weekly_report.summary or {}),
            )

    return copied_batches

def create_workspace_copy_from_main(
    source_version_id: int,
    workspace: Workspace,
    branch_name: str = 'workspace-copy',
    created_by_name: str = '',
    notes: str = '',
) -> TreeVersion:
    """Copy a public main version into a user's workspace as real editable data."""
    source = TreeVersion.objects.select_related('tree', 'tree__main_space').get(id=source_version_id)

    if not source.tree.is_public or source.tree.main_version_id != source.id:
        raise ValueError('Only a public main version can be copied into a workspace.')

    with transaction.atomic():
        copied_tree = PatternTree.objects.create(
            workspace=workspace,
            main_space=source.tree.main_space,
            name=f'{source.tree.name} — workspace copy',
            description=source.tree.description,
            created_by_name=created_by_name,
            is_public=False,
        )

        version = TreeVersion.objects.create(
            tree=copied_tree,
            name=f'{branch_name.strip() or "Workspace copy"} from {source.name}',
            branch_name=branch_name.strip() or 'workspace-copy',
            parent_version=source,
            created_by_name=created_by_name,
            status=TreeVersion.STATUS_DRAFT,
            notes=notes or f'Workspace copy of public main tree: {source.tree.name}',
            snapshot={},
        )

        copied_batch_count = _clone_batches_for_workspace_version(source, version)

        if copied_batch_count == 0:
            # Fallback for older/main versions that only have a snapshot.
            # This will display, but editing requires importing feedback into the copy.
            version.snapshot = tree_version_payload(source.id)
            version.save(update_fields=['snapshot'])

        copied_tree.main_version = version
        copied_tree.save(update_fields=['main_version', 'updated_at'])

    return version

def save_tree_version(
    version_id: int,
    name: str | None = None,
    notes: str = '',
) -> TreeVersion:
    version = TreeVersion.objects.select_related('tree').get(id=version_id)

    if name:
        version.name = name.strip()

    version.notes = notes
    version.status = TreeVersion.STATUS_SAVED
    version.saved_at = timezone.now()
    version.snapshot = tree_version_payload(version.id)
    version.save()

    return version



def _cluster_match_key(cluster: IssueCluster) -> tuple[str, str]:
    return (
        (cluster.theme or '').strip().lower(),
        (cluster.category or '').strip().lower(),
    )


def _cluster_status_changed(cluster: IssueCluster) -> bool:
    return bool(
        cluster.status != IssueCluster.STATUS_UNTOUCHED
        or (cluster.progress_note or '').strip()
        or cluster.completed_at
    )


def _cluster_text_signature(cluster: IssueCluster) -> str:
    examples = ' '.join(str(example) for example in (cluster.examples or [])[:5])
    return clean_text(
        f'{cluster.theme} {cluster.category} {cluster.severity} '
        f'{cluster.suggested_action} {examples}'
    )


def _cluster_post_texts(cluster: IssueCluster, limit: int = 80) -> List[str]:
    """Return deterministic cleaned evidence texts for a cluster.

    This is important for merged/unified trees. A unified tree created from two
    inputs may generate a different theme/category from the two separate input
    trees, but the underlying posts are often the same or very close. Matching
    against the evidence text lets the sync find those hidden relationships.
    """
    posts = (
        CommunityPost.objects
        .filter(batch=cluster.batch, cluster_label=cluster.label)
        .order_by('id')[:limit]
    )
    return [post.cleaned_text or clean_text(post.text) for post in posts]


def _token_set(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r'[a-z0-9]{3,}', clean_text(text))
        if token not in ENGLISH_STOP_WORDS
    }


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / max(1, len(a | b))


def _cluster_post_fingerprints(cluster: IssueCluster, limit: int = 160) -> set[str]:
    """Return stable post fingerprints for exact/subset evidence matching."""
    return {
        (text or '')[:260]
        for text in _cluster_post_texts(cluster, limit=limit)
        if text
    }


def _evidence_overlap_details(source: IssueCluster, target: IssueCluster) -> Dict[str, float | str]:
    """Measure exact and fuzzy evidence overlap between two clusters.

    This is stronger than a simple similarity score because it detects subset
    relationships:
    - source_subset_of_target: a smaller workspace/private node is part of a
      larger main node that contains all/many of the same posts.
    - target_subset_of_source: the pushed source node is broader than the target.
    - equivalent_evidence: both nodes contain nearly the same evidence.

    The subset direction is important for status propagation. If a small source
    node is completed, a larger main node should usually become partially
    resolved rather than fully completed.
    """
    source_posts = _cluster_post_texts(source)
    target_posts = _cluster_post_texts(target)

    if not source_posts or not target_posts:
        return {
            'score': 0.0,
            'exact_overlap': 0.0,
            'token_overlap': 0.0,
            'source_coverage': 0.0,
            'target_coverage': 0.0,
            'common_posts': 0.0,
            'source_posts': float(len(source_posts)),
            'target_posts': float(len(target_posts)),
            'match_kind': 'semantic_related',
        }

    source_exact = {text[:260] for text in source_posts if text}
    target_exact = {text[:260] for text in target_posts if text}
    common = source_exact & target_exact

    common_count = len(common)
    source_count = max(1, len(source_exact))
    target_count = max(1, len(target_exact))

    # Existing behaviour: high when the smaller evidence set is contained in the larger one.
    exact_overlap = common_count / max(1, min(source_count, target_count))

    # New behaviour: direction-aware coverage.
    source_coverage = common_count / source_count
    target_coverage = common_count / target_count

    source_text = ' '.join(source_posts[:40])
    target_text = ' '.join(target_posts[:40])
    token_overlap = _jaccard(_token_set(source_text), _token_set(target_text))

    # Coverage is what catches "private tree has some of the main posts".
    directional_coverage = max(source_coverage, target_coverage)
    score = min(
        1.0,
        (exact_overlap * 0.38)
        + (directional_coverage * 0.42)
        + (token_overlap * 0.20),
    )

    match_kind = 'semantic_related'

    if common_count:
        almost_same_size = abs(source_count - target_count) <= max(1, int(max(source_count, target_count) * 0.18))

        if source_coverage >= 0.86 and target_coverage >= 0.86:
            match_kind = 'equivalent_evidence'
        elif source_coverage >= 0.72 and source_count <= target_count and not almost_same_size:
            match_kind = 'source_subset_of_target'
        elif target_coverage >= 0.72 and target_count <= source_count and not almost_same_size:
            match_kind = 'target_subset_of_source'
        elif exact_overlap >= 0.55:
            match_kind = 'shared_evidence'

    return {
        'score': round(float(score), 3),
        'exact_overlap': round(float(exact_overlap), 3),
        'token_overlap': round(float(token_overlap), 3),
        'source_coverage': round(float(source_coverage), 3),
        'target_coverage': round(float(target_coverage), 3),
        'common_posts': float(common_count),
        'source_posts': float(source_count),
        'target_posts': float(target_count),
        'match_kind': match_kind,
    }


def _post_overlap_score(source: IssueCluster, target: IssueCluster) -> float:
    """Score hidden evidence overlap between clusters.

    This now includes subset coverage. If a private tree node contains a subset
    of the posts inside a bigger main node, the overlap score becomes strong
    enough for propagation even when generated themes/categories differ.
    """
    return float(_evidence_overlap_details(source, target)['score'])


def _signature_similarity(source: IssueCluster, target: IssueCluster) -> float:
    source_text = _cluster_text_signature(source)
    target_text = _cluster_text_signature(target)

    if not source_text or not target_text:
        return 0.0

    vectors = HashingVectorizer(
        n_features=512,
        alternate_sign=False,
        ngram_range=(1, 2),
        stop_words='english',
    ).transform([source_text, target_text])

    return float(cosine_similarity(vectors[0], vectors[1])[0][0])


def _centroid_similarity(source: IssueCluster, target: IssueCluster) -> float:
    source_vec = _cluster_centroid(source)
    target_vec = _cluster_centroid(target)

    if source_vec is None or target_vec is None:
        return 0.0

    return float(np.dot(source_vec, target_vec))


def _batch_lineage_ids(batch: UploadBatch | None) -> set[int]:
    if not batch:
        return set()

    ids = {batch.id}
    column_map = batch.column_map or {}

    for inherited_id in column_map.get('inherited_batch_ids', []) or []:
        try:
            ids.add(int(inherited_id))
        except Exception:
            continue

    return ids


def _version_ancestor_ids(version: TreeVersion | None) -> set[int]:
    ids = set()
    current = version

    while current:
        ids.add(current.id)
        current = current.parent_version

    return ids


def _lineage_bonus(source: IssueCluster, target: IssueCluster) -> float:
    """Bonus when clusters come from related batches/branches.

    This is what lets a merged tree affect the original separate-input trees and
    lets the separate-input trees affect the merged tree. It uses existing
    metadata, so no model migration is needed.
    """
    source_batch_ids = _batch_lineage_ids(source.batch)
    target_batch_ids = _batch_lineage_ids(target.batch)
    bonus = 0.0

    if source_batch_ids and target_batch_ids and source_batch_ids & target_batch_ids:
        bonus += 0.22

    source_version = getattr(source.batch, 'tree_version', None)
    target_version = getattr(target.batch, 'tree_version', None)

    source_ancestors = _version_ancestor_ids(source_version)
    target_ancestors = _version_ancestor_ids(target_version)

    if source_ancestors and target_ancestors and source_ancestors & target_ancestors:
        bonus += 0.08

    return bonus


def _relationship_bonus(source: IssueCluster, target: IssueCluster) -> float:
    source_parent = _cluster_match_key(source.parent_cluster) if source.parent_cluster else None
    target_parent = _cluster_match_key(target.parent_cluster) if target.parent_cluster else None

    bonus = 0.0

    if source_parent and target_parent and source_parent == target_parent:
        bonus += 0.12

    if source.parent_cluster_id and target.parent_cluster_id:
        parent_similarity = _signature_similarity(source.parent_cluster, target.parent_cluster)
        if parent_similarity >= 0.48:
            bonus += 0.07

    if source.relationship_type and source.relationship_type == target.relationship_type:
        bonus += 0.04

    if source.tree_depth == target.tree_depth:
        bonus += 0.03

    return bonus


def _connected_cluster_ids(cluster: IssueCluster) -> set[int]:
    """Return parent/child node ids directly connected to a cluster.

    These connected nodes do not automatically receive full score; they receive
    a smaller connection bonus through _connection_bonus. This lets status
    propagate to branches/leaves that are genuinely attached to the same issue.
    """
    ids = set()

    if cluster.parent_cluster_id:
        ids.add(cluster.parent_cluster_id)

    child_ids = IssueCluster.objects.filter(parent_cluster=cluster).values_list('id', flat=True)
    ids.update(child_ids)

    return ids


def _connection_bonus(source: IssueCluster, target: IssueCluster) -> float:
    source_connections = _connected_cluster_ids(source)
    target_connections = _connected_cluster_ids(target)

    if target.id in source_connections or source.id in target_connections:
        return 0.16

    if source_connections and target_connections and source_connections & target_connections:
        return 0.08

    return 0.0



def _extract_llm_json(text: str) -> Dict[str, Any]:
    """Extract a JSON object from a local LLM response."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r'\{.*\}', text, flags=re.DOTALL)
        if not match:
            raise
        data = json.loads(match.group(0))

    return data if isinstance(data, dict) else {}


def _cluster_llm_evidence(cluster: IssueCluster) -> Dict[str, Any]:
    """Small deterministic evidence packet for pairwise relationship checks."""
    return {
        'theme': cluster.theme,
        'category': cluster.category,
        'severity': cluster.severity,
        'suggested_action': cluster.suggested_action,
        'post_count': cluster.post_count,
        'examples': [str(example)[:320] for example in (cluster.examples or [])[:5]],
        'cleaned_posts': _cluster_post_texts(cluster, limit=8)[:8],
        'relationship_type': cluster.relationship_type,
        'relationship_reason': cluster.relationship_reason,
    }


def _local_llm_relationship_check(
    source: IssueCluster,
    target: IssueCluster,
    base_details: Dict[str, float | str],
) -> Dict[str, Any]:
    """Use the local LLM as a deterministic second-pass relationship judge.

    This is only used for borderline pairs where deterministic evidence overlap
    or embedding similarity is not strong enough on its own. The result is a
    small score adjustment, not an unrestricted override.
    """
    if getattr(settings, 'INTERPRETER_MODE', 'rules') != 'local_llm':
        return {
            'used': False,
            'relationship': 'not_checked',
            'confidence': 0.0,
            'reason': '',
            'bonus': 0.0,
        }

    try:
        base_url = settings.OLLAMA_BASE_URL.rstrip('/')
        model = settings.OLLAMA_MODEL
    except Exception:
        return {
            'used': False,
            'relationship': 'not_checked',
            'confidence': 0.0,
            'reason': '',
            'bonus': 0.0,
        }

    prompt_payload = {
        'source_node': _cluster_llm_evidence(source),
        'target_node': _cluster_llm_evidence(target),
        'deterministic_scores': base_details,
        'allowed_relationships': [
            'equivalent',
            'source_subset_of_target',
            'target_subset_of_source',
            'related',
            'unrelated',
        ],
    }

    prompt = f"""
You are deciding whether a changed source issue should affect a target issue in an issue tree.

Rules:
- equivalent: both nodes are effectively the same operational problem.
- source_subset_of_target: the source is a narrower part/example of the target's broader problem.
- target_subset_of_source: the target is a narrower part/example of the source's broader problem.
- related: same area or likely connected, but not enough to say subset/equivalent.
- unrelated: do not sync status.

Return JSON only with exactly:
{{
  "relationship": "equivalent | source_subset_of_target | target_subset_of_source | related | unrelated",
  "confidence": 0.0,
  "reason": "short reason under 160 characters"
}}

Evidence:
{deterministic_json(prompt_payload)}
""".strip()

    request_payload = {
        'model': model,
        'messages': [
            {
                'role': 'system',
                'content': 'You are a deterministic issue relationship classifier. Return JSON only.',
            },
            {'role': 'user', 'content': prompt},
        ],
        'stream': False,
        'format': 'json',
        'options': ollama_deterministic_options(),
    }

    try:
        request = urllib.request.Request(
            f'{base_url}/api/chat',
            data=json.dumps(request_payload).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        with urllib.request.urlopen(request, timeout=float(settings.OLLAMA_TIMEOUT_SECONDS)) as response:
            body = json.loads(response.read().decode('utf-8'))
        content = body.get('message', {}).get('content', '{}')
        result = _extract_llm_json(content)
    except (
        urllib.error.URLError,
        TimeoutError,
        json.JSONDecodeError,
        KeyError,
        ValueError,
        TypeError,
        OSError,
    ):
        return {
            'used': False,
            'relationship': 'error',
            'confidence': 0.0,
            'reason': '',
            'bonus': 0.0,
        }

    relationship = str(result.get('relationship') or 'unrelated').strip().lower()
    allowed = {
        'equivalent',
        'source_subset_of_target',
        'target_subset_of_source',
        'related',
        'unrelated',
    }
    if relationship not in allowed:
        relationship = 'unrelated'

    try:
        confidence = max(0.0, min(1.0, float(result.get('confidence', 0))))
    except Exception:
        confidence = 0.0

    reason = str(result.get('reason') or '')[:240]

    if relationship == 'equivalent':
        bonus = 0.26 * confidence
    elif relationship in {'source_subset_of_target', 'target_subset_of_source'}:
        bonus = 0.22 * confidence
    elif relationship == 'related':
        bonus = 0.12 * confidence
    else:
        bonus = -0.08 * max(confidence, 0.5)

    return {
        'used': True,
        'relationship': relationship,
        'confidence': round(confidence, 3),
        'reason': reason,
        'bonus': round(bonus, 3),
    }


def _should_use_llm_relationship_check(
    score: float,
    details: Dict[str, float | str],
) -> bool:
    """Call the local LLM only for borderline semantic matches.

    Strong evidence/subset matches do not need the LLM. Very weak matches also
    do not need it, because that would be slow and noisy. This keeps push-to-main
    reasonably fast while catching different-post-but-related issues.
    """
    if getattr(settings, 'INTERPRETER_MODE', 'rules') != 'local_llm':
        return False

    if str(details.get('match_kind', 'semantic_related')) in {
        'equivalent_evidence',
        'source_subset_of_target',
        'target_subset_of_source',
        'shared_evidence',
    }:
        return False

    evidence_overlap = float(details.get('evidence_overlap', 0) or 0)
    lineage_bonus = float(details.get('lineage_bonus', 0) or 0)
    connection_bonus = float(details.get('connection_bonus', 0) or 0)
    signature = float(details.get('signature', 0) or 0)
    centroid = float(details.get('centroid', 0) or 0)

    if evidence_overlap >= 0.18 or lineage_bonus > 0 or connection_bonus > 0:
        return False

    if 0.38 <= score < 0.62:
        return True

    return signature >= 0.34 and centroid >= 0.34 and score < 0.68

def _status_sync_score(source: IssueCluster, target: IssueCluster) -> tuple[float, Dict[str, float | str]]:
    source_key = _cluster_match_key(source)
    target_key = _cluster_match_key(target)

    exact_key = 1.0 if source_key == target_key else 0.0
    signature = _signature_similarity(source, target)
    centroid = _centroid_similarity(source, target)
    evidence = _evidence_overlap_details(source, target)
    evidence_overlap = float(evidence['score'])
    relationship = _relationship_bonus(source, target)
    lineage = _lineage_bonus(source, target)
    connection = _connection_bonus(source, target)

    match_kind = str(evidence['match_kind'])
    subset_bonus = 0.0

    if match_kind == 'equivalent_evidence':
        subset_bonus = 0.30
    elif match_kind in {'source_subset_of_target', 'target_subset_of_source'}:
        subset_bonus = 0.24
    elif match_kind == 'shared_evidence':
        subset_bonus = 0.12

    if exact_key:
        score = 0.93
        if match_kind == 'equivalent_evidence':
            score = 1.0
    else:
        score = (
            (signature * 0.24)
            + (centroid * 0.18)
            + (evidence_overlap * 0.36)
            + relationship
            + lineage
            + connection
            + subset_bonus
        )

    score = min(1.0, score)

    base_details = {
        'exact_key': exact_key,
        'signature': round(signature, 3),
        'centroid': round(centroid, 3),
        'evidence_overlap': round(evidence_overlap, 3),
        'exact_evidence_overlap': evidence['exact_overlap'],
        'source_coverage': evidence['source_coverage'],
        'target_coverage': evidence['target_coverage'],
        'common_posts': evidence['common_posts'],
        'source_posts': evidence['source_posts'],
        'target_posts': evidence['target_posts'],
        'match_kind': match_kind,
        'relationship_bonus': round(relationship, 3),
        'lineage_bonus': round(lineage, 3),
        'connection_bonus': round(connection, 3),
        'subset_bonus': round(subset_bonus, 3),
        'pre_llm_score': round(score, 3),
    }

    llm_check = _local_llm_relationship_check(source, target, base_details) if _should_use_llm_relationship_check(score, base_details) else {
        'used': False,
        'relationship': 'not_checked',
        'confidence': 0.0,
        'reason': '',
        'bonus': 0.0,
    }

    if llm_check.get('used'):
        llm_relationship = str(llm_check.get('relationship') or 'unrelated')
        llm_bonus = float(llm_check.get('bonus') or 0)
        score = max(0.0, min(1.0, score + llm_bonus))

        if llm_relationship == 'equivalent' and score >= 0.72:
            match_kind = 'llm_equivalent'
            score = max(score, 0.82)
        elif llm_relationship == 'source_subset_of_target' and score >= 0.62:
            match_kind = 'llm_source_subset_of_target'
            score = max(score, 0.70)
        elif llm_relationship == 'target_subset_of_source' and score >= 0.62:
            match_kind = 'llm_target_subset_of_source'
            score = max(score, 0.70)
        elif llm_relationship == 'related' and score >= 0.54:
            match_kind = 'llm_related'
            score = max(score, 0.58)

    # If evidence proves a subset/equivalent relationship, never let weak theme
    # wording alone keep the final score below the propagation threshold.
    if match_kind == 'equivalent_evidence':
        score = max(score, 0.93)
    elif match_kind in {'source_subset_of_target', 'target_subset_of_source'}:
        score = max(score, 0.74)
    elif match_kind == 'shared_evidence':
        score = max(score, 0.62)

    details = {
        'exact_key': exact_key,
        'signature': round(signature, 3),
        'centroid': round(centroid, 3),
        'evidence_overlap': round(evidence_overlap, 3),
        'exact_evidence_overlap': evidence['exact_overlap'],
        'source_coverage': evidence['source_coverage'],
        'target_coverage': evidence['target_coverage'],
        'common_posts': evidence['common_posts'],
        'source_posts': evidence['source_posts'],
        'target_posts': evidence['target_posts'],
        'match_kind': match_kind,
        'relationship_bonus': round(relationship, 3),
        'lineage_bonus': round(lineage, 3),
        'connection_bonus': round(connection, 3),
        'subset_bonus': round(subset_bonus, 3),
        'pre_llm_score': base_details.get('pre_llm_score', round(score, 3)),
        'llm_used': bool(llm_check.get('used')),
        'llm_relationship': str(llm_check.get('relationship') or 'not_checked'),
        'llm_confidence': float(llm_check.get('confidence') or 0),
        'llm_bonus': float(llm_check.get('bonus') or 0),
        'llm_reason': str(llm_check.get('reason') or ''),
        'final_score': round(score, 3),
    }
    return score, details


def _candidate_status_sync_clusters(source_version: TreeVersion) -> List[IssueCluster]:
    """Return every node that should receive status sync updates.

    This intentionally includes:
    - public main tree versions,
    - normal users' private workspace tree versions,
    - saved/draft branches in those workspaces,
    - unified/merged tree batches and the separate batches they were built from.

    It excludes only the exact source version being pushed, so users still cannot
    directly edit other people's trees, but a push-to-main can propagate the
    changed status to all affected copies/related trees.
    """
    candidates: List[IssueCluster] = []
    seen_cluster_ids = set()

    source_tree = getattr(source_version, 'tree', None)
    source_main_space_id = getattr(source_tree, 'main_space_id', None)

    versions = (
        TreeVersion.objects
        .select_related('tree', 'tree__workspace', 'tree__main_space', 'parent_version')
        .exclude(id=source_version.id)
        .order_by('tree_id', '-saved_at', '-created_at')
    )

    # Main spaces are isolation boundaries. A push in one main should update
    # related public/workspace trees inside that same main only, not every
    # unrelated community/project on the server.
    if source_main_space_id:
        versions = versions.filter(tree__main_space_id=source_main_space_id)
    else:
        versions = versions.filter(tree_id=source_version.tree_id)

    for target_version in versions:
        if not target_version.tree_id:
            continue

        for batch in _display_batches_for_version(target_version):
            clusters = (
                IssueCluster.objects
                .filter(batch=batch)
                .select_related(
                    'parent_cluster',
                    'batch',
                    'batch__tree_version',
                    'batch__tree_version__parent_version',
                )
            )
            for cluster in clusters:
                if cluster.id in seen_cluster_ids:
                    continue
                seen_cluster_ids.add(cluster.id)
                candidates.append(cluster)

    return candidates


STATUS_PROPAGATION_LADDER = [
    IssueCluster.STATUS_UNTOUCHED,
    IssueCluster.STATUS_NEEDS_REVIEW,
    IssueCluster.STATUS_CONFIRMED,
    IssueCluster.STATUS_PLANNED,
    IssueCluster.STATUS_IN_PROGRESS,
    IssueCluster.STATUS_PARTIALLY_RESOLVED,
    IssueCluster.STATUS_COMPLETED,
]

TERMINAL_STATUSES = {
    IssueCluster.STATUS_COMPLETED,
    IssueCluster.STATUS_WONT_FIX,
    IssueCluster.STATUS_NOT_AFFECTED,
    IssueCluster.STATUS_LEGACY,
}


def _status_rank(status_value: str) -> int:
    try:
        return STATUS_PROPAGATION_LADDER.index(status_value)
    except ValueError:
        if status_value in TERMINAL_STATUSES:
            return len(STATUS_PROPAGATION_LADDER) - 1
        if status_value == IssueCluster.STATUS_BLOCKED:
            return 3
        return 0


def _status_at_rank(rank: int) -> str:
    bounded = max(0, min(rank, len(STATUS_PROPAGATION_LADDER) - 1))
    return STATUS_PROPAGATION_LADDER[bounded]


def _weaken_status(status_value: str, steps: int = 1) -> str:
    """Move a status down the progression ladder by a number of steps."""
    if status_value == IssueCluster.STATUS_BLOCKED:
        return IssueCluster.STATUS_NEEDS_REVIEW

    if status_value in {
        IssueCluster.STATUS_WONT_FIX,
        IssueCluster.STATUS_NOT_AFFECTED,
        IssueCluster.STATUS_LEGACY,
    }:
        return IssueCluster.STATUS_NEEDS_REVIEW

    return _status_at_rank(_status_rank(status_value) - max(0, steps))


def _propagated_status_for_score(
    source_status: str,
    score: float,
    match_kind: str = 'semantic_related',
) -> str | None:
    """Return the status a related node should inherit.

    Equal/near-equal nodes inherit the same status. Less similar nodes inherit a
    lower/weaker status so the UI communicates uncertainty instead of pretending
    the related issue is fully fixed.

    Subset rule:
    - source_subset_of_target means a smaller pushed node is part of a bigger
      target/main node, so the larger node receives a weaker status.
    - target_subset_of_source means the pushed source is broader than the target,
      so a strong match can safely apply the same status to the smaller target.
    """
    if source_status == IssueCluster.STATUS_UNTOUCHED:
        return None

    if source_status in {
        IssueCluster.STATUS_WONT_FIX,
        IssueCluster.STATUS_NOT_AFFECTED,
        IssueCluster.STATUS_LEGACY,
    }:
        if match_kind in {'source_subset_of_target', 'llm_source_subset_of_target'}:
            return IssueCluster.STATUS_NEEDS_REVIEW
        return source_status if score >= 0.93 else IssueCluster.STATUS_NEEDS_REVIEW

    if source_status == IssueCluster.STATUS_BLOCKED:
        if match_kind in {'source_subset_of_target', 'llm_source_subset_of_target'}:
            return IssueCluster.STATUS_NEEDS_REVIEW
        if score >= 0.93:
            return IssueCluster.STATUS_BLOCKED
        if score >= 0.74:
            return IssueCluster.STATUS_NEEDS_REVIEW
        return None

    source_rank = _status_rank(source_status)

    if match_kind in {'equivalent_evidence', 'llm_equivalent'}:
        target_rank = source_rank if score >= 0.82 else source_rank - 1
    elif match_kind in {'source_subset_of_target', 'llm_source_subset_of_target'}:
        # A completed subset usually means the larger main issue is partially
        # resolved, not fully completed.
        if source_status == IssueCluster.STATUS_COMPLETED:
            return IssueCluster.STATUS_PARTIALLY_RESOLVED
        if source_status == IssueCluster.STATUS_PARTIALLY_RESOLVED:
            return IssueCluster.STATUS_IN_PROGRESS
        target_rank = source_rank - 1
    elif match_kind in {'target_subset_of_source', 'llm_target_subset_of_source'}:
        target_rank = source_rank if score >= 0.70 else source_rank - 1
    elif match_kind == 'shared_evidence':
        target_rank = source_rank - (0 if score >= 0.90 else 1)
    elif match_kind == 'llm_related':
        target_rank = source_rank - 2 if score >= 0.62 else source_rank - 3
    elif score >= 0.93:
        target_rank = source_rank
    elif score >= 0.82:
        target_rank = source_rank - 1
    elif score >= 0.68:
        target_rank = source_rank - 2
    elif score >= 0.55:
        return IssueCluster.STATUS_NEEDS_REVIEW
    else:
        return None

    return _status_at_rank(target_rank)


def _should_overwrite_with_propagated_status(target: IssueCluster, new_status: str, confidence: float) -> bool:
    """Manual user decisions win over propagated/system status.

    A propagated sync can update untouched/default nodes, or nodes that are
    already propagated. Once a user directly changes the node, update_cluster_status
    marks it as manual and future propagation will not silently override it.
    """
    if target.status_source == IssueCluster.STATUS_SOURCE_PROPAGATED:
        return confidence >= float(target.status_confidence or 0)

    if target.status == IssueCluster.STATUS_UNTOUCHED and not (target.progress_note or '').strip():
        return True

    return False


def _completed_at_for_status(status_value: str):
    if status_value in {
        IssueCluster.STATUS_COMPLETED,
        IssueCluster.STATUS_PARTIALLY_RESOLVED,
        IssueCluster.STATUS_NOT_AFFECTED,
        IssueCluster.STATUS_WONT_FIX,
        IssueCluster.STATUS_LEGACY,
    }:
        return timezone.now()
    return None


def _apply_cluster_status(
    source: IssueCluster,
    target: IssueCluster,
    reason: str,
    score: float,
    details: Dict[str, float | str] | None = None,
) -> bool:
    details = details or {}
    match_kind = str(details.get('match_kind', 'semantic_related'))
    propagated_status = _propagated_status_for_score(source.status, score, match_kind=match_kind)
    if not propagated_status:
        return False

    confidence = max(0.0, min(1.0, float(score)))

    if not _should_overwrite_with_propagated_status(target, propagated_status, confidence):
        return False

    fields = []

    if target.status != propagated_status:
        target.status = propagated_status
        fields.append('status')

    if target.status_source != IssueCluster.STATUS_SOURCE_PROPAGATED:
        target.status_source = IssueCluster.STATUS_SOURCE_PROPAGATED
        fields.append('status_source')

    if round(float(target.status_confidence or 0), 3) != round(confidence, 3):
        target.status_confidence = confidence
        fields.append('status_confidence')

    if target.status_source_cluster_id != source.id:
        target.status_source_cluster = source
        fields.append('status_source_cluster')

    readable_match = match_kind.replace('_', ' ')
    status_note = (
        f'Auto-propagated from related node “{source.theme}”. '
        f'Match type: {readable_match}. '
        f'Source status: {source.status}; related status applied: {propagated_status}; '
        f'match confidence: {confidence:.2f}.'
    )
    if source.progress_note:
        status_note = f'{status_note} Source note: {source.progress_note}'
    status_note = status_note[:5000]

    if target.progress_note != status_note:
        target.progress_note = status_note
        fields.append('progress_note')

    completed_at = _completed_at_for_status(propagated_status)
    if target.completed_at != completed_at:
        target.completed_at = completed_at
        fields.append('completed_at')

    if target.status_reason != reason:
        target.status_reason = reason
        fields.append('status_reason')

    if target.relationship_reason != reason:
        target.relationship_reason = reason
        fields.append('relationship_reason')

    if fields:
        target.save(update_fields=fields)
        return True

    return False


def _sync_changed_statuses_into_all_related_trees(version: TreeVersion) -> int:
    """Sync changed node statuses into affected nodes across all trees.

    Direction after this update:
    - workspace branch/main push -> public main trees and all workspace trees,
    - public/admin main push -> all workspace/private trees and other public mains,
    - unified/merged tree node -> original separate-input nodes,
    - separate-input node -> unified/merged tree nodes.

    Users still cannot directly edit other users' trees through the API. This is
    system-level propagation that happens only when a version is pushed to main.

    Matching strategy:
    1. Same theme/category key, when available.
    2. Semantic similarity over theme/category/action/examples.
    3. Centroid similarity over the underlying post embeddings.
    4. Evidence/post overlap, which catches merged trees with different node names.
    5. Batch/version lineage metadata from unified trees.
    6. Parent/child connection bonuses for directly connected issues.

    Unlike the previous version, this updates every sufficiently related target,
    not only one best target. That is what allows a combined node to affect both
    of the separate nodes it was created from.
    """
    changed_sources = []
    seen_source_ids = set()

    for batch in _display_batches_for_version(version):
        source_clusters = (
            IssueCluster.objects
            .filter(batch=batch)
            .select_related(
                'parent_cluster',
                'batch',
                'batch__tree_version',
                'batch__tree_version__parent_version',
            )
        )
        for cluster in source_clusters:
            if cluster.id in seen_source_ids:
                continue
            if _cluster_status_changed(cluster):
                changed_sources.append(cluster)
                seen_source_ids.add(cluster.id)

    if not changed_sources:
        return 0

    candidates = _candidate_status_sync_clusters(version)
    changed_count = 0
    touched_pairs = set()

    # Higher threshold for loose matching, lower threshold when there is direct
    # evidence overlap or lineage from a unified/merged batch.
    DEFAULT_THRESHOLD = 0.58
    LINEAGE_THRESHOLD = 0.48
    MAX_TARGETS_PER_SOURCE = 12

    for source in changed_sources:
        scored_targets = []

        for target in candidates:
            if target.id == source.id or (source.id, target.id) in touched_pairs:
                continue

            score, details = _status_sync_score(source, target)
            match_kind = str(details.get('match_kind', 'semantic_related'))
            threshold = LINEAGE_THRESHOLD if (
                details['evidence_overlap'] >= 0.18
                or details.get('source_coverage', 0) >= 0.50
                or details.get('target_coverage', 0) >= 0.50
                or match_kind in {
                    'equivalent_evidence',
                    'source_subset_of_target',
                    'target_subset_of_source',
                    'shared_evidence',
                    'llm_equivalent',
                    'llm_source_subset_of_target',
                    'llm_target_subset_of_source',
                    'llm_related',
                }
                or details['lineage_bonus'] > 0
                or details['connection_bonus'] > 0
            ) else DEFAULT_THRESHOLD

            if score >= threshold:
                scored_targets.append((score, target, details, threshold))

        scored_targets.sort(key=lambda item: (-item[0], item[1].id))

        for score, target, details, threshold in scored_targets[:MAX_TARGETS_PER_SOURCE]:
            source_tree = getattr(getattr(source.batch, 'tree_version', None), 'tree', None)
            target_tree = getattr(getattr(target.batch, 'tree_version', None), 'tree', None)
            source_tree_name = source_tree.name if source_tree else 'another tree'
            target_tree_name = target_tree.name if target_tree else 'this tree'

            reason = (
                f'Status synced into “{target_tree_name}” because “{target.theme}” '
                f'appears affected by “{source.theme}” from “{source_tree_name}”. '
                f'Match score {score:.2f}; threshold {threshold:.2f}; '
                f'match type {details.get("match_kind", "semantic_related")}; '
                f'evidence overlap {details["evidence_overlap"]:.2f}; '
                f'source coverage {details.get("source_coverage", 0):.2f}; '
                f'target coverage {details.get("target_coverage", 0):.2f}; '
                f'common posts {int(details.get("common_posts", 0))}; '
                f'semantic similarity {details["signature"]:.2f}; '
                f'lineage bonus {details["lineage_bonus"]:.2f}; '
                f'connection bonus {details["connection_bonus"]:.2f}; '
                f'LLM check {"used" if details.get("llm_used") else "not used"}; '
                f'LLM relationship {details.get("llm_relationship", "not_checked")}; '
                f'LLM confidence {float(details.get("llm_confidence", 0)):.2f}; '
                f'LLM reason {details.get("llm_reason", "")}.'
            )

            if _apply_cluster_status(source, target, reason, score, details):
                changed_count += 1
                touched_pairs.add((source.id, target.id))

    return changed_count

@transaction.atomic
def push_version_to_main(version_id: int) -> TreeVersion:
    version = TreeVersion.objects.select_related('tree', 'tree__main_version', 'tree__main_space').get(id=version_id)

    synced_count = _sync_changed_statuses_into_all_related_trees(version)

    version.status = TreeVersion.STATUS_MAIN
    version.saved_at = timezone.now()
    version.snapshot = tree_version_payload(version.id)
    if isinstance(version.snapshot, dict):
        snapshot_meta = version.snapshot.get('version', {})
        snapshot_meta['synced_status_count'] = synced_count
        version.snapshot['version'] = snapshot_meta
    version.save()

    tree = version.tree
    tree.main_version = version
    tree.save(update_fields=['main_version', 'updated_at'])

    return version


def markdown_report(batch_id: int) -> str:
    batch = UploadBatch.objects.get(id=batch_id)
    clusters = IssueCluster.objects.filter(batch=batch).order_by('-priority_score')

    lines = [
        '# Community Pattern Radar Report',
        '',
        f'Batch: {batch.filename}',
        f'Total analysed posts: {batch.total_posts}',
        '',
        '## Top recurring issues',
    ]

    for idx, cluster in enumerate(clusters[:5], 1):
        lines.extend([
            '',
            f'### {idx}. {cluster.theme}',
            f'- Category: {cluster.category}',
            f'- Severity: {cluster.severity}',
            f'- Priority score: {cluster.priority_score}',
            f'- Related posts: {cluster.post_count}',
            f'- Status: {cluster.status}',
            f'- Recommended next step: {cluster.suggested_action}',
            '- Evidence:',
        ])

        for example in cluster.examples[:3]:
            lines.append(f'  - {example}')

    return '\n'.join(lines) + '\n'


def action_backlog_rows(batch_id: int) -> List[Dict[str, Any]]:
    clusters = IssueCluster.objects.filter(batch_id=batch_id).order_by('-priority_score')
    rows = []

    for cluster in clusters:
        rows.append({
            'issue': cluster.theme,
            'owner': 'community/product',
            'priority': cluster.severity,
            'priority_score': cluster.priority_score,
            'status': cluster.status,
            'action': cluster.suggested_action,
            'evidence_count': cluster.post_count,
            'examples': ' | '.join(cluster.examples),
        })

    return rows