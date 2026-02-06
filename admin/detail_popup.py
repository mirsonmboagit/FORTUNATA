from kivy.uix.popup import Popup
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.scrollview import ScrollView
from kivy.graphics import Color, Rectangle, Line
from kivy.core.window import Window
from kivy.metrics import dp, sp
from datetime import datetime


# ──────────────────────────────────────────────────────────────
# PALETA PADRÃO (centralizada)
# ──────────────────────────────────────────────────────────────
COLORS = {
    "bg_main": [1, 1, 1, 1],
    "row_alt": [0.95, 0.95, 0.95, 1],
    "row_norm": [1, 1, 1, 1],
    "header": [0.18, 0.2, 0.38, 1],
    "border": [0, 0, 0, 1],
    "text_dark": [0, 0, 0, 1],
    "text_light": [1, 1, 1, 1],

    "green": [0.2, 0.7, 0.3, 1],
    "blue": [0.25, 0.45, 0.75, 1],
    "orange": [0.9, 0.6, 0.1, 1],
    "red": [0.85, 0.15, 0.15, 1],
    "purple": [0.6, 0.2, 0.6, 1],
}


class DetailPopup(Popup):

    def __init__(self, product_data, **kwargs):
        super().__init__(**kwargs)

        self.title = "Detalhes do Produto"
        self.size_hint = (None, None)
        self.background = 'atlas://data/images/defaulttheme/button'
        self.title_color = COLORS["text_dark"]
        self.title_size = sp(18)

        self._apply_size()
        Window.bind(on_resize=self._on_resize)

        # ─────────────────────────────────────────────
        # DADOS
        # ─────────────────────────────────────────────
        remaining_stock = product_data[2]
        profit_unit = product_data[4] - product_data[6]
        total_profit = profit_unit * product_data[3]
        profit_pct = (profit_unit / product_data[6] * 100) if product_data[6] else 0

        is_kg = product_data[15] if len(product_data) > 15 else 0
        unit = "kg" if is_kg else "un"

        def qty(v):
            return f"{v:.2f} {unit}" if is_kg else f"{int(v)} {unit}"

        fields = [
            ("ID", str(product_data[0])),
            ("Descrição", product_data[1]),
            ("Categoria", product_data[11] if len(product_data) > 11 else "NENHUMA"),
            ("Código de Barras", product_data[12] or "NENHUM"),
            ("Data de Validade", self.format_date(product_data[13]) if product_data[13] else "NENHUMA"),
            ("Tipo de Venda", "KG" if is_kg else "UNIDADE"),
            ("Estoque Existente", qty(product_data[2])),
            ("Estoque Vendido", qty(product_data[3])),
            ("Estoque Remanescente", qty(remaining_stock)),
            ("Preço Final de Venda", f"MZN {product_data[4]:.2f}/{unit}"),
            ("Preço de Compra Total", f"MZN {product_data[5]:.2f}"),
            ("Preço de Compra (unitário)", f"MZN {product_data[6]:.2f}/{unit}"),
            ("Lucro por Unidade", f"MZN {profit_unit:.2f}/{unit}"),
            ("Total de Lucro", f"MZN {total_profit:.2f}"),
            ("% de Lucro", f"{profit_pct:.2f}%"),
        ]

        highlights = {
            "Descrição": COLORS["green"],
            "Código de Barras": COLORS["blue"],
            "Total de Lucro": COLORS["blue"],
            "% de Lucro": COLORS["purple"],
        }

        if remaining_stock < 5:
            highlights["Estoque Remanescente"] = COLORS["red"]

        # ─────────────────────────────────────────────
        # LAYOUT
        # ─────────────────────────────────────────────
        main = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(10))

        with main.canvas.before:
            Color(*COLORS["bg_main"])
            self._bg = Rectangle(pos=main.pos, size=main.size)
        main.bind(pos=self._update_bg, size=self._update_bg)

        scroll = ScrollView(do_scroll_x=False)

        table = GridLayout(cols=2, size_hint=(1, None))
        table.bind(minimum_height=table.setter("height"))

        self._add_header(table)

        row_h = dp(36)
        font = sp(14)

        for i, (field, value) in enumerate(fields):
            base_bg = COLORS["row_alt"] if i % 2 == 0 else COLORS["row_norm"]
            val_bg = highlights.get(field, base_bg)
            val_color = COLORS["text_light"] if field in highlights else COLORS["text_dark"]

            table.add_widget(
                self._cell(field, row_h, font, base_bg, bold=True, ratio=0.4)
            )
            table.add_widget(
                self._cell(value, row_h, font, val_bg, val_color, field in highlights, 0.6)
            )

        scroll.add_widget(table)
        main.add_widget(scroll)

        # ─────────────────────────────────────────────
        # BOTÃO
        # ─────────────────────────────────────────────
        footer = BoxLayout(size_hint_y=None, height=dp(48))
        footer.add_widget(BoxLayout())

        close_btn = Button(
            text="Fechar",
            size_hint=(None, None),
            size=(dp(130), dp(36)),
            background_color=[0.15, 0.15, 0.15, 1],
            color=COLORS["text_light"]
        )
        close_btn.bind(on_release=self.dismiss)

        footer.add_widget(close_btn)
        main.add_widget(footer)

        self.content = main
        self.center()

    # ─────────────────────────────────────────────
    # HELPERS
    # ─────────────────────────────────────────────
    def _cell(self, text, height, font, bg, color=(0, 0, 0, 1), bold=False, ratio=0.5):
        box = BoxLayout(size_hint=(ratio, None), height=height)

        with box.canvas.before:
            Color(*bg)
            rect = Rectangle(pos=box.pos, size=box.size)
            Color(*COLORS["border"])
            line = Line(rectangle=(box.x, box.y, box.width, box.height), width=1)

        def _upd(*_):
            rect.pos, rect.size = box.pos, box.size
            line.rectangle = (*box.pos, *box.size)

        box.bind(pos=_upd, size=_upd)

        box.add_widget(
            Label(
                text=text,
                halign="left",
                valign="middle",
                padding=(dp(10), 0),
                color=color,
                bold=bold,
                font_size=font,
                shorten=True,
                shorten_from="right"
            )
        )
        return box

    def _add_header(self, table):
        for title in ("Campo", "Valor"):
            cell = BoxLayout(size_hint=(0.5, None), height=dp(40))
            with cell.canvas.before:
                Color(*COLORS["header"])
                rect = Rectangle(pos=cell.pos, size=cell.size)
            cell.bind(pos=lambda i, v: setattr(rect, "pos", i.pos),
                      size=lambda i, v: setattr(rect, "size", i.size))
            cell.add_widget(Label(text=title, bold=True, color=COLORS["text_light"]))
            table.add_widget(cell)

    # ─────────────────────────────────────────────
    # RESPONSIVO
    # ─────────────────────────────────────────────
    def _apply_size(self):
        self.width = min(dp(900), Window.width * 0.75)
        self.height = min(dp(700), Window.height * 0.8)

    def _on_resize(self, *_):
        self._apply_size()
        self.center()

    def center(self):
        self.pos = (
            (Window.width - self.width) / 2,
            (Window.height - self.height) / 2
        )

    def _update_bg(self, inst, *_):
        self._bg.pos = inst.pos
        self._bg.size = inst.size

    # ─────────────────────────────────────────────
    # DATAS
    # ─────────────────────────────────────────────
    def format_date(self, date):
        try:
            return datetime.strptime(str(date), "%Y-%m-%d").strftime("%d/%m/%Y")
        except Exception:
            return str(date)

    def on_dismiss(self):
        Window.unbind(on_resize=self._on_resize)
        return super().on_dismiss()
