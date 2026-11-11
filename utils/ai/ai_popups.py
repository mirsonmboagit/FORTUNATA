import re

from kivy.animation import Animation
from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import (
    Color, Ellipse, Line, PopMatrix, PushMatrix, Rectangle, RoundedRectangle, Scale,
)
from kivy.metrics import dp
from kivy.uix.anchorlayout import AnchorLayout
from kivy.properties import NumericProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget
from kivy.utils import escape_markup
from ui.components.native_widgets import (
    NATIVE_ICONS as md_icons,
    NativeBoxLayout as MDBoxLayout, NativeCard as MDCard,
    NativeFlatButton as MDFlatButton, NativeIconButton as MDIconButton,
    NativeLabel as MDLabel, NativeProgressBar as MDProgressBar,
)

from utils.business.expiry_alerts import (
    ALERT_COLORS,
    ALERT_LEVEL_ALTO,
    ALERT_LEVEL_CRITICO,
    ALERT_LEVEL_LEVE,
    ALERT_LEVEL_MEDIO,
    ALERT_LEVEL_VENCIDO,
)
from utils.config.theme import get_theme_tokens
try:
    from utils.core.i18n import translate_text, normalize_language
except Exception:
    def translate_text(text, language=None):
        return str(text or "")
    def normalize_language(value, fallback="pt"):
        return str(value or fallback)



class _BannerIconButton(ButtonBehavior, MDLabel):
    pass


class _BannerPillButton(ButtonBehavior, MDLabel):
    """A fixed-width banner action that never grows beyond its container."""

    pass


class _BannerCloseButton(ButtonBehavior, Widget):
    """Botão X desenhado em canvas: sem fundo nativo, sem glifo de fonte."""

    def __init__(self, callback=None, palette=None, **kwargs):
        super().__init__(size_hint=(None, None), size=(dp(34), dp(34)), **kwargs)
        palette = palette or {}
        self._fg = _rgba(palette.get("button_text") or (0.8, 0.8, 0.8, 1))
        self.bind(pos=self._draw, size=self._draw, state=self._draw)
        if callback:
            self.bind(on_release=callback)
        self._draw()

    def _draw(self, *_args):
        self.canvas.clear()
        cx, cy = self.center_x, self.center_y
        r = min(self.width, self.height) / 2.0
        a = r * 0.34
        pressed = self.state == "down"
        with self.canvas:
            Color(self._fg[0], self._fg[1], self._fg[2], 0.16 if pressed else 0.07)
            Ellipse(pos=(cx - r, cy - r), size=(r * 2, r * 2))
            Color(self._fg[0], self._fg[1], self._fg[2], 0.78)
            Line(points=[cx - a, cy - a, cx + a, cy + a], width=dp(1.2), cap="round")
            Line(points=[cx - a, cy + a, cx + a, cy - a], width=dp(1.2), cap="round")


def _build_banner_close_button(callback, palette=None):
    return _BannerCloseButton(callback=callback, palette=palette)


def _rgba(color, alpha=None):
    values = list(color or [0, 0, 0, 1])
    while len(values) < 4:
        values.append(1)
    values = [float(value) for value in values[:4]]
    if alpha is not None:
        values[3] = float(alpha)
    return values


def _blend(base, overlay, factor, alpha=None):
    base_rgba = _rgba(base)
    overlay_rgba = _rgba(overlay)
    weight = max(0.0, min(1.0, float(factor)))
    mixed = [
        base_rgba[index] + (overlay_rgba[index] - base_rgba[index]) * weight
        for index in range(4)
    ]
    if alpha is not None:
        mixed[3] = float(alpha)
    return mixed


def _ui_lang():
    app = App.get_running_app()
    if not app:
        return "pt"
    code = getattr(app, "ui_language", None) or getattr(app, "language", None)
    try:
        return normalize_language(code)
    except Exception:
        return str(code or "pt")


def _tx(text, **kwargs):
    out = translate_text(text, _ui_lang())
    if kwargs:
        try:
            out = out.format(**kwargs)
        except Exception:
            pass
    return out


def _theme_tokens():
    app = App.get_running_app()
    tokens = getattr(app, "theme_tokens", {}) if app else {}
    if tokens:
        return dict(tokens)
    style = getattr(app, "theme_style", "Light") if app else "Light"
    return get_theme_tokens(style)


def _scrollbar_palette():
    tokens = _theme_tokens()
    base = _rgba(tokens.get("surface", tokens.get("card_alt", [1, 1, 1, 1])))
    accent = _rgba(tokens.get("primary", tokens.get("info", [0.15, 0.45, 0.75, 1])))
    dark = _is_dark_color(base)
    return {
        "active": _blend(base, accent, 0.48, alpha=0.22 if not dark else 0.34),
        "inactive": _blend(base, accent, 0.18, alpha=0.03 if not dark else 0.08),
    }


def _apply_scroll_style(scroll):
    palette = _scrollbar_palette()
    scroll.scroll_type = ["bars", "content"]
    scroll.bar_color = palette["active"]
    scroll.bar_inactive_color = palette["inactive"]


def _is_dark_color(color_rgba):
    if not color_rgba:
        return False
    r, g, b = _rgba(color_rgba)[:3]
    luminance = (0.299 * r) + (0.587 * g) + (0.114 * b)
    return luminance < 0.52


def _clean_messages(messages):
    cleaned = []
    for item in messages or []:
        text = str(item or "").strip()
        if text:
            cleaned.append(text)
    return cleaned


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _format_banner_quantity(value, unit):
    """Return quantities in full words so banner text is easy to read."""
    try:
        amount = float(value)
    except (TypeError, ValueError):
        amount = 0.0

    unit_text = str(unit or "").strip().lower()
    is_weight = unit_text in {"kg", "quilo", "quilos", "quilograma", "quilogramas"}
    if is_weight:
        number = f"{amount:.1f}".replace(".", ",")
        label = _tx("quilograma") if abs(amount - 1) < 0.001 else _tx("quilogramas")
    else:
        number = str(int(amount)) if amount.is_integer() else f"{amount:.1f}".replace(".", ",")
        label = _tx("unidade") if abs(amount - 1) < 0.001 else _tx("unidades")
    return f"{number} {label}"


def _format_banner_days(value):
    try:
        days = max(0, int(round(float(value))))
    except (TypeError, ValueError):
        days = 0
    return f"{days} {_tx('dia')}" if days == 1 else f"{days} {_tx('dias')}"


def _variant_name(variant):
    variant = str(variant or "").lower().strip()
    if variant == "error":
        return "danger"
    return variant if variant in ("info", "success", "warning", "danger") else "info"


def _resolve_variant(banner_data):
    explicit = banner_data.get("variant")
    if explicit:
        return _variant_name(explicit)

    kind = str(banner_data.get("kind") or "").lower()
    if kind in ("positive", "stock_ok", "expiry_ok"):
        return "success"

    expiry_level = str(banner_data.get("expiry_level") or "").lower()
    if expiry_level in (ALERT_LEVEL_VENCIDO, ALERT_LEVEL_CRITICO):
        return "danger"
    if expiry_level in (ALERT_LEVEL_ALTO, ALERT_LEVEL_MEDIO):
        return "warning"

    try:
        urgency = float(banner_data.get("urgency"))
    except Exception:
        urgency = 999.0
    if urgency < 1:
        return "danger"
    if urgency < 20:
        return "warning"
    return "info"


def _banner_palette(banner_data):
    tokens = _theme_tokens()
    dark = _is_dark_color(tokens.get("surface"))
    variant = _resolve_variant(banner_data)
    own_bg = banner_data.get("bg_color")
    if own_bg:
        # Modelo classico: cartao com a cor do alerta e texto adaptativo.
        bg = _rgba(own_bg)
        dark_bg = _is_dark_color(bg)
        fg = [1.0, 1.0, 1.0, 1.0] if dark_bg else [0.13, 0.14, 0.16, 1.0]
        body = [1.0, 1.0, 1.0, 0.92] if dark_bg else [0.22, 0.23, 0.26, 1.0]
        tint = [1.0, 1.0, 1.0] if dark_bg else [0.0, 0.0, 0.0]
        return {
            "variant": variant,
            "accent": fg,
            "accent_soft": fg,
            "dark": dark_bg,
            "bar_alpha": 0.0,
            "bg": bg,
            "border": [fg[0], fg[1], fg[2], 0.14],
            "icon_bg": tint + [0.16 if dark_bg else 0.08],
            "chip_bg": tint + [0.24 if dark_bg else 0.12],
            "button_bg": tint + [0.18 if dark_bg else 0.08],
            "button_bg_hover": tint + [0.28 if dark_bg else 0.14],
            "button_text": fg,
            "title": fg,
            "text": body,
            "muted": fg,
            "progress": [fg[0], fg[1], fg[2], 0.55],
            "elevation": 3,
            "hover_elevation": 6,
        }
    accent = _rgba(tokens.get(variant, tokens.get("info", [0.15, 0.45, 0.75, 1])))
    base = _rgba(tokens.get("card", [1, 1, 1, 1]))
    secondary_base = _rgba(tokens.get("card_alt", base))
    divider = _rgba(tokens.get("divider", [0, 0, 0, 0.10]))
    title_c = _rgba(tokens.get("text_primary", [0.15, 0.20, 0.30, 1]))
    soft = _blend(accent, title_c, 0.35 if dark else 0.15)
    return {
        "variant": variant,
        "accent": accent,
        "accent_soft": soft,
        "dark": dark,
        "bg": _blend(base, accent, 0.15 if not dark else 0.20),
        "border": _blend(divider, accent, 0.40, alpha=0.38 if not dark else 0.45),
        "icon_bg": _blend(base, accent, 0.20 if not dark else 0.26),
        "chip_bg": _blend(base, accent, 0.22 if not dark else 0.30),
        "button_bg": _blend(base, accent, 0.16 if not dark else 0.22),
        "button_bg_hover": _blend(base, accent, 0.26 if not dark else 0.32),
        "button_text": soft,
        "title": title_c,
        "text": _blend(
            _rgba(tokens.get("text_secondary", [0.35, 0.40, 0.50, 1])),
            title_c,
            0.35,
        ),
        "muted": _rgba(tokens.get("text_muted", tokens.get("text_secondary", [0.55, 0.60, 0.70, 1]))),
        "progress": _rgba(soft, 0.65),
        "elevation": 2 if not dark else 1,
        "hover_elevation": 5 if not dark else 3,
    }


def _truncate_text(text, limit):
    text = " ".join(str(text or "").split())
    limit = max(60, int(limit or 160))
    if len(text) <= limit:
        return text, False
    clipped = text[: limit - 1].rsplit(" ", 1)[0].strip()
    if not clipped:
        clipped = text[: limit - 1].strip()
    return f"{clipped}...", True


def _bind_auto_height(label, min_height=dp(18)):
    def _update(*_args):
        width = max(label.width, 1)
        label.text_size = (width, None)
        try:
            label.texture_update()
        except Exception:
            pass
        height = max(float(label.texture_size[1] or 0), float(min_height))
        reserve = getattr(label, "_hover_reserve", None)
        if callable(reserve):
            try:
                height = max(height, float(reserve(True)[1]))
            except Exception:
                pass
        label.height = height

    label._relayout = _update
    label.bind(width=_update, text=_update)
    Clock.schedule_once(lambda _dt: _update(), 0)


def _bind_texture_size(label, min_height=dp(18), horizontal_padding=dp(4)):
    label.size_hint = (None, None)

    def _update(*_args):
        label.text_size = (None, None)
        try:
            label.texture_update()
        except Exception:
            pass
        text_w = float(label.texture_size[0] or 0)
        reserve = getattr(label, "_hover_reserve", None)
        if callable(reserve):
            try:
                text_w = max(text_w, float(reserve(False)[0]))
            except Exception:
                pass
        label.width = max(text_w + float(horizontal_padding), float(dp(24)))
        label.height = max(float(label.texture_size[1] or 0), float(min_height))

    label._relayout = _update
    label.bind(text=_update)
    _update()
    Clock.schedule_once(lambda _dt: _update(), 0)


def _fit_scroll_content(scroll, content, max_height, min_height=0):
    viewport_width = max(float(scroll.width or 0), 1.0)
    content_width = max(float(getattr(content, "minimum_width", 0) or 0), viewport_width)
    content_height = max(float(getattr(content, "minimum_height", 0) or 0), float(min_height))
    content.width = content_width
    content.height = content_height
    viewport_height = min(max(content_height, float(min_height)), float(max_height))
    scroll.height = viewport_height
    scroll.do_scroll_y = content_height > viewport_height + 1
    scroll.do_scroll_x = content_width > viewport_width + 1
    scroll.bar_width = dp(3) if (scroll.do_scroll_x or scroll.do_scroll_y) else 0
    return viewport_height


def _sync_box_height(box, *_args):
    box.height = box.minimum_height


def _scroll_banner_into_view(container, widget, padding=dp(10)):
    if not container or not widget:
        return
    scroll = getattr(container, "_ai_banner_scroll", None)
    if scroll is None or not widget.parent:
        return
    try:
        scroll.scroll_to(widget, padding=padding, animate=True)
    except Exception:
        pass


def _cancel_event(event):
    if not event:
        return
    try:
        event.cancel()
    except Exception:
        pass


def _detach_widget(widget):
    if not widget:
        return
    parent = getattr(widget, "parent", None)
    if parent is None:
        return
    try:
        parent.remove_widget(widget)
    except Exception:
        pass


_MARKUP_TOKEN_RE = re.compile(r"(\[/?[a-zA-Z]+(?:=[^\]]*)?\]|&[a-z]+;)")
_MEASURE_CACHE = {}


def _hover_markup_for(label, base_text, was_markup=None):
    """MAIUSCULAS + bold sem estragar tags/entidades de markup."""
    markup = label.markup if was_markup is None else was_markup
    text = str(base_text or "")
    if not markup:
        text = escape_markup(text)
    parts = _MARKUP_TOKEN_RE.split(text)
    out = []
    for part in parts:
        if part and _MARKUP_TOKEN_RE.fullmatch(part):
            out.append(part)
        else:
            out.append(part.upper())
    return "[b]" + "".join(out) + "[/b]"


def _measure_label(label, markup_text, wrap):
    """Mede o texto (sem o desenhar) para reservar o espaco antes do hover."""
    width = max(float(label.width), 1.0) if wrap else 0.0
    key = (markup_text, round(width), float(label.font_size), str(getattr(label, "font_name", "")),
           float(getattr(label, "line_height", 1.0)), wrap)
    cached = _MEASURE_CACHE.get(key)
    if cached is not None:
        return cached
    from kivy.uix.label import Label as _KLabel

    kwargs = {"text_size": (width, None)} if wrap else {}
    probe = _KLabel(
        text=markup_text,
        markup=True,
        font_size=label.font_size,
        line_height=getattr(label, "line_height", 1.0),
        **kwargs,
    )
    font_name = getattr(label, "font_name", None)
    if font_name:
        probe.font_name = font_name
    probe.texture_update()
    size = (float(probe.texture_size[0]), float(probe.texture_size[1]))
    if len(_MEASURE_CACHE) > 400:
        _MEASURE_CACHE.clear()
    _MEASURE_CACHE[key] = size
    return size


def _set_label_text(label, text):
    """Altera o texto respeitando o estado de hover."""
    text = str(text)
    if getattr(label, "_hover_on", False):
        label._normal_text = text
        label.text = _hover_markup_for(label, text, was_markup=label._was_markup)
    else:
        label.text = text


