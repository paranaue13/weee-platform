import json
from sqlalchemy.orm import Session
from .models import AuditEvent, User

def write_audit(db: Session, user: User|None, entity_type: str, entity_id: str|None, action: str, old=None, new=None, reason=None):
    ev = AuditEvent(
        user_id=user.id if user else None, entity_type=entity_type, entity_id=entity_id, action=action,
        old_values=json.dumps(old, ensure_ascii=False, default=str) if old is not None else None,
        new_values=json.dumps(new, ensure_ascii=False, default=str) if new is not None else None,
        reason=reason,
    )
    db.add(ev)
