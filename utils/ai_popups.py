import random

from kivy.animation import Animation
from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, Line, RoundedRectangle
from kivy.metrics import dp
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget
from kivymd.icon_definitions import md_icons
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDFlatButton, MDIconButton
from kivymd.uix.card import MDCard
from kivymd.uix.label import MDLabel
from kivymd.uix.progressbar import MDProgressBar

from utils.expiry_alerts import (
    ALERT_COLORS,
    ALERT_LEVEL_ALTO,
    ALERT_LEVEL_CRITICO,
    ALERT_LEVEL_LEVE,
    ALERT_LEVEL_MEDIO,
    ALERT_LEVEL_VENCIDO,
)
from utils.theme import get_theme_tokens


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
        return "alert-circle", "Vencimento Crítico", color
    if level == ALERT_LEVEL_ALTO:
        return "alert", "Vencimento Alto", color
    if level == ALERT_LEVEL_MEDIO:
        return "calendar-alert", "Vencimento Médio", color
    return "calendar-clock", "Vencimento Leve", color


def _get_stock_message_variant(item_name, stock, unit, days_left):
    del stock, unit
    if days_left < 0:
        variants = [
            f"{item_name} esgotou e precisa reposição imediata",
            f"{item_name} está sem stock disponível",
            f"{item_name} entrou em rutura operacional",
        ]
    elif days_left < 10:
        variants = [
            f"{item_name} está no limite e pode acabar em breve",
            f"{item_name} exige reposição prioritária",
            f"{item_name} está com cobertura muito curta",
        ]
    elif days_left < 15:
        variants = [
            f"{item_name} está com stock reduzido",
            f"{item_name} requer atenção ao ritmo de saída",
            f"{item_name} está abaixo do ideal para os próximos dias",
        ]
    else:
        variants = [
            f"{item_name} está abaixo do ponto de conforto",
            f"{item_name} merece acompanhamento de stock",
            f"{item_name} pede reposição planeada",
        ]
    return random.choice(variants)


def _get_expiry_message_variant(item_name, days_left, date_str):
    if days_left <= 2:
        variants = [
            f"{item_name} vence em {days_left} dias e precisa ação imediata",
            f"{item_name} está em janela crítica de validade",
            f"{item_name} vence já ({date_str}) e deve ganhar prioridade",
        ]
    elif days_left <= 7:
        variants = [
            f"{item_name} vence esta semana e pede aceleração de venda",
            f"{item_name} entra em risco de validade nos próximos dias",
            f"{item_name} está próximo do vencimento ({date_str})",
        ]
    else:
        variants = [
            f"{item_name} tem validade próxima e precisa monitorização",
            f"{item_name} vence em {days_left} dias e deve ser acompanhado",
            f"{item_name} entra no radar de validade ({date_str})",
        ]
    return random.choice(variants)