def _apply_hover_text(label, on):
    if on:
        label._normal_text = label.text
        label._was_markup = label.markup
        hover_text = _hover_markup_for(label, label._normal_text, was_markup=label._was_markup)
        label._hover_on = True
        label.markup = True
        label.text = hover_text
    else:
        label._hover_on = False
        label.markup = label._was_markup
        label.text = label._normal_text


def _fit_hover_scale(label, factor=1.08):
    """Cresce o maximo possivel sem sair da area do texto (tudo legivel dentro do card)."""
    try:
        label.texture_update()
        text_w = float(label.texture_size[0] or 0)
        if text_w <= 0:
            return 1.0
        wraps = label.text_size[0] is not None
        available = float(label.width) if wraps else float(label.width) + dp(10)
        return max(1.0, min(factor, available / text_w))
    except Exception:
        return 1.0


def _attach_hover_grow(label, center=False):
    """Prepara o label: hover => MAIUSCULAS + bold + crescimento (escala por canvas)."""
    label.create_property("hover_scale", 1.0)
    label._hover_on = False
    label._normal_text = label.text
    label._was_markup = label.markup

    def _reserve(wrap, lb=label):
        base = lb._normal_text if lb._hover_on else lb.text
        return _measure_label(lb, _hover_markup_for(lb, base, was_markup=lb._was_markup if lb._hover_on else None), wrap)

    label._hover_reserve = _reserve

    def _track(instance, value):
        if not instance._hover_on:
            instance._normal_text = value

    label.bind(text=_track)

    with label.canvas.before:
        PushMatrix()
        label._grow_scale = Scale(1, 1, 1)
    with label.canvas.after:
        PopMatrix()

    def _sync(*_args):
        ox = label.center_x if center else label.x + dp(1)
        label._grow_scale.origin = (ox, label.center_y)
        scale = float(label.hover_scale)
        label._grow_scale.xyz = (scale, scale, 1)

    label.bind(pos=_sync, size=_sync, hover_scale=_sync)
    _sync()
    # recalcula o tamanho reservado agora que o perfil de hover existe
    Clock.schedule_once(lambda _dt: getattr(label, "_relayout", lambda: None)(), 0)
    return label


def _decorate_pill(widget, bg_color, border_color=None, radius=dp(18)):
    with widget.canvas.before:
        widget._pill_bg_color = Color(*_rgba(bg_color))
        widget._pill_bg_rect = RoundedRectangle(radius=[radius, radius, radius, radius])
    if border_color is not None:
        with widget.canvas.after:
            widget._pill_border_color = Color(*_rgba(border_color))
            widget._pill_border_line = Line(width=1.0)

    def _update(*_args):
        pos = widget.pos
        size = widget.size
        widget._pill_bg_rect.pos = pos
        widget._pill_bg_rect.size = size
        if hasattr(widget, "_pill_border_line"):
            widget._pill_border_line.rounded_rectangle = (
                pos[0],
                pos[1],
                size[0],
                size[1],
                radius,
            )

    widget.bind(pos=_update, size=_update)
    Clock.schedule_once(lambda _dt: _update(), 0)


def _build_chip(text, bg_color, text_color):
    chip = MDCard(
        size_hint=(None, None),
        size=(dp(34), dp(22)),
        radius=[dp(11), dp(11), dp(11), dp(11)],
        elevation=0,
        md_bg_color=bg_color,
    )
    label = MDLabel(
        text=str(text),
        halign="center",
        valign="middle",
        theme_text_color="Custom",
        text_color=text_color,
        font_size=dp(10.5),
        bold=True,
    )
    label.bind(size=lambda instance, value: setattr(instance, "text_size", value))
    chip.add_widget(label)
    return chip


def _collect_expiry_levels(insights):
    raw = insights.get("expiry_levels") or {}
    levels = {
        ALERT_LEVEL_VENCIDO: list(raw.get(ALERT_LEVEL_VENCIDO, []) or []),
        ALERT_LEVEL_CRITICO: list(raw.get(ALERT_LEVEL_CRITICO, []) or []),
        ALERT_LEVEL_ALTO: list(raw.get(ALERT_LEVEL_ALTO, []) or []),
        ALERT_LEVEL_MEDIO: list(raw.get(ALERT_LEVEL_MEDIO, []) or []),
        ALERT_LEVEL_LEVE: list(raw.get(ALERT_LEVEL_LEVE, []) or []),
    }
    if not any(levels.values()):
        levels[ALERT_LEVEL_CRITICO] = list(insights.get("expiring_7", []) or [])
        levels[ALERT_LEVEL_ALTO] = list(insights.get("expiring_15", []) or [])
    return levels


def _expiry_level_meta(level):
    level = str(level or "").lower()
    color = ALERT_COLORS.get(level, ALERT_COLORS[ALERT_LEVEL_LEVE])["rgba"]
    if level == ALERT_LEVEL_VENCIDO:
        return "alert-octagon", _tx("Produtos vencidos"), color
    if level == ALERT_LEVEL_CRITICO:
        return "alert-circle", _tx("Vencem em breve"), color
    if level == ALERT_LEVEL_ALTO:
        return "alert", _tx("Validade próxima"), color
    if level == ALERT_LEVEL_MEDIO:
        return "calendar-alert", _tx("Validades a acompanhar"), color
    return "calendar-clock", _tx("Validades a acompanhar"), color


def _get_stock_message_variant(item_name, stock, unit, days_left):
    quantity = _format_banner_quantity(stock, unit)
    try:
        is_out_of_stock = float(stock) <= 0
    except (TypeError, ValueError):
        is_out_of_stock = False

    if is_out_of_stock or float(days_left or 0) < 0:
        return f"{item_name}: stock esgotado. Reponha assim que possível."
    return f"{item_name}: restam {quantity}. Planeie a reposição."


def _get_stock_action(item_name, stock, days_left):
    """Devolve uma ação operacional sem repetir o diagnóstico do banner."""
    try:
        stock_value = float(stock or 0)
    except (TypeError, ValueError):
        stock_value = 0.0
    try:
        coverage_days = float(days_left)
    except (TypeError, ValueError):
        coverage_days = None

    if stock_value <= 0 or (coverage_days is not None and coverage_days < 0):
        return f"Registe a encomenda de {item_name} e confirme a data de entrega."
    if coverage_days is not None and coverage_days <= 2:
        return f"Priorize a encomenda de {item_name} hoje e confirme o prazo com o fornecedor."
    return f"Programe a compra de {item_name} e confirme preço e disponibilidade com o fornecedor."


def _get_expiry_message_variant(item_name, days_left, date_str):
    if days_left <= 2:
        return (
            f"{item_name}: vence em {_format_banner_days(days_left)} ({date_str}). "
            "Dê prioridade à venda."
        )
    if days_left <= 7:
        return (
            f"{item_name}: vence em {_format_banner_days(days_left)} ({date_str}). "
            "Acompanhe a venda."
        )
    return f"{item_name}: vence em {_format_banner_days(days_left)} ({date_str})."


def _get_expiry_level_message(level, item_name, days_left, date_str):
    if level == ALERT_LEVEL_VENCIDO:
        overdue = abs(int(days_left))
        day_text = _tx("1 dia") if overdue == 1 else f"{overdue} {_tx('dias')}"
        return f"{item_name}: {_tx('vencido há')} {day_text} ({date_str}). {_tx('Retire da venda.')}"
    return _get_expiry_message_variant(item_name, days_left, date_str)


def _stable_banner_source_key(kind, rows, level=None):
    """Build a deterministic identity independent of random display wording."""
    normalized_rows = []
    for row in list(rows or []):
        if isinstance(row, dict):
            normalized = tuple(
                sorted((str(key), str(value)) for key, value in row.items())
            )
        elif isinstance(row, (list, tuple)):
            normalized = tuple(str(value) for value in row)
        else:
            normalized = (str(row),)
        normalized_rows.append(normalized)
    normalized_rows.sort(key=repr)
    return repr((str(kind or ""), str(level or ""), tuple(normalized_rows)))


def build_auto_banner_data(insights):
    banners = []
    low_stock = insights.get("low_stock", [])
    expiry_levels = _collect_expiry_levels(insights)
    fraud_alerts = [
        dict(item)
        for item in list(insights.get("fraud_alerts") or [])
        if isinstance(item, dict)
    ]

    if fraud_alerts:
        def _fraud_severity(item):
            try:
                return int(item.get("severity") or 0)
            except (AttributeError, TypeError, ValueError):
                return 0

        fraud_alerts.sort(key=_fraud_severity, reverse=True)
        max_severity = _fraud_severity(fraud_alerts[0])
        severity_label = {3: "ALTO", 2: "MEDIO", 1: "BAIXO"}
        messages = []
        for item in fraud_alerts:
            label = severity_label.get(_fraud_severity(item), "INFO")
            title = str(item.get("title") or item.get("alert_type") or "Alerta")
            messages.append(f"{label}: {title}")
        banners.append(
            {
                "kind": "fraud",
                "variant": "danger" if max_severity >= 3 else "warning" if max_severity == 2 else "info",
                "icon": "shield-alert-outline" if max_severity >= 3 else "shield-search-outline",
                "bg_color": (0.93, 0.34, 0.34, 1) if max_severity >= 3 else (0.98, 0.76, 0.34, 1),
                "title": _tx("Alertas de fraude"),
                "messages": messages[:5],
                "all_messages": messages,
                "count": len(fraud_alerts),
                "urgency": 0 if max_severity >= 3 else 10 if max_severity == 2 else 30,
                "notification_key": _stable_banner_source_key("fraud", fraud_alerts),
                "action_buttons": [
                    {"text": "PDF", "dismiss_after": False, "export_pdf": True},
                ],
            }
        )

    if low_stock:
        messages = []
        urgency_levels = []
        for item in low_stock:
            if isinstance(item, (list, tuple)) and len(item) >= 4:
                name, stock, is_weight, days_left = item[:4]
                unit = "quilogramas" if is_weight else "unidades"
                messages.append(_get_stock_message_variant(name, stock, unit, days_left))
                urgency_levels.append(days_left)

        min_days = min(urgency_levels) if urgency_levels else 999
        if min_days < 1:
            title = _tx("Produtos sem estoque")
            icon = "alert-circle"
        elif min_days < 10:
            title = _tx("Produtos com estoque baixo")
            icon = "alert"
        else:
            title = _tx("Produtos com estoque baixo")
            icon = "information-outline"

        unique_msgs = []
        seen_m = set()
        for msg in messages:
            key = msg.split(":")[0].strip().casefold()
            if key in seen_m:
                continue
            seen_m.add(key)
            unique_msgs.append(msg)
        real_count = len(unique_msgs) if unique_msgs else len(low_stock)
        summary = unique_msgs[0] if unique_msgs else _tx("Stock a acompanhar.")
        if real_count > 1:
            summary = f"{summary} {_tx('Há mais')} {real_count - 1} {_tx('para consultar nos detalhes.')}"
        banners.append(
            {
                "kind": "stock",
                "variant": "danger" if min_days < 1 else "warning" if min_days < 20 else "info",
                "icon": icon,
                "bg_color": (1, 0.4, 0.4, 1),
                "title": title,
                "messages": (unique_msgs[:2] or [summary]),
                "all_messages": (unique_msgs or [summary]),
                "count": real_count,
                "urgency": min_days,
                "notification_key": _stable_banner_source_key("stock", low_stock),
                "action_buttons": [
                    {"text": "PDF", "dismiss_after": False, "export_pdf": True},
                ],
            }
        )

    expiry_order = [
        ALERT_LEVEL_VENCIDO,
        ALERT_LEVEL_CRITICO,
        ALERT_LEVEL_ALTO,
        ALERT_LEVEL_MEDIO,
        ALERT_LEVEL_LEVE,
    ]
    for level in expiry_order:
        rows = expiry_levels.get(level) or []
        if not rows:
            continue
        icon, title, bg_color = _expiry_level_meta(level)
        unique_rows = []
        seen_names = set()
        urgencies = []
        for row in rows:
            if not isinstance(row, (list, tuple)) or len(row) < 5:
                continue
            name, days_left, date_str, stock, unit = row[:5]
            key = str(name or "").strip().casefold()
            if not key or key in seen_names:
                continue
            seen_names.add(key)
            unique_rows.append((name, days_left, date_str, stock, unit))
            urgencies.append(days_left)
        real_count = len(unique_rows)
        if real_count == 0:
            continue
        # Uma linha de resumo no cabecalho; lista completa so nos detalhes
        top = unique_rows[0]
        row_messages = [
            _get_expiry_level_message(level, r[0], r[1], r[2]) for r in unique_rows
        ]
        summary = _get_expiry_level_message(level, top[0], top[1], top[2])
        if real_count > 1:
            summary = f"{summary} {_tx('Há mais')} {real_count - 1} {_tx('para consultar nos detalhes.')}"
        banners.append(
            {
                "kind": "expiry",
                "variant": "danger" if level in (ALERT_LEVEL_VENCIDO, ALERT_LEVEL_CRITICO) else "warning" if level in (ALERT_LEVEL_ALTO, ALERT_LEVEL_MEDIO) else "info",
                "expiry_level": level,
                "icon": icon,
                "bg_color": bg_color,
                "title": title,
                "messages": (row_messages[:2] or [summary]),
                "all_messages": (row_messages or [summary]),
                "count": real_count,
                "urgency": min(urgencies) if urgencies else 999,
                "notification_key": _stable_banner_source_key("expiry", unique_rows, level=level),
                "action_buttons": [
                    {"text": "PDF", "dismiss_after": False, "export_pdf": True},
                ],
            }
        )

    if not low_stock and not fraud_alerts and not any(bool(expiry_levels.get(level)) for level in expiry_order):
        banners.append(build_positive_banner("all"))

    banners.sort(key=lambda item: item.get("urgency", 999))
    return banners


def build_positive_banner(kind="all"):
    if kind == "stock":
        return {
            "kind": "stock_ok",
            "variant": "success",
            "icon": "check-circle",
            "bg_color": (0.74, 0.92, 0.78, 1),
            "title": "Stock",
            "messages": [
                "Sem produtos com stock baixo.",
            ],
            "count": 0,
            "urgency": 999,
            "notification_key": "positive:stock",
        }
    if kind == "expiry":
        return {
            "kind": "expiry_ok",
            "variant": "success",
            "icon": "check-circle",
            "bg_color": (0.74, 0.92, 0.78, 1),
            "title": "Validades",
            "messages": [
                "Sem produtos com validade proxima.",
            ],
            "count": 0,
            "urgency": 999,
            "notification_key": "positive:expiry",
        }
    return {
        "kind": "positive",
        "variant": "success",
        "icon": "check-circle",
        "bg_color": (0.74, 0.92, 0.78, 1),
        "title": "Sem alertas",
        "messages": [
            "Sem alertas de stock.",
            "Sem alertas de validade.",
        ],
        "count": 0,
        "urgency": 999,
        "notification_key": "positive:all",
    }


