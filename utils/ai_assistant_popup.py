import math
import time
from threading import Thread

from kivy.app import App
from kivy.clock import Clock
from kivy.graphics import (
    Color, Line, Rectangle, Ellipse,
    RoundedRectangle, Canvas, PushMatrix, PopMatrix, Rotate,
)
from kivy.metrics import dp
from kivy.properties import NumericProperty, ListProperty, StringProperty
from kivy.uix.popup import Popup
from kivy.uix.widget import Widget
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDFlatButton, MDRaisedButton
from kivymd.uix.card import MDCard
from kivymd.uix.label import MDLabel
from kivymd.uix.menu import MDDropdownMenu
from kivymd.uix.scrollview import MDScrollView
from kivymd.uix.textfield import MDTextField

from utils.ai_insights import answer_management_question, can_use_ai_api, build_admin_insights

# ─── PALETA FUTURISTA ────────────────────────────────────────────────────────
_C = {
    "bg":           [0.04, 0.05, 0.08, 1.0],
    "bg_alt":       [0.07, 0.09, 0.13, 1.0],
    "panel":        [0.08, 0.11, 0.17, 1.0],
    "primary":      [0.10, 0.85, 0.75, 1.0],   # ciano-esmeralda
    "primary_dim":  [0.10, 0.85, 0.75, 0.15],
    "accent":       [0.90, 0.35, 1.00, 1.0],   # magenta
    "accent_dim":   [0.90, 0.35, 1.00, 0.12],
    "warn":         [1.00, 0.70, 0.10, 1.0],
    "danger":       [1.00, 0.28, 0.38, 1.0],
    "text_hi":      [0.92, 0.98, 1.00, 1.0],
    "text_mid":     [0.60, 0.76, 0.85, 1.0],
    "text_lo":      [0.34, 0.45, 0.58, 1.0],
    "grid":         [0.10, 0.85, 0.75, 0.05],
}


def _theme(name, fallback):
    app = App.get_running_app()
    tokens = getattr(app, "theme_tokens", {}) if app else {}
    return tokens.get(name, fallback)


