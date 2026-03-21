import json
import os


def _load_config():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(base_dir, "config.json")
    if not os.path.exists(config_path):
        return {}
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def get_db():
    cfg = _load_config()
    mode = (cfg.get("db_mode") or "local").lower()
    if mode == "remote":
        from database.client import DatabaseClient
        return DatabaseClient(config=cfg)
    from database.database import Database
    db_path = cfg.get("db_path")
    if db_path:
        return Database(db_path=db_path)
    return Database()
