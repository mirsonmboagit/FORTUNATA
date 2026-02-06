from kivy.animation import Animation
from kivy.clock import Clock
from kivy.metrics import dp
from kivymd.icon_definitions import md_icons
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDIconButton, MDFlatButton
from kivymd.uix.card import MDCard
from kivymd.uix.label import MDLabel
from kivymd.uix.progressbar import MDProgressBar


def animate_banner_in(widget):
    target_x = getattr(widget, "_target_x", widget.x)
    widget.x = -widget.width
    widget.opacity = 1
    Animation(x=target_x, d=0.35, t="out_cubic").start(widget)


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

    parent = widget.parent
    exit_x = getattr(widget, "_exit_x", None)
    if exit_x is None and parent:
        exit_x = parent.width + widget.width
    if exit_x is None:
        exit_x = widget.x + widget.width

    anim = Animation(x=exit_x, d=0.25, t="in_cubic")
    anim.bind(on_complete=_finish)
    anim.start(widget)


def build_auto_banner_data(insights):
    banners = []
    low_stock = insights.get("low_stock", [])
    exp7 = insights.get("expiring_7", [])
    exp15 = insights.get("expiring_15", [])

    if low_stock:
        names = []
        for item in low_stock[:2]:
            if isinstance(item, (list, tuple)):
                names.append(item[0])
            elif isinstance(item, dict):
                names.append(item.get("name"))
        extra = max(0, len(low_stock) - len(names))
        suffix = f" e mais {extra}" if extra else ""
        message = f"{len(low_stock)} produtos com stock baixo: {', '.join(names)}{suffix}."
        banners.append(
            {
                "kind": "stock",
                "icon": "alert",
                "bg_color": (0.97, 0.94, 0.76, 1),
                "message": message,
            }
        )

    if exp7 or exp15:
        total = len(exp7) + len(exp15)
        names = [item[0] for item in (exp7 + exp15)[:2]]
        extra = max(0, total - len(names))
        suffix = f" e mais {extra}" if extra else ""
        message = f"{total} produtos perto do vencimento: {', '.join(names)}{suffix}."
        banners.append(
            {
                "kind": "expiry",
                "icon": "alert-octagon-outline",
                "bg_color": (0.96, 0.76, 0.76, 1),
                "message": message,
            }
        )

    return banners