# ─── GRID DE FUNDO ANIMADO ───────────────────────────────────────────────────
class _GridBackground(Widget):
    """Grade de perspectiva animada estilo holografia."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._t = 0.0
        self._ev = Clock.schedule_interval(self._tick, 1 / 24)
        self.bind(pos=self._redraw, size=self._redraw)

    def _tick(self, dt):
        self._t += dt * 0.4
        self._redraw()

    def _redraw(self, *_):
        self.canvas.clear()
        with self.canvas:
            # fundo sólido
            Color(*_C["bg"])
            Rectangle(pos=self.pos, size=self.size)

            # linhas horizontais (scroll)
            Color(*_C["grid"])
            spacing = dp(28)
            offset = (self._t * dp(18)) % spacing
            y = self.y + offset
            while y < self.y + self.height:
                Line(points=[self.x, y, self.x + self.width, y], width=dp(0.5))
                y += spacing

            # linhas verticais
            col_spacing = dp(48)
            cx = (self.x + self.width / 2)
            for i in range(-12, 13):
                lx = cx + i * col_spacing
                if self.x <= lx <= self.x + self.width:
                    Color(*_C["grid"])
                    Line(points=[lx, self.y, lx, self.y + self.height], width=dp(0.4))

            # scanline sutil
            scan_y = self.y + ((self._t * 60) % self.height)
            Color(0.10, 0.85, 0.75, 0.06)
            Rectangle(pos=(self.x, scan_y), size=(self.width, dp(3)))

    def on_parent(self, inst, parent):
        if not parent and self._ev:
            self._ev.cancel()


# ─── BORDA QUÂNTICA ANIMADA ───────────────────────────────────────────────────
class _QuantumBorderCard(MDCard):
    """Card com borda pulsante multi-camada e cantos hexagonais."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._t = 0.0
        self._ev = Clock.schedule_interval(self._tick, 1 / 30)
        self.bind(pos=self._sync, size=self._sync)

        with self.canvas.after:
            # Camada 1 – glow exterior largo
            self._gc1 = Color(*_C["primary"])
            self._gl1 = Line(rounded_rectangle=(0, 0, 1, 1, dp(16)), width=dp(5))

            # Camada 2 – linha nítida
            self._gc2 = Color(*_C["primary"])
            self._gl2 = Line(rounded_rectangle=(0, 0, 1, 1, dp(16)), width=dp(1.2))

            # Camada 3 – accent interior pulsante
            self._gc3 = Color(*_C["accent"])
            self._gl3 = Line(rounded_rectangle=(0, 0, 1, 1, dp(14)), width=dp(0.8))

            # Cantos – marcadores angulares (4 cantos)
            self._corner_colors = []
            self._corner_lines = []
            for _ in range(4):
                cc = Color(*_C["accent"])
                cl1 = Line(points=[0, 0, 0, 0], width=dp(1.8))
                cl2 = Line(points=[0, 0, 0, 0], width=dp(1.8))
                self._corner_colors.append(cc)
                self._corner_lines.append((cl1, cl2))

        self._sync()

    def _sync(self, *_):
        x, y, w, h = self.x + dp(1), self.y + dp(1), self.width - dp(2), self.height - dp(2)
        rr = (x, y, max(0, w), max(0, h), dp(16))
        self._gl1.rounded_rectangle = rr
        self._gl2.rounded_rectangle = rr
        ri = (x + dp(4), y + dp(4), max(0, w - dp(8)), max(0, h - dp(8)), dp(13))
        self._gl3.rounded_rectangle = ri
        self._draw_corners(x, y, w, h)

    def _draw_corners(self, x, y, w, h):
        s = dp(14)
        corners = [
            (x,     y + h, +1, -1),  # top-left
            (x + w, y + h, -1, -1),  # top-right
            (x,     y,     +1, +1),  # bot-left
            (x + w, y,     -1, +1),  # bot-right
        ]
        for idx, (cx, cy, dx, dy) in enumerate(corners):
            h_line, v_line = self._corner_lines[idx]
            h_line.points = [cx, cy, cx + dx * s, cy]
            v_line.points = [cx, cy, cx, cy + dy * s]

    def _tick(self, dt):
        self._t += dt
        p = self._t
        # primary color shift: ciano → turquesa
        r = 0.05 + 0.08 * math.sin(p * 0.7)
        g = 0.75 + 0.10 * math.sin(p * 0.5)
        b = 0.70 + 0.15 * math.sin(p * 0.9)
        self._gc2.rgba = (r, g, b, 0.95)
        self._gc1.rgba = (r, g, b, 0.12 + 0.08 * math.sin(p))
        self._gl1.width = dp(4 + 2 * abs(math.sin(p * 1.1)))

        # accent pulse: magenta
        ar = 0.85 + 0.10 * math.sin(p * 1.3 + 1.5)
        ag = 0.20 + 0.15 * math.sin(p * 0.8)
        ab = 0.90 + 0.08 * math.sin(p * 1.7)
        alpha = 0.5 + 0.5 * abs(math.sin(p * 2.0))
        self._gc3.rgba = (ar, ag, ab, alpha * 0.7)

        # corner accent blink
        ca = 0.6 + 0.4 * abs(math.sin(p * 3.0))
        for cc in self._corner_colors:
            cc.rgba = (ar, ag, ab, ca)

    def on_parent(self, inst, parent):
        if not parent and self._ev:
            self._ev.cancel()


