from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from finance.config import settings

COOKIE_NAME = "session"
MAX_AGE = 60 * 60 * 24 * 30  # 30 days

_serializer = URLSafeTimedSerializer(settings.app_secret)


def create_session_token(user_id: int) -> str:
    return _serializer.dumps({"uid": user_id})


def read_session_token(token: str) -> int | None:
    try:
        data = _serializer.loads(token, max_age=MAX_AGE)
        return data["uid"]
    except (BadSignature, SignatureExpired, KeyError):
        return None
