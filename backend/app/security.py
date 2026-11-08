from datetime import datetime, timedelta, timezone
from argon2 import PasswordHasher
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from .config import settings
from .db import get_db
from .models import User

ph = PasswordHasher()
oauth2 = OAuth2PasswordBearer(tokenUrl="/auth/token")

def hash_password(value: str) -> str:
    return ph.hash(value)

def verify_password(value: str, hashed: str) -> bool:
    try:
        return ph.verify(hashed, value)
    except Exception:
        return False

def make_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": user.id, "username": user.username, "iat": now, "exp": now + timedelta(minutes=settings.access_token_minutes)}
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")

def current_user(token: str = Depends(oauth2), db: Session = Depends(get_db)) -> User:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        uid = payload["sub"]
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Μη έγκυρη σύνδεση")
    user = db.get(User, uid)
    if not user or not user.active:
        raise HTTPException(status_code=401, detail="Ανενεργός χρήστης")
    db.info["hist_user"] = user.id   # για το ιστορικό Αναίρεσης (history_rows)
    return user

def user_permissions(user: User) -> set[str]:
    return {p.code for r in user.roles for p in r.permissions}

def require_permission(code: str):
    def dep(user: User = Depends(current_user)):
        if code not in user_permissions(user) and "*" not in user_permissions(user):
            raise HTTPException(status_code=403, detail=f"Δεν υπάρχει δικαίωμα: {code}")
        return user
    return dep
