import unicodedata

import bcrypt


QUESTIONS = [
    "Qual foi o nome do seu primeiro professor?",
    "Em que cidade voce nasceu?",
    "Qual e o nome da sua primeira escola?",
]


def normalize_answer(text):
    text = (text or "").strip().lower()
    text = " ".join(text.split())
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _ensure_bytes(value):
    if isinstance(value, memoryview):
        return value.tobytes()
    if isinstance(value, str):
        return value.encode("utf-8")
    return value


def hash_answer(text):
    normalized = normalize_answer(text)
    return bcrypt.hashpw(normalized.encode("utf-8"), bcrypt.gensalt())


def check_answer(text, hashed):
    hashed_bytes = _ensure_bytes(hashed)
    normalized = normalize_answer(text)
    return bcrypt.checkpw(normalized.encode("utf-8"), hashed_bytes)
