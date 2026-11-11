"""Single local admin account. Passwords are hashed with scrypt (stdlib).

Sessions are random tokens held in memory and sent as an HttpOnly cookie;
restarting the server signs everyone out.
"""
import hashlib
import hmac
import secrets

from counter.web import db

COOKIE = "site_session"
_sessions: dict[str, str] = {}

N, R, P = 2 ** 14, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=N, r=R, p=P)
    return f"scrypt${N}${R}${P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, digest = stored.split("$")
        test = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt),
                              n=int(n), r=int(r), p=int(p))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(test.hex(), digest)


def login(username: str, password: str) -> str | None:
    admin = db.get_admin()
    if not admin or not hmac.compare_digest(username, admin["username"]):
        return None
    if not verify_password(password, admin["password_hash"]):
        return None
    token = secrets.token_urlsafe(32)
    _sessions[token] = username
    return token


def logout(token: str | None) -> None:
    _sessions.pop(token or "", None)


def user_for(token: str | None) -> str | None:
    return _sessions.get(token or "")