def _get_expiry_level_message(level, item_name, days_left, date_str):
    if level == ALERT_LEVEL_VENCIDO:
        overdue = abs(int(days_left))
        variants = [
            f"{item_name} está vencido há {overdue} dias",
            f"{item_name} ultrapassou a validade em {date_str}",
            f"{item_name} precisa retirada imediata da venda",
        ]
        return random.choice(variants)
    return _get_expiry_message_variant(item_name, days_left, date_str)


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
                unit = "kg" if is_weight else "unidades"
                messages.append(_get_stock_message_variant(name, stock, unit, days_left))
                urgency_levels.append(days_left)

        min_days = min(urgency_levels) if urgency_levels else 999
        if min_days < 1:
            title = random.choice(["Stock crítico", "Reposição urgente", "Rutura iminente"])
            icon = "alert-circle"
        elif min_days < 10:
            title = random.choice(["Stock baixo", "Atenção ao stock", "Reposição prioritária"])
            icon = "alert"
        else:
            title = random.choice(["Stock em monitorização", "Cobertura reduzida", "Acompanhamento de stock"])
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
            "title": "Stock em ordem",
            "messages": [
                "Nenhum produto com stock baixo no momento.",
                "A operação está estável para reposição.",
            ],
            "count": 0,
            "urgency": 999,
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
        }
    return {
        "kind": "positive",
        "variant": "success",
        "icon": "check-circle",
        "bg_color": (0.74, 0.92, 0.78, 1),
        "title": "Tudo em ordem",
        "messages": [
            "Sem alertas críticos de stock.",
            "Sem riscos imediatos de validade.",
        ],
        "count": 0,
        "urgency": 999,
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
                    unit = "kg" if is_weight else "un"
                    lines.append(f"{name}: {stock:.1f} {unit} (~{days_left:.1f} dias)")
            if lines:
                sections.append(("Produtos críticos", lines))

        forecast = insights.get("stock_forecast") or []
        if forecast:
            lines = []
            for item in forecast:
                if item.get("days_left") is None:
                    continue
                lines.append(f"{item.get('name')} - acaba em ~{float(item.get('days_left')):.1f} dias")
            if lines:
                sections.append(("Previsão de rutura", lines))

        ai_notes = (insights.get("ai_urgente_hoje") or []) + (insights.get("ai_atencao_proximos_dias") or [])
        if ai_notes:
            sections.append(("Análise inteligente", ai_notes))

    elif kind == "expiry":
        _add_recommendations(recommendations_expiry or recommendations_all)
        expiry_levels = _collect_expiry_levels(insights)
        level_titles = {
            ALERT_LEVEL_VENCIDO: "Vencidos",
            ALERT_LEVEL_CRITICO: "Crítico",
            ALERT_LEVEL_ALTO: "Alto",
            ALERT_LEVEL_MEDIO: "Médio",
            ALERT_LEVEL_LEVE: "Leve",
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
                lines.append(f"{name}: {days_left} dias - {stock:.0f} {unit} (vence {date_str})")
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
                    f"{item.get('name')}: vence {days_to_expiry}d, vende ~{float(days_to_sell):.0f}d "
                    f"(perda ~{float(item.get('loss_profit') or 0):.0f} MZN)"
                )
            if lines:
                sections.append(("Análise de risco", lines))

        ai_notes = (insights.get("ai_urgente_hoje") or []) + (insights.get("ai_atencao_proximos_dias") or [])
        ai_expiry = [note for note in ai_notes if any(word in note.lower() for word in ("venc", "valid", "expir"))]
        if ai_expiry:
            sections.append(("Análise inteligente", ai_expiry))

        ai_opportunities = insights.get("ai_oportunidades") or []
        if ai_opportunities:
            sections.append(("Oportunidades", ai_opportunities))

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
                Clock.schedule_once(lambda _dt, current=container: position_banners_center(current, _visible_widgets(current)), 0)


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
        anchor_x="left",
        anchor_y="top",
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


def _create_auto_banner_legacy(banner_data, show_timer=True, insights=None):
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
        padding=[dp(20), dp(22), dp(24), dp(10)],
        spacing=dp(14),
        size_hint_y=None,
        height=dp(48),
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
    )
    title.bind(size=lambda inst, val: setattr(inst, "text_size", (val[0], None)))

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
            halign="center",
            valign="middle",
        )
        badge.bind(size=lambda inst, val: setattr(inst, "text_size", val))
        with badge.canvas.before:
            Color(0.2, 0.2, 0.2, 0.85)
            badge._bg_rect = RoundedRectangle(pos=badge.pos, size=badge.size, radius=[dp(11)])
        badge.bind(pos=lambda *_: setattr(badge._bg_rect, "pos", badge.pos))
        badge.bind(size=lambda *_: setattr(badge._bg_rect, "size", badge.size))

    close_btn = MDIconButton(
        icon="close",
        theme_text_color="Custom",
        text_color=(0.35, 0.35, 0.35, 1),
        size_hint=(None, None),
        size=(dp(32), dp(32)),
        pos_hint={"center_y": 0.5},
        on_release=lambda *_: animate_banner_out(card),
    )

    header.add_widget(icon)
    header.add_widget(title)
    if badge:
        header.add_widget(badge)
    header.add_widget(MDLabel())
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
        size_hint=(None, None),
    )
    body.bind(minimum_height=lambda inst, value: setattr(inst, "height", value))
    body.bind(minimum_width=lambda inst, value: setattr(inst, "width", value))
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
        )
        _bind_texture_size(bullet, min_height=dp(20), horizontal_padding=dp(2))
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
        badge_new = None
        if item_count > 5:
            badge_new = MDLabel(
                text=f"+{item_count}",
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
            padding=[dp(16), dp(4), dp(16), dp(10)],
            size_hint_y=None,
            height=dp(44),
        )
        toggle_container.add_widget(toggle_btn_widget)
        toggle_container.add_widget(MDLabel())
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

    card.add_widget(header)
    card.add_widget(body_wrapper)
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

    total_height = dp(48) + body_wrapper.height
    if toggle_container:
        total_height += dp(44)
    if progress:
        total_height += dp(3)

    card.height = total_height
    card._base_height = total_height
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
    return _create_auto_banner_legacy(
        banner_data,
        show_timer=show_timer,
        insights=insights,
    )