# ─── LABEL COM EFEITO TYPEWRITER ─────────────────────────────────────────────
class _TypewriterLabel(MDLabel):
    full_text = StringProperty("")

    def __init__(self, **kwargs):
        self._full = kwargs.pop("full_text", "")
        super().__init__(**kwargs)
        self.full_text = self._full
        self._idx = 0
        self._ev = None

    def start(self, delay=0.0):
        self.text = ""
        self._idx = 0
        Clock.schedule_once(lambda dt: self._tick_start(), delay)

    def _tick_start(self):
        self._ev = Clock.schedule_interval(self._tick, 0.018)

    def _tick(self, dt):
        chunk = 2
        self._idx = min(self._idx + chunk, len(self.full_text))
        self.text = self.full_text[: self._idx]
        if self._idx >= len(self.full_text):
            if self._ev:
                self._ev.cancel()
            return False

    def on_parent(self, inst, parent):
        if not parent and self._ev:
            self._ev.cancel()


# ─── BARRA DE PROGRESSO IA ───────────────────────────────────────────────────
class _AIScanBar(Widget):
    """Barra de análise animada enquanto processa."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._t = 0.0
        self._active = False
        self._ev = None
        self.size_hint_y = None
        self.height = dp(3)
        self._draw()

    def start(self):
        self._active = True
        self._t = 0.0
        self._ev = Clock.schedule_interval(self._tick, 1 / 30)

    def stop(self):
        self._active = False
        if self._ev:
            self._ev.cancel()
        self.canvas.clear()
        self._draw()

    def _tick(self, dt):
        self._t += dt
        self._draw()

    def _draw(self, *_):
        self.canvas.clear()
        with self.canvas:
            if not self._active:
                Color(*_C["primary_dim"])
                RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(2)])
                return
            # fundo
            Color(*_C["primary_dim"])
            RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(2)])
            # barra deslizante
            p = (self._t * 0.8) % 1.5
            head = min(p, 1.0)
            tail = max(0.0, p - 0.4)
            bw = (head - tail) * self.width
            bx = self.x + tail * self.width
            Color(*_C["primary"])
            RoundedRectangle(pos=(bx, self.y), size=(bw, self.height), radius=[dp(2)])
            # dot lider
            Color(*_C["accent"])
            dot = dp(5)
            Ellipse(pos=(bx + bw - dot / 2, self.y - dot / 2 + self.height / 2), size=(dot, dot))

    def bind(self, **kwargs):
        super().bind(**kwargs)


# ─── POPUP PRINCIPAL ─────────────────────────────────────────────────────────
class ManagementAIAssistantPopup(Popup):

    def __init__(self, db=None, ai_name="NomeDaIA", **kwargs):
        super().__init__(**kwargs)
        self.db = db
        self.ai_name = ai_name or "NomeDaIA"
        self._busy = False
        self._quick_menu = None
        self._recent_questions = []
        self._boot_messages = [
            "SISTEMA INICIALIZADO",
            f"AGENTE: {self.ai_name.upper()}",
            "MODULOS: VENDAS · STOCK · PERDAS · PRODUTIVIDADE",
            "PRONTO PARA ANALISE",
        ]
        self._default_quick_questions = [
            "Qual foi a receita total de hoje?",
            "Quantas vendas promocionais tivemos nos ultimos 7 dias?",
            "Quais sao os 5 produtos com maior faturacao nos ultimos 30 dias?",
            "Quais produtos estao com stock baixo agora?",
            "Quais produtos vencem nos proximos 7 dias?",
            "Qual foi o custo total das perdas nos ultimos 30 dias?",
            "Quem teve mais atividade operacional nos ultimos 30 dias?",
            "Qual acao devo priorizar hoje para reduzir perdas e rupturas?",
        ]
        self._setup_popup()
        self.content = self._build_content()
        Clock.schedule_once(lambda dt: self._run_boot_sequence(), 0.2)

    def _setup_popup(self):
        self.title = ""
        self.separator_height = 0
        self.background = "data/images/defaulttheme/transparent.png"
        self.background_color = (0, 0, 0, 0)
        self.auto_dismiss = False
        self.size_hint = (0.92, 0.90)

    # ── BUILD ────────────────────────────────────────────────────────────────
    def _build_content(self):
        root = MDBoxLayout(orientation="vertical")

        # fundo animado
        self._grid_bg = _GridBackground(size_hint=(1, 1))
        root.add_widget(self._grid_bg)

        # card principal com borda quântica (overlay sobre grid)
        from kivy.uix.floatlayout import FloatLayout
        fl = FloatLayout()
        self._grid_bg2 = _GridBackground(size_hint=(1, 1), pos_hint={"x": 0, "y": 0})

        card = _QuantumBorderCard(
            orientation="vertical",
            padding=[dp(18), dp(14), dp(18), dp(16)],
            spacing=dp(10),
            radius=[dp(16)],
            md_bg_color=[0.05, 0.07, 0.11, 0.97],
            elevation=0,
            size_hint=(1, 1),
            pos_hint={"x": 0, "y": 0},
        )

        # ── CABEÇALHO ───────────────────────────────────────────────────────
        header = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(48),
            spacing=dp(10),
        )

        # ícone/orbe pulsante
        orb = _OrbWidget(size_hint=(None, None), size=(dp(36), dp(36)))
        header.add_widget(orb)

        title_col = MDBoxLayout(orientation="vertical", spacing=dp(1))
        title_col.add_widget(MDLabel(
            text=f"[ {self.ai_name.upper()} ]",
            bold=True,
            font_size="15sp",
            theme_text_color="Custom",
            text_color=_C["primary"],
            halign="left",
            size_hint_y=None,
            height=dp(22),
        ))
        self._status_label = MDLabel(
            text="● INICIALIZANDO...",
            font_size="10sp",
            theme_text_color="Custom",
            text_color=_C["accent"],
            halign="left",
            size_hint_y=None,
            height=dp(16),
        )
        title_col.add_widget(self._status_label)
        header.add_widget(title_col)

        close_btn = MDFlatButton(
            text="[ ESC ]",
            theme_text_color="Custom",
            text_color=_C["text_lo"],
            on_release=self.dismiss,
            size_hint_x=None,
            width=dp(72),
            font_size="10sp",
        )
        header.add_widget(close_btn)
        card.add_widget(header)

        # ── SCAN BAR ────────────────────────────────────────────────────────
        self._scan_bar = _AIScanBar()
        card.add_widget(self._scan_bar)

        # ── INPUT ZONE ──────────────────────────────────────────────────────
        input_card = MDCard(
            orientation="vertical",
            size_hint_y=None,
            adaptive_height=True,
            padding=[dp(12), dp(10), dp(12), dp(8)],
            spacing=dp(8),
            radius=[dp(10)],
            md_bg_color=_C["panel"],
            elevation=0,
        )
        with input_card.canvas.before:
            Color(*_C["primary_dim"])
            self._input_border = Line(rounded_rectangle=(0, 0, 1, 1, dp(10)), width=dp(0.8))
        input_card.bind(pos=self._sync_input_border, size=self._sync_input_border)

        self.question_input = MDTextField(
            hint_text="› QUERY: Ex: produtos com risco de ruptura esta semana?",
            mode="rectangle",
            multiline=True,
            max_height=dp(110),
            size_hint_y=None,
            height=dp(88),
            font_size="12sp",
        )
        # estilo do textfield
        self.question_input.line_color_focus = _C["primary"][:3] + [1]
        self.question_input.line_color_normal = _C["text_lo"][:3] + [0.5]

        input_card.add_widget(self.question_input)

        # botões de ação
        btn_row = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(38),
            spacing=dp(8),
        )
        self.ask_btn = _CyberButton(
            text="⟳  ANALISAR",
            md_bg_color=_C["primary"][:3] + [0.18],
            border_color=_C["primary"],
            text_color=_C["primary"],
            on_release=self._on_ask,
        )
        self.quick_btn = _CyberButton(
            text="≡  QUERIES",
            md_bg_color=_C["accent"][:3] + [0.12],
            border_color=_C["accent"],
            text_color=_C["accent"],
            on_release=self._open_quick_questions_menu,
        )
        self.clear_btn = _CyberButton(
            text="✕  LIMPAR",
            md_bg_color=[0, 0, 0, 0],
            border_color=_C["text_lo"],
            text_color=_C["text_lo"],
            on_release=self._on_clear,
        )
        btn_row.add_widget(self.ask_btn)
        btn_row.add_widget(self.quick_btn)
        btn_row.add_widget(self.clear_btn)
        input_card.add_widget(btn_row)
        card.add_widget(input_card)

        # ── RESPONSE AREA ───────────────────────────────────────────────────
        self.response_container = MDBoxLayout(
            orientation="vertical",
            spacing=dp(8),
            adaptive_height=True,
            padding=[0, dp(4), 0, dp(4)],
        )
        self.response_scroll = MDScrollView(do_scroll_x=False)
        self.response_scroll.add_widget(self.response_container)
        card.add_widget(self.response_scroll)

        # ── RODAPÉ ─────────────────────────────────────────────────────────
        footer = MDLabel(
            text="DADOS LOCAIS  ·  IA API OPCIONAL  ·  ENCRIPTADO",
            font_size="9sp",
            theme_text_color="Custom",
            text_color=_C["text_lo"],
            halign="center",
            size_hint_y=None,
            height=dp(18),
        )
        card.add_widget(footer)

        fl.add_widget(self._grid_bg2)
        fl.add_widget(card)
        return fl

    def _sync_input_border(self, widget, *_):
        self._input_border.rounded_rectangle = (
            widget.x, widget.y, widget.width, widget.height, dp(10)
        )

    # ── BOOT SEQUENCE ────────────────────────────────────────────────────────
    def _run_boot_sequence(self):
        self.response_container.clear_widgets()
        self._scan_bar.start()
        self._blink_t = 0.0
        self._boot_idx = 0
        self._boot_lines = []
        Clock.schedule_once(self._boot_next, 0.1)

    def _boot_next(self, *_):
        if self._boot_idx >= len(self._boot_messages):
            Clock.schedule_once(self._boot_done, 0.4)
            return
        msg = self._boot_messages[self._boot_idx]
        lbl = _TypewriterLabel(
            full_text=f"  {msg}",
            font_size="11sp",
            theme_text_color="Custom",
            text_color=_C["primary"] if self._boot_idx < 3 else _C["accent"],
            size_hint_y=None,
            height=dp(20),
            halign="left",
        )
        self.response_container.add_widget(lbl)
        lbl.start()
        self._boot_lines.append(lbl)
        self._boot_idx += 1
        Clock.schedule_once(self._boot_next, 0.5)

    def _boot_done(self, *_):
        self._scan_bar.stop()
        self._set_status("● PRONTO")
        # limpa e mostra prompt final
        Clock.schedule_once(self._render_ready, 0.3)

    def _render_ready(self, *_):
        self.response_container.clear_widgets()
        self.response_container.add_widget(
            _TerminalLine("  › Aguardando input do operador...", color=_C["text_mid"])
        )
        self.response_container.add_widget(
            _TerminalLine("  › Use 'ANALISAR' ou selecione uma query pré-definida.", color=_C["text_lo"])
        )

    # ── STATUS ───────────────────────────────────────────────────────────────
    def _set_status(self, text, color=None):
        self._status_label.text = text
        self._status_label.text_color = color or _C["accent"]

    # ── BUSY ─────────────────────────────────────────────────────────────────
    def _set_busy(self, busy):
        self._busy = busy
        self.ask_btn.disabled = busy
        self.clear_btn.disabled = busy
        self.quick_btn.disabled = busy
        self.ask_btn.btn_text = "⟳  PROCESSANDO..." if busy else "⟳  ANALISAR"
        if busy:
            self._scan_bar.start()
            self._set_status("● ANALISANDO...", _C["warn"])
        else:
            self._scan_bar.stop()
            self._set_status("● PRONTO", _C["primary"])

    # ── ASK ──────────────────────────────────────────────────────────────────
    def _on_ask(self, *_):
        if self._busy:
            return
        question = (self.question_input.text or "").strip()
        if not question:
            self._render_error("ERRO: Nenhuma query detectada.")
            return
        self._remember_question(question)
        use_api = bool(can_use_ai_api())
        self._set_busy(True)
        self.response_container.clear_widgets()
        self.response_container.add_widget(
            _TerminalLine("  › Processando query...", color=_C["warn"])
        )
        Thread(
            target=self._run_analysis_worker,
            args=(question, use_api),
            daemon=True,
        ).start()

    def _on_clear(self, *_):
        self.question_input.text = ""
        self._render_ready(None)

    def _open_quick_questions_menu(self, caller):
        if self._busy:
            return
        if self._quick_menu:
            self._quick_menu.dismiss()
            self._quick_menu = None
        questions = self._build_dynamic_quick_questions()
        items = [
            {"text": q, "on_release": (lambda q=q: self._select_quick_question(q))}
            for q in questions
        ]
        self._quick_menu = MDDropdownMenu(
            caller=caller,
            items=items,
            width_mult=7,
            max_height=dp(360),
            position="bottom",
            hor_growth="right",
        )
        self._quick_menu.open()

    def _select_quick_question(self, question):
        if self._quick_menu:
            self._quick_menu.dismiss()
            self._quick_menu = None
        self.question_input.text = question
        self._on_ask()

    # ── WORKER ───────────────────────────────────────────────────────────────
    def _run_analysis_worker(self, question, use_api):
        try:
            result = answer_management_question(
                question, db=self.db, use_api=use_api, lookback_days=30,
            )
            Clock.schedule_once(lambda dt: self._render_result(result), 0)
        except Exception as exc:
            Clock.schedule_once(
                lambda dt: self._render_error(f"FALHA DE SISTEMA: {exc}"), 0
            )

    # ── RENDER RESULT ────────────────────────────────────────────────────────
    def _extract_primary_answer_lines(self, result):
        api_error = str(result.get("api_error", "") or "").strip()
        sections = result.get("sections") or []
        if not api_error:
            for section in sections:
                if str(section.get("title", "")).strip().lower() == "explicacao avancada (api)":
                    lines = [str(i).strip() for i in (section.get("lines") or []) if str(i).strip()]
                    if lines:
                        return lines
        for section in sections:
            if str(section.get("title", "")).strip().lower() == "resposta direta":
                lines = [str(i).strip() for i in (section.get("lines") or []) if str(i).strip()]
                if lines:
                    return lines
        for section in sections:
            lines = [str(i).strip() for i in (section.get("lines") or []) if str(i).strip()]
            if lines:
                return lines
        if api_error:
            return [api_error]
        summary = str(result.get("summary", "") or "").strip()
        return [summary] if summary else ["Sem resposta disponivel."]

    def _render_result(self, result):
        self._set_busy(False)
        self.response_container.clear_widgets()

        lines = self._extract_primary_answer_lines(result)
        text = str(lines[0]).strip() if lines else "Sem resposta."

        # Card de resposta com typewriter
        resp_card = _ResponseCard(text)
        self.response_container.add_widget(resp_card)

        # linhas adicionais
        for extra in lines[1:4]:
            self.response_container.add_widget(
                _TerminalLine(f"  › {extra}", color=_C["text_mid"])
            )

    def _render_error(self, message):
        self._set_busy(False)
        self.response_container.clear_widgets()
        self.response_container.add_widget(
            _TerminalLine(f"  ✕ {message}", color=_C["danger"])
        )

    # ── QUICK Q HELPERS ──────────────────────────────────────────────────────
    def _safe_product_name(self, value, max_chars=34):
        text = str(value or "").strip() or "Produto"
        return text if len(text) <= max_chars else f"{text[:max_chars-3].rstrip()}..."

    def _remember_question(self, question):
        q = str(question or "").strip()
        if not q:
            return
        dedup = [q] + [i for i in self._recent_questions if i.strip().lower() != q.lower()]
        self._recent_questions = dedup[:6]

    def _build_dynamic_quick_questions(self):
        questions = list(self._recent_questions)
        try:
            insights = build_admin_insights(self.db)
        except Exception:
            insights = {}
        low_stock = insights.get("low_stock") or []
        exp7 = insights.get("expiring_7") or []
        exp15 = insights.get("expiring_15") or []
        neg_profit = insights.get("negative_profit") or []

        if low_stock:
            fn = self._safe_product_name(low_stock[0][0] if low_stock[0] else "Produto")
            questions += [f"{fn} esta com risco de ruptura? O que fazer?",
                          "Quais produtos estao com stock baixo agora?"]
        if exp7:
            fn = self._safe_product_name(exp7[0][0] if exp7[0] else "Produto")
            questions += [f"{fn} vence em breve. Acao prioritaria?",
                          "Quais produtos vencem nos proximos 7 dias?"]
        elif exp15:
            questions.append("Quais produtos vencem nos proximos 15 dias?")
        if neg_profit:
            fn = self._safe_product_name(neg_profit[0][0] if neg_profit[0] else "Produto")
            questions += [f"{fn} esta com margem negativa? O que ajustar?"]
        if low_stock or exp7 or exp15:
            questions.append("Qual alerta mais critico de hoje e qual acao imediata?")
        for q in self._default_quick_questions:
            questions.append(q)

        unique, seen = [], set()
        for q in questions:
            k = str(q).strip().lower()
            if k and k not in seen:
                seen.add(k)
                unique.append(str(q).strip())
        return unique[:12]

    def on_dismiss(self):
        if self._quick_menu:
            self._quick_menu.dismiss()
            self._quick_menu = None
        return super().on_dismiss()


# ─── COMPONENTES AUXILIARES ──────────────────────────────────────────────────
class _TerminalLine(MDLabel):
    def __init__(self, text="", color=None, **kwargs):
        super().__init__(
            text=text,
            font_size="11sp",
            theme_text_color="Custom",
            text_color=color or _C["text_mid"],
            size_hint_y=None,
            height=dp(20),
            halign="left",
            **kwargs,
        )


class _ResponseCard(MDCard):
    """Card de resposta com typewriter e borda primária."""

    def __init__(self, text, **kwargs):
        super().__init__(
            orientation="vertical",
            size_hint_y=None,
            padding=[dp(14), dp(12), dp(14), dp(12)],
            radius=[dp(10)],
            md_bg_color=_C["panel"],
            elevation=0,
            **kwargs,
        )
        with self.canvas.before:
            Color(*_C["primary"][:3], 0.4)
            self._border = Line(rounded_rectangle=(0, 0, 1, 1, dp(10)), width=dp(0.9))
        self.bind(pos=self._sync, size=self._sync)

        prefix = MDLabel(
            text="  ▸ RESPOSTA DO SISTEMA",
            font_size="9sp",
            theme_text_color="Custom",
            text_color=_C["primary"],
            size_hint_y=None,
            height=dp(16),
            bold=True,
        )
        self.add_widget(prefix)

        self._body = _TypewriterLabel(
            full_text=text,
            font_size="12.5sp",
            theme_text_color="Custom",
            text_color=_C["text_hi"],
            size_hint_y=None,
            halign="left",
            valign="top",
        )

        def _reflow(*_):
            w = max(dp(160), self._body.width)
            self._body.text_size = (w, None)
            self._body.texture_update()
            self._body.height = self._body.texture_size[1] + dp(4)
            self.height = prefix.height + self._body.height + dp(28)

        self._body.bind(width=_reflow)
        Clock.schedule_once(lambda dt: _reflow(), 0)
        self.add_widget(self._body)
        Clock.schedule_once(lambda dt: self._body.start(delay=0.1), 0)

    def _sync(self, *_):
        self._border.rounded_rectangle = (self.x, self.y, self.width, self.height, dp(10))


class _OrbWidget(Widget):
    """Orbe pulsante de IA."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._t = 0.0
        self._ev = Clock.schedule_interval(self._tick, 1 / 30)
        self.bind(pos=self._draw, size=self._draw)

    def _tick(self, dt):
        self._t += dt
        self._draw()

    def _draw(self, *_):
        self.canvas.clear()
        cx = self.x + self.width / 2
        cy = self.y + self.height / 2
        with self.canvas:
            # glow externo
            pulse = 0.5 + 0.5 * abs(math.sin(self._t * 2.0))
            Color(*_C["primary"][:3], 0.08 + 0.12 * pulse)
            d_outer = self.width * 1.4
            Ellipse(pos=(cx - d_outer / 2, cy - d_outer / 2), size=(d_outer, d_outer))

            # glow médio
            Color(*_C["accent"][:3], 0.10 + 0.08 * pulse)
            d_mid = self.width * 0.9
            Ellipse(pos=(cx - d_mid / 2, cy - d_mid / 2), size=(d_mid, d_mid))

            # núcleo
            r = 0.05 + 0.08 * math.sin(self._t * 0.8)
            g = 0.70 + 0.15 * math.sin(self._t * 0.5)
            b = 0.65 + 0.15 * math.sin(self._t * 1.2)
            Color(r, g, b, 0.9)
            d_core = self.width * 0.55
            Ellipse(pos=(cx - d_core / 2, cy - d_core / 2), size=(d_core, d_core))

            # brilho interno
            Color(1, 1, 1, 0.4 + 0.2 * pulse)
            d_hi = self.width * 0.18
            Ellipse(
                pos=(cx - d_hi / 2 + d_core * 0.12, cy - d_hi / 2 + d_core * 0.12),
                size=(d_hi, d_hi),
            )

    def on_parent(self, inst, parent):
        if not parent and self._ev:
            self._ev.cancel()