def build_banner_details_sections(insights, kind, max_lines=None, expiry_level=None):
    """Secoes estruturadas sem repetir o texto do cabecalho do banner."""
    del max_lines
    sections = []
    insights = insights or {}

    if kind == "stock":
        low_stock = insights.get("low_stock") or []
        product_lines = []
        seen = set()
        for item in low_stock:
            if not isinstance(item, (list, tuple)) or len(item) < 4:
                continue
            name, stock, is_weight, days_left = item[:4]
            key = str(name or "").strip().casefold()
            if not key or key in seen:
                continue
            seen.add(key)
            unit = "quilogramas" if is_weight else "unidades"
            quantity = _format_banner_quantity(stock, unit)
            try:
                stock_v = float(stock or 0)
            except (TypeError, ValueError):
                stock_v = 0.0
            try:
                days_v = float(days_left)
            except (TypeError, ValueError):
                days_v = None
            if stock_v <= 0 or (days_v is not None and days_v < 0):
                product_lines.append(f"{name}  ·  esgotado  ·  {quantity}")
            elif days_v is not None and days_v <= 2:
                product_lines.append(
                    f"{name}  ·  critico ({_format_banner_days(days_v)})  ·  {quantity}"
                )
            else:
                coverage = _format_banner_days(days_v) if days_v is not None else "—"
                product_lines.append(f"{name}  ·  cobertura {coverage}  ·  {quantity}")
        if product_lines:
            sections.append(("Produtos", product_lines))
            sections.append((
                "Acao",
                [
                    "Priorize a reposição dos itens esgotados e críticos.",
                    "Confirme preço e prazo com o fornecedor ainda hoje.",
                ],
            ))

    elif kind == "expiry":
        expiry_levels = _collect_expiry_levels(insights)
        level_meta = {
            ALERT_LEVEL_VENCIDO: "Vencidos",
            ALERT_LEVEL_CRITICO: "Críticos (≤2 dias)",
            ALERT_LEVEL_ALTO: "Altos (≤7 dias)",
            ALERT_LEVEL_MEDIO: "Médios",
            ALERT_LEVEL_LEVE: "Leves",
        }
        level_order = [
            ALERT_LEVEL_VENCIDO,
            ALERT_LEVEL_CRITICO,
            ALERT_LEVEL_ALTO,
            ALERT_LEVEL_MEDIO,
            ALERT_LEVEL_LEVE,
        ]
        if expiry_level in level_meta:
            level_order = [expiry_level]

        any_rows = False
        for level in level_order:
            rows = expiry_levels.get(level) or []
            if not rows:
                continue
            lines_out = []
            seen = set()
            for row in rows:
                if not isinstance(row, (list, tuple)) or len(row) < 5:
                    continue
                name, days_left, date_str, stock, unit = row[:5]
                key = str(name or "").strip().casefold()
                if not key or key in seen:
                    continue
                seen.add(key)
                quantity = _format_banner_quantity(stock, unit)
                try:
                    days_i = int(days_left)
                except (TypeError, ValueError):
                    days_i = 0
                if days_i <= 0:
                    lines_out.append(f"{name}  ·  desde {date_str}  ·  {quantity}")
                else:
                    lines_out.append(
                        f"{name}  ·  {_format_banner_days(days_i)} ({date_str})  ·  {quantity}"
                    )
            if lines_out:
                any_rows = True
                sections.append((level_meta[level], lines_out))

        if any_rows:
            if expiry_level == ALERT_LEVEL_VENCIDO or (
                expiry_level is None and (expiry_levels.get(ALERT_LEVEL_VENCIDO) or [])
            ):
                sections.append((
                    "Acao",
                    [
                        "Retire da venda todos os itens vencidos.",
                        "Registe perdas com evidencia e atualize o stock.",
                    ],
                ))
            else:
                sections.append((
                    "Acao",
                    [
                        "Priorize a venda dos itens mais próximos do vencimento.",
                        "Considere promoção rápida se o stock for elevado.",
                    ],
                ))

    elif kind == "fraud":
        fraud_alerts = [
            dict(item)
            for item in list(insights.get("fraud_alerts") or [])
            if isinstance(item, dict)
        ]
        if fraud_alerts:
            lines_out = []
            seen = set()
            for item in fraud_alerts:
                title = str(item.get("title") or item.get("alert_type") or "Alerta").strip()
                detail = str(item.get("detail") or item.get("message") or "").strip()
                key = title.casefold()
                if key in seen:
                    continue
                seen.add(key)
                if detail and detail.casefold() != key:
                    lines_out.append(f"{title}  ·  {detail}")
                else:
                    lines_out.append(title)
            if lines_out:
                sections.append(("Alertas", lines_out))
                sections.append((
                    "Acao",
                    ["Reveja os registos assinalados e confirme a operação com a equipa."],
                ))

    return sections


class _BannerModalBlocker(Widget):
    """Camada modal: escurece e bloqueia todo o ecrã por baixo dos banners."""

    scrim = NumericProperty(0.0)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        with self.canvas:
            self._scrim_color = Color(0, 0, 0, 0)
            self._scrim_rect = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._sync, size=self._sync, scrim=self._sync)

    def _sync(self, *_args):
        self._scrim_color.rgba = (0, 0, 0, float(self.scrim))
        self._scrim_rect.pos = self.pos
        self._scrim_rect.size = self.size

    # Consome SEMPRE os toques (clique, arrasto, roda do rato): nada passa para baixo.
    def on_touch_down(self, touch):
        return True

    def on_touch_move(self, touch):
        return True

    def on_touch_up(self, touch):
        return True


class _PillIcon(Widget):
    """Ícone fino desenhado em canvas para os botões (chevron / download)."""

    def __init__(self, kind="chevron_down", color=(1, 1, 1, 1), **kwargs):
        super().__init__(size_hint=(None, None), size=(dp(16), dp(16)), **kwargs)
        self.kind = kind
        self.color = _rgba(color)
        self.bind(pos=self._draw, size=self._draw)

    def set_kind(self, kind):
        if kind != self.kind:
            self.kind = kind
            self._draw()

    def _draw(self, *_args):
        self.canvas.clear()
        cx, cy = self.center_x, self.center_y
        a = dp(4.2)
        w = dp(1.4)
        with self.canvas:
            Color(self.color[0], self.color[1], self.color[2], 0.95)
            if self.kind == "chevron_up":
                Line(points=[cx - a, cy - a * 0.5, cx, cy + a * 0.5, cx + a, cy - a * 0.5],
                     width=w, cap="round", joint="round")
            elif self.kind == "download":
                Line(points=[cx, cy + a, cx, cy - a * 0.7], width=w, cap="round")
                Line(points=[cx - a * 0.8, cy - a * 0.1, cx, cy - a * 0.9, cx + a * 0.8, cy - a * 0.1],
                     width=w, cap="round", joint="round")
                Line(points=[cx - a, cy - a * 1.5, cx + a, cy - a * 1.5], width=w, cap="round")
            else:
                Line(points=[cx - a, cy + a * 0.5, cx, cy - a * 0.5, cx + a, cy + a * 0.5],
                     width=w, cap="round", joint="round")


class _ActionPill(ButtonBehavior, BoxLayout):
    """Botão em pílula: [ícone] [texto] [+N]. Mesma altura e estilo para todos."""

    def __init__(self, text="", icon_kind=None, color=(1, 1, 1, 1), bg=None, border=None, **kwargs):
        super().__init__(
            orientation="horizontal",
            spacing=dp(7),
            padding=[dp(12), 0, dp(14), 0],
            size_hint=(None, None),
            height=dp(34),
            **kwargs,
        )
        self._color = _rgba(color)
        self.chip = None
        self._count = 0
        self.icon = None
        if icon_kind:
            self.icon = _PillIcon(icon_kind, color, pos_hint={"center_y": 0.5})
            self.add_widget(self.icon)
        self.label = MDLabel(
            text=str(text),
            theme_text_color="Custom",
            text_color=color,
            font_size=dp(12),
            bold=True,
            halign="center",
            valign="middle",
            pos_hint={"center_y": 0.5},
        )
        _bind_texture_size(self.label, min_height=dp(18), horizontal_padding=dp(2))
        self.add_widget(self.label)
        self.bind(minimum_width=lambda inst, value: setattr(inst, "width", value))
        if bg is not None:
            _decorate_pill(self, bg, border, radius=dp(17))

    def set_text(self, text):
        _set_label_text(self.label, text)

    def set_count(self, count, bg, color):
        count = int(count or 0)
        if count == self._count:
            return
        self._count = count
        if self.chip is not None:
            self.remove_widget(self.chip)
            self.chip = None
        if count > 0:
            label = f"+{count}"
            self.chip = _build_chip(label, bg, color)
            self.chip.width = max(dp(30), dp(12 + 6.6 * len(label)))
            self.chip.pos_hint = {"center_y": 0.5}
            self.add_widget(self.chip)


class _BannerStatusIcon(Widget):
    """Ícone de estado desenhado em canvas (sem depender de fontes)."""

    _SHAPE_BY_KIND = {
        "stock": "box",
        "expiry": "calendar",
        "fraud": "shield",
        "positive": "success",
        "stock_ok": "success",
        "expiry_ok": "success",
    }

    def __init__(self, variant="info", color=(1, 1, 1, 1), kind=None, **kwargs):
        super().__init__(**kwargs)
        self.variant = variant
        self.kind = kind
        self.color = _rgba(color)
        self.bind(pos=self._draw, size=self._draw)

    def _draw(self, *_args):
        self.canvas.clear()
        s = min(self.width, self.height) * 0.32
        if s <= 0:
            return
        shape = self._SHAPE_BY_KIND.get(str(self.kind or ""), self.variant)
        cx, cy = self.center_x, self.center_y
        w = max(dp(1.3), s * 0.09)
        dot = max(dp(2.2), s * 0.16)
        with self.canvas:
            Color(self.color[0], self.color[1], self.color[2], 0.92)
            if shape == "calendar":
                Line(rounded_rectangle=(cx - s, cy - s * 0.85, s * 2, s * 1.8, dp(3)), width=w)
                Line(points=[cx - s, cy + s * 0.3, cx + s, cy + s * 0.3], width=w)
                Line(points=[cx - s * 0.5, cy + s * 0.75, cx - s * 0.5, cy + s * 1.15], width=w, cap="round")
                Line(points=[cx + s * 0.5, cy + s * 0.75, cx + s * 0.5, cy + s * 1.15], width=w, cap="round")
                Line(points=[cx, cy - s * 0.02, cx, cy - s * 0.32], width=w, cap="round")
                Ellipse(pos=(cx - dot / 2, cy - s * 0.58 - dot / 2), size=(dot, dot))
            elif shape == "box":
                Line(rounded_rectangle=(cx - s, cy - s * 0.8, s * 2, s * 1.6, dp(3)), width=w)
                Line(points=[cx - s, cy + s * 0.2, cx + s, cy + s * 0.2], width=w)
                Line(points=[cx - s * 0.35, cy - s * 0.25, cx + s * 0.35, cy - s * 0.25], width=w, cap="round")
            elif shape == "shield":
                Line(points=[cx, cy + s, cx + s * 0.85, cy + s * 0.62, cx + s * 0.85, cy - s * 0.1,
                             cx, cy - s, cx - s * 0.85, cy - s * 0.1, cx - s * 0.85, cy + s * 0.62],
                     close=True, width=w, joint="round")
                Line(points=[cx, cy + s * 0.35, cx, cy - s * 0.15], width=w, cap="round")
                Ellipse(pos=(cx - dot / 2, cy - s * 0.42 - dot / 2), size=(dot, dot))
            elif shape == "success":
                Line(circle=(cx, cy, s), width=w)
                Line(points=[cx - s * 0.42, cy, cx - s * 0.1, cy - s * 0.32, cx + s * 0.45, cy + s * 0.34],
                     width=w, cap="round", joint="round")
            elif shape == "warning":
                Line(points=[cx, cy + s, cx + s * 1.05, cy - s * 0.7, cx - s * 1.05, cy - s * 0.7],
                     close=True, width=w, joint="round")
                Line(points=[cx, cy + s * 0.32, cx, cy - s * 0.18], width=w, cap="round")
                Ellipse(pos=(cx - dot / 2, cy - s * 0.46 - dot / 2), size=(dot, dot))
            elif shape == "danger":
                Line(circle=(cx, cy, s), width=w)
                Line(points=[cx, cy + s * 0.5, cx, cy - s * 0.1], width=w, cap="round")
                Ellipse(pos=(cx - dot / 2, cy - s * 0.42 - dot / 2), size=(dot, dot))
            else:  # info
                Line(circle=(cx, cy, s), width=w)
                Ellipse(pos=(cx - dot / 2, cy + s * 0.42 - dot / 2), size=(dot, dot))
                Line(points=[cx, cy + s * 0.12, cx, cy - s * 0.5], width=w, cap="round")


_EMPHASIS_RE = re.compile(
    r"\d+(?:[.,]\d+)?\s*(?:unidades?|units?|quilogramas?|quilos?|kg|dias?|days?|MZN)\b"
    r"|\b(?:out of stock|esgotado|vencido|expired|cr[ií]tico|critical|"
    r"restam|remaining|vence em|expires in|poss[ií]vel perda)\b",
    re.IGNORECASE,
)


