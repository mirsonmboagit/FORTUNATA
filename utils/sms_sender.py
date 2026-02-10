import json
import os

import requests
from kivy.app import App


def _base_dir():
    app = App.get_running_app()
    if app and getattr(app, "base_dir", None):
        return app.base_dir
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def load_sms_settings():
    data = {}
    base_dir = _base_dir()
    settings_path = os.path.join(base_dir, "sms_settings.json")
    app_settings_path = os.path.join(base_dir, "app_settings.json")
    for path in (settings_path, app_settings_path):
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f) or {}
            if path.endswith("app_settings.json"):
                loaded = loaded.get("sms_settings") or loaded.get("whatsapp_settings") or {}
            data.update(loaded)
        except Exception:
            pass

    env_map = {
        "SMS_PROVIDER": "provider",
        "TWILIO_ACCOUNT_SID": "account_sid",
        "TWILIO_AUTH_TOKEN": "auth_token",
        "TWILIO_FROM_NUMBER": "from_number",
    }
    for env_key, key in env_map.items():
        val = os.environ.get(env_key)
        if val:
            data[key] = val

    return data


def _normalize_whatsapp_number(number):
    if not number:
        return number
    number = number.strip()
    if number.lower().startswith("whatsapp:"):
        return number
    return f"whatsapp:{number}"


def send_whatsapp(to_number, message):
    settings = load_sms_settings()
    provider = (settings.get("provider") or "twilio_whatsapp").lower()

    if provider in ("twilio", "twilio_whatsapp"):
        account_sid = settings.get("account_sid")
        auth_token = settings.get("auth_token")
        from_number = settings.get("from_number")
        if not account_sid or not auth_token or not from_number:
            return False, "WhatsApp nao configurado"

        url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
        try:
            response = requests.post(
                url,
                data={
                    "To": _normalize_whatsapp_number(to_number),
                    "From": _normalize_whatsapp_number(from_number),
                    "Body": message,
                },
                auth=(account_sid, auth_token),
                timeout=10,
            )
        except Exception:
            return False, "Falha ao enviar WhatsApp"

        if response.status_code not in (200, 201):
            return False, f"Erro ao enviar WhatsApp ({response.status_code})"

        return True, ""

    return False, "Provider de WhatsApp nao suportado"


def send_sms(to_number, message):
    return send_whatsapp(to_number, message)