def animate_banner_in(widget):
    if not widget:
        return
    target_x = getattr(widget, "_target_x", widget.x)
    target_y = getattr(widget, "_target_y", widget.y)
    target_opacity = getattr(widget, "_target_opacity", 1)
    start_x = getattr(widget, "_entry_x", target_x - max(float(widget.width or 0) * 0.42, float(dp(180))))
    start_y = getattr(widget, "_entry_y", target_y + dp(10))
    pass_x = getattr(widget, "_pass_x", target_x + dp(12))
    pass_y = getattr(widget, "_pass_y", target_y - dp(4))
    Animation.cancel_all(widget)
    widget.x = start_x
    widget.y = start_y
    widget.opacity = 0
    (
        Animation(
            x=pass_x,
            y=pass_y,
            opacity=min(1.0, float(target_opacity) + 0.08),
            d=0.16,
            t="out_cubic",
        )
        + Animation(x=target_x, y=target_y, opacity=target_opacity, d=0.10, t="out_quad")
    ).start(widget)
    card = getattr(widget, "_banner_card", None)
    if card is not None and hasattr(card, "_animate_icon_intro"):
        try:
            card._animate_icon_intro()
        except Exception:
            pass


def animate_banner_out(widget):
    if not widget:
        return
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
            Clock.schedule_once(
                lambda _dt, current=container, visible=remaining: position_banners_center(
                    current,
                    visible,
                    reset_x=False,
                ),
                0,
            )
            return
        if getattr(container, "_ai_render_ev", None) is not None:
            return
        clear_banner_container(container)

    parent = widget.parent
    exit_x = getattr(widget, "_exit_x", None)
    if exit_x is None and parent:
        exit_x = parent.width + widget.width
    if exit_x is None:
        exit_x = widget.x + widget.width
    target_y = getattr(widget, "_target_y", widget.y)

    Animation.cancel_all(widget)
    anim = (
        Animation(x=widget.x + dp(14), opacity=0.94, d=0.05, t="out_quad")
        + Animation(x=exit_x, y=target_y, opacity=0, d=0.12, t="in_cubic")
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
        size_hint=(None, None),
    )
    details_content.bind(minimum_height=lambda inst, value: setattr(inst, "height", value))
    details_content.bind(minimum_width=lambda inst, value: setattr(inst, "width", value))
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
        )
        _bind_texture_size(title_label, min_height=dp(20), horizontal_padding=dp(2))
        details_content.add_widget(title_label)
        for item in items:
            item_label = MDLabel(
                text=f"  • {item}",
                theme_text_color="Custom",
                text_color=(0.3, 0.3, 0.3, 1),
                font_size=dp(12),
                halign="left",
                valign="middle",
            )
            _bind_texture_size(item_label, min_height=dp(18), horizontal_padding=dp(2))
            details_content.add_widget(item_label)
        if sections.index((title, items)) < len(sections) - 1:
            details_content.add_widget(MDLabel(size_hint=(None, None), width=dp(4), height=dp(4)))

    def _sync_details_scroll(*_args):
        details_height = _fit_scroll_content(
            details_scroll,
            details_content,
            max_height=dp(168),
            min_height=dp(40),
        )
        details_box._target_height = details_height + dp(20)

    details_scroll.bind(width=_sync_details_scroll)
    details_content.bind(minimum_height=_sync_details_scroll, minimum_width=_sync_details_scroll)
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


