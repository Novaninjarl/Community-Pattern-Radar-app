"""Cluster interpretation layer for Community Pattern Radar.

The embedding + clustering pipeline discovers groups of similar posts. This module turns
those groups into human-friendly labels and actions.

Modes:
- rules: fast/free keyword fallback
- local_llm: generic local Ollama interpreter with rules fallback
- cloud_llm: placeholder-ready mode that currently falls back to rules
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from collections import Counter
from typing import Any, Dict, List, Sequence

from django.conf import settings

CATEGORY_KEYWORDS = {
    'pricing': ['price', 'pricing', 'expensive', 'cost', 'paid', 'billing', 'refund', 'subscription'],
    'spam / abuse': ['spam', 'scam', 'bot', 'fake', 'phishing', 'abuse', 'harass', 'troll'],
    'product bug': ['bug', 'broken', 'crash', 'error', 'not working', 'failed', 'glitch'],
    'onboarding': ['confused', 'how do i', 'setup', 'sign up', 'login', 'onboarding', 'tutorial'],
    'content quality': ['low quality', 'irrelevant', 'duplicate', 'misleading', 'ai generated'],
    'feature request': ['please add', 'feature', 'request', 'wish', 'would love', 'can you add'],
}

UNRESOLVED_STATUSES = {'', 'open', 'pending', 'flagged', 'reported', 'needs review', 'unresolved'}


def deterministic_json(data: Any) -> str:
    """Stable JSON string so the same evidence creates the exact same prompt."""
    return json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(',', ':'),
    )


def ollama_deterministic_options() -> Dict[str, Any]:
    """Options that make Ollama generation as deterministic as the model allows.

    temperature=0 removes sampling, top_k=1 forces the highest-probability token,
    seed fixes any remaining model RNG, and num_thread=1 avoids small nondeterministic
    differences from multi-thread scheduling on some local machines.
    """
    return {
        'temperature': 0,
        'top_k': 1,
        'top_p': 1,
        'seed': int(getattr(settings, 'OLLAMA_DETERMINISTIC_SEED', 42)),
        'num_thread': int(getattr(settings, 'OLLAMA_NUM_THREAD', 1)),
    }


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def severity_from_score(score: float) -> str:
    if score >= 86:
        return 'critical'
    if score >= 61:
        return 'high'
    if score >= 31:
        return 'medium'
    return 'low'


def calculate_priority_score(evidence: Dict[str, Any]) -> float:
    """Data-driven priority score, independent of hardcoded categories."""
    count = int(evidence.get('count', 0) or 0)
    total_reports = int(evidence.get('report_count_total', 0) or 0)
    total_upvotes = int(evidence.get('upvotes_total', 0) or 0)
    statuses = [str(s).strip().lower() for s in evidence.get('moderation_statuses', [])]
    unresolved_count = sum(1 for s in statuses if s in UNRESOLVED_STATUSES or 'flag' in s or 'report' in s)

    # Keep this transparent and tunable. For an MVP, these signals are usually available.
    size_score = min(count * 4, 35)
    report_score = min(total_reports * 8, 30)
    moderation_score = min(unresolved_count * 5, 20)
    engagement_score = min(total_upvotes * 0.5, 10)

    # Basic risk-language boost without mapping to categories.
    examples_text = ' '.join(evidence.get('cleaned_examples', [])).lower()
    risk_terms = ['scam', 'harass', 'abuse', 'threat', 'unsafe', 'fraud', 'phishing', 'hate', 'illegal']
    risk_score = 5 if any(term in examples_text for term in risk_terms) else 0

    return round(clamp(size_score + report_score + moderation_score + engagement_score + risk_score, 0, 100), 2)


def build_cluster_evidence(posts: Sequence[Any], terms: List[str]) -> Dict[str, Any]:
    statuses = [getattr(p, 'moderation_status', '') for p in posts if getattr(p, 'moderation_status', '')]
    return {
        'count': len(posts),
        'examples': [getattr(p, 'text', '')[:500] for p in posts[:8]],
        'cleaned_examples': [getattr(p, 'cleaned_text', '')[:500] for p in posts[:8]],
        'top_terms': terms,
        'report_count_total': sum(getattr(p, 'report_count', 0) or 0 for p in posts),
        'upvotes_total': sum(getattr(p, 'upvotes', 0) or 0 for p in posts),
        'moderation_statuses': statuses,
        'channels': dict(Counter(getattr(p, 'channel', '') for p in posts if getattr(p, 'channel', ''))),
        'unique_users': len({getattr(p, 'user_id', '') for p in posts if getattr(p, 'user_id', '')}),
    }


def _fallback_category(cleaned_examples: List[str]) -> str:
    joined = ' '.join(cleaned_examples).lower()
    scores = {cat: sum(joined.count(k) for k in kws) for cat, kws in CATEGORY_KEYWORDS.items()}
    best, score = max(scores.items(), key=lambda x: x[1])
    return best if score > 0 else 'general community feedback'


def _fallback_theme(terms: List[str]) -> str:
    if not terms:
        return 'Recurring community issue'
    return ' / '.join(t.title() for t in terms[:3])


def _fallback_action(category: str, terms: List[str]) -> str:
    focus = ', '.join(terms[:3]) if terms else 'the repeated issue'
    actions = {
        'pricing': f'Review pricing copy and collect 5-10 follow-up examples around {focus}; add a clearer plan comparison or FAQ.',
        'spam / abuse': f'Add a moderation rule or review queue for patterns around {focus}; inspect repeated users/channels before escalating.',
        'product bug': 'Reproduce the issue using the example posts, create a bug ticket, and update affected users once fixed.',
        'onboarding': f'Improve onboarding/help text around {focus}; add a short guide or pinned answer where these messages appear.',
        'content quality': f'Tighten posting guidelines and surface better examples; consider flagging repeated low-quality patterns around {focus}.',
        'feature request': 'Log this as a product discovery theme, quantify affected users, and test demand with a lightweight survey or changelog comment.',
    }
    return actions.get(category, 'Review the examples, tag the pattern, assign an owner, and decide whether product, support, or moderation follow-up is needed.')


def interpret_with_rules(evidence: Dict[str, Any], priority_score: float | None = None) -> Dict[str, Any]:
    terms = evidence.get('top_terms', []) or []
    cleaned_examples = evidence.get('cleaned_examples', []) or []
    score = calculate_priority_score(evidence) if priority_score is None else priority_score
    category = _fallback_category(cleaned_examples)
    return {
        'theme': _fallback_theme(terms),
        'category': category,
        'severity': severity_from_score(score),
        'priority_score': score,
        'suggested_action': _fallback_action(category, terms),
        'owner': 'community',
        'confidence': 0.45,
        'interpreter': 'rules',
    }


def _extract_json(text: str) -> Dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r'\{.*\}', text, flags=re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def _clean_llm_result(data: Dict[str, Any], evidence: Dict[str, Any], priority_score: float) -> Dict[str, Any]:
    fallback = interpret_with_rules(evidence, priority_score)
    severity = severity_from_score(priority_score)
    confidence = data.get('confidence', fallback['confidence'])
    try:
        confidence = round(clamp(float(confidence), 0, 1), 2)
    except Exception:
        confidence = fallback['confidence']

    return {
        'theme': str(data.get('theme') or fallback['theme'])[:255],
        'category': str(data.get('category') or fallback['category'])[:100],
        # Score remains deterministic, but LLM writes the labels/actions.
        'severity': severity,
        'priority_score': priority_score,
        'suggested_action': str(data.get('suggested_action') or fallback['suggested_action']),
        'owner': str(data.get('owner') or fallback['owner'])[:50],
        'confidence': confidence,
        'interpreter': 'local_llm',
    }


def interpret_with_ollama(evidence: Dict[str, Any], priority_score: float) -> Dict[str, Any]:
    base_url = settings.OLLAMA_BASE_URL.rstrip('/')
    model = settings.OLLAMA_MODEL
    url = f'{base_url}/api/chat'

    prompt = f"""