class ModernBannerCard(MDCard):
    def __init__(self, banner_data, show_timer=True, insights=None, **kwargs):
        self.banner_data = dict(banner_data or {})
        # Banner payloads may be cached or produced before the current UI
        # language was selected.  Localise at the rendering boundary so that
        # live product data stays intact while every surrounding UI phrase
        # follows the active language.
        if self.banner_data.get("title"):
            self.banner_data["title"] = _tx(self.banner_data["title"])
        for field in ("messages", "all_messages"):
            values = self.banner_data.get(field) or []
            self.banner_data[field] = [_tx(value) for value in values]
        sections = self.banner_data.get("details_sections") or []
        self.banner_data["details_sections"] = [
            (_tx(title), [_tx(item) for item in (items or [])])
            for title, items in sections
        ]
        self.palette = _banner_palette(self.banner_data)
        self.all_messages = _clean_messages(self.banner_data.get("all_messages") or self.banner_data.get("messages") or [])
        self.details_sections = list(self.banner_data.get("details_sections") or [])
        if not self.details_sections and insights:
            self.details_sections = build_banner_details_sections(
                insights,
                self.banner_data.get("kind"),
                expiry_level=self.banner_data.get("expiry_level"),
            )
            self.details_sections = [
                (_tx(title), [_tx(item) for item in (items or [])])
                for title, items in self.details_sections
            ]
        self.full_description = self._build_description_text()
        self._grow_labels = []
        self._expanded = False
        self._compact = False
        self._preview_truncated = False
        self._has_extra_content = False
        self._window_bound = False
        # ModernBannerCard is mounted directly in the banner overlay.  Keeping
        # itself as the host lets the height updates from "Ver mais" request a
        # new centred position while the details panel is animating.
        self._wrapper = self
        self._progress = None
        self._recenter_event = None

        super().__init__(
            orientation="vertical",
            padding=0,
            spacing=0,
            # A largura e definida pelo posicionador central de banners. Sem
            # size_hint, o limite de leitura e preservado em ecras largos.
            size_hint=(None, None),
            size_hint_y=None,
            radius=[dp(18), dp(18), dp(18), dp(18)],
            elevation=self.palette["elevation"],
            md_bg_color=self.palette["bg"],
            **kwargs,
        )

        with self.canvas.after:
            self._accent_color_instruction = Color(*_rgba(self.palette["accent"], self.palette.get("bar_alpha", 0.70)))
            self._accent_bar = RoundedRectangle(radius=[dp(2), dp(2), dp(2), dp(2)])
            self._border_color_instruction = Color(*_rgba(self.palette["border"]))
            self._border_line = Line(width=1.0)

        self.insights = insights
        self._insights = insights
        self._build_ui(show_timer=show_timer)
        self.bind(size=self._handle_size_change, pos=self._update_decorations)

    def on_parent(self, _instance, parent):
        if parent is None and self._window_bound:
            try:
                Window.unbind(mouse_pos=self._handle_mouse_pos)
            except Exception:
                pass
            self._window_bound = False
            return
        if parent is not None and not self._window_bound:
            try:
                Window.bind(mouse_pos=self._handle_mouse_pos)
                self._window_bound = True
            except Exception:
                pass

    def on_touch_down(self, touch):
        handled = super().on_touch_down(touch)
        if self.collide_point(*touch.pos) and self.opacity > 0.05:
            return True  # nunca deixa o toque passar para o ecrã por baixo
        return handled

    def on_touch_move(self, touch):
        handled = super().on_touch_move(touch)
        return True if self.collide_point(*touch.pos) else handled

    def on_touch_up(self, touch):
        handled = super().on_touch_up(touch)
        return True if self.collide_point(*touch.pos) else handled

    def _grow(self, label, center=False):
        _attach_hover_grow(label, center=center)
        self._grow_labels.append(label)
        return label

    def _set_grow(self, label, on):
        if getattr(label, "_grow_on", False) == on:
            return
        label._grow_on = on
        _apply_hover_text(label, on)
        target = _fit_hover_scale(label) if on else 1.0
        Animation.cancel_all(label, "hover_scale")
        Animation(hover_scale=target, d=0.14, t="out_quad").start(label)

    def _update_word_hover(self, pos):
        active = self.opacity > 0.05 and not self.disabled
        for label in list(self._grow_labels):
            if label.parent is None:
                self._grow_labels.remove(label)
                continue
            inside = False
            if active:
                try:
                    lx, ly = label.to_widget(*pos)
                    text_w = max(float(label.texture_size[0] or 0), 1.0)
                    inside = (
                        label.x <= lx <= label.x + text_w
                        and label.y <= ly <= label.top
                    )
                except Exception:
                    inside = False
            self._set_grow(label, inside)

    def _build_description_text(self):
        if not self.all_messages:
            count = int(self.banner_data.get("count") or 0)
            return (f"{count} {_tx('itens foram agrupados neste aviso.')}" if count > 0 else _tx("Sem detalhes adicionais."))
        first = self.all_messages[0]
        first = first if first.endswith((".", "!", "?")) else f"{first}."
        count = int(self.banner_data.get("count") or 0)
        remaining = max(count - 1, len(self.all_messages) - 1)
        if remaining > 0:
            noun = _tx("ocorrencia") if remaining == 1 else _tx("ocorrencias")
            return f"{first} {_tx('Há mais')} {remaining} {noun} {_tx('para consultar nos detalhes.')}"
        # Os banners positivos podem ter dois pontos curtos e complementares.
        if len(self.all_messages) > 1:
            second = self.all_messages[1]
            second = second if second.endswith((".", "!", "?")) else f"{second}."
            return f"{first} {second}"
        return first

    @staticmethod
    def _emphasize_banner_text(text):
        raw_text = str(text or "").strip()
        if not raw_text:
            return ""
        rendered = escape_markup(raw_text)

        head = ""
        m = re.match(r"^([^:\n]{1,100}):(\s*)", rendered)
        if m:  # "Produto: ..." -> nome em negrito
            head = f"[b]{m.group(1).strip()}[/b]:{m.group(2)}"
            rendered = rendered[m.end():]
        else:
            m = re.match(r"^(.+?)(\s+·\s+)", rendered)
            if m:  # "Produto · detalhe · qtd" -> nome em negrito
                head = f"[b]{m.group(1).strip()}[/b]{m.group(2)}"
                rendered = rendered[m.end():]

        # uma só passagem, sem [b] aninhado
        rendered = _EMPHASIS_RE.sub(lambda mm: f"[b]{mm.group(0)}[/b]", rendered)
        return head + rendered

    def _build_ui(self, show_timer):
        self._content = MDBoxLayout(
            orientation="vertical",
            spacing=dp(12),
            padding=[dp(22), dp(18), dp(18), dp(16)],
            size_hint_y=None,
        )
        self._content.bind(minimum_height=self._sync_card_height)
        self.add_widget(self._content)

        self._top_row = MDBoxLayout(
            orientation="horizontal",
            spacing=dp(14),
            size_hint_y=None,
        )
        self._top_row.bind(minimum_height=_sync_box_height)
        self._content.add_widget(self._top_row)

        self._icon_shell = MDCard(
            size_hint=(None, None),
            size=(dp(46), dp(46)),
            radius=[dp(14), dp(14), dp(14), dp(14)],
            elevation=0,
            md_bg_color=self.palette["icon_bg"],
        )
        self._icon_label = _BannerStatusIcon(
            variant=self.palette["variant"],
            kind=self.banner_data.get("kind"),
            color=self.palette["button_text"],
        )
        self._icon_shell.add_widget(self._icon_label)
        # icone do cabecalho removido (o shell fica fora do layout)

        self._text_box = MDBoxLayout(
            orientation="vertical",
            spacing=dp(5),
            size_hint=(1, None),
        )
        self._text_box.bind(minimum_height=_sync_box_height)
        self._top_row.add_widget(self._text_box)

        self._title_row = MDBoxLayout(
            orientation="horizontal",
            spacing=dp(8),
            size_hint_y=None,
        )
        self._title_row.bind(minimum_height=_sync_box_height)
        self._text_box.add_widget(self._title_row)

        self._title_label = MDLabel(
            text=str(self.banner_data.get("title") or "Atualização importante"),
            theme_text_color="Custom",
            text_color=self.palette["title"],
            font_size=dp(15.5),
            bold=True,
            size_hint_y=None,
        )
        _bind_auto_height(self._title_label, dp(22))
        self._grow(self._title_label)
        self._title_row.add_widget(self._title_label)

        count = int(self.banner_data.get("count") or 0)
        self._count_chip = _build_chip(count, self.palette["chip_bg"], self.palette["button_text"]) if count > 0 else None
        if self._count_chip is not None:
            self._title_row.add_widget(self._count_chip)

        self._description_box = MDBoxLayout(
            orientation="vertical",
            spacing=dp(3),
            size_hint_y=None,
        )
        self._description_box.bind(minimum_height=_sync_box_height)
        self._text_box.add_widget(self._description_box)

        self._close_btn = _build_banner_close_button(
            lambda *_args: animate_banner_out(self._wrapper or self),
            {"button_text": self.palette["muted"], "close_bg": self.palette["icon_bg"]},
        )
        self._close_btn.pos_hint = {"top": 1}
        self._top_row.add_widget(self._close_btn)

        # Linha unica de acoes: "Ver mais" e "PDF" alinhados (mesma altura/estilo).
        self._actions_row = MDBoxLayout(
            orientation="horizontal",
            spacing=dp(8),
            padding=[0, 0, 0, 0],
            size_hint_y=None,
            height=dp(34),
        )
        self._toggle_btn = self._build_action_button()
        self._actions_row.add_widget(self._toggle_btn)
        for quick_btn in self._build_quick_actions():
            self._actions_row.add_widget(quick_btn)
        self._actions_row.add_widget(Widget())
        self._content.add_widget(self._actions_row)

        self._details_scroll = ScrollView(
            size_hint=(1, None),
            height=0,
            opacity=0,
            do_scroll_x=False,
            do_scroll_y=False,
            bar_width=0,
        )
        # The details panel changes height over several animation frames.  Keep
        # the card height and its centre in sync in every one of them.
        self._details_scroll.bind(height=self._sync_card_height)
        _apply_scroll_style(self._details_scroll)
        self._details_content = MDBoxLayout(
            orientation="vertical",
            spacing=dp(10),
            padding=[0, dp(4), 0, 0],
            size_hint=(1, None),
        )
        self._details_content.bind(minimum_height=lambda instance, value: setattr(instance, "height", value))
        self._details_content.bind(minimum_height=lambda *_args: self._on_details_content_height())
        self._details_scroll.add_widget(self._details_content)
        self._content.add_widget(self._details_scroll)

        if show_timer:
            self._progress = MDProgressBar(
                value=100,
                max=100,
                size_hint_x=1,
                size_hint_y=None,
                height=dp(3),
                color=self.palette["progress"],
            )
            # Keep the timer in the content layout.  A direct child of the
            # card can be laid out below its bounds when the banner
            # height changes, leaving the line visibly outside the banner.
            self._content.add_widget(self._progress)

        self._rebuild_details_content()
        self._refresh_expandable_state()
        Clock.schedule_once(lambda _dt: self._handle_size_change(), 0)

    def _build_quick_actions(self):
        specs = [
            spec
            for spec in (self.banner_data.get("action_buttons") or [])
            if isinstance(spec, dict) and str(spec.get("text") or "").strip()
        ][:3]
        self._quick_action_buttons = []
        for spec in specs:
            label = str(spec.get("text") or "").strip().upper()
            callback = spec.get("callback") or spec.get("on_release")
            dismiss_after = bool(spec.get("dismiss_after", True))
            export_pdf = bool(spec.get("export_pdf"))
            button = _ActionPill(
                text=label,
                icon_kind="download" if export_pdf else None,
                color=self.palette["button_text"],
                bg=self.palette["button_bg"],
                border=self.palette["border"],
            )
            button.bind(on_press=lambda instance: self._animate_button(instance, pressed=True))
            button.bind(
                on_release=lambda btn, cb=callback, close=dismiss_after, exp=export_pdf: self._run_quick_action(
                    btn, cb, close, export_pdf=exp
                )
            )
            button.bind(on_release=lambda instance: self._animate_button(instance, pressed=False))
            self._grow(button.label, center=True)
            self._quick_action_buttons.append(button)
        return self._quick_action_buttons

    def _run_quick_action(self, button, callback, dismiss_after, export_pdf=False):
        if export_pdf:
            try:
                insights = getattr(self, "_insights", None) or getattr(self, "insights", None)
                if not insights:
                    # Tenta obter insights atualizados da app
                    try:
                        from utils.ai.ai_insights import build_admin_insights
                        insights = build_admin_insights()
                    except Exception:
                        insights = {}
                path = export_banner_alerts_pdf(
                    banner_data=self.banner_data,
                    insights=insights,
                )
                app = App.get_running_app()
                if path and app and hasattr(app, "show_toast"):
                    app.show_toast(f"Relatório exportado: {path}")
                elif path:
                    old = getattr(button.label, "_normal_text", button.label.text)
                    button.set_text("OK")
                    Clock.schedule_once(lambda _dt: button.set_text(old), 1.4)
            except Exception:
                pass
            return
        if dismiss_after:
            animate_banner_out(self._wrapper or self)
        if callable(callback):
            try:
                callback()
            except TypeError:
                callback(button)

    def _sync_quick_action_widths(self):
        return

    @staticmethod
    def _bind_pill_text(button):
        def _sync_text_area(instance, size):
            instance.text_size = (max(float(size[0]) - dp(16), 1), float(size[1]))

        button.bind(size=_sync_text_area)
        Clock.schedule_once(lambda _dt: _sync_text_area(button, button.size), 0)

    def _build_action_button(self):
        button = _ActionPill(
            text=_tx("Ver mais"),
            icon_kind="chevron_down",
            color=self.palette["button_text"],
            bg=self.palette["button_bg"],
            border=self.palette["border"],
        )
        button.bind(on_press=lambda instance: self._animate_button(instance, pressed=True))
        button.bind(on_release=lambda *_args: self._toggle_details())
        button.bind(on_release=lambda instance: self._animate_button(instance, pressed=False))
        self._grow(button.label, center=True)
        return button

    def _animate_button(self, button, pressed):
        Animation.cancel_all(button)
        Animation(opacity=0.84 if pressed else 1, d=0.08 if pressed else 0.12, t="out_quad").start(button)

    def _build_section_title(self, text):
        label = MDLabel(
            text=str(text or ""),
            theme_text_color="Custom",
            text_color=self.palette["title"],
            font_size=dp(12.2),
            bold=True,
            size_hint_y=None,
        )
        _bind_auto_height(label, dp(18))
        return self._grow(label)

    def _build_text_block(self, text):
        label = MDLabel(
            text=self._emphasize_banner_text(text),
            markup=True,
            theme_text_color="Custom",
            text_color=self.palette["text"],
            font_size=dp(12.6),
            line_height=1.22,
            size_hint_y=None,
        )
        _bind_auto_height(label, dp(22))
        return self._grow(label)

    def _build_bullet_text(self, text):
        label = MDLabel(
            text=f"• {self._emphasize_banner_text(text)}",
            markup=True,
            theme_text_color="Custom",
            text_color=self.palette["text"],
            font_size=dp(12.2),
            line_height=1.18,
            size_hint_y=None,
        )
        _bind_auto_height(label, dp(18))
        return self._grow(label)

    def _shown_messages(self):
        msgs = _clean_messages(self.banner_data.get("messages") or self.all_messages)
        return msgs[:3]

    def _hidden_count(self):
        shown = len(self._shown_messages())
        count = int(self.banner_data.get("count") or 0)
        return max(count - shown, len(self.all_messages) - shown, 0)

    def _refresh_expandable_state(self):
        shown = self._shown_messages()
        self._preview_truncated = False
        self._has_extra_content = bool(self.details_sections or self._hidden_count() > 0)
        if shown:
            lines = [f"• {self._emphasize_banner_text(msg)}" for msg in shown]
        else:
            lines = [self._emphasize_banner_text(self.full_description)]
        signature = tuple(lines)
        if signature != getattr(self, "_desc_signature", None):
            self._desc_signature = signature
            self._description_box.clear_widgets()
            for line in lines:
                self._description_box.add_widget(self._make_description_line(line))
        self._apply_action_button_state()

    def _make_description_line(self, markup_text):
        label = MDLabel(
            text=markup_text,
            markup=True,
            theme_text_color="Custom",
            text_color=self.palette["text"],
            font_size=dp(12.8),
            line_height=1.22,
            size_hint_y=None,
        )
        _bind_auto_height(label, dp(20))
        return self._grow(label)

    def _apply_action_button_state(self):
        label = _tx("Ver menos") if self._expanded else _tx("Ver mais")
        self._toggle_btn.set_text(label)
        self._toggle_btn.icon.set_kind("chevron_up" if self._expanded else "chevron_down")
        self._toggle_btn.set_count(
            0 if self._expanded else self._hidden_count(),
            self.palette["chip_bg"],
            self.palette["button_text"],
        )

        visible = bool(self._has_extra_content)
        in_row = self._toggle_btn.parent is not None
        if visible and not in_row:
            self._actions_row.add_widget(self._toggle_btn, index=len(self._actions_row.children))
        elif not visible and in_row:
            self._actions_row.remove_widget(self._toggle_btn)

        has_row = visible or bool(getattr(self, "_quick_action_buttons", []))
        self._actions_row.height = dp(34) if has_row else 0
        self._actions_row.opacity = 1 if has_row else 0

    def _rebuild_details_content(self):
        self._details_content.clear_widgets()

        extra = self.all_messages[len(self._shown_messages()):]
        if extra and not self.details_sections:
            self._details_content.add_widget(self._build_section_title(_tx("Pontos observados")))
            for message in extra:
                self._details_content.add_widget(self._build_bullet_text(message))

        for title, items in self.details_sections:
            if not items:
                continue
            self._details_content.add_widget(self._build_section_title(title))
            for item in items:
                self._details_content.add_widget(self._build_bullet_text(item))

    def _toggle_details(self, *_args):
        if not self._has_extra_content:
            return

        self._expanded = not self._expanded
        target_height = self._details_target_height() if self._expanded else 0

        Animation.cancel_all(self._details_scroll)
        if self._expanded:
            self._details_scroll.opacity = 1
            self._details_scroll.height = max(float(target_height or 0), float(dp(72)))
        Animation(
            height=target_height,
            opacity=1 if self._expanded else 0,
            d=0.18,
            t="out_cubic",
        ).start(self._details_scroll)

        if self._expanded:
            self._pause_auto_dismiss()
            Clock.schedule_once(self._stabilize_expanded_details, 0)
            Clock.schedule_once(self._stabilize_expanded_details, 0.08)
            container = getattr(self._wrapper, "_banner_container", None)
            if container is not None and self._wrapper is not None:
                Clock.schedule_once(
                    lambda _dt, current=container, widget=self._wrapper: _scroll_banner_into_view(current, widget),
                    0.10,
                )
        else:
            self._resume_auto_dismiss()
        self._apply_action_button_state()

    def _stabilize_expanded_details(self, *_args):
        if not self._expanded:
            return
        target_height = self._details_target_height()
        if target_height <= 0:
            return
        self._details_scroll.opacity = 1
        self._details_scroll.height = target_height
        self._sync_card_height()

    def _pause_auto_dismiss(self):
        wrapper = self._wrapper
        if not wrapper:
            return
        _cancel_event(getattr(wrapper, "_auto_dismiss_ev", None))
        wrapper._auto_dismiss_ev = None
        if self._progress is not None:
            Animation.cancel_all(self._progress)
        wrapper._auto_paused = True

    def _resume_auto_dismiss(self):
        wrapper = self._wrapper
        if not wrapper or not getattr(wrapper, "_auto_paused", False):
            return
        wrapper._auto_paused = False
        auto_dismiss_seconds = getattr(wrapper, "_auto_dismiss_seconds", None)
        if not auto_dismiss_seconds:
            return
        if self._progress is not None and getattr(wrapper, "_auto_show_timer", False):
            self._progress.value = 100
            Animation(value=0, d=auto_dismiss_seconds, t="linear").start(self._progress)
        wrapper._auto_dismiss_ev = Clock.schedule_once(
            lambda _dt, current=wrapper: animate_banner_out(current),
            auto_dismiss_seconds,
        )

    def _animate_icon_intro(self):
        Animation.cancel_all(self._icon_label)
        (
            Animation(opacity=0.72, d=0.10, t="out_quad")
            + Animation(opacity=1, d=0.18, t="out_quad")
        ).start(self._icon_label)

    def _handle_mouse_pos(self, _window, pos):
        if not self.get_root_window():
            return
        self._update_word_hover(pos)
        local = self.to_widget(*pos)
        hovered = self.collide_point(*local)
        if hovered and not getattr(self, "_hovered", False):
            self._hovered = True
            # The card is positioned by the central banner layout.  Moving its
            # ``y`` on hover placed an expanded banner at the bottom of the
            # overlay, so the hover feedback must not change its position.
            Animation.cancel_all(self, "elevation")
            Animation(elevation=self.palette["hover_elevation"], d=0.18, t="out_quad").start(self)
        elif not hovered and getattr(self, "_hovered", False):
            self._hovered = False
            Animation.cancel_all(self, "elevation")
            Animation(elevation=self.palette["elevation"], d=0.18, t="out_quad").start(self)

    def _handle_size_change(self, *_args):
        self._compact = self.width < dp(620)
        self._content.padding = [dp(18), dp(16), dp(16), dp(14)] if self._compact else [dp(22), dp(18), dp(18), dp(16)]
        self._top_row.spacing = dp(10) if self._compact else dp(14)
        self._icon_shell.size = (dp(40), dp(40)) if self._compact else (dp(46), dp(46))
        self._icon_shell.radius = [dp(12)] * 4 if self._compact else [dp(14)] * 4
        self._actions_row.padding = [0, 0, 0, 0]
        self._refresh_expandable_state()
        if self._expanded:
            self._details_scroll.height = self._details_target_height()
        self._update_decorations()

    def _update_decorations(self, *_args):
        accent_x = self.x + dp(12)
        accent_y = self.y + dp(14)
        self._accent_bar.pos = (accent_x, accent_y)
        self._accent_bar.size = (dp(3), max(dp(40), self.height - dp(28)))
        self._border_line.rounded_rectangle = (
            self.x + 0.5,
            self.y + 0.5,
            max(self.width - 1, 0),
            max(self.height - 1, 0),
            dp(18),
        )

    def _on_details_content_height(self, *_args):
        if self._expanded:
            self._details_scroll.height = self._details_target_height()
        self._sync_card_height()

    def _details_target_height(self):
        content_height = float(self._details_content.height or 0)
        if content_height <= 0:
            self._details_scroll.do_scroll_y = False
            self._details_scroll.bar_width = 0
            return 0

        if self.width >= dp(860):
            max_height = dp(260)
        elif self.width >= dp(620):
            max_height = dp(220)
        else:
            max_height = dp(176)

        scrollable = content_height > (max_height + dp(2))
        self._details_scroll.do_scroll_y = scrollable
        self._details_scroll.bar_width = dp(2) if scrollable else 0
        return min(content_height, max_height)

    def _sync_card_height(self, *_args):
        self._content.height = self._content.minimum_height
        self.height = self._content.height
        self._schedule_recenter()

    def _schedule_recenter(self):
        wrapper = self._wrapper or self
        container = getattr(wrapper, "_banner_container", None)
        if container is None or self._recenter_event is not None:
            return

        def _recenter(_dt, current=container, widget=wrapper):
            self._recenter_event = None
            visible = _visible_widgets(current)
            if widget in visible:
                position_banners_center(current, visible, reset_x=False)

        self._recenter_event = Clock.schedule_once(_recenter, 0)