def position_banners_center(container, widgets, spacing=dp(14), reset_x=True, columns=None):
    del columns
    if not container:
        return
    if not widgets:
        return

    if container.width <= 0 or container.height <= 0:
        Clock.schedule_once(
            lambda dt: position_banners_center(container, widgets, spacing, reset_x),
            0.05,
        )
        return

    use_staircase = 1 < len(widgets) <= 4
    if use_staircase:
        max_height = max(float(w.height or 0) for w in widgets)
        x_step = min(max(container.width * 0.026, float(dp(18))), float(dp(34)))
        y_step = min(max(max_height * 0.26, float(dp(26))), float(dp(42)))
        banner_width = min(container.width * 0.84, dp(720))
        footprint_width = banner_width + x_step * (len(widgets) - 1)
        footprint_height = max_height + y_step * (len(widgets) - 1)
        start_x = max((container.width - footprint_width) / 2.0, dp(12))
        start_y = max((container.height - footprint_height) / 2.0, dp(18))

        for idx, widget in enumerate(widgets):
            widget.width = banner_width
            widget._target_x = start_x + idx * x_step
            widget._target_y = start_y + (len(widgets) - 1 - idx) * y_step
            widget._target_opacity = max(0.82, 1.0 - (idx * 0.06))
            widget._entry_x = -banner_width - min(max(banner_width * 0.18, dp(96)), dp(180))
            widget._entry_y = widget._target_y + dp(12) + idx * dp(3)
            widget._pass_x = widget._target_x + min(max(banner_width * 0.02, dp(10)), dp(16))
            widget._pass_y = widget._target_y - dp(4)
            widget._exit_x = container.width + min(max(banner_width * 0.08, dp(70)), dp(120))
            y = widget._target_y
            if reset_x:
                widget.pos = (widget._entry_x, widget._entry_y)
                widget.opacity = 0
            else:
                widget.pos = (getattr(widget, "_target_x", widget.x), y)
                widget.opacity = getattr(widget, "_target_opacity", widget.opacity)
        return

    total_height = sum(w.height for w in widgets) + spacing * (len(widgets) - 1)
    start_y = (container.height - total_height) / 2.0

    banner_width = min(container.width * 0.92, dp(760))
    for idx, widget in enumerate(widgets):
        widget.width = banner_width
        widget._target_x = (container.width - banner_width) / 2.0
        widget._target_y = start_y + (len(widgets) - 1 - idx) * (widget.height + spacing)
        widget._target_opacity = 1
        widget._entry_x = -banner_width - min(max(banner_width * 0.22, dp(120)), dp(220))
        widget._entry_y = widget._target_y + dp(8)
        widget._pass_x = widget._target_x + min(max(banner_width * 0.03, dp(12)), dp(20))
        widget._pass_y = widget._target_y - dp(4)
        widget._exit_x = container.width + min(max(banner_width * 0.10, dp(80)), dp(140))
        y = widget._target_y
        if reset_x:
            widget.pos = (widget._entry_x, widget._entry_y)
            widget.opacity = 0
        else:
            widget.pos = (getattr(widget, "_target_x", widget.x), y)
            widget.opacity = getattr(widget, "_target_opacity", widget.opacity)


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

        draw_widgets = list(reversed(widgets)) if 1 < len(widgets) <= 4 else list(widgets)
        for widget in draw_widgets:
            container.add_widget(widget)

        container._ai_banner_widgets = widgets
        position_banners_center(container, widgets)

        separation_seconds = max(float(stagger_seconds or 0.0), 0.0)
        for idx, widget in enumerate(widgets):
            delay = idx * separation_seconds

            def _start(_inner_dt, w=widget):
                animate_banner_in(w)
                progress = getattr(w, "_progress", None)
                if progress and show_timer and auto_dismiss_seconds:
                    progress.value = 100
                    Animation(value=0, d=auto_dismiss_seconds, t="linear").start(progress)
                if auto_dismiss_seconds:
                    w._auto_dismiss_ev = Clock.schedule_once(
                        lambda dt2, ww=w: animate_banner_out(ww),
                        auto_dismiss_seconds,
                    )

            Clock.schedule_once(_start, delay)

    container._ai_render_ev = Clock.schedule_once(_mount, 0.01 if old_widgets else 0)
