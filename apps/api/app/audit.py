import json

from .models import AuditLog


def record(db, actor, action, target, detail=None, ok=True):
    """Adds an audit row to the caller's transaction. Never pass passwords in detail."""
    name = actor if isinstance(actor, str) else actor.username
    text = json.dumps(detail, ensure_ascii=False, default=str) if isinstance(detail, (dict, list)) else detail
    db.add(AuditLog(actor=name, action=action, target=str(target)[:160], detail=text, ok=ok))
