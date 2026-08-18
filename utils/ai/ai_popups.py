from kivy.animation import Animation
from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, Line, RoundedRectangle
from kivy.metrics import dp
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget
from kivymd.icon_definitions import md_icons
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDFlatButton, MDIconButton
from kivymd.uix.card import MDCard
from kivymd.uix.label import MDLabel
from kivymd.uix.progressbar import MDProgressBar

from utils.business.expiry_alerts import (
    ALERT_COLORS,
    ALERT_LEVEL_ALTO,
    ALERT_LEVEL_CRITICO,
    ALERT_LEVEL_LEVE,
    ALERT_LEVEL_MEDIO,
    ALERT_LEVEL_VENCIDO,
)
from utils.config.theme import get_theme_tokens


class _BannerIconButton(ButtonBehavior, MDLabel):
    pass


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


def _format_banner_quantity(value, unit):
    """Return quantities in full words so banner text is easy to read."""
    try:
        amount = float(value)
    except (TypeError, ValueError):
        amount = 0.0

    unit_text = str(unit or "").strip().lower()
    is_weight = unit_text in {"kg", "quilo", "quilos", "quilograma", "quilogramas"}
    if is_weight:
        number = f"{amount:.1f}"
        label = "quilograma" if abs(amount - 1) < 0.001 else "quilogramas"
    else:
        number = str(int(amount)) if amount.is_integer() else f"{amount:.1f}"
        label = "unidade" if abs(amount - 1) < 0.001 else "unidades"
    return f"{number} {label}"


