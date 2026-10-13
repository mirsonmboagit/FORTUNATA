from datetime import datetime

from kivy.app import App
from kivy.core.window import Window
from kivy.graphics import Color, Rectangle, RoundedRectangle
from kivy.metrics import dp, sp
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget

from ui.components.native_widgets import (
    NativeBoxLayout as MDBoxLayout,
    NativeCard as MDCard,
    NativeIcon as MDIcon,
    NativeIconButton as MDIconButton,
    NativeLabel as MDLabel,
)


def _theme_color(name, fallback):
    app = App.get_running_app()
    tokens = getattr(app, "theme_tokens", {}) if app else {}
    return tokens.get(name, fallback)


def _tint(color, alpha=0.18):
    return [color[0], color[1], color[2], alpha]


class _StockBar(Widget):
    """Barra horizontal de progresso (trilho + preenchimento arredondados)."""

    def __init__(self, ratio, fill, track, **kwargs):
        super().__init__(**kwargs)
        self.ratio = max(0.0, min(1.0, float(ratio)))
        with self.canvas:
            Color(*track)
            self._track = RoundedRectangle(radius=[dp(5)])
            Color(*fill)
            self._fill = RoundedRectangle(radius=[dp(5)])
        self.bind(pos=self._sync, size=self._sync)

    def _sync(self, *_args):
        self._track.pos = self.pos
        self._track.size = self.size
        width = max(dp(10), self.width * self.ratio) if self.ratio > 0 else 0
        self._fill.pos = self.pos
        self._fill.size = (width, self.height)