def build_banner_details_sections(insights, kind, max_lines=3):
    sections = []
    recommendations_stock = insights.get("recommendations_stock") or []
    recommendations_expiry = insights.get("recommendations_expiry") or []

    if kind == "stock":
        low_stock = insights.get("low_stock") or []
        if low_stock:
            lines = []
            for item in low_stock[:max_lines]:
                if isinstance(item, (list, tuple)):
                    name = item[0]
                    stock = item[1]
                    unit = "kg" if len(item) > 2 and item[2] else "un"
                else:
                    name = item.get("name")
                    stock = item.get("stock")
                    unit = item.get("unit") or "un"
                lines.append(f"{name} (stock: {stock} {unit})")
            sections.append(("Produtos criticos", lines))

        forecast = insights.get("stock_forecast") or []
        if forecast:
            lines = []
            for item in forecast[:max_lines]:
                name = item.get("name")
                days_left = item.get("days_left")
                qty = item.get("recommended_qty")
                unit = item.get("unit") or "un"
                if days_left is None:
                    continue
                lines.append(f"{name} ~{days_left:.1f} dias (repor {qty:.2f} {unit})")
            if lines:
                sections.append(("Previsao de ruptura", lines))

        ai_notes = insights.get("ai_stock_notes") or []
        if ai_notes:
            sections.append(("IA - sugestoes", ai_notes[:max_lines]))
        if recommendations_stock:
            sections.append(("Recomendacoes", recommendations_stock[:5]))

    elif kind == "expiry":
        exp7 = insights.get("expiring_7") or []
        if exp7:
            lines = []
            for name, days_left, date_str, stock, unit in exp7[:max_lines]:
                lines.append(
                    f"{name} - {days_left} dias (vence {date_str}) — restam {stock} {unit}"
                )
            sections.append(("Vencimento critico (7 dias)", lines))

        exp15 = insights.get("expiring_15") or []
        if exp15:
            lines = []
            for name, days_left, date_str, stock, unit in exp15[:max_lines]:
                lines.append(
                    f"{name} - {days_left} dias (vence {date_str}) — restam {stock} {unit}"
                )
            sections.append(("Vencimento em 15 dias", lines))

        expiry_risk = insights.get("expiry_risk") or []
        if expiry_risk:
            lines = []
            for item in expiry_risk[:max_lines]:
                name = item.get("name")
                days_to_expiry = item.get("days_to_expiry")
                days_to_sell = item.get("days_to_sell")
                if days_to_expiry is None or days_to_sell is None:
                    continue
                lines.append(
                    f"{name} vence em {days_to_expiry} dias, vende em ~{days_to_sell:.1f} dias"
                )
            if lines:
                sections.append(("Risco de vencimento", lines))

        if expiry_risk:
            lines = []
            for item in expiry_risk[:max_lines]:
                name = item.get("name")
                loss_revenue = item.get("loss_revenue")
                loss_profit = item.get("loss_profit")
                if loss_revenue is None or loss_profit is None:
                    continue
                lines.append(
                    f"{name}: perda receita ~{loss_revenue:.2f} MZN | perda lucro ~{loss_profit:.2f} MZN"
                )
            if lines:
                sections.append(("Perda estimada", lines))

        ai_notes = insights.get("ai_expiry_notes") or []
        if ai_notes:
            sections.append(("IA - sugestoes", ai_notes[:max_lines]))
        if recommendations_expiry:
            sections.append(("Recomendacoes", recommendations_expiry[:5]))

    return sections


def _build_details_box(sections):
    details_box = MDBoxLayout(
        orientation="vertical",
        spacing=dp(4),
        padding=[dp(16), 0, dp(16), dp(10)],
        size_hint_y=None,
        height=0,
        opacity=0,
    )
    for title, items in sections:
        details_box.add_widget(
            MDLabel(
                text=title,
                bold=True,
                theme_text_color="Custom",
                text_color=(0.2, 0.2, 0.2, 1),
                size_hint_y=None,
                height=dp(18),
            )
        )
        for item in items:
            details_box.add_widget(
                MDLabel(
                    text=f"- {item}",
                    theme_text_color="Custom",
                    text_color=(0.25, 0.25, 0.25, 1),
                    size_hint_y=None,
                    height=dp(16),
                    shorten=True,
                    shorten_from="right",
                )
            )
    details_box._target_height = max(_calc_details_height(details_box), dp(48))
    return details_box


def _calc_details_height(details_box):
    total = 0
    for child in details_box.children:
        total += child.height
    if details_box.children:
        total += details_box.spacing * (len(details_box.children) - 1)
    return max(total, details_box.minimum_height)