def _format_banner_days(value):
    try:
        days = max(0, int(round(float(value))))
    except (TypeError, ValueError):
        days = 0
    return f"{days} dia" if days == 1 else f"{days} dias"


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
    accent = _rgba(tokens.get(variant, tokens.get("info", [0.15, 0.45, 0.75, 1])))
    base = _rgba(tokens.get("card", [1, 1, 1, 1]))
    secondary_base = _rgba(tokens.get("card_alt", base))
    divider = _rgba(tokens.get("divider", [0, 0, 0, 0.10]))
    return {
        "variant": variant,
        "accent": accent,
        "dark": dark,
        "bg": _blend(base, accent, 0.09 if not dark else 0.14),
        "border": _blend(divider, accent, 0.44, alpha=0.52 if not dark else 0.72),
        "icon_bg": _blend(secondary_base, accent, 0.18 if not dark else 0.28),
        "chip_bg": _blend(base, accent, 0.16 if not dark else 0.22),
        "button_bg": _blend(secondary_base, accent, 0.18 if not dark else 0.28),
        "button_bg_hover": _blend(secondary_base, accent, 0.25 if not dark else 0.36),
        "button_text": accent,
        "title": _rgba(tokens.get("text_primary", [0.15, 0.20, 0.30, 1])),
        "text": _rgba(tokens.get("text_secondary", [0.35, 0.40, 0.50, 1])),
        "muted": _rgba(tokens.get("text_muted", tokens.get("text_secondary", [0.55, 0.60, 0.70, 1]))),
        "progress": _rgba(accent, 0.92),
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
        label.height = max(float(label.texture_size[1] or 0), float(min_height))

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
        label.width = max(float(label.texture_size[0] or 0) + float(horizontal_padding), float(dp(24)))
        label.height = max(float(label.texture_size[1] or 0), float(min_height))

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
        return "alert-octagon", "Produtos Vencidos", color
    if level == ALERT_LEVEL_CRITICO:
        return "alert-circle", "Produtos que Vencem em Breve", color
    if level == ALERT_LEVEL_ALTO:
        return "alert", "Produtos Próximos da Validade", color
    if level == ALERT_LEVEL_MEDIO:
        return "calendar-alert", "Produtos para Acompanhar", color
    return "calendar-clock", "Produtos com Validade a Acompanhar", color


def _get_stock_message_variant(item_name, stock, unit, days_left):
    quantity = _format_banner_quantity(stock, unit)
    try:
        is_out_of_stock = float(stock) <= 0
    except (TypeError, ValueError):
        is_out_of_stock = False

    if is_out_of_stock or float(days_left or 0) < 0:
        return f"{item_name} está sem estoque. Faça a reposição o mais cedo possível."
    return f"{item_name} está com estoque baixo. Restam {quantity}. Faça a reposição."


def _get_expiry_message_variant(item_name, days_left, date_str):
    if days_left <= 2:
        return (
            f"{item_name} vence em {_format_banner_days(days_left)}, no dia {date_str}. "
            "Dê prioridade à venda."
        )
    if days_left <= 7:
        return (
            f"{item_name} vence em {_format_banner_days(days_left)}, no dia {date_str}. "
            "Acompanhe a venda deste produto."
        )
    return f"{item_name} vence em {_format_banner_days(days_left)}, no dia {date_str}."


def _get_expiry_level_message(level, item_name, days_left, date_str):
    if level == ALERT_LEVEL_VENCIDO:
        overdue = abs(int(days_left))
        day_text = "1 dia" if overdue == 1 else f"{overdue} dias"
        return f"{item_name} está vencido há {day_text}, desde {date_str}. Retire-o da venda."
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
            title = "Produtos sem estoque"
            icon = "alert-circle"
        elif min_days < 10:
            title = "Produtos com estoque baixo"
            icon = "alert"
        else:
            title = "Produtos com estoque baixo"
            icon = "information-outline"

        banners.append(
            {
                "kind": "stock",
                "variant": "danger" if min_days < 1 else "warning" if min_days < 20 else "info",
                "icon": icon,
                "bg_color": (1, 0.4, 0.4, 1),
                "title": title,
                "messages": messages[:5],
                "all_messages": messages,
                "count": len(low_stock),
                "urgency": min_days,
                "notification_key": _stable_banner_source_key("stock", low_stock),
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
        messages = []
        urgencies = []
        for name, days_left, date_str, _stock, _unit in rows:
            messages.append(_get_expiry_level_message(level, name, days_left, date_str))
            urgencies.append(days_left)
        banners.append(
            {
                "kind": "expiry",
                "variant": "danger" if level in (ALERT_LEVEL_VENCIDO, ALERT_LEVEL_CRITICO) else "warning" if level in (ALERT_LEVEL_ALTO, ALERT_LEVEL_MEDIO) else "info",
                "expiry_level": level,
                "icon": icon,
                "bg_color": bg_color,
                "title": title,
                "messages": messages[:5],
                "all_messages": messages,
                "count": len(rows),
                "urgency": min(urgencies) if urgencies else 999,
                "notification_key": _stable_banner_source_key("expiry", rows, level=level),
            }
        )

    if not low_stock and not any(bool(expiry_levels.get(level)) for level in expiry_order):
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
            "title": "Estoque em ordem",
            "messages": [
                "Não há produtos com estoque baixo neste momento.",
                "A reposição está em dia.",
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
            "title": "Validades em ordem",
            "messages": [
                "Sem alertas relevantes de vencimento.",
                "Nenhum risco imediato identificado.",
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
        "title": "Tudo em ordem",
        "messages": [
            "Não há alertas críticos de estoque.",
            "Sem riscos imediatos de validade.",
        ],
        "count": 0,
        "urgency": 999,
        "notification_key": "positive:all",
    }


def build_banner_details_sections(insights, kind, max_lines=None, expiry_level=None):
    del max_lines
    sections = []
    recommendations_stock = insights.get("recommendations_stock") or []
    recommendations_expiry = insights.get("recommendations_expiry") or []
    recommendations_all = insights.get("recommendations") or []

    def _add_recommendations(lines):
        if lines:
            sections.append(("Recomendações", list(lines[:5])))

    if kind == "stock":
        _add_recommendations(recommendations_stock or recommendations_all)

        low_stock = insights.get("low_stock") or []
        if low_stock:
            lines = []
            for item in low_stock:
                if isinstance(item, (list, tuple)) and len(item) >= 4:
                    name, stock, is_weight, days_left = item[:4]
                    unit = "quilogramas" if is_weight else "unidades"
                    quantity = _format_banner_quantity(stock, unit)
                    if float(stock or 0) <= 0 or float(days_left or 0) < 0:
                        lines.append(f"{name}: o estoque está esgotado. Faça a reposição.")
                    else:
                        lines.append(
                            f"{name}: restam {quantity}. "
                            f"O estoque deve durar cerca de {_format_banner_days(days_left)}."
                        )
            if lines:
                sections.append(("Produtos com Estoque Baixo", lines))

        forecast = insights.get("stock_forecast") or []
        if forecast:
            lines = []
            for item in forecast:
                if item.get("days_left") is None:
                    continue
                lines.append(
                    f"{item.get('name')}: poderá ficar sem estoque em cerca de "
                    f"{_format_banner_days(item.get('days_left'))}."
                )
            if lines:
                sections.append(("Previsão de Reposição", lines))

    elif kind == "expiry":
        _add_recommendations(recommendations_expiry or recommendations_all)
        expiry_levels = _collect_expiry_levels(insights)
        level_titles = {
            ALERT_LEVEL_VENCIDO: "Produtos Vencidos",
            ALERT_LEVEL_CRITICO: "Produtos que Vencem em Breve",
            ALERT_LEVEL_ALTO: "Produtos Próximos da Validade",
            ALERT_LEVEL_MEDIO: "Produtos para Acompanhar",
            ALERT_LEVEL_LEVE: "Produtos com Validade a Acompanhar",
        }
        level_order = [
            ALERT_LEVEL_VENCIDO,
            ALERT_LEVEL_CRITICO,
            ALERT_LEVEL_ALTO,
            ALERT_LEVEL_MEDIO,
            ALERT_LEVEL_LEVE,
        ]
        if expiry_level in level_titles:
            level_order = [expiry_level]

        for level in level_order:
            rows = expiry_levels.get(level) or []
            if not rows:
                continue
            lines = []
            for name, days_left, date_str, stock, unit in rows:
                quantity = _format_banner_quantity(stock, unit)
                if int(days_left) <= 0:
                    lines.append(
                        f"{name}: está vencido desde {date_str}. Restam {quantity}. "
                        "Retire-o da venda."
                    )
                else:
                    lines.append(
                        f"{name}: vence em {_format_banner_days(days_left)}, no dia {date_str}. "
                        f"Restam {quantity}."
                    )
            if lines:
                sections.append((level_titles[level], lines))

        expiry_risk = insights.get("expiry_risk") or []
        if expiry_risk:
            lines = []
            for item in expiry_risk:
                days_to_expiry = item.get("days_to_expiry")
                days_to_sell = item.get("days_to_sell")
                if days_to_expiry is None or days_to_sell is None:
                    continue
                lines.append(
                    f"{item.get('name')}: vence em {_format_banner_days(days_to_expiry)}. "
                    f"O estoque atual poderá durar cerca de {_format_banner_days(days_to_sell)}. "
                    f"A perda possível de lucro é de {float(item.get('loss_profit') or 0):.0f} meticais."
                )
            if lines:
                sections.append(("Risco de Perda", lines))

    return sections


class ModernBannerCard(MDCard):
    def __init__(self, banner_data, show_timer=True, insights=None, **kwargs):
        self.banner_data = dict(banner_data or {})
        self.palette = _banner_palette(self.banner_data)
        self.all_messages = _clean_messages(self.banner_data.get("all_messages") or self.banner_data.get("messages") or [])
        self.details_sections = list(self.banner_data.get("details_sections") or [])
        if not self.details_sections and insights:
            self.details_sections = build_banner_details_sections(
                insights,
                self.banner_data.get("kind"),
                expiry_level=self.banner_data.get("expiry_level"),
            )
        self.full_description = self._build_description_text()
        self._expanded = False
        self._compact = False
        self._preview_truncated = False
        self._has_extra_content = False
        self._window_bound = False
        self._wrapper = None
        self._progress = None

        super().__init__(
            orientation="vertical",
            padding=0,
            spacing=0,
            size_hint=(1, None),
            size_hint_y=None,
            radius=[dp(18), dp(18), dp(18), dp(18)],
            elevation=self.palette["elevation"],
            md_bg_color=self.palette["bg"],
            **kwargs,
        )

        with self.canvas.after:
            self._accent_color_instruction = Color(*_rgba(self.palette["accent"]))
            self._accent_bar = RoundedRectangle(radius=[dp(2), dp(2), dp(2), dp(2)])
            self._border_color_instruction = Color(*_rgba(self.palette["border"]))
            self._border_line = Line(width=1.0)

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

    def _build_description_text(self):
        if not self.all_messages:
            count = int(self.banner_data.get("count") or 0)
            return f"{count} itens foram agrupados neste aviso." if count > 0 else "Sem detalhes adicionais."
        parts = []
        for item in self.all_messages[:4]:
            parts.append(item if item.endswith((".", "!", "?")) else f"{item}.")
        return " ".join(parts)

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
            radius=[dp(23), dp(23), dp(23), dp(23)],
            elevation=0,
            md_bg_color=self.palette["icon_bg"],
        )
        self._icon_label = MDLabel(
            text=md_icons.get(str(self.banner_data.get("icon") or "information-outline"), md_icons.get("information-outline", "")),
            font_style="Icon",
            halign="center",
            valign="middle",
            theme_text_color="Custom",
            text_color=self.palette["button_text"],
            font_size=dp(22),
        )
        self._icon_label.bind(size=lambda instance, value: setattr(instance, "text_size", value))
        self._icon_shell.add_widget(self._icon_label)
        self._top_row.add_widget(self._icon_shell)

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
            text=str(self.banner_data.get("title") or "Banner inteligente"),
            theme_text_color="Custom",
            text_color=self.palette["title"],
            font_size=dp(15.5),
            bold=True,
            shorten=True,
            shorten_from="right",
            size_hint_y=None,
        )
        _bind_auto_height(self._title_label, dp(22))
        self._title_row.add_widget(self._title_label)

        count = int(self.banner_data.get("count") or 0)
        self._count_chip = _build_chip(count, self.palette["chip_bg"], self.palette["button_text"]) if count > 0 else None
        if self._count_chip is not None:
            self._title_row.add_widget(self._count_chip)

        self._description_label = MDLabel(
            text="",
            theme_text_color="Custom",
            text_color=self.palette["text"],
            font_size=dp(12.8),
            line_height=1.22,
            size_hint_y=None,
        )
        _bind_auto_height(self._description_label, dp(20))
        self._text_box.add_widget(self._description_label)

        self._inline_actions = MDBoxLayout(
            orientation="horizontal",
            spacing=dp(8),
            size_hint=(None, None),
        )
        self._inline_actions.bind(minimum_width=lambda instance, value: setattr(instance, "width", value))
        self._inline_actions.bind(minimum_height=lambda instance, value: setattr(instance, "height", max(value, dp(34))))
        self._top_row.add_widget(self._inline_actions)

        self._inline_toggle_btn = self._build_action_button()
        self._inline_actions.add_widget(self._inline_toggle_btn)

        self._close_btn = MDIconButton(
            icon="close",
            theme_text_color="Custom",
            text_color=self.palette["muted"],
            size_hint=(None, None),
            size=(dp(34), dp(34)),
            on_release=lambda *_args: animate_banner_out(self._wrapper or self),
        )
        self._inline_actions.add_widget(self._close_btn)

        self._bottom_actions = MDBoxLayout(
            orientation="horizontal",
            spacing=dp(8),
            size_hint_y=None,
            height=0,
            opacity=0,
        )
        self._bottom_toggle_btn = self._build_action_button()
        self._bottom_actions.add_widget(self._bottom_toggle_btn)
        self._bottom_actions.add_widget(Widget())
        self._content.add_widget(self._bottom_actions)

        self._quick_actions = self._build_quick_actions()
        if self._quick_actions is not None:
            self._content.add_widget(self._quick_actions)

        self._details_scroll = ScrollView(
            size_hint=(1, None),
            height=0,
            opacity=0,
            do_scroll_x=False,
            do_scroll_y=False,
            bar_width=0,
        )
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
                size_hint_y=None,
                height=dp(3),
                color=self.palette["progress"],
            )
            self.add_widget(self._progress)

        self._rebuild_details_content()
        self._refresh_expandable_state()
        Clock.schedule_once(lambda _dt: self._handle_size_change(), 0)

    def _build_quick_actions(self):
        specs = [
            spec
            for spec in (self.banner_data.get("action_buttons") or [])
            if isinstance(spec, dict) and str(spec.get("text") or "").strip()
        ][:3]
        if not specs:
            return None

        row = MDBoxLayout(
            orientation="horizontal",
            spacing=dp(8),
            size_hint_y=None,
            height=dp(38),
        )
        self._quick_action_buttons = []
        for spec in specs:
            label = str(spec.get("text") or "").strip()
            callback = spec.get("callback") or spec.get("on_release")
            dismiss_after = bool(spec.get("dismiss_after", True))
            button = MDFlatButton(
                text=label.upper(),
                theme_text_color="Custom",
                text_color=self.palette["button_text"],
                size_hint=(None, None),
                size=(max(dp(104), dp(7.4 * len(label) + 30)), dp(36)),
            )
            button._preferred_banner_width = button.width
            _decorate_pill(button, self.palette["button_bg"], self.palette["border"])
            button.bind(
                on_release=lambda btn, cb=callback, close=dismiss_after: self._run_quick_action(
                    btn, cb, close
                )
            )
            row.add_widget(button)
            self._quick_action_buttons.append(button)
        row.add_widget(Widget())
        return row

    def _run_quick_action(self, button, callback, dismiss_after):
        if dismiss_after:
            animate_banner_out(self._wrapper or self)
        if callable(callback):
            try:
                callback()
            except TypeError:
                callback(button)

    def _sync_quick_action_widths(self):
        buttons = getattr(self, "_quick_action_buttons", [])
        if not buttons:
            return
        available = max(self.width - dp(44) - dp(8) * max(len(buttons) - 1, 0), dp(88))
        maximum = max(dp(88), available / len(buttons))
        for button in buttons:
            button.width = min(float(button._preferred_banner_width), maximum)

    def _build_action_button(self):
        button = MDFlatButton(
            text="Ver mais",
            theme_text_color="Custom",
            text_color=self.palette["button_text"],
            size_hint=(None, None),
            size=(dp(104), dp(36)),
            on_release=lambda *_args: self._toggle_details(),
        )
        _decorate_pill(button, self.palette["button_bg"], self.palette["border"])
        button.bind(on_press=lambda instance: self._animate_button(instance, pressed=True))
        button.bind(on_release=lambda instance: self._animate_button(instance, pressed=False))
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
        return label

    def _build_text_block(self, text):
        label = MDLabel(
            text=str(text or ""),
            theme_text_color="Custom",
            text_color=self.palette["text"],
            font_size=dp(12.6),
            line_height=1.22,
            size_hint_y=None,
        )
        _bind_auto_height(label, dp(22))
        return label

    def _build_bullet_text(self, text):
        label = MDLabel(
            text=f"• {str(text or '').strip()}",
            theme_text_color="Custom",
            text_color=self.palette["text"],
            font_size=dp(12.2),
            line_height=1.18,
            size_hint_y=None,
        )
        _bind_auto_height(label, dp(18))
        return label

    def _refresh_expandable_state(self):
        preview_limit = 230 if self.width >= dp(860) else 180 if self.width >= dp(620) else 130
        preview_text, truncated = _truncate_text(self.full_description, preview_limit)
        self._preview_truncated = truncated
        self._has_extra_content = bool(truncated or self.details_sections or len(self.all_messages) > 2)
        self._description_label.text = preview_text
        self._apply_action_button_state()

    def _apply_action_button_state(self):
        label = "Ver menos" if self._expanded else "Ver mais"
        self._inline_toggle_btn.text = label
        self._bottom_toggle_btn.text = label

        inline_visible = self._has_extra_content and not self._compact
        bottom_visible = self._has_extra_content and self._compact

        self._inline_toggle_btn.disabled = not inline_visible
        self._inline_toggle_btn.opacity = 1 if inline_visible else 0
        self._inline_toggle_btn.width = dp(104) if inline_visible else 0

        self._bottom_toggle_btn.disabled = not bottom_visible
        self._bottom_toggle_btn.opacity = 1 if bottom_visible else 0
        self._bottom_toggle_btn.width = dp(104) if bottom_visible else 0
        self._bottom_actions.opacity = 1 if bottom_visible else 0
        self._bottom_actions.height = dp(40) if bottom_visible else 0

    def _rebuild_details_content(self):
        self._details_content.clear_widgets()

        if self._preview_truncated:
            self._details_content.add_widget(self._build_section_title("Descrição completa"))
            self._details_content.add_widget(self._build_text_block(self.full_description))

        if len(self.all_messages) > 1:
            self._details_content.add_widget(self._build_section_title("Pontos observados"))
            for message in self.all_messages:
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
        local = self.to_widget(*pos)
        hovered = self.collide_point(*local)
        if hovered and not getattr(self, "_hovered", False):
            self._hovered = True
            Animation.cancel_all(self)
            Animation(y=dp(4), d=0.18, t="out_quad").start(self)
            Animation(elevation=self.palette["hover_elevation"], d=0.18, t="out_quad").start(self)
        elif not hovered and getattr(self, "_hovered", False):
            self._hovered = False
            Animation.cancel_all(self)
            Animation(y=0, d=0.18, t="out_quad").start(self)
            Animation(elevation=self.palette["elevation"], d=0.18, t="out_quad").start(self)

    def _handle_size_change(self, *_args):
        self._compact = self.width < dp(620)
        self._content.padding = [dp(18), dp(16), dp(16), dp(14)] if self._compact else [dp(22), dp(18), dp(18), dp(16)]
        self._top_row.spacing = dp(10) if self._compact else dp(14)
        self._icon_shell.size = (dp(40), dp(40)) if self._compact else (dp(46), dp(46))
        self._icon_shell.radius = [dp(20)] * 4 if self._compact else [dp(23)] * 4
        self._sync_quick_action_widths()
        self._refresh_expandable_state()
        if self._expanded:
            self._details_scroll.height = self._details_target_height()
        self._update_decorations()

    def _update_decorations(self, *_args):
        accent_x = self.x + dp(12)
        accent_y = self.y + dp(12)
        self._accent_bar.pos = (accent_x, accent_y)
        self._accent_bar.size = (dp(4), max(dp(52), self.height - dp(24)))
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
        extra = self._progress.height if self._progress is not None else 0
        self.height = self._content.height + extra
        if self._wrapper is not None:
            self._wrapper.height = self.height + dp(6)
            container = getattr(self._wrapper, "_banner_container", None)
            if container is not None:
                Clock.schedule_once(
                    lambda _dt, current=container: position_banners_center(
                        current, _visible_widgets(current), reset_x=False
                    ),
                    0,
                )


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
        noun = "alerta" if remaining == 1 else "alertas"
        message = f"{message} Há mais {remaining} {noun} neste aviso."
    message_scroll = _build_horizontal_banner_text_scroll(
        f"[b]ATENÇÃO:[/b] {message}",
        (0.2, 0.2, 0.2, 1),
    )

    close_btn = MDIconButton(
        icon="close",
        theme_text_color="Custom",
        text_color=(0.35, 0.35, 0.35, 1),
        size_hint=(None, None),
        size=(dp(32), dp(32)),
        pos_hint={"center_y": 0.5},
        on_release=lambda *_args: animate_banner_out(card),
    )

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


def _create_auto_banner_legacy(banner_data, show_timer=True, insights=None):
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
        text_color=(0.2, 0.2, 0.2, 1),
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
        text_color=(0.15, 0.15, 0.15, 1),
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
            Color(0.2, 0.2, 0.2, 0.85)
            badge._bg_rect = RoundedRectangle(pos=badge.pos, size=badge.size, radius=[dp(11)])
        badge.bind(pos=lambda *_: setattr(badge._bg_rect, "pos", badge.pos))
        badge.bind(size=lambda *_: setattr(badge._bg_rect, "size", badge.size))

    close_btn = _BannerIconButton(
        text=md_icons.get("close", ""),
        font_style="Icon",
        theme_text_color="Custom",
        text_color=(0.35, 0.35, 0.35, 1),
        font_size=dp(22),
        size_hint=(None, None),
        size=(dp(34), dp(34)),
        pos_hint={"center_y": 0.5},
        halign="center",
        valign="middle",
        on_release=lambda *_: animate_banner_out(card),
    )
    close_btn.bind(size=lambda inst, val: setattr(inst, "text_size", val))

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
            text=f"• {msg}",
            theme_text_color="Custom",
            text_color=(0.25, 0.25, 0.25, 1),
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
            text_color=(0.15, 0.15, 0.15, 1),
            font_size=dp(20),
            size_hint=(None, None),
            size=(dp(24), dp(24)),
            halign="center",
            valign="middle",
        )
        btn_icon.bind(size=lambda inst, val: setattr(inst, "text_size", val))

        btn_text = MDLabel(
            text="Ver mais",
            theme_text_color="Custom",
            text_color=(0.15, 0.15, 0.15, 1),
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
            Color(0, 0, 0, 0.08)
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
            size_hint_y=None,
            height=dp(48),
        )
        toggle_container.add_widget(toggle_btn_widget)
        toggle_container.add_widget(Widget())
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
    ]
    if action_specs:
        action_container = MDBoxLayout(
            orientation="horizontal",
            padding=[dp(16), dp(6), dp(16), dp(10)],
            spacing=dp(8),
            size_hint_y=None,
            height=dp(50),
        )

        def _run_banner_action(_button, callback=None, dismiss_after=True):
            if dismiss_after:
                animate_banner_out(card)
            if callable(callback):
                try:
                    callback()
                except TypeError:
                    callback(_button)

        action_buttons = []
        for spec in action_specs[:3]:
            text = str(spec.get("text") or "").strip().upper()
            callback = spec.get("callback") or spec.get("on_release")
            dismiss_after = bool(spec.get("dismiss_after", True))
            preferred_width = max(dp(104), dp(7.6 * len(text) + 28))
            button = MDFlatButton(
                text=text,
                theme_text_color="Custom",
                text_color=(0.15, 0.15, 0.15, 1),
                size_hint=(None, None),
                size=(preferred_width, dp(34)),
            )
            button._preferred_banner_width = preferred_width
            _decorate_pill(button, (1, 1, 1, 0.52), (0, 0, 0, 0.14), radius=dp(8))
            button.bind(
                on_release=lambda btn, cb=callback, close=dismiss_after: _run_banner_action(
                    btn,
                    callback=cb,
                    dismiss_after=close,
                )
            )
            action_container.add_widget(button)
            action_buttons.append(button)
        action_container.add_widget(Widget())

        def _sync_action_widths(*_args):
            if not action_buttons:
                return
            available = max(
                float(card.width or 0)
                - float(action_container.padding[0] + action_container.padding[2])
                - float(action_container.spacing * len(action_buttons)),
                float(dp(96) * len(action_buttons)),
            )
            max_button_width = max(dp(96), available / len(action_buttons))
            for button in action_buttons:
                button.width = min(float(getattr(button, "_preferred_banner_width", dp(104))), max_button_width)

        card.bind(width=_sync_action_widths)
        Clock.schedule_once(lambda _dt: _sync_action_widths(), 0)

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
        card.height = total
        card._base_height = total
        container = getattr(card, "_banner_container", None)
        if container is not None:
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
        _setup_details_toggle(card, toggle_btn_widget, details_sections)

    return card


