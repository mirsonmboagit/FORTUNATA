from __future__ import annotations

from datetime import datetime

from kivy.app import App
from kivy.clock import Clock
from kivy.metrics import dp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.card import MDCard
from kivymd.uix.gridlayout import MDGridLayout
from kivymd.uix.label import MDLabel

FigureCanvasKivyAgg = None
Figure = None
MATPLOTLIB_AVAILABLE = None


def _ensure_matplotlib():
    global FigureCanvasKivyAgg, Figure, MATPLOTLIB_AVAILABLE
    if MATPLOTLIB_AVAILABLE is not None:
        return MATPLOTLIB_AVAILABLE
    try:
        from kivy_garden.matplotlib.backend_kivyagg import FigureCanvasKivyAgg as _Canvas
        from matplotlib.figure import Figure as _Figure

        FigureCanvasKivyAgg = _Canvas
        Figure = _Figure
        MATPLOTLIB_AVAILABLE = True
    except Exception:
        FigureCanvasKivyAgg = None
        Figure = None
        MATPLOTLIB_AVAILABLE = False
    return MATPLOTLIB_AVAILABLE


def _theme(name, fallback):
    app = App.get_running_app()
    tokens = getattr(app, "theme_tokens", {}) if app else {}
    return tokens.get(name, fallback)


def _format_mzn(value):
    try:
        return f"{float(value):,.2f} MZN".replace(",", " ")
    except Exception:
        return "0.00 MZN"


def _format_count(value):
    try:
        return str(int(value or 0))
    except Exception:
        return "0"


def _format_quantity(value):
    try:
        return f"{float(value):,.1f}".replace(",", " ")
    except Exception:
        return "0.0"


def _format_percent(value):
    if value is None:
        return "N/D"
    try:
        return f"{float(value):.1f}%"
    except Exception:
        return "N/D"


def _format_short_date(value):
    text = str(value or "").strip()
    if not text:
        return "--/--"
    try:
        return datetime.fromisoformat(text).strftime("%d/%m")
    except Exception:
        pass
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).strftime("%d/%m")
        except Exception:
            continue
    return text


def _set_label_text_color(label, color):
    label.theme_text_color = "Custom"
    label.text_color = color


