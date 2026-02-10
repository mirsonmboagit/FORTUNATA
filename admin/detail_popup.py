from datetime import datetime

from kivy.app import App
from kivy.core.window import Window
from kivy.metrics import dp, sp
from kivy.uix.scrollview import ScrollView
from kivy.uix.popup import Popup

from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.card import MDCard
from kivymd.uix.label import MDLabel, MDIcon
from kivymd.uix.button import MDRaisedButton
from kivymd.uix.card import MDSeparator


def _theme_color(name, fallback):
    app = App.get_running_app()
    tokens = getattr(app, "theme_tokens", {}) if app else {}
    return tokens.get(name, fallback)


def _tint(color, alpha=0.18):
    return [color[0], color[1], color[2], alpha]


class DetailPopup(Popup):
    def __init__(self, product_data, **kwargs):
        super().__init__(**kwargs)
        self._product_data = product_data
        self._tokens = {
            "card": _theme_color("card", [1, 1, 1, 1]),
            "card_alt": _theme_color("card_alt", [0.95, 0.96, 0.98, 1]),
            "surface": _theme_color("surface", [1, 1, 1, 1]),
            "text_primary": _theme_color("text_primary", [0.2, 0.2, 0.2, 1]),
            "text_secondary": _theme_color("text_secondary", [0.5, 0.5, 0.5, 1]),
            "primary": _theme_color("primary", [0.15, 0.52, 0.76, 1]),
            "success": _theme_color("success", [0.2, 0.7, 0.3, 1]),
            "warning": _theme_color("warning", [0.9, 0.6, 0.1, 1]),
            "danger": _theme_color("danger", [0.85, 0.15, 0.15, 1]),
            "info": _theme_color("info", [0.25, 0.45, 0.75, 1]),
            "on_primary": _theme_color("on_primary", [1, 1, 1, 1]),
        }

        self.title = ""
        self.separator_height = 0
        self.background = ""
        self.auto_dismiss = True
        self.size_hint = (None, None)
        self._apply_size()

        self.content = self._build_content()
        Window.bind(on_resize=self._on_resize)

    def _apply_size(self):
        w, h = Window.size
        self.size = (min(dp(920), w * 0.85), min(dp(760), h * 0.9))

    def _on_resize(self, *_):
        self._apply_size()

    def on_dismiss(self):
        Window.unbind(on_resize=self._on_resize)

    def _build_content(self):
        container = MDCard(
            orientation="vertical",
            padding=dp(16),
            spacing=dp(12),
            radius=[dp(12)],
            md_bg_color=self._tokens["card"],
            elevation=4,
        )

        container.add_widget(self._build_header())
        container.add_widget(MDSeparator())
        container.add_widget(self._build_body())
        container.add_widget(self._build_footer())
        return container

    def _build_header(self):
        desc = self._get(1, "Produto")
        category = self._get(11, "NENHUMA")

        header = MDCard(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(64),
            padding=[dp(12), dp(10)],
            spacing=dp(12),
            radius=[dp(10)],
            md_bg_color=self._tokens["card_alt"],
            elevation=0,
        )

        icon = MDIcon(
            icon="package-variant",
            theme_text_color="Custom",
            text_color=self._tokens["primary"],
            font_size=dp(28),
        )
        header.add_widget(icon)

        labels = MDBoxLayout(orientation="vertical", spacing=dp(2))
        title = MDLabel(
            text="Detalhes do Produto",
            font_style="Subtitle1",
            bold=True,
            theme_text_color="Custom",
            text_color=self._tokens["text_primary"],
        )
        subtitle = MDLabel(
            text=str(desc),
            font_style="Body2",
            theme_text_color="Custom",
            text_color=self._tokens["text_secondary"],
            shorten=True,
            shorten_from="right",
        )
        meta = MDLabel(
            text=f"Categoria: {category}",
            font_style="Caption",
            theme_text_color="Custom",
            text_color=self._tokens["text_secondary"],
            shorten=True,
            shorten_from="right",
        )
        labels.add_widget(title)
        labels.add_widget(subtitle)
        labels.add_widget(meta)
        header.add_widget(labels)

        return header

    def _build_body(self):
        scroll = ScrollView(do_scroll_x=False)
        body = MDBoxLayout(orientation="vertical", spacing=dp(6), size_hint_y=None)
        body.bind(minimum_height=body.setter("height"))

        # Header row
        header_row = MDCard(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(32),
            padding=[dp(10), 0],
            radius=[dp(6)],
            elevation=0,
            md_bg_color=self._tokens["primary"],
        )
        header_row.add_widget(MDLabel(
            text="Campo",
            halign="left",
            theme_text_color="Custom",
            text_color=self._tokens["on_primary"],
            bold=True,
            size_hint_x=0.45,
        ))
        header_row.add_widget(MDLabel(
            text="Valor",
            halign="right",
            theme_text_color="Custom",
            text_color=self._tokens["on_primary"],
            bold=True,
            size_hint_x=0.55,
        ))
        body.add_widget(header_row)

        for row in self._build_rows():
            body.add_widget(row)

        scroll.add_widget(body)
        return scroll

    def _build_footer(self):
        footer = MDBoxLayout(size_hint_y=None, height=dp(44))
        footer.add_widget(MDBoxLayout())
        close_btn = MDRaisedButton(
            text="Fechar",
            md_bg_color=self._tokens["primary"],
            text_color=self._tokens["on_primary"],
            on_release=self.dismiss,
            size_hint_x=None,
            width=dp(120),
        )
        footer.add_widget(close_btn)
        return footer

    def _build_rows(self):
        rows = []
        data = self._product_data
        now = datetime.now()

        def fmt_money(value, suffix=""):
            try:
                return f"MZN {float(value):.2f}{suffix}"
            except Exception:
                return f"MZN 0.00{suffix}"

        def fmt_pct(value):
            try:
                return f"{float(value):.2f}%"
            except Exception:
                return "0.00%"

        is_kg = self._get(15, 0)
        unit = "kg" if is_kg else "un"

        existing_stock = self._get(2, 0)
        sold_stock = self._get(3, 0)
        remaining_stock = self._to_float(existing_stock)

        profit_unit = self._get(7, None)
        if profit_unit in (None, "NENHUMA"):
            profit_unit = self._to_float(self._get(4, 0)) - self._to_float(self._get(6, 0))

        total_profit = self._get(8, None)
        if total_profit in (None, "NENHUMA"):
            total_profit = profit_unit * self._to_float(sold_stock)

        profit_pct = self._get(9, None)
        if profit_pct in (None, "NENHUMA"):
            base = self._to_float(self._get(6, 1))
            profit_pct = (profit_unit / base * 100) if base else 0

        price_pct = self._get(10, None)

        def qty(v):
            v = self._to_float(v)
            return f"{v:.2f} {unit}" if is_kg else f"{int(v)} {unit}"

        barcode_value = self._get(12, "NENHUM")
        expiry_value = self._get(13, "")
        expiry_text = self._format_date(expiry_value) or "NENHUMA"
        expiry_level = None
        try:
            expiry_dt = datetime.strptime(str(expiry_value), "%Y-%m-%d")
            if expiry_dt.date() < now.date():
                expiry_level = "danger"
            elif (expiry_dt.date() - now.date()).days <= 7:
                expiry_level = "warning"
        except Exception:
            expiry_level = None

        status_value = self._get(16, "N/A")
        status_level = None
        if isinstance(status_value, str):
            status_upper = status_value.upper()
            if "EXPIR" in status_upper:
                status_level = "danger"
            elif "INAT" in status_upper or "DESAT" in status_upper:
                status_level = "warning"

        rows_data = [
            ("ID", str(self._get(0, "")), None),
            ("Descricao", self._get(1, "NENHUMA"), None),
            ("Categoria", self._get(11, "NENHUMA"), "info"),
            ("Quantidade/Conteudo", self._get(21, "NENHUMA"), None),
            ("Codigo de Barras", barcode_value, "warning" if barcode_value == "NENHUM" else None),
            ("Data de Validade", expiry_text, expiry_level),
            ("Data de Cadastro", self._format_datetime(self._get(14, "")) or "NENHUMA", None),
            ("Tipo de Venda", "KG" if is_kg else "UNIDADE", None),
            ("Estoque Existente", qty(existing_stock), None),
            ("Estoque Vendido", qty(sold_stock), None),
            ("Estoque Remanescente", qty(remaining_stock), "danger" if remaining_stock < 5 else None),
            ("Preco Final de Venda", fmt_money(self._get(4, 0), f"/{unit}"), None),
            ("Preco de Compra Total", fmt_money(self._get(5, 0)), None),
            ("Preco de Compra (unitario)", fmt_money(self._get(6, 0), f"/{unit}"), None),
            ("Lucro por Unidade", fmt_money(profit_unit, f"/{unit}"), None),
            ("Total de Lucro", fmt_money(total_profit), "success"),
            ("% de Lucro", fmt_pct(profit_pct), "info"),
        ]

        if price_pct not in (None, "NENHUMA"):
            rows_data.append(("% Margem Preco", fmt_pct(price_pct), None))

        rows_data.extend([
            ("Status", status_value, status_level),
            ("Fonte", self._get(17, "N/A"), None),
            ("Motivo", self._get(18, "N/A"), None),
            ("Atualizado em", self._format_datetime(self._get(19, "")) or "N/A", None),
            ("Atualizado por", self._get(20, "N/A"), None),
        ])

        for idx, (label, value, highlight) in enumerate(rows_data):
            bg = self._tokens["card_alt"] if idx % 2 == 0 else self._tokens["card"]
            if highlight == "danger":
                bg = _tint(self._tokens["danger"], 0.16)
            elif highlight == "warning":
                bg = _tint(self._tokens["warning"], 0.16)
            elif highlight == "info":
                bg = _tint(self._tokens["info"], 0.16)
            elif highlight == "success":
                bg = _tint(self._tokens["success"], 0.16)
            row = MDCard(
                orientation="horizontal",
                size_hint_y=None,
                height=dp(28),
                padding=[dp(10), 0],
                radius=[dp(4)],
                elevation=0,
                md_bg_color=bg,
            )

            label_widget = MDLabel(
                text=label,
                halign="left",
                theme_text_color="Custom",
                text_color=self._tokens["text_secondary"],
                font_style="Caption",
                size_hint_x=0.45,
                shorten=True,
                shorten_from="right",
            )

            value_color = self._tokens["text_primary"]
            if highlight == "danger":
                value_color = self._tokens["danger"]
            elif highlight == "warning":
                value_color = self._tokens["warning"]
            elif highlight == "info":
                value_color = self._tokens["info"]
            elif highlight == "success":
                value_color = self._tokens["success"]

            value_widget = MDLabel(
                text=str(value),
                halign="right",
                theme_text_color="Custom",
                text_color=value_color,
                font_style="Caption",
                size_hint_x=0.55,
                bold=highlight in ("danger", "info"),
                shorten=True,
                shorten_from="right",
            )

            row.add_widget(label_widget)
            row.add_widget(value_widget)
            rows.append(row)

        return rows

    def _get(self, idx, default=None):
        if len(self._product_data) > idx and self._product_data[idx] not in (None, ""):
            return self._product_data[idx]
        return default

    @staticmethod
    def _to_float(value):
        try:
            return float(value)
        except Exception:
            return 0

    @staticmethod
    def _format_date(value):
        if not value:
            return ""
        try:
            return datetime.strptime(str(value), "%Y-%m-%d").strftime("%d/%m/%Y")
        except Exception:
            return str(value)

    @staticmethod
    def _format_datetime(value):
        if not value:
            return ""
        try:
            return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S").strftime("%d/%m/%Y %H:%M")
        except Exception:
            return str(value)