def create_auto_banner(banner_data, show_timer=True, insights=None):
    """Create the compact banner from the original project version."""
    return _create_auto_banner_original(
        banner_data,
        show_timer=show_timer,
        insights=insights,
    )


def animate_banner_in(widget):
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
    target_x = widget._target_x
    target_y = widget._target_y
    target_opacity = getattr(widget, "_target_opacity", 1)
    Animation.cancel_all(widget)
    # Banners are overlays: they must never travel across dashboard content.
    # Keep them at their final centred coordinates and animate only visibility.
    widget.x = target_x
    widget.y = target_y
    widget.opacity = 0
    Animation(opacity=target_opacity, d=0.20, t="out_quad").start(widget)
    card = getattr(widget, "_banner_card", None)
    if card is not None and hasattr(card, "_animate_icon_intro"):
        try:
            card._animate_icon_intro()
        except Exception:
            pass


def animate_banner_out(widget):
    if not widget:
        return
    _cancel_event(getattr(widget, "_position_retry_ev", None))
    widget._position_retry_ev = None
    auto_event = getattr(widget, "_auto_dismiss_ev", None)
    if auto_event:
        auto_event.cancel()

    def _finish(*args):
        parent = widget.parent
        if parent:
            parent.remove_widget(widget)
        container = getattr(widget, "_banner_container", None)
        if container is None:
            return
        remaining = _visible_widgets(container)
        container._ai_banner_widgets = [item for item in remaining if item is not widget]
        if remaining:
            def _promote_next(_dt, current=container, visible=remaining):
                position_banners_center(current, visible, reset_x=False)
                _resume_auto_dismiss(visible[0])

            Clock.schedule_once(
                _promote_next,
                0,
            )
            return
        if getattr(container, "_ai_render_ev", None) is not None:
            return
        clear_banner_container(container)

    Animation.cancel_all(widget)
    anim = Animation(opacity=0, d=0.16, t="in_quad")
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
                toggle_btn._text.text = "Ver mais"
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


