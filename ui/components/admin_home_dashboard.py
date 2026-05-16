from datetime import datetime

from kivy.app import App
from kivy.metrics import dp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.label import MDLabel
from ui.components.chart_hover import MatplotlibHoverController
from ui.components.hover_widgets import HoverCard

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


def _set_label_text_color(label, color):
    label.theme_text_color = "Custom"
    label.text_color = color


def _format_mzn(value):
    try:
        return f"{float(value):,.2f} MZN".replace(",", " ")
    except Exception:
        return "0.00 MZN"


def _format_short_date(value):
    text = str(value or "").strip()
    if not text:
        return "--/--"
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).strftime("%d/%m")
        except Exception:
            continue
    try:
        return datetime.fromisoformat(text).strftime("%d/%m")
    except Exception:
        return text


class _BaseChartCard(HoverCard):
    def __init__(self, title, subtitle, height=dp(320), **kwargs):
        super().__init__(**kwargs)
        self.orientation = "vertical"
        self.size_hint_y = None
        self.height = height
        self.padding = [dp(16), dp(14), dp(16), dp(12)]
        self.spacing = dp(8)
        self.radius = [dp(12)]
        self.elevation = 1
        self.hover_bg_mix = 0.06
        self.hover_line_mix = 0.24
        self.hover_elevation_delta = 1.5
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
        self._hover_controller = MatplotlibHoverController(_theme)

        self.add_widget(self.title_label)
        self.add_widget(self.subtitle_label)
        self.add_widget(self.content_box)
        self._apply_theme()

    def _apply_theme(self):
        self.md_bg_color = _theme("card", (1, 1, 1, 1))
        _set_label_text_color(self.title_label, _theme("text_primary", (0.2, 0.2, 0.2, 1)))
        _set_label_text_color(self.subtitle_label, _theme("text_secondary", (0.45, 0.48, 0.52, 1)))

    def _clear_content(self):
        self._hover_controller.detach()
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

    def set_figure(self, figure, hover_items=None):
        if not _ensure_matplotlib():
            self.set_state_text("Graficos indisponiveis no momento.")
            return
        self._apply_theme()
        self._clear_content()
        self._figure = figure
        self._canvas_widget = FigureCanvasKivyAgg(figure)
        self.content_box.add_widget(self._canvas_widget)
        self._hover_controller.attach(self._canvas_widget, figure, hover_items or [])