You are analysing a cluster of similar posts from an online community or UGC product.

Infer the recurring issue represented by this cluster. Do not rely on predefined categories.
Create the most specific useful category from the evidence.

The numeric priority score and severity are calculated separately by the app, so do not change them.
Return valid JSON only with this exact shape:
{{
  "theme": "short human-readable issue title under 12 words",
  "category": "specific issue category",
  "suggested_action": "specific operational next step for the team",
  "owner": "community | product | support | trust_safety | growth | engineering",
  "confidence": 0.0
}}

Cluster evidence:
{deterministic_json(evidence)}

Calculated priority score: {priority_score}
Calculated severity: {severity_from_score(priority_score)}
""".strip()

    payload = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': 'You are a concise community operations analyst. Return JSON only.'},
            {'role': 'user', 'content': prompt},
        ],
        'stream': False,
        'format': 'json',
        'options': ollama_deterministic_options(),
    }

    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    timeout = float(settings.OLLAMA_TIMEOUT_SECONDS)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = json.loads(response.read().decode('utf-8'))
    content = body.get('message', {}).get('content', '{}')
    return _clean_llm_result(_extract_json(content), evidence, priority_score)


def interpret_cluster(evidence: Dict[str, Any]) -> Dict[str, Any]:
    mode = getattr(settings, 'INTERPRETER_MODE', 'rules')
    priority_score = calculate_priority_score(evidence)

    if mode == 'local_llm':
        try:
            return interpret_with_ollama(evidence, priority_score)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError, ValueError, TypeError, OSError):
            result = interpret_with_rules(evidence, priority_score)
            result['interpreter'] = 'rules_fallback_after_ollama_error'
            return result

    # cloud_llm is deliberately a seam for later; no paid API is required in this MVP.
    return interpret_with_rules(evidence, priority_score)


def weekly_report_summary(batch_total_posts: int, cluster_summaries: List[Dict[str, Any]]) -> Dict[str, Any]:
    summary = {
        'headline': f'{batch_total_posts} posts analysed; {len(cluster_summaries)} recurring issues need review.',
        'top_5_recurring_issues': cluster_summaries,
        'what_changed': 'Initial upload baseline. Upload a later CSV to compare week-over-week movement.',
        'category_mix': dict(Counter(item['category'] for item in cluster_summaries)),
        'recommended_next_steps': [item['recommended_next_step'] for item in cluster_summaries[:3]],
    }

    if getattr(settings, 'INTERPRETER_MODE', 'rules') != 'local_llm' or not cluster_summaries:
        return summary

    try:
        base_url = settings.OLLAMA_BASE_URL.rstrip('/')
        prompt = f"""