def _build_details_box(sections):
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
            text_color=(0.15, 0.15, 0.15, 1),
            font_size=dp(13),
            halign="left",
            valign="middle",
            size_hint_y=None,
        )
        _bind_auto_height(title_label, min_height=dp(20))
        details_content.add_widget(title_label)
        for item in items:
            item_label = MDLabel(
                text=f"  • {item}",
                theme_text_color="Custom",
                text_color=(0.3, 0.3, 0.3, 1),
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


def _setup_details_toggle(card, toggle_btn, details_sections):
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
                toggle_btn._text.text = "Ver mais"

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
                toggle_btn._text.text = "Ver menos"

            card._details_expanded = True
            _toggle_siblings(False)
            Clock.schedule_once(lambda dt: _recenter(), 0.3)

    toggle_btn.bind(on_touch_down=_on_touch_down)
    card._details_box = details_box
    card._toggle_details = _toggle


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
    if len(widgets) > 1:
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
    for idx, widget in enumerate(widgets):
        widget.width = banner_width
        widget.pos_hint = {}
        widget.disabled = False
        widget._stack_depth = 0
        widget._target_x = center_x - (banner_width / 2.0)
        widget._target_y = start_y + (len(widgets) - 1 - idx) * (widget.height + spacing)
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
    stagger_seconds=0.05,
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

            separation_seconds = max(float(stagger_seconds or 0.0), 0.0)
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
