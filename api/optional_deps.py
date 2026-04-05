import re

try:
    from bs4 import BeautifulSoup as _BeautifulSoup
except Exception:
    _BeautifulSoup = None

BeautifulSoup = _BeautifulSoup


def has_beautifulsoup():
    return BeautifulSoup is not None


def strip_html_text(value):
    text = str(value or "").strip()
    if not text:
        return ""
    if BeautifulSoup is not None:
        try:
            return BeautifulSoup(text, "html.parser").get_text(" ", strip=True)
        except Exception:
            pass
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()