Create a concise weekly community report from these recurring issue clusters.
Return JSON only with:
{{
  "headline": "one sentence executive summary",
  "what_changed": "short note; say this is the initial baseline if no prior batch exists",
  "recommended_next_steps": ["step 1", "step 2", "step 3"]
}}

Total posts analysed: {batch_total_posts}
Top clusters:
{deterministic_json(cluster_summaries)}
""".strip()
        payload = {
            'model': settings.OLLAMA_MODEL,
            'messages': [
                {'role': 'system', 'content': 'You write concise, practical community operations reports. Return JSON only.'},
                {'role': 'user', 'content': prompt},
            ],
            'stream': False,
            'format': 'json',
            'options': ollama_deterministic_options(),
        }
        request = urllib.request.Request(
            f'{base_url}/api/chat',
            data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        with urllib.request.urlopen(request, timeout=float(settings.OLLAMA_TIMEOUT_SECONDS)) as response:
            body = json.loads(response.read().decode('utf-8'))
        content = body.get('message', {}).get('content', '{}')
        llm = _extract_json(content)
        summary['headline'] = str(llm.get('headline') or summary['headline'])
        summary['what_changed'] = str(llm.get('what_changed') or summary['what_changed'])
        steps = llm.get('recommended_next_steps')
        if isinstance(steps, list) and steps:
            summary['recommended_next_steps'] = [str(step) for step in steps[:5]]
    except Exception:
        pass

    return summary
