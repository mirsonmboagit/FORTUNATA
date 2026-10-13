"""
Pré-visualização interna de relatórios — paginada e legível.
"""

from __future__ import annotations

from kivy.app import App
from kivy.clock import Clock
from kivy.metrics import dp, sp
from kivy.uix.scrollview import ScrollView
from kivy.core.window import Window

from ui.components.native_widgets import (
    NativeBoxLayout as MDBoxLayout,
    NativeButton as MDRaisedButton,
    NativeCard as MDCard,
    NativeDialog as MDDialog,
    NativeFlatButton as MDFlatButton,
    NativeLabel as MDLabel,
    NativeTextField as MDTextField,
)

PAGE_SIZE = 40


def _theme(name, fallback):
    app = App.get_running_app()
    tokens = getattr(app, "theme_tokens", {}) if app else {}
    return tokens.get(name, fallback)


def _fmt_num(value, decimals=2):
    try:
        n = float(value)
    except (TypeError, ValueError):
        return "—"
    if decimals == 0:
        return f"{int(round(n)):,}".replace(",", " ")
    if abs(n - int(n)) < 1e-9:
        return f"{int(n):,}".replace(",", " ")
    return f"{n:,.{decimals}f}".replace(",", " ")


class ReportDataPreview(MDDialog):
    """Dialog de visualização tabular com paginação e KPIs."""

    def __init__(
        self,
        title="Pré-visualização",
        dataframe=None,
        columns=None,
        kpis=None,
        on_export_pdf=None,
        page_size=PAGE_SIZE,
        **kwargs,
    ):
        self._df = dataframe
        self._columns = list(columns or [])
        self._kpis = list(kpis or [])
        self._on_export_pdf = on_export_pdf
        self._page_size = max(10, int(page_size or PAGE_SIZE))
        self._page = 0
        self._view_df = dataframe
        self._total_rows = 0 if dataframe is None else int(len(dataframe))
        self._title_text = str(title or "Pré-visualização")

        content = self._build_content()
        buttons = [
            MDFlatButton(
                text="FECHAR",
                text_color=_theme("text_secondary", (0.62, 0.64, 0.68, 1)),
                on_release=lambda *_: self.dismiss(),
            ),
        ]
        if callable(on_export_pdf):
            buttons.append(
                MDRaisedButton(
                    text="EXPORTAR PDF",
                    md_bg_color=_theme("primary", (0.15, 0.52, 0.76, 1)),
                    text_color=_theme("on_primary", (1, 1, 1, 1)),
                    on_release=lambda *_: self._export(),
                )
            )

        width = min(dp(920), max(dp(340), Window.width * 0.92))
        height = min(dp(620), max(dp(400), Window.height * 0.86))
        super().__init__(
            title="",
            type="custom",
            content_cls=content,
            size_hint=(None, None),
            size=(width, height),
            buttons=buttons,
            auto_dismiss=False,
            **kwargs,
        )
        Window.bind(on_resize=self._on_resize)
        # refrescar depois do dialog ter tamanho real
        Clock.schedule_once(lambda dt: self._fit_and_refresh(), 0)
        Clock.schedule_once(lambda dt: self._fit_and_refresh(), 0.08)
        Clock.schedule_once(lambda dt: self._fit_and_refresh(), 0.2)

    def _build_content(self):
        root = MDBoxLayout(
            orientation="vertical",
            spacing=dp(8),
            padding=[dp(8), dp(6), dp(8), dp(4)],
            size_hint_y=None,
        )
        root.bind(minimum_height=root.setter("height"))
        self._root = root

        root.add_widget(
            MDLabel(
                text=self._title_text,
                bold=True,
                font_size=sp(16),
                theme_text_color="Custom",
                text_color=_theme("text_primary", (0.95, 0.96, 0.98, 1)),
                size_hint_y=None,
                height=dp(26),
                shorten=True,
            )
        )

        if self._kpis:
            kpi_row = MDBoxLayout(
                orientation="horizontal",
                size_hint_y=None,
                height=dp(52),
                spacing=dp(6),
            )
            for label, value in self._kpis[:5]:
                chip = MDCard(
                    orientation="vertical",
                    size_hint_x=1,
                    size_hint_y=None,
                    height=dp(52),
                    padding=[dp(6), dp(6)],
                    radius=[dp(10)],
                    elevation=0,
                    md_bg_color=_theme("card_alt", (0.14, 0.16, 0.20, 1)),
                )
                chip.add_widget(
                    MDLabel(
                        text=str(value),
                        bold=True,
                        font_size=sp(13),
                        theme_text_color="Custom",
                        text_color=_theme("text_primary", (0.95, 0.96, 0.98, 1)),
                        halign="center",
                        size_hint_y=None,
                        height=dp(22),
                        shorten=True,
                    )
                )
                chip.add_widget(
                    MDLabel(
                        text=str(label),
                        font_size=sp(10),
                        theme_text_color="Custom",
                        text_color=_theme("text_secondary", (0.58, 0.60, 0.64, 1)),
                        halign="center",
                        size_hint_y=None,
                        height=dp(16),
                        shorten=True,
                    )
                )
                kpi_row.add_widget(chip)
            root.add_widget(kpi_row)

        search_row = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(42),
            spacing=dp(8),
        )
        self._search = MDTextField(
            hint_text="Filtrar por produto ou categoria…",
            mode="rectangle",
            size_hint_x=1,
            font_size=sp(13),
            on_text_validate=lambda *_: self._apply_filter(),
        )
        search_row.add_widget(self._search)
        search_row.add_widget(
            MDRaisedButton(
                text="FILTRAR",
                size_hint=(None, None),
                size=(dp(96), dp(38)),
                font_size=sp(12),
                md_bg_color=_theme("info", (0.18, 0.55, 0.82, 1)),
                text_color=_theme("on_primary", (1, 1, 1, 1)),
                on_release=lambda *_: self._apply_filter(),
            )
        )
        root.add_widget(search_row)

        self._info = MDLabel(
            text="",
            font_size=sp(11),
            theme_text_color="Custom",
            text_color=_theme("text_secondary", (0.58, 0.60, 0.64, 1)),
            size_hint_y=None,
            height=dp(18),
        )
        root.add_widget(self._info)

        # --- TABELA: alturas EXPLÍCITAS (ScrollView com size_hint_y=1 ficava a 0) ---
        self._table_h = dp(300)
        table_card = MDBoxLayout(
            orientation="vertical",
            size_hint_y=None,
            height=self._table_h,
            spacing=0,
            padding=[0, 0],
        )
        self._table_card = table_card

        header = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(34),
            padding=[dp(8), 0],
            spacing=dp(4),
            md_bg_color=_theme("primary", (0.12, 0.38, 0.58, 1)),
        )
        self._header = header
        on_p = _theme("on_primary", (1, 1, 1, 1))
        for _key, label, weight, numeric in self._columns:
            lbl = MDLabel(
                text=str(label),
                bold=True,
                font_size=sp(11),
                theme_text_color="Custom",
                text_color=on_p,
                size_hint_x=weight,
                halign="right" if numeric else "left",
                valign="middle",
                shorten=True,
            )
            header.add_widget(lbl)
        table_card.add_widget(header)

        # altura do scroll = card - header (definida em _fit)
        self._scroll = ScrollView(
            size_hint=(1, None),
            height=self._table_h - dp(34),
            do_scroll_x=False,
            bar_width=dp(5),
        )
        self._body = MDBoxLayout(
            orientation="vertical",
            size_hint_y=None,
            height=dp(1),
            spacing=0,
            padding=[0, 0],
        )
        self._body.bind(minimum_height=self._body.setter("height"))
        self._scroll.add_widget(self._body)
        table_card.add_widget(self._scroll)
        root.add_widget(table_card)

        nav = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(36),
            spacing=dp(6),
        )
        self._prev_btn = MDFlatButton(
            text="◀ Anterior",
            font_size=sp(12),
            text_color=_theme("primary", (0.35, 0.70, 0.95, 1)),
            on_release=lambda *_: self._change_page(-1),
        )
        self._page_lbl = MDLabel(
            text="1 / 1",
            halign="center",
            valign="middle",
            font_size=sp(12),
            theme_text_color="Custom",
            text_color=_theme("text_primary", (0.92, 0.93, 0.95, 1)),
            bold=True,
        )
        self._next_btn = MDFlatButton(
            text="Seguinte ▶",
            font_size=sp(12),
            text_color=_theme("primary", (0.35, 0.70, 0.95, 1)),
            on_release=lambda *_: self._change_page(1),
        )
        nav.add_widget(self._prev_btn)
        nav.add_widget(self._page_lbl)
        nav.add_widget(self._next_btn)
        root.add_widget(nav)
        return root

    def _fit_and_refresh(self):
        try:
            chrome = dp(250)
            if self._kpis:
                chrome += dp(56)
            table_h = max(dp(180), float(self.height) - chrome)
            self._table_h = table_h
            self._table_card.height = table_h
            self._scroll.height = max(dp(120), table_h - dp(34))
            if hasattr(self, "_root"):
                self._root.width = max(dp(280), float(self.width) - dp(40))
        except Exception as exc:
            print(f"[ReportPreview] fit: {exc}")
        self._refresh_table()

    def _on_resize(self, *_args):
        try:
            if self.parent is None:
                return
            self.size = (
                min(dp(920), max(dp(340), Window.width * 0.92)),
                min(dp(620), max(dp(400), Window.height * 0.86)),
            )
            self._fit_and_refresh()
        except Exception:
            pass

    def on_dismiss(self, *args):
        try:
            Window.unbind(on_resize=self._on_resize)
        except Exception:
            pass
        return super().on_dismiss(*args)

    def _apply_filter(self):
        text = (getattr(self._search, "text", None) or "").strip().lower()
        self._page = 0
        if self._df is None or not text:
            self._view_df = self._df
        else:
            try:
                mask = None
                for key, _label, _w, numeric in self._columns:
                    if numeric or key not in self._df.columns:
                        continue
                    series = self._df[key].astype(str).str.lower()
                    part = series.str.contains(text, na=False, regex=False)
                    mask = part if mask is None else (mask | part)
                self._view_df = self._df[mask] if mask is not None else self._df
            except Exception as exc:
                print(f"[ReportPreview] filter: {exc}")
                self._view_df = self._df
        self._refresh_table()

    def _total_pages(self):
        n = 0 if self._view_df is None else len(self._view_df)
        if n <= 0:
            return 1
        return max(1, (n + self._page_size - 1) // self._page_size)

    def _change_page(self, delta):
        total = self._total_pages()
        self._page = max(0, min(self._page + int(delta), total - 1))
        self._refresh_table()

    def _cell_text(self, row, key, numeric):
        raw = None
        try:
            if key in getattr(row, "index", []):
                raw = row[key]
            elif hasattr(row, "get"):
                raw = row.get(key)
        except Exception:
            raw = None
        if raw is None or (isinstance(raw, float) and raw != raw):  # NaN
            return "—"
        if numeric:
            if key in ("sold_stock", "entrada", "remanescente", "saida"):
                return _fmt_num(raw, 0)
            return _fmt_num(raw, 2)
        text = str(raw).strip() or "—"
        if len(text) > 34:
            return text[:31] + "..."
        return text

    def _make_row(self, cells, alt):
        """Linha simples — MDBoxLayout + labels (sem widgets custom)."""
        bg = (
            (0.14, 0.16, 0.20, 1)
            if alt
            else (0.10, 0.11, 0.14, 1)
        )
        # prefer theme
        try:
            bg = (
                _theme("card_alt", bg)
                if alt
                else _theme("card", bg)
            )
        except Exception:
            pass

        row = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(30),
            padding=[dp(8), 0],
            spacing=dp(4),
        )
        # fundo via canvas (funciona mesmo se NativeBoxLayout ignorar md_bg_color)
        try:
            from kivy.graphics import Color, Rectangle

            with row.canvas.before:
                Color(*bg)
                rect = Rectangle(pos=row.pos, size=row.size)

            def _sync(*_a):
                rect.pos = row.pos
                rect.size = row.size

            row.bind(pos=_sync, size=_sync)
        except Exception:
            pass

        fg = _theme("text_primary", (0.92, 0.93, 0.95, 1))
        for (_key, _label, weight, numeric), text in zip(self._columns, cells):
            row.add_widget(
                MDLabel(
                    text=str(text),
                    font_size=sp(11),
                    theme_text_color="Custom",
                    text_color=fg,
                    size_hint_x=weight,
                    size_hint_y=1,
                    halign="right" if numeric else "left",
                    valign="middle",
                    shorten=True,
                    bold=bool(numeric),
                )
            )
        return row

    def _refresh_table(self):
        try:
            self._body.clear_widgets()
        except Exception:
            return

        view = self._view_df
        total = 0 if view is None else int(len(view))
        pages = self._total_pages()
        self._page = max(0, min(self._page, pages - 1))
        start = self._page * self._page_size
        end = min(start + self._page_size, total)

        self._info.text = (
            f"Mostrando {start + 1 if total else 0}–{end} de {total:,}"
            f"   ·   total no relatório: {self._total_rows:,}"
        ).replace(",", " ")
        self._page_lbl.text = f"Página {self._page + 1} de {pages}"
        self._prev_btn.disabled = self._page <= 0
        self._next_btn.disabled = self._page >= pages - 1

        if view is None or total == 0:
            self._body.add_widget(
                MDLabel(
                    text="Sem dados para este filtro.",
                    theme_text_color="Custom",
                    text_color=_theme("text_secondary", (0.6, 0.6, 0.6, 1)),
                    size_hint_y=None,
                    height=dp(48),
                    halign="center",
                )
            )
            return

        try:
            page_df = view.iloc[start:end]
        except Exception as exc:
            print(f"[ReportPreview] iloc: {exc}")
            page_df = view

        alt = False
        added = 0
        try:
            for _, row in page_df.iterrows():
                cells = [
                    self._cell_text(row, key, numeric)
                    for key, _label, _w, numeric in self._columns
                ]
                self._body.add_widget(self._make_row(cells, alt=alt))
                alt = not alt
                added += 1
        except Exception as exc:
            print(f"[ReportPreview] rows: {exc}")
            self._body.add_widget(
                MDLabel(
                    text=f"Erro ao desenhar linhas: {exc}",
                    theme_text_color="Custom",
                    text_color=(0.9, 0.3, 0.3, 1),
                    size_hint_y=None,
                    height=dp(40),
                )
            )

        if added == 0 and total > 0:
            self._body.add_widget(
                MDLabel(
                    text="Dados carregados, mas nenhuma linha foi desenhada.",
                    theme_text_color="Custom",
                    text_color=_theme("warning", (0.9, 0.7, 0.2, 1)),
                    size_hint_y=None,
                    height=dp(40),
                )
            )

        try:
            self._scroll.scroll_y = 1
        except Exception:
            pass

    def _export(self):
        if callable(self._on_export_pdf):
            try:
                self._on_export_pdf(self._df)
            except TypeError:
                self._on_export_pdf()
        self.dismiss()