def _visible_widgets(container):
    widgets = getattr(container, "_ai_banner_widgets", []) if container else []
    return [w for w in widgets if w and w.parent and not getattr(w, "_is_hidden", False)]


def _cancel_batch_events(container):
    if not container:
        return
    for event in getattr(container, "_ai_batch_events", []) or []:
        _cancel_event(event)
    container._ai_batch_events = []


def _cancel_render_event(container):
    if not container:
        return
    _cancel_event(getattr(container, "_ai_render_ev", None))
    container._ai_render_ev = None


def _cancel_banner_widget(widget):
    if not widget:
        return
    _cancel_event(getattr(widget, "_position_retry_ev", None))
    widget._position_retry_ev = None
    _cancel_event(getattr(widget, "_auto_dismiss_ev", None))
    widget._auto_dismiss_ev = None
    card = getattr(widget, "_banner_card", None)
    if card is not None:
        Animation.cancel_all(widget)
        Animation.cancel_all(card)
        if getattr(card, "_progress", None) is not None:
            Animation.cancel_all(card._progress)
    else:
        Animation.cancel_all(widget)
        if getattr(widget, "_progress", None) is not None:
            Animation.cancel_all(widget._progress)


def clear_banner_container(container):
    if not container:
        return
    _cancel_render_event(container)
    _cancel_batch_events(container)
    for widget in list(getattr(container, "_ai_banner_widgets", []) or []):
        _cancel_banner_widget(widget)
    container._ai_banner_widgets = []
    _release_modal_blocker(container)
    container.clear_widgets()
    container._ai_banner_host = None
    container._ai_banner_shell = None
    container._ai_banner_scroll = None
    container._ai_banner_stack = None
    recenter = getattr(container, "_ai_banner_recenter", None)
    if recenter is not None:
        try:
            container.unbind(size=recenter)
            Window.unbind(size=recenter)
        except Exception:
            pass
        container._ai_banner_recenter = None


def _ensure_modal_blocker(container):
    """Bloqueia o ecrã por baixo dos banners: sem cliques, sem scroll, nada se move."""
    if not container:
        return None
    blocker = getattr(container, "_ai_banner_blocker", None)
    if blocker is None:
        blocker = _BannerModalBlocker(size_hint=(None, None))

        def _fit(*_args):
            blocker.pos = container.pos
            blocker.size = container.size

        container.bind(pos=_fit, size=_fit)
        blocker._fit = _fit
        container._ai_banner_blocker = blocker
    blocker._fit()
    if blocker.parent is not None:
        blocker.parent.remove_widget(blocker)
    container.add_widget(blocker)  # os banners sao adicionados depois, ficam por cima
    Animation.cancel_all(blocker, "scrim")
    Animation(scrim=0.38, d=0.25, t="out_quad").start(blocker)
    return blocker


def _release_modal_blocker(container):
    blocker = getattr(container, "_ai_banner_blocker", None) if container else None
    if blocker is None:
        return
    fit = getattr(blocker, "_fit", None)
    if fit is not None:
        try:
            container.unbind(pos=fit, size=fit)
        except Exception:
            pass
    Animation.cancel_all(blocker)
    if blocker.parent is not None:
        blocker.parent.remove_widget(blocker)
    container._ai_banner_blocker = None


def _ensure_banner_surface(container):
    if not container:
        return None, None, None

    shell = getattr(container, "_ai_banner_shell", None)
    scroll = getattr(container, "_ai_banner_scroll", None)
    host = getattr(container, "_ai_banner_host", None)
    if (
        shell is not None
        and scroll is not None
        and host is not None
        and getattr(shell, "parent", None) is container
        and getattr(scroll, "parent", None) is shell
        and getattr(host, "parent", None) is scroll
    ):
        return shell, scroll, host

    shell = AnchorLayout(
        anchor_x="center",
        anchor_y="center",
        size_hint=(1, 1),
    )
    scroll = ScrollView(
        size_hint=(1, 1),
        do_scroll_x=True,
        do_scroll_y=True,
        bar_width=dp(4),
    )
    _apply_scroll_style(scroll)
    host = FloatLayout(
        size_hint=(None, None),
        width=max(float(container.width or 0), 1.0),
        height=max(float(container.height or 0), 1.0),
    )
    scroll.add_widget(host)
    shell.add_widget(scroll)
    container.add_widget(shell)
    container._ai_banner_shell = shell
    container._ai_banner_scroll = scroll
    container._ai_banner_host = host
    container._ai_banner_stack = host
    return shell, scroll, host


def _build_horizontal_banner_text_scroll(text, text_color):
    """Keep the main banner sentence complete, with horizontal scrolling if needed."""
    scroll = ScrollView(
        size_hint=(1, None),
        height=dp(52),
        do_scroll_x=True,
        do_scroll_y=False,
        bar_width=dp(3),
    )
    _apply_scroll_style(scroll)
    label = MDLabel(
        text=text,
        markup=True,
        theme_text_color="Custom",
        text_color=text_color,
        font_size=dp(14),
        halign="left",
        valign="middle",
        size_hint=(None, None),
    )

    def _sync_label_size(*_args):
        label.text_size = (None, None)
        try:
            label.texture_update()
        except Exception:
            pass
        label.width = max(float(label.texture_size[0] or 0) + dp(16), float(scroll.width or 0))
        label.height = max(float(label.texture_size[1] or 0), float(scroll.height or dp(52)))
        needs_scroll = label.width > float(scroll.width or 0) + 1
        scroll.do_scroll_x = needs_scroll
        scroll.bar_width = dp(3) if needs_scroll else 0

    label.bind(text=_sync_label_size)
    scroll.bind(width=_sync_label_size, height=_sync_label_size)
    scroll.add_widget(label)
    _sync_label_size()
    Clock.schedule_once(lambda _dt: _sync_label_size(), 0)
    return scroll


