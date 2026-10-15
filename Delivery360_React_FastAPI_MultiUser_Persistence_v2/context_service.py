"""Bounded agent context with durable summaries and structured business references."""
import json, os, re

# Keep the complete transcript in the database; bound only the model request.
RECENT_TURNS = max(2, int(os.getenv('DELIVERY360_RECENT_TURNS', '8')))
MAX_HISTORY_CHARS = max(12000, int(os.getenv('DELIVERY360_MAX_HISTORY_CHARS', '85000')))


def split_turns(history):
    """Keep complete tool-call/output groups together when compacting history."""
    chunks=[]; chunk=[]
    for item in history:
        if item.get('role') == 'user' and chunk:
            chunks.append(chunk); chunk=[]
        chunk.append(item)
    if chunk: chunks.append(chunk)
    return chunks


def bounded_history(history):
    chunks=split_turns(history)
    retained=chunks[-RECENT_TURNS:]
    while len(retained)>1 and len(json.dumps([x for c in retained for x in c],default=str))>MAX_HISTORY_CHARS:
        retained.pop(0)
    dropped=chunks[:len(chunks)-len(retained)]
    return [x for c in retained for x in c], [x for c in dropped for x in c]


def reference_updates(trace):
    """Extract stable IDs from successful tool responses, not from model guesses."""
    found={}
    for event in trace:
        result=event.get('result') or {}
        if not isinstance(result,dict) or not result.get('ok'): continue
        data=result.get('data')
        serialized=json.dumps(data,default=str)
        for key in ('employee_id','project_id','sow_id','account_id','assignment_id','document_id'):
            vals=re.findall(r'"'+key+r'"\s*:\s*"([A-Za-z0-9_-]{1,50})"',serialized)
            if vals: found.setdefault(key,[]).extend(vals)
    return {k:list(dict.fromkeys(v))[:30] for k,v in found.items()}


def merge_references(previous, updates):
    previous=dict(previous or {})
    for key,values in updates.items():
        previous[key]=list(dict.fromkeys(previous.get(key,[])+values))[-30:]
    return previous


def summarize_archived(previous, dropped, client=None, model=None):
    """Summarize archived context. If unavailable, retain a conservative extract."""
    if not dropped: return previous or ''
    # Capture human requests and final assistant answers; exclude verbose tool outputs.
    extracts=[]
    for item in dropped:
        if item.get('role')=='user' and isinstance(item.get('content'),str):
            extracts.append('User: '+item['content'][:900])
        elif item.get('type')=='message' and item.get('role')=='assistant':
            content=item.get('content') or []
            text=' '.join(p.get('text','') for p in content if isinstance(p,dict) and p.get('type')=='output_text')
            if text: extracts.append('Assistant: '+text[:1200])
    source=('Existing summary:\n'+(previous or '')+'\nArchived turns:\n'+'\n'.join(extracts))[-24000:]
    if client and extracts:
        try:
            response=client.responses.create(model=model or os.getenv('OPENAI_MODEL','gpt-4.1-mini'),store=False,
                instructions=('Summarize conversation context for future follow-up questions. Preserve explicit user constraints, '
                              'named clients, employee/project/SOW identifiers, decisions and unresolved questions. '
                              'Distinguish user requirements from historical observations. Do not invent facts. '
                              'Business availability and status must be refreshed through tools. Max 900 words.'),
                input=source,max_output_tokens=1300)
            if response.status=='completed' and response.output_text.strip(): return response.output_text.strip()[:6000]
        except Exception:
            pass
    # Conservative fallback: don't manufacture a summary when LLM unavailable.
    return (source[-6000:])


def context_note(summary,references):
    if not summary and not references: return ''
    return ('Prior conversation context (historical, not authoritative operational facts):\n'
            + (summary or '(none)') + '\nBusiness IDs observed in successful tool results: '
            + json.dumps(references or {},ensure_ascii=False)
            + '\nAlways re-query tools for current availability, SOW status, dates, and other mutable facts.')