COMPLETE_COLUMNS = [
    ("description", "Produto", 2.0, False),
    ("category", "Categoria", 1.2, False),
    ("entrada", "Entr.", 0.7, True),
    ("sold_stock", "Vend.", 0.7, True),
    ("remanescente", "Est.", 0.7, True),
    ("sale_price", "P.venda", 0.85, True),
    ("valor_total_vendas", "Receita", 1.05, True),
    ("lucro_total", "Lucro", 0.95, True),
]

SALES_COLUMNS = [
    ("description", "Produto", 2.4, False),
    ("category", "Categoria", 1.3, False),
    ("sold_stock", "Qtd", 0.8, True),
    ("sale_price", "Preço", 0.9, True),
    ("valor_total_vendas", "Total", 1.2, True),
]

STOCK_COLUMNS = [
    ("description", "Produto", 2.4, False),
    ("category", "Categoria", 1.3, False),
    ("remanescente", "Estoque", 1.0, True),
    ("entrada", "Entrada", 1.0, True),
    ("sold_stock", "Saídas", 1.0, True),
]

PROFIT_COLUMNS = [
    ("description", "Produto", 2.4, False),
    ("category", "Categoria", 1.2, False),
    ("lucro_unitario", "Lucro un.", 1.0, True),
    ("lucro_total", "Lucro total", 1.2, True),
    ("valor_total_vendas", "Receita", 1.2, True),
]


def kpis_from_dataframe(df):
    if df is None or len(df) == 0:
        return [("Linhas", "0")]
    n = len(df)
    kpis = [("Produtos", _fmt_num(n, 0))]
    if "sold_stock" in df.columns:
        kpis.append(("Vendidos", _fmt_num(df["sold_stock"].sum(), 0)))
    if "valor_total_vendas" in df.columns:
        kpis.append(("Receita", f"MZN {_fmt_num(df['valor_total_vendas'].sum())}"))
    if "lucro_total" in df.columns:
        kpis.append(("Lucro", f"MZN {_fmt_num(df['lucro_total'].sum())}"))
    if "remanescente" in df.columns:
        kpis.append(("Esgotados", _fmt_num((df["remanescente"] <= 0).sum(), 0)))
    return kpis[:5]


def columns_for_report(kind):
    return {
        "sales": SALES_COLUMNS,
        "stock": STOCK_COLUMNS,
        "profit": PROFIT_COLUMNS,
        "complete": COMPLETE_COLUMNS,
    }.get(kind, COMPLETE_COLUMNS)