def _create_auto_banner_original(banner_data, show_timer=True, insights=None):
    """Build the compact banner design from the project's first version."""
    card = MDCard(
        orientation="vertical",
        padding=[0, 0, 0, 0],
        spacing=dp(6),
        size_hint=(None, None),
        size_hint_y=None,
        height=dp(78),
        md_bg_color=banner_data["bg_color"],
        radius=[10, 10, 10, 10],
        elevation=2,
        opacity=0,
    )
    card._target_height = dp(78)

    icon_text = md_icons.get(banner_data["icon"], md_icons.get("alert", ""))
    icon = MDLabel(
        text=icon_text,
        font_style="Icon",
        theme_text_color="Custom",
        text_color=(0.25, 0.25, 0.25, 1),
        font_size=dp(20),
        size_hint=(None, None),
        size=(dp(24), dp(24)),
        halign="center",
        valign="middle",
    )
    icon.bind(size=lambda inst, val: setattr(inst, "text_size", val))

    messages = [
        str(message).strip()
        for message in (banner_data.get("messages") or [])
        if str(message).strip()
    ]
    message = str(banner_data.get("message") or "").strip()
    if not message:
        message = messages[0] if messages else str(banner_data.get("title") or "Alerta")
    count = int(banner_data.get("count") or 0)
    if count > 1 and len(messages) > 1:
        remaining = count - 1
        noun = _tx("alerta") if remaining == 1 else _tx("alertas")
        message = f"{message} {_tx('Há mais')} {remaining} {noun} {_tx('neste aviso.')}"
    message_scroll = _build_horizontal_banner_text_scroll(
        f"[b]ATENÇÃO:[/b] {message}",
        (0.2, 0.2, 0.2, 1),
    )

    close_btn = _build_banner_close_button(
        lambda *_args: animate_banner_out(card),
        {"button_text": (0.35, 0.35, 0.35, 1), "close_bg": (1, 1, 1, 0.48)},
    )
    close_btn.pos_hint = {"center_y": 0.5}

    body = MDBoxLayout(
        orientation="vertical",
        spacing=dp(6),
        size_hint_y=None,
        height=0,
    )
    content = MDBoxLayout(
        orientation="horizontal",
        padding=[dp(14), dp(10), dp(10), 0],
        spacing=dp(10),
        size_hint_y=None,
        height=dp(58),
    )
    content.add_widget(icon)
    content.add_widget(message_scroll)
    content.add_widget(close_btn)
    body.add_widget(content)

    details_sections = list(banner_data.get("details_sections") or [])
    if not details_sections and insights:
        details_sections = build_banner_details_sections(
            insights,
            banner_data.get("kind"),
            expiry_level=banner_data.get("expiry_level"),
        )

    details_box = None
    toggle_btn = None
    toggle_row = None
    if details_sections:
        toggle_btn = MDFlatButton(
            text="Saber mais",
            theme_text_color="Custom",
            text_color=(0.2, 0.2, 0.2, 1),
            size_hint=(None, None),
            width=dp(110),
            height=dp(28),
        )
        toggle_row = MDBoxLayout(
            orientation="horizontal",
            padding=[dp(12), 0, dp(12), 0],
            size_hint_y=None,
            height=dp(32),
        )
        toggle_row.add_widget(toggle_btn)
        body.add_widget(toggle_row)
        details_box = _build_details_box(details_sections)

    action_row = None
    action_buttons = []
    action_specs = [
        spec
        for spec in (banner_data.get("action_buttons") or [])
        if isinstance(spec, dict) and str(spec.get("text") or "").strip()
    ][:3]
    if action_specs:
        action_row = MDBoxLayout(
            orientation="horizontal",
            padding=[dp(12), dp(3), dp(12), dp(5)],
            spacing=dp(8),
            size_hint_y=None,
            height=dp(36),
        )
        action_row.add_widget(Widget())

        def _run_action(button, callback=None, dismiss_after=True):
            if dismiss_after:
                animate_banner_out(card)
            if callable(callback):
                try:
                    callback()
                except TypeError:
                    callback(button)

        for spec in action_specs:
            label = str(spec.get("text") or "").strip().upper()
            callback = spec.get("callback") or spec.get("on_release")
            dismiss_after = bool(spec.get("dismiss_after", True))
            button = MDFlatButton(
                text=label,
                theme_text_color="Custom",
                text_color=(0.18, 0.18, 0.18, 1),
                size_hint=(None, None),
                size=(dp(116), dp(28)),
                font_size=dp(10.5),
            )
            _decorate_pill(button, (1, 1, 1, 0.48), (0, 0, 0, 0.15), radius=dp(7))
            button.bind(
                on_release=lambda btn, cb=callback, close=dismiss_after: _run_action(
                    btn,
                    callback=cb,
                    dismiss_after=close,
                )
            )
            action_row.add_widget(button)
            action_buttons.append(button)
        action_row.add_widget(Widget())
        body.add_widget(action_row)

        def _sync_action_widths(*_args):
            if not action_buttons:
                return
            horizontal_padding = float(action_row.padding[0] + action_row.padding[2])
            available = max(
                float(card.width or 0)
                - horizontal_padding
                - float(action_row.spacing * (len(action_buttons) + 1)),
                float(dp(88) * len(action_buttons)),
            )
            standard_width = min(dp(116), max(dp(88), available / len(action_buttons)))
            for action_button in action_buttons:
                action_button.width = standard_width

        card.bind(width=_sync_action_widths)
        Clock.schedule_once(lambda _dt: _sync_action_widths(), 0)

    body.height = sum(child.height for child in body.children) + body.spacing * max(
        len(body.children) - 1,
        0,
    )
    body._base_height = body.height
    card.add_widget(body)

    progress = None
    if show_timer:
        progress = MDProgressBar(
            value=100,
            max=100,
            size_hint_y=None,
            height=dp(3),
            color=(0.25, 0.25, 0.25, 0.6),
        )
        card.add_widget(progress)

    card._progress = progress
    card._body = body
    card._details_box = details_box
    card._message_scroll = message_scroll
    card._details_expanded = False
    card._base_height = body.height + (progress.height if progress else 0)
    card._toggle_btn = toggle_btn
    card._toggle_container = toggle_row
    card._action_container = action_row
    card._action_buttons = action_buttons
    card.height = card._base_height

    if details_sections and toggle_btn and details_box:
        def _recenter(*_args):
            container = getattr(card, "_banner_container", None)
            widgets = _visible_widgets(container)
            if container and widgets:
                position_banners_center(container, widgets, reset_x=False)

        # Keep the complete banner stack centred during every frame of the
        # expand/collapse animation, not only before or after the click.
        card.bind(height=_recenter)

        def _toggle_details(*_args):
            if card._details_expanded:
                anim = Animation(height=0, opacity=0, d=0.2, t="in_out_cubic")
                anim.start(details_box)
                Animation(height=body._base_height, d=0.2, t="in_out_cubic").start(body)
                Animation(height=card._base_height, d=0.2, t="in_out_cubic").start(card)

                def _finish(*_finish_args):
                    if details_box.parent:
                        details_box.parent.remove_widget(details_box)
                    toggle_btn.text = "Saber mais"
                    card._details_expanded = False
                    Clock.schedule_once(lambda _dt: _recenter(), 0)

                anim.bind(on_complete=_finish)
                return

            if details_box.parent is None:
                body.add_widget(details_box)
            sync_scroll = getattr(details_box, "_sync_scroll", None)
            if callable(sync_scroll):
                sync_scroll()
            target_height = max(
                float(getattr(details_box, "_target_height", 0) or 0),
                float(_calc_details_height(details_box)),
            )
            details_box._target_height = target_height
            body_target = body._base_height + target_height + body.spacing
            card_target = card._base_height + target_height + body.spacing
            Animation(height=target_height, opacity=1, d=0.25, t="out_cubic").start(details_box)
            Animation(height=body_target, d=0.25, t="out_cubic").start(body)
            Animation(height=card_target, d=0.25, t="out_cubic").start(card)
            toggle_btn.text = "Ocultar"
            card._details_expanded = True
            Clock.schedule_once(lambda _dt: _recenter(), 0)
            Clock.schedule_once(lambda _dt: _recenter(), 0.30)

        toggle_btn.bind(on_release=_toggle_details)

    return card


def _run_pdf_export(banner_data, insights, button=None):
    try:
        data = insights
        if not data:
            try:
                from utils.ai.ai_insights import build_admin_insights
                data = build_admin_insights()
            except Exception:
                data = {}
        path = export_banner_alerts_pdf(banner_data=banner_data, insights=data)
        app = App.get_running_app()
        if path and app and hasattr(app, "show_toast"):
            app.show_toast(f"Relatório exportado: {path}")
        elif path and button is not None:
            old = getattr(button, "text", "PDF")
            button.text = "OK"
            Clock.schedule_once(lambda _dt: setattr(button, "text", old), 1.4)
    except Exception:
        pass


def _create_auto_banner_legacy(banner_data, show_timer=True, insights=None):
    # Cores adaptativas: texto claro em fundos escuros, escuro em fundos claros.
    _bg = _rgba(banner_data.get("bg_color") or (0.9, 0.9, 0.9, 1))
    _dark_bg = _is_dark_color(_bg)
    c_title = (1, 1, 1, 1) if _dark_bg else (0.15, 0.15, 0.15, 1)
    c_text = (1, 1, 1, 0.94) if _dark_bg else (0.25, 0.25, 0.25, 1)
    c_btn_bg = (1, 1, 1, 0.18) if _dark_bg else (0, 0, 0, 0.08)
    c_close = (1, 1, 1, 0.95) if _dark_bg else (0.35, 0.35, 0.35, 1)
    c_badge_bg = (1, 1, 1, 0.24) if _dark_bg else (0.2, 0.2, 0.2, 0.85)
    c_details_text = (1, 1, 1, 0.9) if _dark_bg else (0.3, 0.3, 0.3, 1)
    header_height = dp(64)
    card = MDCard(
        orientation="vertical",
        padding=0,
        spacing=0,
        size_hint=(None, None),
        size_hint_y=None,
        height=dp(120),
        md_bg_color=banner_data["bg_color"],
        radius=[12, 12, 12, 12],
        elevation=4,
    )

    header = MDBoxLayout(
        orientation="horizontal",
        padding=[dp(18), dp(16), dp(14), dp(12)],
        spacing=dp(10),
        size_hint_y=None,
        height=header_height,
    )

    icon_text = md_icons.get(banner_data["icon"], md_icons.get("alert", ""))
    icon = MDLabel(
        text=icon_text,
        font_style="Icon",
        theme_text_color="Custom",
        text_color=c_title,
        font_size=dp(26),
        size_hint=(None, None),
        size=(dp(32), dp(32)),
        pos_hint={"center_y": 0.5},
        halign="center",
        valign="middle",
    )
    icon.bind(size=lambda inst, val: setattr(inst, "text_size", val))

    title_text = banner_data.get("title", "Alerta")
    title = MDLabel(
        text=f"[b]{title_text}[/b]",
        markup=True,
        theme_text_color="Custom",
        text_color=c_title,
        font_size=dp(15),
        halign="left",
        valign="middle",
        shorten=True,
        shorten_from="right",
        size_hint=(1, None),
        height=dp(34),
        pos_hint={"center_y": 0.5},
    )
    title.bind(size=lambda inst, val: setattr(inst, "text_size", val))

    count = banner_data.get("count", 0)
    badge = None
    if count > 0:
        badge = MDLabel(
            text=str(count),
            bold=True,
            theme_text_color="Custom",
            text_color=(1, 1, 1, 1),
            font_size=dp(11),
            size_hint=(None, None),
            size=(dp(22), dp(22)),
            pos_hint={"center_y": 0.5},
            halign="center",
            valign="middle",
        )
        badge.bind(size=lambda inst, val: setattr(inst, "text_size", val))
        with badge.canvas.before:
            Color(*c_badge_bg)
            badge._bg_rect = RoundedRectangle(pos=badge.pos, size=badge.size, radius=[dp(11)])
        badge.bind(pos=lambda *_: setattr(badge._bg_rect, "pos", badge.pos))
        badge.bind(size=lambda *_: setattr(badge._bg_rect, "size", badge.size))

    close_btn = _build_banner_close_button(
        lambda *_args: animate_banner_out(card),
        {"button_text": c_close, "close_bg": (1, 1, 1, 0.48)},
    )
    close_btn.pos_hint = {"center_y": 0.5}

    header.add_widget(icon)
    header.add_widget(title)
    if badge:
        header.add_widget(badge)
    header.add_widget(close_btn)

    messages = banner_data.get("messages", [])
    body_wrapper = MDBoxLayout(
        orientation="vertical",
        padding=[dp(16), 0, dp(16), dp(10)],
        size_hint_y=None,
    )
    body_scroll = ScrollView(
        size_hint=(1, None),
        do_scroll_x=False,
        do_scroll_y=False,
        bar_width=0,
    )
    _apply_scroll_style(body_scroll)
    body = MDBoxLayout(
        orientation="vertical",
        spacing=dp(5),
        size_hint=(1, None),
    )
    body.bind(minimum_height=lambda inst, value: setattr(inst, "height", value))
    body_scroll.add_widget(body)
    body_wrapper.add_widget(body_scroll)

    for msg in messages:
        bullet = MDLabel(
            text=f"• {ModernBannerCard._emphasize_banner_text(msg)}",
            markup=True,
            theme_text_color="Custom",
            text_color=c_text,
            font_size=dp(13),
            halign="left",
            valign="middle",
            size_hint_y=None,
        )
        _bind_auto_height(bullet, min_height=dp(20))
        body.add_widget(bullet)

    details_sections = banner_data.get("details_sections") or []
    if not details_sections and insights:
        details_sections = build_banner_details_sections(
            insights,
            banner_data.get("kind"),
            expiry_level=banner_data.get("expiry_level"),
        )

    toggle_btn_widget = None
    toggle_container = None
    if details_sections:
        toggle_btn_widget = MDBoxLayout(
            orientation="horizontal",
            spacing=dp(8),
            size_hint=(None, None),
            width=dp(190),
            height=dp(34),
        )

        btn_icon = MDLabel(
            text=md_icons.get("chevron-down", ""),
            font_style="Icon",
            theme_text_color="Custom",
            text_color=c_title,
            font_size=dp(20),
            size_hint=(None, None),
            size=(dp(24), dp(24)),
            halign="center",
            valign="middle",
        )
        btn_icon.bind(size=lambda inst, val: setattr(inst, "text_size", val))

        btn_text = MDLabel(
            text=_tx("Ver mais"),
            theme_text_color="Custom",
            text_color=c_title,
            font_size=dp(12.5),
            bold=True,
            halign="left",
            valign="middle",
        )
        btn_text.bind(size=lambda inst, val: setattr(inst, "text_size", (val[0], None)))

        item_count = sum(len(items) for _, items in details_sections) if details_sections else 0
        try:
            raw_count = int(banner_data.get("count") or 0)
        except Exception:
            raw_count = 0
        visible_messages = len([msg for msg in messages if str(msg or "").strip()])
        hidden_count = max(raw_count - visible_messages, 0)
        if hidden_count <= 0:
            hidden_count = max(item_count - 5, 0)
        badge_new = None
        if hidden_count > 0:
            badge_new = MDLabel(
                text=f"+{hidden_count}",
                theme_text_color="Custom",
                text_color=(1, 1, 1, 1),
                font_size=dp(10),
                bold=True,
                size_hint=(None, None),
                size=(dp(28), dp(18)),
                halign="center",
                valign="middle",
            )
            badge_new.bind(size=lambda inst, val: setattr(inst, "text_size", val))
            with badge_new.canvas.before:
                Color(0.9, 0.3, 0.2, 0.9)
                badge_new._bg = RoundedRectangle(pos=badge_new.pos, size=badge_new.size, radius=[dp(9)])
            badge_new.bind(pos=lambda *_: setattr(badge_new._bg, "pos", badge_new.pos))
            badge_new.bind(size=lambda *_: setattr(badge_new._bg, "size", badge_new.size))

        toggle_btn_widget.add_widget(btn_icon)
        toggle_btn_widget.add_widget(btn_text)
        if badge_new:
            toggle_btn_widget.add_widget(badge_new)

        with toggle_btn_widget.canvas.before:
            Color(*c_btn_bg)
            toggle_btn_widget._bg_rect = RoundedRectangle(
                pos=toggle_btn_widget.pos,
                size=toggle_btn_widget.size,
                radius=[dp(8)],
            )
        toggle_btn_widget.bind(pos=lambda *_: setattr(toggle_btn_widget._bg_rect, "pos", toggle_btn_widget.pos))
        toggle_btn_widget.bind(size=lambda *_: setattr(toggle_btn_widget._bg_rect, "size", toggle_btn_widget.size))

        toggle_container = MDBoxLayout(
            orientation="horizontal",
            padding=[dp(16), dp(6), dp(16), dp(8)],
            spacing=dp(8),
            size_hint_y=None,
            height=dp(48),
        )
        toggle_container.add_widget(toggle_btn_widget)
        toggle_btn_widget._icon = btn_icon
        toggle_btn_widget._text = btn_text

    def _sync_body_scroll(*_args):
        body_height = _fit_scroll_content(
            body_scroll,
            body,
            max_height=dp(118),
            min_height=dp(20 if messages else 0),
        )
        body_wrapper.height = body_height + dp(10)

    body_scroll.bind(width=_sync_body_scroll)
    body.bind(minimum_height=_sync_body_scroll, minimum_width=_sync_body_scroll)
    _sync_body_scroll()

    action_container = None
    action_specs = [
        spec
        for spec in (banner_data.get("action_buttons") or [])
        if isinstance(spec, dict) and str(spec.get("text") or "").strip()
    ][:3]
    action_buttons = []
    for spec in action_specs:
        label = str(spec.get("text") or "").strip().upper()
        callback = spec.get("callback") or spec.get("on_release")
        dismiss_after = bool(spec.get("dismiss_after", True))
        export_pdf = bool(spec.get("export_pdf"))
        button = MDFlatButton(
            text=label,
            theme_text_color="Custom",
            text_color=c_title,
            size_hint=(None, None),
            size=(max(dp(84), dp(7.6 * len(label) + 40)), dp(34)),
            font_size=dp(12),
        )
        _decorate_pill(button, c_btn_bg, None, radius=dp(8))

        def _on_action(btn, cb=callback, close=dismiss_after, exp=export_pdf):
            if exp:
                _run_pdf_export(banner_data, insights, btn)
                return
            if close:
                animate_banner_out(card)
            if callable(cb):
                try:
                    cb()
                except TypeError:
                    cb(btn)

        button.bind(on_release=_on_action)
        action_buttons.append(button)

    if action_buttons:
        if toggle_container is not None:
            # mesma linha e mesma altura do botao "Ver mais"
            for button in action_buttons:
                toggle_container.add_widget(button)
        else:
            action_container = MDBoxLayout(
                orientation="horizontal",
                padding=[dp(16), dp(6), dp(16), dp(10)],
                spacing=dp(8),
                size_hint_y=None,
                height=dp(50),
            )
            for button in action_buttons:
                action_container.add_widget(button)
            action_container.add_widget(Widget())
    if toggle_container is not None:
        toggle_container.add_widget(Widget())

    def _sync_card_height(*_args):
        if getattr(card, "_details_expanded", False):
            return
        total = header.height + body_wrapper.height
        if action_container:
            total += action_container.height
        if toggle_container:
            total += toggle_container.height
        if progress:
            total += progress.height
        previous = getattr(card, "_synced_height", None)
        card.height = total
        card._base_height = total
        card._synced_height = total
        container = getattr(card, "_banner_container", None)
        if container is not None and (previous is None or abs(previous - total) > 0.5):
            Clock.schedule_once(
                lambda _dt, current=container: position_banners_center(
                    current,
                    _visible_widgets(current),
                    reset_x=False,
                ),
                0,
            )

    card.add_widget(header)
    card.add_widget(body_wrapper)
    if action_container:
        card.add_widget(action_container)
    if toggle_container:
        card.add_widget(toggle_container)

    progress = None
    if show_timer:
        progress = MDProgressBar(
            value=100,
            max=100,
            size_hint_y=None,
            height=dp(3),
            color=(0.3, 0.3, 0.3, 0.5),
        )
        card.add_widget(progress)

    body_wrapper.bind(height=_sync_card_height)
    header.bind(height=_sync_card_height)
    if action_container:
        action_container.bind(height=_sync_card_height)
    if toggle_container:
        toggle_container.bind(height=_sync_card_height)
    if progress:
        progress.bind(height=_sync_card_height)
    card.bind(width=lambda *_args: Clock.schedule_once(lambda _dt: _sync_card_height(), 0))
    _sync_card_height()
    Clock.schedule_once(lambda _dt: _sync_card_height(), 0)
    Clock.schedule_once(lambda _dt: _sync_card_height(), 0.05)

    card._body = body_wrapper
    card._progress = progress
    card._toggle_btn = toggle_btn_widget
    card._toggle_container = toggle_container
    card._details_sections = details_sections
    card._details_expanded = False

    if toggle_btn_widget and details_sections:
        _setup_details_toggle(
            card, toggle_btn_widget, details_sections,
            colors=(c_title, c_details_text),
        )

    return card