class _CyberButton(MDCard):
    """Botão estilo cyber com borda colorida e hover."""

    def __init__(self, text="", md_bg_color=None, border_color=None, text_color=None, on_release=None, **kwargs):
        super().__init__(
            orientation="vertical",
            size_hint_y=None,
            height=dp(34),
            padding=[dp(8), 0, dp(8), 0],
            radius=[dp(6)],
            md_bg_color=md_bg_color or [0, 0, 0, 0],
            elevation=0,
            ripple_behavior=True,
            **kwargs,
        )
        self.btn_text = text
        self._border_color = border_color or _C["primary"]
        self._text_color = text_color or _C["text_hi"]
        self._on_release_cb = on_release

        with self.canvas.before:
            self._bc = Color(*self._border_color)
            self._bl = Line(rounded_rectangle=(0, 0, 1, 1, dp(6)), width=dp(0.9))

        self.bind(pos=self._sync, size=self._sync)
        self.bind(on_release=self._fire)

        self._lbl = MDLabel(
            text=text,
            font_size="11sp",
            theme_text_color="Custom",
            text_color=self._text_color,
            halign="center",
            valign="middle",
            bold=True,
        )
        self.add_widget(self._lbl)

    def _sync(self, *_):
        self._bl.rounded_rectangle = (self.x, self.y, self.width, self.height, dp(6))

    def _fire(self, *_):
        if self._on_release_cb:
            self._on_release_cb(self)

    @property
    def btn_text(self):
        return self._lbl.text if hasattr(self, "_lbl") else ""

    @btn_text.setter
    def btn_text(self, val):
        if hasattr(self, "_lbl"):
            self._lbl.text = val


# ─── ENTRY POINT ─────────────────────────────────────────────────────────────
def open_management_ai_assistant(db=None, ai_name=None):
    app = App.get_running_app()
    resolved_name = ai_name or getattr(app, "assistant_name", "JoeIA")
    popup = ManagementAIAssistantPopup(db=db, ai_name=resolved_name)
    popup.open()
    return popup