class ProductivityKpiStrip(MDGridLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.cols = 4
        self.spacing = dp(12)
        self.size_hint_y = None
        self.adaptive_height = True
        self.bind(minimum_height=self.setter("height"))
        self._cards = {}
        self._sync_layout_trigger = Clock.create_trigger(self._sync_layout, 0)
        self.bind(width=lambda *_: self._sync_layout_trigger())
        self._build()

    def _build(self):
        specs = [
            ("sales", "Vendas", _theme("primary", (0.15, 0.52, 0.76, 1))),
            ("revenue", "Receita", _theme("success", (0.19, 0.65, 0.33, 1))),
            ("ticket", "Ticket Medio", _theme("warning", (0.86, 0.57, 0.17, 1))),
            ("terminals", "Caixas Ativos", _theme("info", (0.12, 0.55, 0.72, 1))),
        ]
        for key, title, accent in specs:
            card = MDCard(
                orientation="vertical",
                size_hint_y=None,
                height=dp(106),
                padding=[dp(16), dp(14), dp(16), dp(14)],
                spacing=dp(6),
                radius=[dp(12)],
                elevation=1,
                md_bg_color=_theme("card_alt", (0.96, 0.97, 0.98, 1)),
            )
            title_label = MDLabel(
                text=title,
                font_style="Caption",
                size_hint_y=None,
                height=dp(18),
            )
            value_label = MDLabel(
                text="0",
                bold=True,
                font_size=dp(24),
                size_hint_y=None,
                height=dp(34),
            )
            subtitle_label = MDLabel(
                text="",
                font_style="Caption",
                size_hint_y=None,
                height=dp(20),
            )
            _set_label_text_color(title_label, _theme("text_secondary", (0.45, 0.48, 0.52, 1)))
            _set_label_text_color(value_label, accent)
            _set_label_text_color(subtitle_label, _theme("text_secondary", (0.45, 0.48, 0.52, 1)))
            card.add_widget(title_label)
            card.add_widget(value_label)
            card.add_widget(subtitle_label)
            self._cards[key] = {
                "card": card,
                "title": title_label,
                "value": value_label,
                "subtitle": subtitle_label,
                "accent": accent,
            }
            self.add_widget(card)
        self._sync_layout()

    def _sync_layout(self, *_args):
        if self.width >= dp(1160):
            self.cols = 4
        elif self.width >= dp(720):
            self.cols = 2
        else:
            self.cols = 1

    def set_summary(self, summary):
        summary = summary or {}
        best_day = summary.get("best_day") or {}
        cards = self._cards
        cards["sales"]["value"].text = _format_count(summary.get("total_sales"))
        cards["sales"]["subtitle"].text = f"Qtd total: {_format_quantity(summary.get('total_quantity'))}"

        cards["revenue"]["value"].text = _format_mzn(summary.get("total_revenue"))
        if best_day:
            cards["revenue"]["subtitle"].text = (
                f"Pico: {_format_short_date(best_day.get('date'))} | {_format_mzn(best_day.get('revenue'))}"
            )
        else:
            cards["revenue"]["subtitle"].text = "Sem pico relevante"

        cards["ticket"]["value"].text = _format_mzn(summary.get("avg_ticket"))
        cards["ticket"]["subtitle"].text = f"Desc. medio: {_format_percent(summary.get('avg_discount_percent'))}"

        cards["terminals"]["value"].text = _format_count(summary.get("active_terminals"))
        cards["terminals"]["subtitle"].text = f"Margem media: {_format_percent(summary.get('avg_margin_percent'))}"

        for data in cards.values():
            data["card"].md_bg_color = _theme("card_alt", (0.96, 0.97, 0.98, 1))
            _set_label_text_color(data["title"], _theme("text_secondary", (0.45, 0.48, 0.52, 1)))
            _set_label_text_color(data["value"], data["accent"])
            _set_label_text_color(data["subtitle"], _theme("text_secondary", (0.45, 0.48, 0.52, 1)))


class _BaseChartCard(MDCard):
    def __init__(self, title, subtitle, height=dp(320), **kwargs):
        super().__init__(**kwargs)
        self.orientation = "vertical"
        self.size_hint_y = None
        self.height = height
        self.padding = [dp(16), dp(14), dp(16), dp(12)]
        self.spacing = dp(8)
        self.radius = [dp(12)]
        self.elevation = 1
        self.md_bg_color = _theme("card", (1, 1, 1, 1))

        self.title_label = MDLabel(
            text=title,
            font_style="Subtitle1",
            bold=True,
            size_hint_y=None,
            height=dp(24),
        )
        self.subtitle_label = MDLabel(
            text=subtitle,
            font_style="Caption",
            size_hint_y=None,
            height=dp(18),
        )
        self.content_box = MDBoxLayout(orientation="vertical")
        self._canvas_widget = None
        self._figure = None

        self.add_widget(self.title_label)
        self.add_widget(self.subtitle_label)
        self.add_widget(self.content_box)
        self._apply_theme()

    def _apply_theme(self):
        self.md_bg_color = _theme("card", (1, 1, 1, 1))
        _set_label_text_color(self.title_label, _theme("text_primary", (0.2, 0.2, 0.2, 1)))
        _set_label_text_color(self.subtitle_label, _theme("text_secondary", (0.45, 0.48, 0.52, 1)))

    def _clear_content(self):
        if self._figure is not None:
            try:
                self._figure.clear()
            except Exception:
                pass
            self._figure = None
        self._canvas_widget = None
        self.content_box.clear_widgets()

    def set_state_text(self, text):
        self._apply_theme()
        self._clear_content()
        label = MDLabel(
            text=text,
            halign="center",
            valign="middle",
        )
        label.bind(size=lambda inst, value: setattr(inst, "text_size", value))
        _set_label_text_color(label, _theme("text_secondary", (0.45, 0.48, 0.52, 1)))
        self.content_box.add_widget(label)

    def set_figure(self, figure):
        if not _ensure_matplotlib():
            self.set_state_text("Graficos indisponiveis no momento.")
            return
        self._apply_theme()
        self._clear_content()
        self._figure = figure
        self._canvas_widget = FigureCanvasKivyAgg(figure)
        self.content_box.add_widget(self._canvas_widget)


class DailyProductivityChart(_BaseChartCard):
    def __init__(self, **kwargs):
        super().__init__(
            title="Tendencia Diaria",
            subtitle="Volume de vendas por dia no periodo selecionado",
            height=dp(332),
            **kwargs,
        )

    def set_series(self, series, summary=None):
        summary = summary or {}
        if not _ensure_matplotlib():
            self.set_state_text("Graficos indisponiveis no momento.")
            return
        series = list(series or [])
        if not series or not any(int(item.get("sales_count") or 0) > 0 for item in series):
            self.set_state_text("Sem vendas no período selecionado.")
            return

        tokens = getattr(App.get_running_app(), "theme_tokens", {}) or {}
        primary = tokens.get("primary", (0.15, 0.52, 0.76, 1))
        success = tokens.get("success", (0.19, 0.65, 0.33, 1))
        info = tokens.get("info", (0.18, 0.58, 0.86, 1))
        warning = tokens.get("warning", (0.92, 0.68, 0.18, 1))
        danger = tokens.get("danger", (0.88, 0.34, 0.30, 1))
        divider = tokens.get("divider", (0.82, 0.85, 0.9, 1))
        label_color = tokens.get("text_secondary", (0.42, 0.46, 0.5, 1))
        bg_color = tokens.get("card", (1, 1, 1, 1))

        labels = [_format_short_date(item.get("date")) for item in series]
        values = [int(item.get("sales_count") or 0) for item in series]
        revenues = [float(item.get("revenue") or 0.0) for item in series]
        x_values = list(range(len(series)))

        figure = Figure(figsize=(6.4, 3.2), dpi=100)
        figure.patch.set_facecolor(bg_color)
        ax = figure.add_subplot(111)
        ax.set_facecolor(bg_color)
        palette = [
            primary,
            success,
            info,
            warning,
            danger,
            (*primary[:3], 0.78),
            (*success[:3], 0.78),
        ]
        bar_colors = [palette[index % len(palette)] for index in range(len(values))]
        bars = ax.bar(x_values, values, color=bar_colors, width=0.62)
        ax.grid(axis="y", color=(*divider[:3], 0.55), linewidth=0.9)
        ax.set_axisbelow(True)

        if len(x_values) == 1:
            ax.set_xlim(-0.5, 0.5)
        else:
            ax.set_xlim(-0.6, len(x_values) - 0.4)

        tick_step = max(1, len(labels) // 7)
        tick_positions = list(range(0, len(labels), tick_step))
        if tick_positions[-1] != len(labels) - 1:
            tick_positions.append(len(labels) - 1)
        ax.set_xticks(tick_positions)
        ax.set_xticklabels([labels[index] for index in tick_positions], rotation=0)
        ax.tick_params(axis="x", colors=label_color, labelsize=9)
        ax.tick_params(axis="y", colors=label_color, labelsize=9)

        for spine_name in ("top", "right"):
            ax.spines[spine_name].set_visible(False)
        ax.spines["left"].set_color((*divider[:3], 0.8))
        ax.spines["bottom"].set_color((*divider[:3], 0.8))

        best_day = summary.get("best_day") or {}
        if best_day:
            best_date = str(best_day.get("date") or "")
            for index, item in enumerate(series):
                if str(item.get("date") or "") == best_date:
                    bars[index].set_color(success)
                    ax.annotate(
                        "Pico",
                        xy=(index, values[index]),
                        xytext=(0, 12),
                        textcoords="offset points",
                        ha="center",
                        color=success,
                        fontsize=9,
                        fontweight="bold",
                    )
                    break

        max_value = max(values) if values else 0
        ax.set_ylim(0, max(max_value * 1.2, 4))
        for index, bar in enumerate(bars):
            ax.text(
                bar.get_x() + (bar.get_width() / 2.0),
                bar.get_height() + max(max_value * 0.025, 0.15),
                str(values[index]),
                ha="center",
                va="bottom",
                color=label_color,
                fontsize=8,
                fontweight="bold",
            )
        if revenues:
            self.subtitle_label.text = (
                f"{len(series)} dias | Receita acumulada {_format_mzn(sum(revenues))}"
            )
        figure.subplots_adjust(left=0.08, right=0.98, top=0.9, bottom=0.2)
        self.set_figure(figure)


class TerminalRankingChart(_BaseChartCard):
    def __init__(self, **kwargs):
        super().__init__(
            title="Ranking por Caixa",
            subtitle="Ordenado por numero de vendas no periodo",
            height=dp(332),
            **kwargs,
        )

    def set_series(self, series, summary=None):
        if not _ensure_matplotlib():
            self.set_state_text("Graficos indisponiveis no momento.")
            return
        series = list(series or [])
        if not series:
            self.set_state_text("Sem vendas no período selecionado.")
            return

        tokens = getattr(App.get_running_app(), "theme_tokens", {}) or {}
        primary = tokens.get("primary", (0.15, 0.52, 0.76, 1))
        success = tokens.get("success", (0.19, 0.65, 0.33, 1))
        divider = tokens.get("divider", (0.82, 0.85, 0.9, 1))
        label_color = tokens.get("text_secondary", (0.42, 0.46, 0.5, 1))
        bg_color = tokens.get("card", (1, 1, 1, 1))

        top_items = series[:6]
        labels = [str(item.get("terminal_id") or "CAIXA-PRINCIPAL") for item in top_items]
        values = [int(item.get("sales_count") or 0) for item in top_items]
        revenues = [float(item.get("revenue") or 0.0) for item in top_items]

        figure = Figure(figsize=(4.2, 3.2), dpi=100)
        figure.patch.set_facecolor(bg_color)
        ax = figure.add_subplot(111)
        ax.set_facecolor(bg_color)

        bar_colors = [success] + [(*primary[:3], max(0.45, 0.9 - (0.08 * index))) for index in range(1, len(labels))]
        positions = list(range(len(labels)))
        bars = ax.barh(positions, values, color=bar_colors, height=0.58)
        ax.set_yticks(positions)
        ax.set_yticklabels(labels)
        ax.invert_yaxis()
        ax.grid(axis="x", color=(*divider[:3], 0.55), linewidth=0.9)
        ax.set_axisbelow(True)
        ax.tick_params(axis="x", colors=label_color, labelsize=9)
        ax.tick_params(axis="y", colors=label_color, labelsize=9)

        for spine_name in ("top", "right"):
            ax.spines[spine_name].set_visible(False)
        ax.spines["left"].set_color((*divider[:3], 0.8))
        ax.spines["bottom"].set_color((*divider[:3], 0.8))

        max_value = max(values) if values else 0
        ax.set_xlim(0, max(max_value * 1.25, 4))
        for index, bar in enumerate(bars):
            ax.text(
                bar.get_width() + max(max_value * 0.03, 0.2),
                bar.get_y() + (bar.get_height() / 2.0),
                f"{values[index]} | {revenues[index]:.0f} MZN",
                va="center",
                ha="left",
                color=label_color,
                fontsize=8.5,
            )

        self.subtitle_label.text = f"Top {len(top_items)} caixas ativos no período"
        figure.subplots_adjust(left=0.2, right=0.97, top=0.9, bottom=0.14)
        self.set_figure(figure)


class ProductivityInsightsCard(MDCard):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.orientation = "vertical"
        self.size_hint_y = None
        self.adaptive_height = True
        self.bind(minimum_height=self.setter("height"))
        self.padding = [dp(18), dp(16), dp(18), dp(14)]
        self.spacing = dp(8)
        self.radius = [dp(12)]
        self.elevation = 1
        self.md_bg_color = _theme("card_alt", (0.96, 0.97, 0.98, 1))

        self.title_label = MDLabel(
            text="Insights Inteligentes",
            font_style="Subtitle1",
            bold=True,
            size_hint_y=None,
            height=dp(24),
        )
        self.add_widget(self.title_label)
        self._items_box = MDBoxLayout(
            orientation="vertical",
            spacing=dp(6),
            size_hint_y=None,
            adaptive_height=True,
        )
        self._items_box.bind(minimum_height=self._items_box.setter("height"))
        self.add_widget(self._items_box)
        self._apply_theme()

    def _apply_theme(self):
        self.md_bg_color = _theme("card_alt", (0.96, 0.97, 0.98, 1))
        _set_label_text_color(self.title_label, _theme("text_primary", (0.2, 0.2, 0.2, 1)))

    def set_items(self, items):
        self._apply_theme()
        self._items_box.clear_widgets()
        for text in list(items or [])[:4]:
            label = MDLabel(
                text=f"- {text}",
                size_hint_y=None,
            )
            label.bind(width=lambda inst, value: setattr(inst, "text_size", (value, None)))
            label.bind(texture_size=lambda inst, value: setattr(inst, "height", max(dp(20), value[1])))
            _set_label_text_color(label, _theme("text_secondary", (0.42, 0.46, 0.5, 1)))
            self._items_box.add_widget(label)


class ProductivityDashboard(MDCard):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.orientation = "vertical"
        self.size_hint_y = None
        self.adaptive_height = True
        self.bind(minimum_height=self.setter("height"))
        self.padding = [dp(22), dp(20), dp(22), dp(18)]
        self.spacing = dp(14)
        self.radius = [dp(12)]
        self.elevation = 1

        self.header_box = MDBoxLayout(
            orientation="vertical",
            spacing=dp(4),
            size_hint_y=None,
            adaptive_height=True,
        )
        self.header_box.bind(minimum_height=self.header_box.setter("height"))
        self.title_label = MDLabel(
            text="Produtividade Inteligente",
            font_style="H6",
            bold=True,
            size_hint_y=None,
            height=dp(28),
        )
        self.subtitle_label = MDLabel(
            text="Analise por caixa com base apenas no periodo selecionado",
            font_style="Caption",
            size_hint_y=None,
            height=dp(18),
        )
        self.header_box.add_widget(self.title_label)
        self.header_box.add_widget(self.subtitle_label)

        self.kpi_strip = ProductivityKpiStrip()
        self.state_card = MDCard(
            orientation="vertical",
            size_hint_y=None,
            height=dp(86),
            padding=[dp(16), dp(12), dp(16), dp(12)],
            radius=[dp(10)],
            elevation=0,
        )
        self.state_label = MDLabel(
            text="Selecione um período para visualizar os gráficos de produtividade",
            halign="center",
            valign="middle",
        )
        self.state_label.bind(size=lambda inst, value: setattr(inst, "text_size", value))
        self.state_card.add_widget(self.state_label)

        self.charts_row = MDBoxLayout(
            orientation="horizontal",
            spacing=dp(12),
            size_hint_y=None,
            adaptive_height=True,
        )
        self.charts_row.bind(minimum_height=self.charts_row.setter("height"))
        self.daily_chart = DailyProductivityChart()
        self.ranking_chart = TerminalRankingChart()
        self.charts_row.add_widget(self.daily_chart)
        self.charts_row.add_widget(self.ranking_chart)

        self.insights_card = ProductivityInsightsCard()
        self._layout_trigger = Clock.create_trigger(self._sync_layout, 0)
        self.bind(width=lambda *_: self._layout_trigger())
        self._layout_trigger()
        self.show_empty("Selecione um período para visualizar os gráficos de produtividade")

    def _apply_theme(self):
        self.md_bg_color = _theme("card", (1, 1, 1, 1))
        self.state_card.md_bg_color = _theme("card_alt", (0.96, 0.97, 0.98, 1))
        _set_label_text_color(self.title_label, _theme("text_primary", (0.2, 0.2, 0.2, 1)))
        _set_label_text_color(self.subtitle_label, _theme("text_secondary", (0.42, 0.46, 0.5, 1)))
        _set_label_text_color(self.state_label, _theme("text_secondary", (0.42, 0.46, 0.5, 1)))

    def _sync_layout(self, *_args):
        desktop = self.width >= dp(1160)
        self.charts_row.orientation = "horizontal" if desktop else "vertical"
        if desktop:
            self.daily_chart.size_hint_x = 0.62
            self.ranking_chart.size_hint_x = 0.38
        else:
            self.daily_chart.size_hint_x = 1
            self.ranking_chart.size_hint_x = 1

    def _compose(self, *widgets):
        self._apply_theme()
        self.clear_widgets()
        self.add_widget(self.header_box)
        for widget in widgets:
            if widget:
                self.add_widget(widget)
        self._layout_trigger()

    def show_empty(self, message):
        self.state_label.text = message
        self._compose(self.state_card)

    def show_loading(self, message="A carregar gráficos de produtividade..."):
        self.state_label.text = message
        self._compose(self.state_card)

    def show_error(self, message):
        self.state_label.text = message
        self._compose(self.state_card)

    def show_no_data(self, message, summary=None):
        self.kpi_strip.set_summary(summary or {})
        self.state_label.text = message
        self._compose(self.kpi_strip, self.state_card)

    def set_payload(self, payload, insights):
        payload = payload or {}
        summary = payload.get("summary") or {}
        self.kpi_strip.set_summary(summary)
        if not _ensure_matplotlib():
            self.state_label.text = "Graficos indisponiveis no momento."
            self._compose(self.kpi_strip, self.state_card)
            return
        self.daily_chart.set_series(payload.get("daily_series") or [], summary)
        self.ranking_chart.set_series(payload.get("terminal_series") or [], summary)
        self.insights_card.set_items(insights)
        self._compose(self.kpi_strip, self.charts_row, self.insights_card)