def _collect_all_alert_report(insights):
    """Agrega todos os alertas (stock, validade, fraude) sem duplicados."""
    insights = insights or {}
    report = {
        "generated_at": None,
        "summary": {},
        "sections": [],
    }
    import datetime as _dt
    report["generated_at"] = _dt.datetime.now().strftime("%d/%m/%Y %H:%M")

    # Stock
    low_stock = insights.get("low_stock") or []
    stock_lines = []
    seen = set()
    for item in low_stock:
        if not isinstance(item, (list, tuple)) or len(item) < 4:
            continue
        name, stock, is_weight, days_left = item[:4]
        key = str(name or "").strip().casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        unit = "quilogramas" if is_weight else "unidades"
        quantity = _format_banner_quantity(stock, unit)
        try:
            stock_v = float(stock or 0)
            days_v = float(days_left)
        except (TypeError, ValueError):
            stock_v, days_v = 0.0, 999.0
        if stock_v <= 0 or days_v < 0:
            stock_lines.append(f"{name}  ·  ESGOTADO  ·  {quantity}")
        else:
            stock_lines.append(
                f"{name}  ·  cobertura {_format_banner_days(days_v)}  ·  {quantity}"
            )
    report["summary"]["stock"] = len(stock_lines)
    if stock_lines:
        report["sections"].append({
            "title": "Stock baixo / esgotado",
            "count": len(stock_lines),
            "items": stock_lines,
            "action": "Priorize a reposição dos itens esgotados e críticos.",
        })

    # Expiry by level
    expiry_levels = _collect_expiry_levels(insights)
    level_titles = {
        ALERT_LEVEL_VENCIDO: "Produtos vencidos",
        ALERT_LEVEL_CRITICO: "Validade crítica (≤2 dias)",
        ALERT_LEVEL_ALTO: "Validade próxima (≤7 dias)",
        ALERT_LEVEL_MEDIO: "Validades a acompanhar (médias)",
        ALERT_LEVEL_LEVE: "Validades a acompanhar (leves)",
    }
    total_expiry = 0
    for level, title in level_titles.items():
        rows = expiry_levels.get(level) or []
        lines = []
        seen = set()
        for row in rows:
            if not isinstance(row, (list, tuple)) or len(row) < 5:
                continue
            name, days_left, date_str, stock, unit = row[:5]
            key = str(name or "").strip().casefold()
            if not key or key in seen:
                continue
            seen.add(key)
            quantity = _format_banner_quantity(stock, unit)
            try:
                days_i = int(days_left)
            except (TypeError, ValueError):
                days_i = 0
            if days_i <= 0:
                lines.append(f"{name}  ·  desde {date_str}  ·  {quantity}")
            else:
                lines.append(
                    f"{name}  ·  {_format_banner_days(days_i)} ({date_str})  ·  {quantity}"
                )
        if lines:
            total_expiry += len(lines)
            action = (
                "Retire da venda todos os itens vencidos."
                if level == ALERT_LEVEL_VENCIDO
                else "Priorize a venda dos itens próximos do vencimento."
            )
            report["sections"].append({
                "title": title,
                "count": len(lines),
                "items": lines,
                "action": action,
            })
    report["summary"]["expiry"] = total_expiry

    # Fraud
    fraud_alerts = [
        dict(item)
        for item in list(insights.get("fraud_alerts") or [])
        if isinstance(item, dict)
    ]
    fraud_lines = []
    seen = set()
    for item in fraud_alerts:
        title = str(item.get("title") or item.get("alert_type") or "Alerta").strip()
        detail = str(item.get("detail") or item.get("message") or "").strip()
        key = title.casefold()
        if key in seen:
            continue
        seen.add(key)
        fraud_lines.append(f"{title}" + (f"  ·  {detail}" if detail else ""))
    report["summary"]["fraud"] = len(fraud_lines)
    if fraud_lines:
        report["sections"].append({
            "title": _tx("Alertas de fraude"),
            "count": len(fraud_lines),
            "items": fraud_lines,
            "action": "Reveja os registos e confirme com a equipa.",
        })

    report["summary"]["total"] = (
        report["summary"].get("stock", 0)
        + report["summary"].get("expiry", 0)
        + report["summary"].get("fraud", 0)
    )
    return report


def export_banner_alerts_pdf(banner_data=None, insights=None, filepath=None):
    """Exporta TODOS os alertas (stock, validade, fraude) para PDF organizado.

    O botao PDF de qualquer banner gera o relatorio completo, nao so o banner atual.
    """
    from pathlib import Path as _P
    import datetime as _dt

    insights = insights or {}
    # Se nao houver insights no cartao, tenta reconstruir a partir de banners ativos
    report = _collect_all_alert_report(insights)

    # Se insights vazios, inclui pelo menos o banner atual
    if report["summary"].get("total", 0) == 0 and banner_data:
        kind = banner_data.get("kind")
        level = banner_data.get("expiry_level")
        sections = build_banner_details_sections({}, kind, expiry_level=level)
        # fallback: messages
        items = list(banner_data.get("all_messages") or banner_data.get("messages") or [])
        report["sections"].append({
            "title": str(banner_data.get("title") or "Alerta"),
            "count": int(banner_data.get("count") or len(items)),
            "items": items,
            "action": "",
        })
        for title, lines in sections:
            if title.lower() == "acao":
                if report["sections"]:
                    report["sections"][-1]["action"] = lines[0] if lines else ""
            else:
                report["sections"].append({
                    "title": title,
                    "count": len(lines),
                    "items": lines,
                    "action": "",
                })
        report["summary"]["total"] = sum(s.get("count", 0) for s in report["sections"])

    base = _P("data") / "reports"
    try:
        base.mkdir(parents=True, exist_ok=True)
    except Exception:
        base = _P(".")
    stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")

    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.pdfgen import canvas as pdf_canvas
        from reportlab.lib.colors import HexColor, black

        path = filepath or str(base / f"alertas_nectar_{stamp}.pdf")
        c = pdf_canvas.Canvas(path, pagesize=A4)
        width, height = A4
        left = 18 * mm
        right = width - 18 * mm
        y = height - 18 * mm

        def _newline(h=5 * mm):
            nonlocal y
            y -= h
            if y < 18 * mm:
                c.showPage()
                y = height - 18 * mm
                return True
            return False

        # Titulo
        c.setFillColor(HexColor("#1a3d2e"))
        c.setFont("Helvetica-Bold", 16)
        c.drawString(left, y, "NECTAR — Relatório de Alertas")
        _newline(7 * mm)

        c.setFillColor(HexColor("#555555"))
        c.setFont("Helvetica", 9)
        c.drawString(
            left,
            y,
            f"Gerado em {report.get('generated_at') or stamp}  ·  Total de itens: {report['summary'].get('total', 0)}",
        )
        _newline(5 * mm)

        # Resumo em negrito
        c.setFillColor(black)
        c.setFont("Helvetica-Bold", 11)
        c.drawString(left, y, "Resumo")
        _newline(5 * mm)
        c.setFont("Helvetica", 10)
        s = report["summary"]
        summary_bits = [
            f"Stock: {s.get('stock', 0)}",
            f"Validade: {s.get('expiry', 0)}",
            f"Fraude: {s.get('fraud', 0)}",
        ]
        c.drawString(left, y, "  ·  ".join(summary_bits))
        _newline(7 * mm)

        # Linha separadora
        c.setStrokeColor(HexColor("#cccccc"))
        c.line(left, y, right, y)
        _newline(6 * mm)

        for section in report["sections"]:
            # Titulo de secao (STRONG)
            c.setFillColor(HexColor("#1a3d2e"))
            c.setFont("Helvetica-Bold", 12)
            title = str(section.get("title") or "")
            count = section.get("count", 0)
            c.drawString(left, y, f"{title}  ({count})")
            _newline(5.5 * mm)

            c.setFillColor(black)
            for item in section.get("items") or []:
                text = str(item)
                # Nome do produto em negrito: parte antes do primeiro " · "
                if " · " in text:
                    name, rest = text.split(" · ", 1)
                    c.setFont("Helvetica-Bold", 9)
                    c.drawString(left + 2 * mm, y, f"• {name}")
                    name_w = c.stringWidth(f"• {name} ", "Helvetica-Bold", 9)
                    c.setFont("Helvetica", 9)
                    c.setFillColor(HexColor("#333333"))
                    c.drawString(left + 2 * mm + name_w, y, f"· {rest}"[:90])
                    c.setFillColor(black)
                else:
                    c.setFont("Helvetica", 9)
                    c.drawString(left + 2 * mm, y, f"• {text}"[:95])
                _newline(4.5 * mm)

            action = str(section.get("action") or "").strip()
            if action:
                _newline(1 * mm)
                c.setFont("Helvetica-Bold", 9)
                c.setFillColor(HexColor("#0d5c3a"))
                c.drawString(left + 2 * mm, y, "Ação: ")
                aw = c.stringWidth("Ação: ", "Helvetica-Bold", 9)
                c.setFont("Helvetica", 9)
                c.drawString(left + 2 * mm + aw, y, action[:85])
                c.setFillColor(black)
                _newline(6 * mm)
            else:
                _newline(4 * mm)

        # Rodape
        c.setFont("Helvetica", 8)
        c.setFillColor(HexColor("#888888"))
        c.drawString(left, 12 * mm, "Documento gerado pelo sistema NECTAR  ·  Uso interno")
        c.save()
        return path
    except Exception:
        # Fallback texto com marcadores de negrito
        path = filepath or str(base / f"alertas_nectar_{stamp}.txt")
        lines = [
            "NECTAR — RELATÓRIO DE ALERTAS",
            f"Gerado em {report.get('generated_at')}",
            f"Total: {report['summary'].get('total', 0)}",
            "",
            "RESUMO",
            f"  Stock: {report['summary'].get('stock', 0)}  |  Validade: {report['summary'].get('expiry', 0)}  |  Fraude: {report['summary'].get('fraud', 0)}",
            "",
        ]
        for section in report["sections"]:
            lines.append(f"** {section.get('title')} ({section.get('count', 0)}) **")
            for item in section.get("items") or []:
                lines.append(f"  • {item}")
            if section.get("action"):
                lines.append(f"  AÇÃO: {section['action']}")
            lines.append("")
        lines.append("Documento gerado pelo sistema NECTAR")
        _P(path).write_text("\n".join(lines), encoding="utf-8")
        return path



def create_auto_banner(banner_data, show_timer=True, insights=None):
    """Banner classico (cor propria do alerta) com icones desenhados e botoes em pilula."""
    return ModernBannerCard(
        banner_data,
        show_timer=show_timer,
        insights=insights,
    )


def animate_banner_in(widget):
    """Entra pela esquerda, desliza ate ao centro com fade suave."""
    if not widget:
        return

    # A newly mounted FloatLayout starts at (0, 0). Never treat that default
    # position as the banner target while Kivy is still resolving the overlay
    # size; wait until position_banners_center has set both coordinates.
    if not hasattr(widget, "_target_x") or not hasattr(widget, "_target_y"):
        widget.opacity = 0
        if getattr(widget, "_position_retry_ev", None) is None:
            def _retry(_dt, current=widget):
                current._position_retry_ev = None
                container = getattr(current, "_banner_container", None)
                active_widgets = getattr(container, "_ai_banner_widgets", []) if container else []
                if container is not None and current not in active_widgets:
                    return
                animate_banner_in(current)

            widget._position_retry_ev = Clock.schedule_once(_retry, 0.05)
        return

    _cancel_event(getattr(widget, "_position_retry_ev", None))
    widget._position_retry_ev = None
    target_x = float(widget._target_x)
    target_y = float(widget._target_y)
    target_opacity = float(getattr(widget, "_target_opacity", 1) or 1)
    Animation.cancel_all(widget)

    # Origem: fora do ecran a esquerda (proporcional a largura do banner)
    width = float(widget.width or 0) or float(dp(320))
    slide = min(max(width * 0.55, float(dp(120))), float(dp(420)))
    start_x = target_x - slide

    widget.y = target_y
    widget.x = start_x
    widget.opacity = 0

    anim = Animation(
        x=target_x,
        opacity=target_opacity,
        d=0.55,
        t="out_cubic",
    )
    anim.start(widget)

    card = getattr(widget, "_banner_card", None)
    if card is not None and hasattr(card, "_animate_icon_intro"):
        try:
            card._animate_icon_intro()
        except Exception:
            pass


def animate_banner_out(widget):
    """Sai pela direita com fade suave."""
    if not widget:
        return
    _cancel_event(getattr(widget, "_position_retry_ev", None))
    widget._position_retry_ev = None
    auto_event = getattr(widget, "_auto_dismiss_ev", None)
    if auto_event:
        auto_event.cancel()
        widget._auto_dismiss_ev = None

    def _finish(*_args):
        parent = widget.parent
        if parent:
            try:
                parent.remove_widget(widget)
            except Exception:
                pass
        container = getattr(widget, "_banner_container", None)
        if container is None:
            return
        remaining = [item for item in _visible_widgets(container) if item is not widget]
        container._ai_banner_widgets = remaining
        if remaining:
            def _promote_next(_dt, current=container, visible=remaining):
                position_banners_center(current, visible, reset_x=False)
                _resume_auto_dismiss(visible[0])

            Clock.schedule_once(_promote_next, 0)
            return
        if getattr(container, "_ai_render_ev", None) is not None:
            return
        clear_banner_container(container)

    Animation.cancel_all(widget)
    width = float(widget.width or 0) or float(dp(320))
    slide = min(max(width * 0.55, float(dp(120))), float(dp(420)))
    end_x = float(widget.x) + slide

    container_out = getattr(widget, "_banner_container", None)
    if container_out is not None:
        blocker = getattr(container_out, "_ai_banner_blocker", None)
        others = [w for w in _visible_widgets(container_out) if w is not widget]
        if blocker is not None and not others and getattr(container_out, "_ai_render_ev", None) is None:
            Animation.cancel_all(blocker, "scrim")
            Animation(scrim=0.0, d=0.4, t="out_quad").start(blocker)

    anim = Animation(
        x=end_x,
        opacity=0,
        d=0.48,
        t="in_cubic",
    )
    anim.bind(on_complete=_finish)
    anim.start(widget)