class SalesTrendChart(_BaseChartCard):
    def __init__(self, **kwargs):
        super().__init__(
            title="Vendas Recentes",
            subtitle="Receita diaria dos ultimos dias",
            height=dp(322),
            **kwargs,
        )

    def set_series(self, series):
        series = list(series or [])
        if not _ensure_matplotlib():
            self.set_state_text("Graficos indisponiveis no momento.")
            return
        if not series or not any(float(item.get("revenue") or 0.0) > 0 for item in series):
            self.set_state_text("Sem vendas suficientes para gerar o grafico.")
            return

        tokens = getattr(App.get_running_app(), "theme_tokens", {}) or {}
        primary = tokens.get("primary", (0.10, 0.35, 0.65, 1))
        success = tokens.get("success", (0.2, 0.65, 0.3, 1))
        info = tokens.get("info", (0.18, 0.58, 0.86, 1))
        warning = tokens.get("warning", (0.92, 0.68, 0.18, 1))
        danger = tokens.get("danger", (0.88, 0.34, 0.30, 1))
        divider = tokens.get("divider", (0.82, 0.85, 0.9, 1))
        label_color = tokens.get("text_secondary", (0.42, 0.46, 0.5, 1))
        bg_color = tokens.get("card", (1, 1, 1, 1))

        labels = [_format_short_date(item.get("date")) for item in series]
        values = [float(item.get("revenue") or 0.0) for item in series]
        counts = [int(item.get("sales_count") or 0) for item in series]
        x_values = list(range(len(series)))

        figure = Figure(figsize=(6.3, 3.15), dpi=100)
        figure.patch.set_facecolor(bg_color)
        ax = figure.add_subplot(111)
        ax.set_facecolor(bg_color)
        palette = [
            primary,
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

        last_index = len(values) - 1
        bars[last_index].set_color(success)
        ax.annotate(
            "Hoje",
            xy=(last_index, values[last_index]),
            xytext=(0, 12),
            textcoords="offset points",
            ha="center",
            color=success,
            fontsize=9,
            fontweight="bold",
        )

        max_value = max(values) if values else 0
        ax.set_ylim(0, max(max_value * 1.2, 4))
        hover_items = []
        for index, bar in enumerate(bars):
            ax.text(
                bar.get_x() + (bar.get_width() / 2.0),
                bar.get_height() + max(max_value * 0.02, 0.15),
                f"{values[index]:.0f}",
                ha="center",
                va="bottom",
                color=label_color,
                fontsize=8,
                fontweight="bold",
            )
            hover_items.append(
                {
                    "artist": bar,
                    "position": (
                        bar.get_x() + (bar.get_width() / 2.0),
                        bar.get_height(),
                    ),
                    "text": (
                        f"Dia: {labels[index]}\n"
                        f"Receita: {_format_mzn(values[index])}\n"
                        f"Vendas: {counts[index]}"
                    ),
                }
            )
        self.subtitle_label.text = (
            f"{sum(counts)} vendas | Receita acumulada {_format_mzn(sum(values))}"
        )
        figure.subplots_adjust(left=0.08, right=0.98, top=0.9, bottom=0.2)
        self.set_figure(figure, hover_items=hover_items)


class StockFlowChart(_BaseChartCard):
    def __init__(self, **kwargs):
        super().__init__(
            title="Fluxo de Stock",
            subtitle="Entradas e saidas recentes",
            height=dp(322),
            **kwargs,
        )

    def set_series(self, series):
        series = list(series or [])
        if not _ensure_matplotlib():
            self.set_state_text("Graficos indisponiveis no momento.")
            return
        if not series or not any(
            (float(item.get("in_qty") or 0.0) > 0 or float(item.get("out_qty") or 0.0) > 0)
            for item in series
        ):
            self.set_state_text("Sem movimentacoes recentes para comparar.")
            return

        tokens = getattr(App.get_running_app(), "theme_tokens", {}) or {}
        success = tokens.get("success", (0.2, 0.65, 0.3, 1))
        danger = tokens.get("danger", (0.88, 0.34, 0.30, 1))
        divider = tokens.get("divider", (0.82, 0.85, 0.9, 1))
        label_color = tokens.get("text_secondary", (0.42, 0.46, 0.5, 1))
        bg_color = tokens.get("card", (1, 1, 1, 1))

        labels = [_format_short_date(item.get("date")) for item in series]
        in_values = [float(item.get("in_qty") or 0.0) for item in series]
        out_values = [float(item.get("out_qty") or 0.0) for item in series]
        positions = list(range(len(series)))

        figure = Figure(figsize=(5.0, 3.15), dpi=100)
        figure.patch.set_facecolor(bg_color)
        ax = figure.add_subplot(111)
        ax.set_facecolor(bg_color)

        width = 0.36
        left_positions = [pos - (width / 2.0) for pos in positions]
        right_positions = [pos + (width / 2.0) for pos in positions]
        in_bars = ax.bar(left_positions, in_values, width=width, color=success, label="Entradas")
        out_bars = ax.bar(right_positions, out_values, width=width, color=danger, label="Saidas")

        ax.set_xticks(positions)
        ax.set_xticklabels(labels, rotation=0)
        ax.grid(axis="y", color=(*divider[:3], 0.55), linewidth=0.9)
        ax.set_axisbelow(True)
        ax.tick_params(axis="x", colors=label_color, labelsize=9)
        ax.tick_params(axis="y", colors=label_color, labelsize=9)

        for spine_name in ("top", "right"):
            ax.spines[spine_name].set_visible(False)
        ax.spines["left"].set_color((*divider[:3], 0.8))
        ax.spines["bottom"].set_color((*divider[:3], 0.8))
        ax.legend(frameon=False, fontsize=8.5, labelcolor=label_color, loc="upper right")

        max_value = max(in_values + out_values) if (in_values or out_values) else 0
        ax.set_ylim(0, max(max_value * 1.22, 4))
        self.subtitle_label.text = (
            f"Entradas {sum(in_values):.1f} | Saidas {sum(out_values):.1f}"
        )
        figure.subplots_adjust(left=0.09, right=0.98, top=0.88, bottom=0.2)
        hover_items = []
        for index, bar in enumerate(in_bars):
            hover_items.append(
                {
                    "artist": bar,
                    "position": (
                        bar.get_x() + (bar.get_width() / 2.0),
                        bar.get_height(),
                    ),
                    "text": f"Dia: {labels[index]}\nEntradas: {in_values[index]:.1f}",
                }
            )
        for index, bar in enumerate(out_bars):
            hover_items.append(
                {
                    "artist": bar,
                    "position": (
                        bar.get_x() + (bar.get_width() / 2.0),
                        bar.get_height(),
                    ),
                    "text": f"Dia: {labels[index]}\nSaidas: {out_values[index]:.1f}",
                }
            )
        self.set_figure(figure, hover_items=hover_items)