class DetailPopup(Popup):
    ROW_H = dp(34)
    TITLE_H = dp(32)
    SECTION_PAD = dp(12)
    SECTION_GAP = dp(4)

    def __init__(self, product_data, **kwargs):
        super().__init__(**kwargs)
        self._product_data = product_data
        self._tokens = {
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
        }
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

    # ------------------------------------------------------------------
    #  Tamanho / ciclo de vida
    # ------------------------------------------------------------------
    def _apply_size(self):
        w, h = Window.size
        if w < dp(720):
            self.size = (w * 0.95, h * 0.95)
        else:
            self.size = (min(dp(1040), w * 0.90), min(dp(780), h * 0.92))
        self._compact = w < dp(720)

    def _on_resize(self, *_):
        prev = self._compact
        self._apply_size()
        if prev != self._compact:
            self.content = self._build_content()

    def on_dismiss(self):
        Window.unbind(on_resize=self._on_resize)

    # ------------------------------------------------------------------
    #  Dados
    # ------------------------------------------------------------------
    def _get(self, idx, default=None):
        if len(self._product_data) > idx and self._product_data[idx] not in (None, ""):
            return self._product_data[idx]
        return default

    @staticmethod
    def _to_float(value):
        try:
            return float(value)
        except Exception:
            return 0.0

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

    @staticmethod
    def _money(value, suffix=""):
        try:
            text = f"{float(value):,.2f}".replace(",", " ")
        except Exception:
            text = "0.00"
        return f"{text} MT{suffix}"

    @staticmethod
    def _pct(value):
        try:
            return f"{float(value):.2f}%"
        except Exception:
            return "0.00%"

    def _collect(self):
        now = datetime.now()
        is_kg = bool(self._get(15, 0))
        unit = "KG" if is_kg else "UN"

        existing = self._to_float(self._get(2, 0))
        sold = self._to_float(self._get(3, 0))
        sale_price = self._to_float(self._get(4, 0))
        purchase_total = self._to_float(self._get(5, 0))
        purchase_unit = self._to_float(self._get(6, 0))

        profit_unit = self._get(7, None)
        profit_unit = (
            sale_price - purchase_unit
            if profit_unit in (None, "NENHUMA")
            else self._to_float(profit_unit)
        )
        total_profit = self._get(8, None)
        total_profit = (
            profit_unit * sold
            if total_profit in (None, "NENHUMA")
            else self._to_float(total_profit)
        )
        profit_pct = self._get(9, None)
        if profit_pct in (None, "NENHUMA"):
            profit_pct = (profit_unit / purchase_unit * 100) if purchase_unit else 0.0
        else:
            profit_pct = self._to_float(profit_pct)
        price_pct = self._get(10, None)

        def qty(value):
            return f"{value:.2f} {unit}" if is_kg else f"{int(value)} {unit}"

        # Validade
        expiry_raw = self._get(13, "")
        days_left = None
        try:
            expiry_dt = datetime.strptime(str(expiry_raw), "%Y-%m-%d")
            days_left = (expiry_dt.date() - now.date()).days
        except Exception:
            days_left = None

        if days_left is None:
            expiry_level, expiry_msg = None, "Sem data de validade"
        elif days_left < 0:
            plural = "dia" if days_left == -1 else "dias"
            expiry_level, expiry_msg = "danger", f"Expirado há {-days_left} {plural}"
        elif days_left == 0:
            expiry_level, expiry_msg = "warning", "Expira hoje"
        elif days_left <= 7:
            plural = "dia" if days_left == 1 else "dias"
            expiry_level, expiry_msg = "warning", f"Expira em {days_left} {plural}"
        else:
            expiry_level, expiry_msg = "success", f"Válido por mais {days_left} dias"

        # Estado
        status_raw = str(self._get(16, "N/A"))
        status_upper = status_raw.upper()
        if "EXPIR" in status_upper:
            status_level = "danger"
        elif "INAT" in status_upper or "DESAT" in status_upper:
            status_level = "warning"
        elif status_upper in ("N/A", ""):
            status_level = None
        else:
            status_level = "success"
        status_text = status_raw.replace("_", " ").title() if status_upper != "N/A" else "Sem estado"

        # Lotes agrupados
        lot_count = 1
        source_ids = ()
        data = self._product_data
        if len(data) > 27:
            try:
                lot_count = max(1, int(data[27]))
            except Exception:
                lot_count = 1
        if len(data) > 28 and data[28]:
            try:
                source_ids = tuple(int(v) for v in data[28])
            except Exception:
                source_ids = tuple(data[28]) if isinstance(data[28], (list, tuple)) else ()

        pack_units = self._get(23, None)
        try:
            pack_text = str(int(float(pack_units))) if pack_units not in (None, "") else "Nenhuma"
        except Exception:
            pack_text = "Nenhuma"

        total_entered = existing + sold
        return {
            "name": str(self._get(1, "Produto")),
            "category": str(self._get(11, "Sem categoria")),
            "is_kg": is_kg,
            "unit": unit,
            "qty": qty,
            "existing": existing,
            "sold": sold,
            "total_entered": total_entered,
            "sale_price": sale_price,
            "purchase_total": purchase_total,
            "purchase_unit": purchase_unit,
            "profit_unit": profit_unit,
            "total_profit": total_profit,
            "profit_pct": profit_pct,
            "price_pct": price_pct,
            "expiry_raw": expiry_raw,
            "expiry_level": expiry_level,
            "expiry_msg": expiry_msg,
            "status_text": status_text,
            "status_level": status_level,
            "lot_count": lot_count,
            "source_ids": source_ids,
            "pack_text": pack_text,
            "allow_pack_sale": bool(self._get(24, 0)),
            "barcode": str(self._get(12, "Nenhum")),
            "sku": str(self._get(22, "Nenhum")),
        }

    def _level_color(self, level):
        return {
            "danger": self._tokens["danger"],
            "warning": self._tokens["warning"],
            "success": self._tokens["success"],
            "info": self._tokens["info"],
        }.get(level, self._tokens["text_secondary"])

    # ------------------------------------------------------------------
    #  Helpers de widgets
    # ------------------------------------------------------------------
    def _label(self, text, size, color, bold=False, halign="left", **kwargs):
        label = MDLabel(
            text=str(text),
            font_size=size,
            bold=bold,
            halign=halign,
            valign="middle",
            theme_text_color="Custom",
            text_color=color,
            shorten=True,
            shorten_from="right",
            **kwargs,
        )
        label.bind(size=lambda inst, value: setattr(inst, "text_size", value))
        return label

    def _chip(self, text, color, height=None):
        height = height or dp(24)
        width = dp(22) + len(str(text)) * dp(7.5)
        chip = MDCard(
            orientation="horizontal",
            size_hint=(None, None),
            size=(width, height),
            radius=[height / 2],
            elevation=0,
            md_bg_color=_tint(color, 0.20),
            padding=[dp(10), 0, dp(10), 0],
        )
        chip.add_widget(self._label(text, sp(12), color, bold=True, halign="center"))
        return chip

    def _icon_badge(self, icon, color, size):
        badge = MDCard(
            size_hint=(None, None),
            size=(size, size),
            radius=[size / 2],
            elevation=0,
            md_bg_color=_tint(color, 0.20),
        )
        anchor = AnchorLayout(anchor_x="center", anchor_y="center")
        glyph = MDIcon(
            icon=icon,
            size_hint=(None, None),
            size=(size * 0.55, size * 0.55),
            halign="center",
            valign="middle",
            font_size=size * 0.5,
            theme_text_color="Custom",
            text_color=color,
        )
        glyph.bind(size=lambda inst, value: setattr(inst, "text_size", value))
        anchor.add_widget(glyph)
        badge.add_widget(anchor)
        return badge

    # ------------------------------------------------------------------
    #  Estrutura
    # ------------------------------------------------------------------
    def _build_content(self):
        self._info = self._collect()
        compact = self._compact
        container = MDCard(
            orientation="vertical",
            padding=dp(14) if compact else dp(18),
            spacing=dp(12),
            radius=[dp(20)],
            md_bg_color=self._tokens["card"],
            elevation=4,
        )
        container.add_widget(self._build_header())
        container.add_widget(self._build_body())
        return container

    def _build_header(self):
        info = self._info
        compact = self._compact
        header = MDCard(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(96) if compact else dp(88),
            padding=[dp(16), dp(12), dp(8), dp(12)],
            spacing=dp(14),
            radius=[dp(16)],
            md_bg_color=self._tokens["card_alt"],
            elevation=0,
        )
        header.add_widget(self._icon_badge("package-variant-closed", self._tokens["primary"], dp(52)))

        text_col = MDBoxLayout(orientation="vertical", spacing=dp(6))
        text_col.add_widget(self._label(
            info["name"], sp(19) if compact else sp(21),
            self._tokens["text_primary"], bold=True,
        ))

        chips = MDBoxLayout(
            orientation="horizontal", size_hint_y=None, height=dp(24), spacing=dp(8),
        )
        chips.add_widget(self._chip(info["category"], self._tokens["info"]))
        chips.add_widget(self._chip(
            info["status_text"], self._level_color(info["status_level"]),
        ))
        chips.add_widget(self._chip(
            "Venda por KG" if info["is_kg"] else "Venda por unidade",
            self._tokens["primary"],
        ))
        if info["lot_count"] > 1:
            chips.add_widget(self._chip(f"{info['lot_count']} lotes", self._tokens["warning"]))
        chips.add_widget(Widget())
        text_col.add_widget(chips)
        header.add_widget(text_col)

        header.add_widget(MDIconButton(
            icon="close",
            theme_text_color="Custom",
            text_color=self._tokens["text_secondary"],
            md_bg_color=self._tokens["card"],
            size_hint=(None, None),
            size=(dp(38), dp(38)),
            pos_hint={"center_y": 0.5},
            on_release=self.dismiss,
        ))
        return header

    def _build_body(self):
        scroll = ScrollView(
            do_scroll_x=False,
            bar_width=dp(6),
            bar_color=_tint(self._tokens["primary"], 0.78),
            bar_inactive_color=_tint(self._tokens["text_secondary"], 0.28),
        )
        body = MDBoxLayout(orientation="vertical", spacing=dp(12), size_hint_y=None)
        body.bind(minimum_height=body.setter("height"))

        body.add_widget(self._build_kpis())

        sections = self._build_sections()
        if self._compact:
            for spec in sections["all"]:
                body.add_widget(self._section(spec))
        else:
            body.add_widget(self._two_columns(sections["left"], sections["right"]))

        scroll.add_widget(body)
        return scroll

    # ------------------------------------------------------------------
    #  KPIs
    # ------------------------------------------------------------------
    def _build_kpis(self):
        info = self._info
        low_stock = info["existing"] < 5
        kpis = [
            (
                "Disponível",
                info["qty"](info["existing"]),
                "package-variant-closed",
                self._tokens["danger"] if low_stock else self._tokens["success"],
            ),
            (
                "Preço de venda",
                self._money(info["sale_price"], f"/{info['unit']}"),
                "tag-outline",
                self._tokens["info"],
            ),
            (
                "Lucro por unidade",
                self._money(info["profit_unit"], f"/{info['unit']}"),
                "cash",
                self._tokens["success"] if info["profit_unit"] >= 0 else self._tokens["danger"],
            ),
            (
                "Margem de lucro",
                self._pct(info["profit_pct"]),
                "chart-line",
                self._tokens["info"],
            ),
        ]
        cards = [self._kpi_card(*item) for item in kpis]

        card_h = dp(72)
        if self._compact:
            wrapper = MDBoxLayout(
                orientation="vertical", size_hint_y=None,
                height=card_h * 2 + dp(8), spacing=dp(8),
            )
            for start in (0, 2):
                row = MDBoxLayout(orientation="horizontal", spacing=dp(8))
                for card in cards[start:start + 2]:
                    row.add_widget(card)
                wrapper.add_widget(row)
            return wrapper

        row = MDBoxLayout(
            orientation="horizontal", size_hint_y=None, height=card_h, spacing=dp(10),
        )
        for card in cards:
            row.add_widget(card)
        return row

    def _kpi_card(self, label, value, icon, color):
        card = MDCard(
            orientation="horizontal",
            padding=[dp(12), dp(8), dp(10), dp(8)],
            spacing=dp(10),
            radius=[dp(14)],
            elevation=0,
            md_bg_color=_tint(color, 0.12),
        )
        badge = self._icon_badge(icon, color, dp(38))
        badge.pos_hint = {"center_y": 0.5}
        card.add_widget(badge)

        text_col = MDBoxLayout(orientation="vertical", spacing=0)
        text_col.add_widget(self._label(label, sp(12), self._tokens["text_secondary"]))
        text_col.add_widget(self._label(value, sp(16), color, bold=True))
        card.add_widget(text_col)
        return card

    # ------------------------------------------------------------------
    #  Seccoes
    # ------------------------------------------------------------------
    def _build_sections(self):
        info = self._info
        unit = info["unit"]

        stock = {
            "title": "Stock",
            "icon": "package-variant-closed",
            "color": self._tokens["success"],
            "extra": "stock",
            "rows": [
                ("Disponível", info["qty"](info["existing"]),
                 "danger" if info["existing"] < 5 else None),
                ("Vendido", info["qty"](info["sold"]), None),
                ("Total registado", info["qty"](info["total_entered"]), None),
            ],
        }

        prices_rows = [
            ("Compra total", self._money(info["purchase_total"]), None),
            ("Compra (unitário)", self._money(info["purchase_unit"], f"/{unit}"), None),
            ("Venda final", self._money(info["sale_price"], f"/{unit}"), "info"),
            ("Lucro por unidade",
             self._money(info["profit_unit"], f"/{unit}"),
             "success" if info["profit_unit"] >= 0 else "danger"),
            ("Lucro total", self._money(info["total_profit"]),
             "success" if info["total_profit"] >= 0 else "danger"),
            ("% de lucro", self._pct(info["profit_pct"]), None),
        ]
        if info["price_pct"] not in (None, "NENHUMA"):
            prices_rows.append(("% margem de preço", self._pct(info["price_pct"]), None))
        prices = {
            "title": "Preços e lucro",
            "icon": "cash",
            "color": self._tokens["info"],
            "extra": None,
            "rows": prices_rows,
        }

        ident_rows = [
            ("ID", str(self._get(0, "")), None),
            ("Código de barras", info["barcode"],
             "warning" if info["barcode"].upper() == "NENHUM" else None),
            ("SKU", info["sku"],
             "warning" if info["sku"].upper() == "NENHUM" else None),
            ("Unidade de medida", str(self._get(21, "Nenhuma")), None),
            ("Unid. por embalagem", info["pack_text"], None),
            ("Venda por embalagem", "Ativa" if info["allow_pack_sale"] else "Inativa",
             "success" if info["allow_pack_sale"] else None),
        ]
        if info["lot_count"] > 1:
            ident_rows.append(("Lotes agrupados", str(info["lot_count"]), "info"))
            if info["source_ids"]:
                ident_rows.append((
                    "IDs dos lotes",
                    ", ".join(str(v) for v in info["source_ids"]),
                    None,
                ))
        ident = {
            "title": "Identificação",
            "icon": "barcode-scan",
            "color": self._tokens["primary"],
            "extra": None,
            "rows": ident_rows,
        }

        validity = {
            "title": "Validade e registo",
            "icon": "calendar-clock",
            "color": self._level_color(info["expiry_level"]),
            "extra": "expiry",
            "rows": [
                ("Data de validade", self._format_date(info["expiry_raw"]) or "Nenhuma",
                 info["expiry_level"] if info["expiry_level"] in ("danger", "warning") else None),
                ("Data de cadastro",
                 self._format_datetime(self._get(14, "")) or "Nenhuma", None),
            ],
        }

        history = {
            "title": "Última alteração",
            "icon": "clock-outline",
            "color": self._tokens["text_secondary"],
            "extra": None,
            "rows": [
                ("Alterado em", self._format_datetime(self._get(19, "")) or "N/A", None),
                ("Alterado por", str(self._get(20, "N/A")), None),
                ("Fonte", str(self._get(17, "N/A")), None),
                ("Motivo", str(self._get(18, "N/A")), None),
            ],
        }

        return {
            "all": [stock, prices, ident, validity, history],
            "left": [stock, validity, history],
            "right": [prices, ident],
        }

    def _section_height(self, spec):
        extra_h = {"stock": dp(46), "expiry": dp(36)}.get(spec.get("extra"), 0)
        children = 1 + (1 if extra_h else 0) + len(spec["rows"])
        return (
            self.SECTION_PAD * 2
            + self.TITLE_H
            + extra_h
            + len(spec["rows"]) * self.ROW_H
            + (children - 1) * self.SECTION_GAP
        )

    def _section(self, spec):
        card = MDCard(
            orientation="vertical",
            size_hint_y=None,
            height=self._section_height(spec),
            padding=[dp(14), self.SECTION_PAD, dp(14), self.SECTION_PAD],
            spacing=self.SECTION_GAP,
            radius=[dp(16)],
            elevation=0,
            md_bg_color=self._tokens["card_alt"],
        )

        title_row = MDBoxLayout(
            orientation="horizontal", size_hint_y=None, height=self.TITLE_H, spacing=dp(10),
        )
        badge = self._icon_badge(spec["icon"], spec["color"], dp(28))
        badge.pos_hint = {"center_y": 0.5}
        title_row.add_widget(badge)
        title_row.add_widget(self._label(
            spec["title"], sp(15), self._tokens["text_primary"], bold=True,
        ))
        card.add_widget(title_row)

        if spec.get("extra") == "stock":
            card.add_widget(self._stock_block())
        elif spec.get("extra") == "expiry":
            card.add_widget(self._expiry_block())

        for label, value, level in spec["rows"]:
            card.add_widget(self._row(label, value, level))
        return card

    def _two_columns(self, left_specs, right_specs):
        gap = dp(12)

        def column(specs):
            height = sum(self._section_height(s) for s in specs) + gap * (len(specs) - 1)
            col = MDBoxLayout(
                orientation="vertical", size_hint_y=None, height=height, spacing=gap,
            )
            for spec in specs:
                col.add_widget(self._section(spec))
            return col, height

        left_col, left_h = column(left_specs)
        right_col, right_h = column(right_specs)

        wrapper = MDBoxLayout(
            orientation="horizontal", size_hint_y=None,
            height=max(left_h, right_h), spacing=gap,
        )
        wrapper.add_widget(left_col)
        wrapper.add_widget(right_col)
        return wrapper

    # ------------------------------------------------------------------
    #  Blocos especiais
    # ------------------------------------------------------------------
    def _stock_block(self):
        info = self._info
        total = info["total_entered"]
        ratio = (info["existing"] / total) if total > 0 else 0.0
        low = info["existing"] < 5
        color = self._tokens["danger"] if low else self._tokens["success"]

        block = MDBoxLayout(
            orientation="vertical", size_hint_y=None, height=dp(46), spacing=dp(6),
        )
        bar = _StockBar(
            ratio,
            fill=color,
            track=_tint(self._tokens["text_secondary"], 0.20),
            size_hint_y=None,
            height=dp(10),
        )
        block.add_widget(bar)
        if total > 0:
            caption = f"{ratio * 100:.0f}% do stock registado ainda está disponível"
        else:
            caption = "Sem movimento de stock registado"
        if low and info["existing"] > 0:
            caption = "Stock baixo  ·  " + caption
        elif info["existing"] <= 0:
            caption = "Sem stock  ·  " + caption
        block.add_widget(self._label(caption, sp(12), color, bold=low))
        return block

    def _expiry_block(self):
        info = self._info
        color = self._level_color(info["expiry_level"])
        block = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(36))
        block.add_widget(self._chip(info["expiry_msg"], color, height=dp(30)))
        block.add_widget(Widget())
        return block

    def _row(self, label, value, level=None):
        row = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=self.ROW_H,
            spacing=dp(8),
            padding=[dp(2), 0, dp(2), 0],
        )
        with row.canvas.after:
            Color(*_tint(self._tokens["text_secondary"], 0.14))
            line = Rectangle(pos=row.pos, size=(row.width, dp(1)))
        row.bind(
            pos=lambda inst, _v, ln=line: setattr(ln, "pos", inst.pos),
            size=lambda inst, _v, ln=line: setattr(ln, "size", (inst.width, dp(1))),
        )

        value_color = self._tokens["text_primary"]
        if level:
            value_color = self._level_color(level)

        row.add_widget(self._label(
            label, sp(13), self._tokens["text_secondary"], size_hint_x=0.45,
        ))
        row.add_widget(self._label(
            value, sp(14), value_color, bold=True, halign="right", size_hint_x=0.55,
        ))
        return row