def _set_banner_hidden(widget, hidden):
    if not widget:
        return
    Animation.cancel_all(widget)
    widget._is_hidden = bool(hidden)
    if hidden:
        widget.opacity = 0
        widget.disabled = True
        widget.pos = (-widget.width * 2, widget.y)
    else:
        widget.opacity = 1
        widget.disabled = False


def _force_collapse_banner(widget):
    if not widget:
        return
    if getattr(widget, "_details_expanded", False):
        details_box = getattr(widget, "_details_box", None)
        if details_box:
            Animation.cancel_all(details_box)
            if details_box.parent:
                details_box.parent.remove_widget(details_box)
        widget._details_expanded = False
        toggle_btn = getattr(widget, "_toggle_btn", None)
        if toggle_btn:
            if hasattr(toggle_btn, "_icon"):
                toggle_btn._icon.text = md_icons.get("chevron-down", "")
            if hasattr(toggle_btn, "_text"):
                toggle_btn._text.text = _tx("Ver mais")
        base_height = getattr(widget, "_base_height", None)
        if base_height is not None:
            widget.height = base_height


def _pause_auto_dismiss(widget):
    if not widget:
        return
    auto_event = getattr(widget, "_auto_dismiss_ev", None)
    if auto_event:
        auto_event.cancel()
        widget._auto_dismiss_ev = None
    progress = getattr(widget, "_progress", None)
    if progress:
        Animation.cancel_all(progress)
    widget._auto_paused = True


def _resume_auto_dismiss(widget):
    if not widget or not getattr(widget, "_auto_paused", False):
        return
    widget._auto_paused = False
    auto_dismiss_seconds = getattr(widget, "_auto_dismiss_seconds", None)
    show_timer = getattr(widget, "_auto_show_timer", False)
    if not auto_dismiss_seconds:
        return
    progress = getattr(widget, "_progress", None)
    if progress and show_timer:
        progress.value = 100
        Animation(value=0, d=auto_dismiss_seconds, t="linear").start(progress)
    widget._auto_dismiss_ev = Clock.schedule_once(
        lambda dt, ww=widget: animate_banner_out(ww),
        auto_dismiss_seconds,
    )


def _build_details_box(sections, title_color=(0.15, 0.15, 0.15, 1), text_color=(0.3, 0.3, 0.3, 1)):
    details_box = MDBoxLayout(
        orientation="vertical",
        padding=[dp(16), dp(8), dp(16), dp(12)],
        size_hint_y=None,
        height=0,
        opacity=0,
    )
    details_scroll = ScrollView(
        size_hint=(1, None),
        do_scroll_x=False,
        do_scroll_y=False,
        bar_width=0,
    )
    _apply_scroll_style(details_scroll)
    details_content = MDBoxLayout(
        orientation="vertical",
        spacing=dp(6),
        size_hint=(1, None),
    )
    details_content.bind(minimum_height=lambda inst, value: setattr(inst, "height", value))
    details_scroll.add_widget(details_content)
    details_box.add_widget(details_scroll)

    for title, items in sections:
        title_label = MDLabel(
            text=f"[b]{title}[/b]",
            markup=True,
            theme_text_color="Custom",
            text_color=title_color,
            font_size=dp(13),
            halign="left",
            valign="middle",
            size_hint_y=None,
        )
        _bind_auto_height(title_label, min_height=dp(20))
        details_content.add_widget(title_label)
        for item in items:
            item_label = MDLabel(
                text=f"  • {ModernBannerCard._emphasize_banner_text(item)}",
                markup=True,
                theme_text_color="Custom",
                text_color=text_color,
                font_size=dp(12),
                halign="left",
                valign="middle",
                size_hint_y=None,
            )
            _bind_auto_height(item_label, min_height=dp(18))
            details_content.add_widget(item_label)
        if sections.index((title, items)) < len(sections) - 1:
            details_content.add_widget(MDLabel(size_hint=(None, None), width=dp(4), height=dp(4)))

    def _sync_details_scroll(*_args):
        details_height = _fit_scroll_content(
            details_scroll,
            details_content,
            max_height=dp(136),
            min_height=dp(40),
        )
        details_box._target_height = details_height + dp(20)

    details_scroll.bind(width=_sync_details_scroll)
    details_content.bind(minimum_height=_sync_details_scroll)
    _sync_details_scroll()
    details_box._details_scroll = details_scroll
    details_box._details_content = details_content
    details_box._sync_scroll = _sync_details_scroll
    return details_box


def _calc_details_height(details_box):
    total = 0
    for child in details_box.children:
        total += child.height
    if details_box.children:
        total += details_box.spacing * max(len(details_box.children) - 1, 0)
    total += details_box.padding[1] + details_box.padding[3]
    return max(total, dp(60))


def _setup_details_toggle(card, toggle_btn, details_sections, colors=None):
    if colors:
        details_box = _build_details_box(details_sections, title_color=colors[0], text_color=colors[1])
    else:
        details_box = _build_details_box(details_sections)

    def _recenter():
        container = getattr(card, "_banner_container", None)
        widgets = _visible_widgets(container)
        if container and widgets:
            position_banners_center(container, widgets, reset_x=False)

    def _toggle_siblings(show):
        container = getattr(card, "_banner_container", None)
        widgets = getattr(container, "_ai_banner_widgets", None) if container else None
        if not widgets or len(widgets) <= 1:
            return
        for w in widgets:
            if w is card:
                continue
            if show:
                _set_banner_hidden(w, False)
                _resume_auto_dismiss(w)
            else:
                _force_collapse_banner(w)
                _pause_auto_dismiss(w)
                _set_banner_hidden(w, True)

    def _on_touch_down(instance, touch):
        if instance.collide_point(*touch.pos):
            _toggle()
            return True
        return False

    def _toggle(*args):
        if card._details_expanded:
            card._details_expanded = False
            _toggle_siblings(True)
            anim = Animation(height=0, opacity=0, d=0.2, t="in_out_cubic")
            anim.start(details_box)
            Animation(height=card._base_height, d=0.2, t="in_out_cubic").start(card)
            if hasattr(toggle_btn, "_icon"):
                toggle_btn._icon.text = md_icons.get("chevron-down", "")
                toggle_btn._text.text = _tx("Ver mais")

            def _finish(*_):
                if details_box.parent:
                    details_box.parent.remove_widget(details_box)
                Clock.schedule_once(lambda dt: _recenter(), 0.05)

            anim.bind(on_complete=_finish)
        else:
            if card._toggle_container and card._toggle_container in card.children:
                toggle_index = card.children.index(card._toggle_container)
                card.add_widget(details_box, index=toggle_index + 1)
            else:
                card.add_widget(details_box)

            sync_scroll = getattr(details_box, "_sync_scroll", None)
            if callable(sync_scroll):
                sync_scroll()
            target_h = details_box._target_height
            card_target = card._base_height + target_h
            Animation(height=target_h, opacity=1, d=0.25, t="out_cubic").start(details_box)
            Animation(height=card_target, d=0.25, t="out_cubic").start(card)
            if hasattr(toggle_btn, "_icon"):
                toggle_btn._icon.text = md_icons.get("chevron-up", "")
                toggle_btn._text.text = _tx("Ver menos")

            card._details_expanded = True
            _toggle_siblings(False)
            Clock.schedule_once(lambda dt: _recenter(), 0.3)

    toggle_btn.bind(on_touch_down=_on_touch_down)
    card._details_box = details_box
    card._toggle_details = _toggle


_USE_DECK_LAYOUT = True  # True = banners sobrepostos em baralho (o da frente fica 100% legivel)


def position_banners_center(
    container,
    widgets,
    spacing=dp(14),
    reset_x=True,
    columns=None,
    on_ready=None,
):
    if not container:
        return False
    if not widgets:
        return False

    if container.width <= 0 or container.height <= 0:
        Clock.schedule_once(
            lambda _dt: position_banners_center(
                container,
                widgets,
                spacing=spacing,
                reset_x=reset_x,
                columns=columns,
                on_ready=on_ready,
            ),
            0.05,
        )
        return False

    # The banners are direct children of this overlay, so their coordinates
    # must be calculated in the overlay's own coordinate system. Converting
    # the centre of Window through nested screens can yield (0, 0), leaving
    # the banners stuck in the lower-left corner.
    overlay_width = max(float(container.width), 1.0)
    overlay_height = max(float(container.height), 1.0)
    center_x = overlay_width / 2.0
    center_y = overlay_height / 2.0

    available_width = max(overlay_width - dp(24), dp(220))

    # Multiple alerts form one centred deck. The front card stays fully
    # readable while small portions of the cards behind it remain visible.
    if _USE_DECK_LAYOUT and len(widgets) > 1:
        visible_layers = min(len(widgets), 5)
        x_step = min(max(overlay_width * 0.012, float(dp(8))), float(dp(14)))
        y_step = min(max(overlay_height * 0.014, float(dp(8))), float(dp(12)))
        stack_x = x_step * (visible_layers - 1)
        stack_y = y_step * (visible_layers - 1)
        banner_width = min(
            overlay_width * 0.88,
            max(available_width - stack_x, dp(180)),
            dp(720),
        )
        max_height = max(float(widget.height or 0) for widget in widgets)
        footprint_width = banner_width + stack_x
        footprint_height = max_height + stack_y
        start_x = center_x - (footprint_width / 2.0)
        start_y = center_y - (footprint_height / 2.0)

        for idx, widget in enumerate(widgets):
            depth = min(idx, visible_layers - 1)
            widget.width = banner_width
            widget.pos_hint = {}
            widget.disabled = idx != 0
            widget._stack_depth = depth
            widget._target_x = start_x + (depth * x_step)
            widget._target_y = start_y + ((visible_layers - 1 - depth) * y_step)
            widget._target_opacity = max(0.76, 1.0 - (depth * 0.06))
            widget._entry_y = widget._target_y
            widget._pass_x = widget._target_x
            widget._pass_y = widget._target_y
            if reset_x:
                widget.pos = (widget._target_x, widget._target_y)
                widget.opacity = 0
            else:
                widget.pos = (widget._target_x, widget._target_y)
                widget.opacity = widget._target_opacity

        if callable(on_ready):
            on_ready()
        return True

    total_height = sum(w.height for w in widgets) + spacing * (len(widgets) - 1)
    start_y = center_y - (total_height / 2.0)
    banner_width = min(overlay_width * 0.92, available_width, dp(760))
    cursor = min(center_y + total_height / 2.0, overlay_height - dp(8))
    for idx, widget in enumerate(widgets):
        widget.width = banner_width
        widget.pos_hint = {}
        widget.disabled = False
        widget._stack_depth = 0
        widget._target_x = center_x - (banner_width / 2.0)
        cursor -= float(widget.height)
        widget._target_y = cursor
        cursor -= spacing
        widget._target_opacity = 1
        widget._entry_y = widget._target_y + dp(8)
        widget._pass_x = widget._target_x + min(max(banner_width * 0.03, dp(12)), dp(20))
        widget._pass_y = widget._target_y - dp(4)
        y = widget._target_y
        if reset_x:
            widget.pos = (widget._target_x, widget._target_y)
            widget.opacity = 0
        else:
            widget.pos = (getattr(widget, "_target_x", widget.x), y)
            widget.opacity = getattr(widget, "_target_opacity", widget.opacity)

    if callable(on_ready):
        on_ready()
    return True


def render_auto_banners(
    container,
    banner_data_list,
    insights=None,
    auto_dismiss_seconds=15,
    show_timer=True,
    stagger_seconds=1.0,
    columns=1,
    batch_size=None,
    batch_interval_seconds=None,
):
    del columns, batch_size, batch_interval_seconds
    if not container:
        return

    _cancel_render_event(container)
    _cancel_batch_events(container)
    old_widgets = list(getattr(container, "_ai_banner_widgets", []) or [])
    if not banner_data_list:
        clear_banner_container(container)
        return

    for widget in old_widgets:
        _cancel_event(getattr(widget, "_auto_dismiss_ev", None))
        widget._auto_dismiss_ev = None
        card = getattr(widget, "_banner_card", None)
        Animation.cancel_all(widget)
        if card is not None:
            Animation.cancel_all(card)
            if getattr(card, "_progress", None) is not None:
                Animation.cancel_all(card._progress)
        animate_banner_out(widget)

    def _mount(_dt):
        widgets = []
        container._ai_render_ev = None
        container._ai_banner_widgets = []
        for data in banner_data_list:
            widget = create_auto_banner(data, show_timer=show_timer, insights=insights)
            widget._banner_container = container
            widget._auto_dismiss_seconds = auto_dismiss_seconds
            widget._auto_show_timer = bool(show_timer)
            widget._auto_paused = False
            widgets.append(widget)

        _ensure_modal_blocker(container)
        # Add the priority card last so Kivy draws it above every card behind.
        draw_widgets = list(reversed(widgets))
        for widget in draw_widgets:
            container.add_widget(widget)

        container._ai_banner_widgets = widgets

        # Keep the overlay centred when the application window changes size.
        old_recenter = getattr(container, "_ai_banner_recenter", None)
        if old_recenter is not None:
            try:
                container.unbind(size=old_recenter)
                Window.unbind(size=old_recenter)
            except Exception:
                pass

        def _recenter_visible(*_args):
            visible = _visible_widgets(container)
            if visible:
                position_banners_center(container, visible, reset_x=False)

        container._ai_banner_recenter = _recenter_visible
        container.bind(size=_recenter_visible)
        Window.bind(size=_recenter_visible)

        animations_started = False

        def _start_animations():
            nonlocal animations_started
            if animations_started:
                return
            active_widgets = list(getattr(container, "_ai_banner_widgets", []) or [])
            if active_widgets != widgets or any(widget.parent is not container for widget in widgets):
                return
            animations_started = True

            # 1s entre cada banner por omissao; entrada esquerda → centro
            separation_seconds = max(float(stagger_seconds if stagger_seconds is not None else 1.0), 0.0)
            for idx, widget in enumerate(widgets):
                delay = idx * separation_seconds
                widget._auto_paused = idx != 0

                def _start(_inner_dt, w=widget, is_front=idx == 0):
                    current_widgets = getattr(container, "_ai_banner_widgets", []) or []
                    if w.parent is not container or w not in current_widgets:
                        return
                    animate_banner_in(w)
                    progress = getattr(w, "_progress", None)
                    if progress:
                        progress.value = 100
                    if is_front and progress and show_timer and auto_dismiss_seconds:
                        Animation(value=0, d=auto_dismiss_seconds, t="linear").start(progress)
                    if is_front and auto_dismiss_seconds:
                        w._auto_dismiss_ev = Clock.schedule_once(
                            lambda _dt, ww=w: animate_banner_out(ww),
                            auto_dismiss_seconds,
                        )

                Clock.schedule_once(_start, delay)

        # The animation starts only after the overlay has valid dimensions and
        # every banner has received its final centred coordinates.
        position_banners_center(container, widgets, on_ready=_start_animations)

    container._ai_render_ev = Clock.schedule_once(_mount, 0.01 if old_widgets else 0)