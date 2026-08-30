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
        # O popup e usado sobre uma tela escura. Estas cores locais mantem
        # contraste consistente, inclusive em temas com tons muito apagados.
        self._tokens.update({
            "card": [0.075, 0.090, 0.115, 1],
            "card_alt": [0.125, 0.145, 0.180, 1],
            "text_primary": [0.96, 0.97, 0.99, 1],
            "text_secondary": [0.73, 0.78, 0.86, 1],
            "primary": [0.16, 0.50, 0.82, 1],
            "success": [0.28, 0.86, 0.52, 1],
            "warning": [1.00, 0.76, 0.28, 1],
            "danger": [1.00, 0.40, 0.42, 1],
            "info": [0.35, 0.70, 1.00, 1],
            "on_primary": [1, 1, 1, 1],
        })

        self._compact = None

        self.title = ""
        self.separator_height = 0
        self.background = ""
        self.background_color = [0, 0, 0, 0]
        self.border = [0, 0, 0, 0]
        self.auto_dismiss = True
        self.size_hint = (None, None)
        self._apply_size()

        self.content = self._build_content()
        Window.bind(on_resize=self._on_resize)

    def _apply_size(self):
        w, h = Window.size
        if w < dp(720):
            self.size = (w * 0.95, h * 0.95)
        else:
            # A tabela possui campos financeiros e de stock. Em desktop, uma
            # largura maior evita valores cortados e permite uma fonte legivel.
            self.size = (min(dp(1040), w * 0.90), min(dp(820), h * 0.92))
        self._compact = w < dp(720)

    def _on_resize(self, *_):
        prev = self._compact
        self._apply_size()
        if prev != self._compact:
            self.content = self._build_content()

    def on_dismiss(self):
        Window.unbind(on_resize=self._on_resize)

    def _build_content(self):
        container = MDCard(
            orientation="vertical",
            padding=dp(20) if not self._compact else dp(16),
            spacing=dp(14) if not self._compact else dp(12),
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
            height=dp(64) if self._compact else dp(76),
            padding=[dp(14), dp(12)],
            spacing=dp(12),
            radius=[dp(10)],
            md_bg_color=self._tokens["card_alt"],
            elevation=0,
        )

        icon_size = dp(28) if self._compact else dp(32)
        icon = MDIcon(
            icon="package-variant",
            size_hint=(None, None),
            size=(icon_size, icon_size),
            halign="center",
            valign="middle",
            theme_text_color="Custom",
            text_color=self._tokens["primary"],
            font_size=sp(26) if self._compact else sp(32),
        )
        icon.bind(size=lambda inst, value: setattr(inst, "text_size", value))
        header.add_widget(icon)

        labels = MDBoxLayout(orientation="vertical", spacing=dp(2))
        title = MDLabel(
            text="Detalhes do Produto",
            font_style="Subtitle1",
            font_size=sp(19) if self._compact else sp(21),
            bold=True,
            theme_text_color="Custom",
            text_color=self._tokens["text_primary"],
        )
        subtitle = MDLabel(
            text=str(desc),
            font_style="Body2",
            font_size=sp(15) if self._compact else sp(17),
            theme_text_color="Custom",
            text_color=self._tokens["text_secondary"],
            shorten=True,
            shorten_from="right",
        )
        meta = MDLabel(
            text=f"Categoria: {category}",
            font_style="Caption",
            font_size=sp(13) if self._compact else sp(14),
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
        scroll = ScrollView(
            do_scroll_x=False,
            bar_width=dp(8),
            bar_color=_tint(self._tokens["primary"], 0.78),
            bar_inactive_color=_tint(self._tokens["text_secondary"], 0.32),
        )
        body = MDBoxLayout(
            orientation="vertical",
            spacing=dp(8) if not self._compact else dp(6),
            size_hint_y=None,
        )
        body.bind(minimum_height=body.setter("height"))

        if not self._compact:
            # Header row
            header_row = MDCard(
                orientation="horizontal",
                size_hint_y=None,
                height=dp(42),
                padding=[dp(12), 0],
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
                font_size=sp(16),
                size_hint_x=0.42,
            ))
            header_row.add_widget(MDLabel(
                text="Valor",
                halign="right",
                theme_text_color="Custom",
                text_color=self._tokens["on_primary"],
                bold=True,
                font_size=sp(16),
                size_hint_x=0.58,
            ))
            body.add_widget(header_row)


        for row in self._build_rows():
            body.add_widget(row)

        scroll.add_widget(body)
        return scroll

    def _build_footer(self):
        footer = MDBoxLayout(size_hint_y=None, height=dp(52))
        footer.add_widget(MDBoxLayout())
        close_btn = MDRaisedButton(
            text="Fechar",
            md_bg_color=self._tokens["primary"],
            text_color=self._tokens["on_primary"],
            font_size=sp(15),
            on_release=self.dismiss,
            size_hint_x=None,
            width=dp(120),
        )
        if self._compact:
            close_btn.width = min(dp(160), self.width * 0.6)
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
        unit = "KG" if is_kg else "UN"

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
        sku_value = self._get(22, "NENHUM")
        pack_units = self._get(23, None)
        allow_pack_sale = bool(self._get(24, 0))
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
            ("Unidade de Medida", self._get(21, "NENHUMA"), None),
            ("Unidades por Embalagem", str(int(float(pack_units))) if pack_units not in (None, "") else "NENHUMA", None),
            ("Venda por Embalagem", "ATIVA" if allow_pack_sale else "INATIVA", None),
            ("Codigo de Barras", barcode_value, "warning" if barcode_value == "NENHUM" else None),
            ("SKU", sku_value, "warning" if sku_value == "NENHUM" else None),
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

        lot_count = 1
        source_ids = ()
        if len(data) > 27:
            try:
                lot_count = max(1, int(data[27]))
            except Exception:
                lot_count = 1
        if len(data) > 28 and data[28]:
            try:
                source_ids = tuple(int(value) for value in data[28])
            except Exception:
                source_ids = tuple(data[28]) if isinstance(data[28], (list, tuple)) else ()
        if lot_count > 1:
            rows_data.insert(1, ("Lotes Agrupados", str(lot_count), "info"))
            if source_ids:
                rows_data.insert(2, ("IDs dos Lotes", ", ".join(str(value) for value in source_ids), None))

        if price_pct not in (None, "NENHUMA"):
            rows_data.append(("% Margem Preco", fmt_pct(price_pct), None))

        rows_data.extend([
            ("Status", status_value, status_level),
            ("Fonte", self._get(17, "N/A"), None),
            ("Motivo", self._get(18, "N/A"), None),
            ("Alterado em", self._format_datetime(self._get(19, "")) or "N/A", None),
            ("Alterado por", self._get(20, "N/A"), None),
        ])

        compact = self._compact
        row_height = dp(58) if compact else dp(40)
        label_hint = 1 if compact else 0.42
        value_hint = 1 if compact else 0.58
        value_halign = "left" if compact else "right"
        row_padding = [dp(12), dp(7)] if compact else [dp(12), 0]
        row_orientation = "vertical" if compact else "horizontal"
        label_font_size = sp(14) if compact else sp(14.5)
        value_font_size = sp(15) if compact else sp(15.5)

        for idx, (label, value, highlight) in enumerate(rows_data):
            bg = self._tokens["card_alt"] if idx % 2 == 0 else self._tokens["card"]
            if highlight == "danger":
                bg = _tint(self._tokens["danger"], 0.24)
            elif highlight == "warning":
                bg = _tint(self._tokens["warning"], 0.24)
            elif highlight == "info":
                bg = _tint(self._tokens["info"], 0.24)
            elif highlight == "success":
                bg = _tint(self._tokens["success"], 0.24)
            row = MDCard(
                orientation=row_orientation,
                size_hint_y=None,
                height=row_height,
                padding=row_padding,
                radius=[dp(4)],
                elevation=0,
                md_bg_color=bg,
            )

            label_widget = MDLabel(
                text=label,
                halign="left",
                theme_text_color="Custom",
                text_color=self._tokens["text_secondary"],
                font_style="Body2",
                font_size=label_font_size,
                size_hint_x=label_hint,
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
                halign=value_halign,
                theme_text_color="Custom",
                text_color=value_color,
                font_style="Body2",
                font_size=value_font_size,
                size_hint_x=value_hint,
                bold=True,
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