def create_auto_banner(banner_data, show_timer=True):
    card = MDCard(
        orientation="vertical",
        padding=[0, 0, 0, 0],
        spacing=dp(6),
        size_hint=(None, None),
        size_hint_y=None,
        height=dp(70),
        md_bg_color=banner_data["bg_color"],
        radius=[10, 10, 10, 10],
        elevation=2,
    )
    card._target_height = dp(70)

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

    text = MDLabel(
        text=f"[b]ATENCAO:[/b] {banner_data['message']}",
        markup=True,
        theme_text_color="Custom",
        text_color=(0.2, 0.2, 0.2, 1),
        halign="left",
        valign="middle",
        shorten=True,
        shorten_from="right",
    )
    text.bind(size=lambda inst, val: setattr(inst, "text_size", (val[0], None)))

    close_btn = MDIconButton(
        icon="close",
        theme_text_color="Custom",
        text_color=(0.35, 0.35, 0.35, 1),
        size_hint=(None, None),
        size=(dp(32), dp(32)),
        pos_hint={"center_y": 0.5},
        on_release=lambda x: animate_banner_out(card),
    )

    body = MDBoxLayout(
        orientation="vertical",
        spacing=dp(6),
        size_hint_y=None,
        height=0,
    )

    content = MDBoxLayout(
        orientation="horizontal",
        padding=[dp(14), dp(10), dp(10), dp(0)],
        spacing=dp(10),
        size_hint_y=None,
        height=dp(50),
    )
    content.add_widget(icon)
    content.add_widget(text)
    content.add_widget(close_btn)
    body.add_widget(content)

    details_sections = banner_data.get("details_sections") or []
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

    body.height = (
        sum(child.height for child in body.children)
        + body.spacing * max(len(body.children) - 1, 0)
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
    card._details_expanded = False
    card._base_height = body.height + (progress.height if progress else 0)
    card.height = card._base_height

    if details_sections and toggle_btn and details_box:
        def _recenter():
            container = getattr(card, "_banner_container", None)
            widgets = getattr(container, "_ai_banner_widgets", None) if container else None
            if container and widgets:
                position_banners_center(container, widgets, reset_x=False)

        def _toggle_details(*args):
            if card._details_expanded:
                anim = Animation(height=0, opacity=0, d=0.2, t="in_out_cubic")
                anim.start(details_box)
                Animation(height=card._body._base_height, d=0.2, t="in_out_cubic").start(card._body)
                Animation(height=card._base_height, d=0.2, t="in_out_cubic").start(card)

                def _finish(*_):
                    if details_box.parent:
                        details_box.parent.remove_widget(details_box)
                    toggle_btn.text = "Saber mais"
                    card._details_expanded = False
                    Clock.schedule_once(lambda dt: _recenter(), 0)

                anim.bind(on_complete=_finish)
            else:
                if details_box.parent is None:
                    card._body.add_widget(details_box)
                target_h = max(
                    getattr(details_box, "_target_height", 0),
                    _calc_details_height(details_box),
                )
                details_box._target_height = target_h
                body_target = card._body._base_height + target_h + card._body.spacing
                card_target = card._base_height + target_h + card._body.spacing
                Animation(height=target_h, opacity=1, d=0.25, t="out_cubic").start(details_box)
                Animation(height=body_target, d=0.25, t="out_cubic").start(card._body)
                Animation(height=card_target, d=0.25, t="out_cubic").start(card)
                toggle_btn.text = "Ocultar"
                card._details_expanded = True
                Clock.schedule_once(lambda dt: _recenter(), 0.01)

        toggle_btn.bind(on_release=_toggle_details)

    return card


def position_banners_center(container, widgets, spacing=dp(12), reset_x=True):
    if not widgets:
        return
    if container.width <= 0 or container.height <= 0:
        Clock.schedule_once(
            lambda dt: position_banners_center(container, widgets, spacing), 0
        )
        return

    total_height = sum(w.height for w in widgets) + spacing * (len(widgets) - 1)
    start_y = (container.height - total_height) / 2.0

    banner_width = container.width * 0.9
    for idx, widget in enumerate(widgets):
        widget.width = banner_width
        widget._target_x = (container.width - banner_width) / 2.0
        widget._exit_x = container.width + banner_width
        y = start_y + (len(widgets) - 1 - idx) * (widget.height + spacing)
        if reset_x:
            widget.pos = (-widget.width, y)
        else:
            widget.pos = (getattr(widget, "_target_x", widget.x), y)


def render_auto_banners(
    container, banner_data_list, auto_dismiss_seconds=10, show_timer=True
):
    container.clear_widgets()
    widgets = []
    for data in banner_data_list:
        widget = create_auto_banner(data, show_timer=show_timer)
        widget._banner_container = container
        container.add_widget(widget)
        widgets.append(widget)

    container._ai_banner_widgets = widgets
    position_banners_center(container, widgets)
    for idx, widget in enumerate(widgets):
        delay = idx * 1.0

        def _start(dt, w=widget):
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
