from datetime import datetime, timedelta
from collections import deque
from pathlib import Path
from threading import Thread
from time import perf_counter
from contextlib import nullcontext

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, RoundedRectangle
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.properties import BooleanProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.modalview import ModalView
from kivy.uix.widget import Widget
from kivy.uix.image import Image
from ui.components.native_widgets import (
    NativeBoxLayout, NativeButton, NativeCard, NativeDialog, NativeFlatButton,
    NativeLabel, NativeScreen,
)
from database.provider import get_db
from utils.screens.reports_screen import DateRangeDialog
from utils.config.paths import resolve_path, temp_path


Builder.load_file(str(Path(__file__).with_name("losses_history_screen.kv")))


def _theme_color(name, fallback):
    app = App.get_running_app()
    tokens = getattr(app, "theme_tokens", {}) if app else {}
    return tokens.get(name, fallback)


def _popup_paint(widget, color, radius=12):
    with widget.canvas.before:
        Color(rgba=color)
        rect = RoundedRectangle(pos=widget.pos, size=widget.size, radius=[dp(radius)])
    def _sync(*_):
        rect.pos = widget.pos
        rect.size = widget.size
    widget.bind(pos=_sync, size=_sync)


def _popup_label(text, size=13, color=(0.95, 0.96, 0.98, 1), bold=False, **kwargs):
    return NativeLabel(
        text=text,
        font_size=dp(size),
        bold=bold,
        theme_text_color="Custom",
        text_color=color,
        **kwargs,
    )


def _popup_button(text, color, width=140, height=40, font_size=12):
    btn = NativeButton(
        text=text,
        size_hint=(None, None),
        size=(dp(width), dp(height)),
        font_size=dp(font_size),
        md_bg_color=color,
        elevation=0,
    )
    return btn


LOSS_LABELS = {
    "DAMAGE": "Danificado",
    "EXPIRED": "Expirado",
    "THEFT": "Roubo",
    "ADJUSTMENT": "Ajuste",
}


class LossesHistoryScreen(NativeScreen):
    ENTER_CACHE_SECONDS = 5
    compact_mode = BooleanProperty(False)

    def __init__(self, db=None, **kwargs):
        self.db = db or get_db()
        self.loss_report = None
        self.pdf_viewer = None
        self._render_ev = None
        self._pending_rows = deque()
        self._render_index = 0
        self._display_rows = []
        self._page_size = 60
        self._current_page = 1
        self._load_token = 0
        self._render_token = 0
        self._row_theme = {}
        self._last_loaded_at = 0.0
        self._exporting_pdf = False
        self._evidence_popup = None
        self.back_target = "losses"
        super().__init__(**kwargs)
        self._layout_trigger = Clock.create_trigger(self._update_responsive_layout, 0)

    def _ensure_loss_report(self):
        if self.loss_report is None:
            from pdfs.loss_report import LossReport
            self.loss_report = LossReport()
        return self.loss_report

    def _ensure_pdf_viewer(self):
        if self.pdf_viewer is None:
            from pdfs.pdf_viewer import PDFViewer
            self.pdf_viewer = PDFViewer(error_callback=lambda msg: self._show_simple_dialog("Erro", msg))
        return self.pdf_viewer

    def on_enter(self):
        self.request_enter_refresh()

    def on_kv_post(self, base_widget):
        self._update_responsive_layout()

    def on_size(self, *args):
        self._layout_trigger()

    def request_enter_refresh(self, force=False, delay=0.05):
        stale = (perf_counter() - self._last_loaded_at) >= self.ENTER_CACHE_SECONDS
        if not force and self._display_rows and not stale:
            return
        Clock.schedule_once(lambda dt: self.load_losses_table(), delay)

    def go_back(self):
        if self.manager:
            target = self.back_target if getattr(self, "back_target", None) in self.manager.screen_names else "losses"
            self.manager.current = target

    def _set_header_state(self, widget, visible, size_hint_x):
        if widget is None:
            return
        widget.opacity = 1 if visible else 0
        widget.disabled = not visible
        widget.size_hint_x = size_hint_x

    def _update_responsive_layout(self, *_args):
        if not hasattr(self, "ids") or "header_date" not in self.ids:
            return
        width = self.width or dp(1200)
        compact = width < dp(1040)
        if compact != self.compact_mode:
            self.compact_mode = compact
            if self._display_rows:
                self._populate_losses_list(list(self._display_rows), already_aggregated=True)
        self._apply_header_layout()

    def _apply_header_layout(self):
        if not hasattr(self, "ids") or "header_date" not in self.ids:
            return
        if self.compact_mode:
            self.ids.header_date.size_hint_x = 0.17
            self.ids.header_product.size_hint_x = 0.36
            self.ids.header_type.size_hint_x = 0.16
            self.ids.header_qty.size_hint_x = 0.12
            self.ids.header_cost.size_hint_x = 0.12
            self._set_header_state(self.ids.header_user, False, 0)
            self._set_header_state(self.ids.header_evidence, True, 0.07)
        else:
            self.ids.header_date.size_hint_x = 0.14
            self.ids.header_product.size_hint_x = 0.30
            self.ids.header_type.size_hint_x = 0.14
            self.ids.header_qty.size_hint_x = 0.10
            self.ids.header_cost.size_hint_x = 0.12
            self._set_header_state(self.ids.header_user, True, 0.12)
            self._set_header_state(self.ids.header_evidence, True, 0.08)

    def load_losses_table(self, *args):
        if not hasattr(self, "ids") or "losses_list" not in self.ids:
            return

        self._load_token += 1
        token = self._load_token

        if "load_more_btn" in self.ids:
            self.ids.load_more_btn.disabled = True

        end_dt = datetime.now()
        start_dt = end_dt - timedelta(days=365)
        connection_factory = getattr(self.db, "background_connection", None)
        connection = connection_factory() if callable(connection_factory) else nullcontext(self.db)

        def worker():
            try:
                with connection as db:
                    rows = db.get_loss_history_items(start_dt, end_dt, limit=300) or []
            except Exception as exc:
                print(f"Erro ao carregar perdas: {exc}")
                rows = []
            Clock.schedule_once(
                lambda dt, data=rows, tok=token: self._apply_loaded_losses(data, tok),
                0
            )

        Thread(target=worker, daemon=True).start()

    def _apply_loaded_losses(self, rows, token):
        if token != self._load_token:
            return
        self._last_loaded_at = perf_counter()
        self._populate_losses_list(rows, already_aggregated=True)

    def _populate_losses_list(self, rows, already_aggregated=False):
        self.ids.losses_list.clear_widgets()
        rows = rows or []
        if not already_aggregated:
            rows = self._aggregate_loss_rows(rows)

        if not rows:
            self.ids.losses_empty.opacity = 1
            self.ids.losses_empty.height = dp(80)
            self.ids.losses_empty.disabled = False
            self._stop_batch_render()
            if "load_more_btn" in self.ids:
                self.ids.load_more_btn.opacity = 0
                self.ids.load_more_btn.disabled = True
            return

        self.ids.losses_empty.opacity = 0
        self.ids.losses_empty.height = 0
        self.ids.losses_empty.disabled = True

        self._display_rows = rows
        self._current_page = 1
        self._render_page(reset=True)

    def _stop_batch_render(self):
        if self._render_ev:
            Clock.unschedule(self._render_ev)
            self._render_ev = None
        self._render_token += 1
        self._pending_rows = deque()

    def _render_page(self, reset=False):
        if not self._display_rows:
            return
        if reset:
            start = 0
            self._current_page = 1
        else:
            start = (self._current_page - 1) * self._page_size
        end = self._current_page * self._page_size
        rows_to_render = self._display_rows[start:end]
        self._start_batch_render(rows_to_render, reset=reset)
        has_more = end < len(self._display_rows)
        if "load_more_btn" in self.ids:
            self.ids.load_more_btn.opacity = 1 if has_more else 0
            self.ids.load_more_btn.disabled = not has_more

    def load_more_rows(self):
        if not self._display_rows:
            return
        end = self._current_page * self._page_size
        if end >= len(self._display_rows):
            return
        self._current_page += 1
        self._render_page(reset=False)

    def _start_batch_render(self, rows, reset=False):
        self._stop_batch_render()
        self._pending_rows = deque(rows)
        if reset:
            self.ids.losses_list.clear_widgets()
            self._render_index = 0
        if not self._pending_rows:
            return
        self._row_theme = {
            "bg_even": _theme_color("surface_alt", [0.14, 0.16, 0.20, 1]),
            "bg_odd": _theme_color("card", [0.16, 0.19, 0.24, 1]),
            "text_primary": _theme_color("text_primary", [0.95, 0.96, 0.98, 1]),
            "text_secondary": _theme_color("text_secondary", [0.55, 0.60, 0.66, 1]),
            "danger": _theme_color("danger", [0.85, 0.3, 0.3, 1]),
        }
        token = self._render_token
        self._render_ev = Clock.schedule_interval(lambda dt, tok=token: self._render_next_batch(dt, tok), 0)

    def _render_next_batch(self, dt, token):
        if token != self._render_token:
            return False
        batch_size = 35
        for _ in range(min(batch_size, len(self._pending_rows))):
            row = self._pending_rows.popleft()
            self.ids.losses_list.add_widget(self._create_loss_row(row, self._render_index, self._row_theme))
            self._render_index += 1
        if not self._pending_rows:
            self._render_ev = None
            return False
        return True

    def _aggregate_loss_rows(self, rows):
        grouped = {}
        for row in rows:
            created_at, product, movement_type, qty, unit, total_cost, total_price, reason, created_by = row
            product_name = (product or "Produto").strip()
            key = product_name.lower()
            qty_val = float(qty or 0)
            cost_val = float(total_cost or 0)

            if key not in grouped:
                grouped[key] = {
                    "product": product_name,
                    "qty": 0.0,
                    "total_cost": 0.0,
                    "unit": unit,
                    "types": set(),
                    "users": set(),
                    "latest_date": created_at,
                    "latest_dt": self._safe_parse_date(created_at),
                }

            g = grouped[key]
            g["qty"] += qty_val
            g["total_cost"] += cost_val
            if unit and not g["unit"]:
                g["unit"] = unit
            g["types"].add(movement_type)
            g["users"].add(created_by or "N/A")

            dt = self._safe_parse_date(created_at)
            if dt and (g["latest_dt"] is None or dt > g["latest_dt"]):
                g["latest_dt"] = dt
                g["latest_date"] = created_at

        aggregated = []
        for g in grouped.values():
            types = list(g["types"])
            type_label = types[0] if len(types) == 1 else "Varios"
            users = list(g["users"])
            user_label = users[0] if len(users) == 1 else "Varios"
            aggregated.append((
                g["latest_date"],
                g["product"],
                type_label,
                g["qty"],
                g["unit"] or "UN",
                g["total_cost"],
                0,
                "",
                user_label,
            ))

        aggregated.sort(key=lambda r: self._safe_parse_date(r[0]) or datetime.min, reverse=True)
        return aggregated

    def _safe_parse_date(self, value):
        try:
            return datetime.fromisoformat(str(value))
        except Exception:
            return None

    def _create_loss_row(self, row, index, theme=None):
        if isinstance(row, dict):
            created_at = row.get("created_at")
            product = row.get("product")
            movement_type = row.get("movement_type")
            qty = row.get("qty")
            unit = row.get("unit")
            total_cost = row.get("total_cost")
            reason = row.get("reason")
            created_by = row.get("created_by")
            evidence_id = row.get("evidence_id")
            note = row.get("note")
        else:
            row = tuple(row)
            if len(row) < 10:
                row = row + (None,) * (10 - len(row))
            (
                created_at, product, movement_type, qty, unit,
                total_cost, total_price, reason, created_by, evidence_id,
            ) = row[:10]
            note = None
        theme = theme or {
            "bg_even": _theme_color("surface_alt", [0.14, 0.16, 0.20, 1]),
            "bg_odd": _theme_color("card", [0.16, 0.19, 0.24, 1]),
            "text_primary": _theme_color("text_primary", [0.95, 0.96, 0.98, 1]),
            "text_secondary": _theme_color("text_secondary", [0.55, 0.60, 0.66, 1]),
            "danger": _theme_color("danger", [0.85, 0.3, 0.3, 1]),
        }
        bg = theme["bg_even"] if index % 2 == 0 else theme["bg_odd"]
        text_primary = theme["text_primary"]
        text_secondary = theme["text_secondary"]

        try:
            dt = datetime.fromisoformat(str(created_at))
            date_str = dt.strftime("%d/%m/%y\n%H:%M")
        except Exception:
            date_str = str(created_at)[:16]

        label = LOSS_LABELS.get(movement_type, movement_type)
        try:
            qty_val = float(qty)
            if unit == "UN" and qty_val.is_integer():
                qty_str = f"{int(qty_val)} {unit}"
            else:
                qty_str = f"{qty_val:.2f} {unit}"
        except Exception:
            qty_str = f"{qty} {unit}"
        cost_str = f"{float(total_cost or 0):.2f} MZN"
        if self.compact_mode:
            date_hint, product_hint, type_hint, qty_hint, cost_hint, evidence_hint = 0.17, 0.36, 0.16, 0.12, 0.12, 0.07
        else:
            date_hint, product_hint, type_hint, qty_hint, cost_hint, user_hint, evidence_hint = 0.14, 0.30, 0.14, 0.10, 0.12, 0.12, 0.08

        line = NativeCard(
            size_hint_y=None,
            height=dp(48),
            padding=[dp(16), dp(8)],
            spacing=dp(0),
            md_bg_color=bg,
        )

        line.add_widget(NativeLabel(
            text=date_str, size_hint_x=date_hint, halign="left", font_size=dp(10),
            theme_text_color="Custom", text_color=text_secondary,
        ))
        line.add_widget(NativeLabel(
            text=str(product), size_hint_x=product_hint, halign="left", font_size=dp(11),
            theme_text_color="Custom", text_color=text_primary, shorten=True, shorten_from="right",
        ))
        line.add_widget(NativeLabel(
            text=label, size_hint_x=type_hint, halign="center", font_size=dp(11),
            theme_text_color="Custom", text_color=text_secondary,
        ))
        line.add_widget(NativeLabel(
            text=qty_str, size_hint_x=qty_hint, halign="center", font_size=dp(11),
            theme_text_color="Custom", text_color=text_secondary,
        ))
        line.add_widget(NativeLabel(
            text=cost_str, size_hint_x=cost_hint, halign="right", font_size=dp(11),
            theme_text_color="Custom", text_color=theme["danger"],
        ))
        if not self.compact_mode:
            line.add_widget(NativeLabel(
                text=created_by or "N/A", size_hint_x=user_hint, halign="right", font_size=dp(11),
                theme_text_color="Custom", text_color=text_secondary, shorten=True, shorten_from="right",
            ))

        if movement_type == "DAMAGE" and evidence_id:
            evidence_payload = {
                "evidence_id": evidence_id,
                "reason": reason,
                "note": note,
            }
            line.add_widget(NativeFlatButton(
                text="FOTO",
                size_hint_x=evidence_hint,
                font_size=dp(10),
                on_release=lambda _x, item=evidence_payload: self.open_damage_evidence(item),
            ))
        else:
            line.add_widget(Widget(size_hint_x=evidence_hint))

        container = NativeBoxLayout(
            orientation="vertical", size_hint_y=None, height=dp(49), spacing=0,
        )
        container.add_widget(line)
        container.add_widget(Widget(size_hint_y=None, height=dp(1)))
        return container

    def open_damage_evidence(self, row):
        """Abre a foto anexada sem expor caminhos privados no historico."""
        evidence_id = (row or {}).get("evidence_id") if isinstance(row, dict) else None
        if not evidence_id:
            self._show_simple_dialog("Foto", "Esta perda nao possui foto anexada.")
            return

        def worker():
            try:
                evidence = self.db.get_damage_evidence(evidence_id)
                if not evidence:
                    return {"ok": False, "message": "Evidencia nao encontrada ou sem permissao."}
                relative_path = self.db.get_damage_evidence_storage_path(evidence_id)
                data = resolve_path(relative_path).read_bytes() if relative_path else b""
                mime_type = evidence.get("mime_type")
                if not data:
                    return {"ok": False, "message": "A imagem da evidencia ja nao esta disponivel."}
                suffix = {"image/png": ".png", "image/webp": ".webp"}.get(str(mime_type), ".jpg")
                preview_path = temp_path("evidence-previews", f"{evidence_id}{suffix}")
                preview_path.parent.mkdir(parents=True, exist_ok=True)
                preview_path.write_bytes(data)
                return {
                    "ok": True,
                    "evidence": evidence,
                    "evidence_id": evidence_id,
                    "preview_path": str(preview_path),
                }
            except Exception as exc:
                return {"ok": False, "message": f"Nao foi possivel abrir a evidencia: {exc}"}

        def finish():
            result = worker()
            Clock.schedule_once(lambda _dt, payload=result: self._show_damage_evidence(payload, row), 0)

        Thread(target=finish, daemon=True).start()

    def _show_damage_evidence(self, result, row):
        if not result.get("ok"):
            self._show_simple_dialog("Evidencia", result.get("message") or "Falha ao abrir evidencia.")
            return

        BG = (0.12, 0.14, 0.18, 1)
        CARD = (0.16, 0.19, 0.24, 1)
        TXT = (0.95, 0.96, 0.98, 1)
        MUTED = (0.62, 0.67, 0.75, 1)
        DANGER = (0.85, 0.22, 0.24, 1)
        GRAY = (0.28, 0.32, 0.38, 1)
        PRIMARY = _theme_color("primary", (0.15, 0.48, 0.82, 1))

        evidence_id = result.get("evidence_id") or (row or {}).get("evidence_id")
        reason = str((row or {}).get("reason") or "—")
        note = str((row or {}).get("note") or "").strip()

        popup = ModalView(
            size_hint=(None, None),
            size=(min(Window.width * 0.9, dp(460)), min(Window.height * 0.82, dp(480))),
            background="",
            background_color=[0, 0, 0, 0],
            overlay_color=[0, 0, 0, 0.6],
            auto_dismiss=True,
        )
        root = BoxLayout(
            orientation="vertical",
            padding=[dp(16), dp(14)],
            spacing=dp(10),
        )
        _popup_paint(root, BG, radius=14)

        # Header
        header = BoxLayout(size_hint_y=None, height=dp(28), spacing=dp(8))
        header.add_widget(_popup_label("Foto do produto danificado", size=16, color=TXT, bold=True))
        root.add_widget(header)

        # Image card
        img_shell = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            height=dp(260),
            padding=dp(6),
        )
        _popup_paint(img_shell, CARD, radius=10)
        img = Image(
            source=result["preview_path"],
            allow_stretch=True,
            keep_ratio=True,
        )
        img_shell.add_widget(img)
        root.add_widget(img_shell)

        # Meta
        root.add_widget(_popup_label(
            f"Motivo: {reason}",
            size=12, color=MUTED,
            size_hint_y=None, height=dp(20),
        ))
        if note:
            root.add_widget(_popup_label(
                f"Observacao: {note}",
                size=12, color=MUTED,
                size_hint_y=None, height=dp(20),
            ))

        # Actions
        actions = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(10))
        close_btn = _popup_button("FECHAR", GRAY, width=120, height=40, font_size=12)
        delete_btn = _popup_button("ELIMINAR FOTO", DANGER, width=150, height=40, font_size=12)
        actions.add_widget(close_btn)
        actions.add_widget(Widget())
        actions.add_widget(delete_btn)
        root.add_widget(actions)

        close_btn.bind(on_release=lambda *_: popup.dismiss())
        delete_btn.bind(
            on_release=lambda *_: self._confirm_delete_evidence(popup, evidence_id)
        )

        popup.add_widget(root)
        self._evidence_popup = popup
        popup.open()

    def _confirm_delete_evidence(self, parent_popup, evidence_id):
        """Confirmacao antes de eliminar a foto."""
        BG = (0.12, 0.14, 0.18, 1)
        TXT = (0.95, 0.96, 0.98, 1)
        MUTED = (0.62, 0.67, 0.75, 1)
        DANGER = (0.85, 0.22, 0.24, 1)
        GRAY = (0.28, 0.32, 0.38, 1)

        confirm = ModalView(
            size_hint=(None, None),
            size=(min(Window.width * 0.85, dp(380)), dp(200)),
            background="",
            background_color=[0, 0, 0, 0],
            overlay_color=[0, 0, 0, 0.55],
            auto_dismiss=True,
        )
        root = BoxLayout(orientation="vertical", padding=[dp(16), dp(14)], spacing=dp(10))
        _popup_paint(root, BG, radius=14)
        root.add_widget(_popup_label("Eliminar foto?", size=16, color=TXT, bold=True,
                                     size_hint_y=None, height=dp(24)))
        root.add_widget(_popup_label(
            "A imagem sera apagada permanentemente da base de dados e do disco.",
            size=12, color=MUTED, size_hint_y=None, height=dp(48),
        ))
        actions = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(10))
        cancel_btn = _popup_button("CANCELAR", GRAY, width=120, height=40, font_size=12)
        ok_btn = _popup_button("ELIMINAR", DANGER, width=120, height=40, font_size=12)
        actions.add_widget(cancel_btn)
        actions.add_widget(Widget())
        actions.add_widget(ok_btn)
        root.add_widget(actions)
        cancel_btn.bind(on_release=lambda *_: confirm.dismiss())
        ok_btn.bind(on_release=lambda *_: self._execute_delete_evidence(confirm, parent_popup, evidence_id))
        confirm.add_widget(root)
        confirm.open()

    def _execute_delete_evidence(self, confirm_popup, parent_popup, evidence_id):
        try:
            confirm_popup.dismiss()
        except Exception:
            pass

        def worker():
            fn = getattr(self.db, "delete_damage_evidence_force", None)
            if callable(fn):
                return fn(evidence_id)
            # fallback: try unbound delete
            fn2 = getattr(self.db, "delete_damage_evidence", None)
            if callable(fn2):
                path = fn2(evidence_id)
                return {"ok": bool(path), "message": None if path else "Nao foi possivel eliminar."}
            return {"ok": False, "message": "Metodo de eliminacao indisponivel na BD."}

        def finish():
            result = worker()
            Clock.schedule_once(lambda _dt, r=result: self._on_evidence_deleted(r, parent_popup), 0)

        Thread(target=finish, daemon=True).start()

    def _on_evidence_deleted(self, result, parent_popup):
        try:
            if parent_popup:
                parent_popup.dismiss()
        except Exception:
            pass
        if not (result or {}).get("ok"):
            self._show_simple_dialog(
                "Erro",
                (result or {}).get("message") or "Nao foi possivel eliminar a foto.",
            )
            return
        self._show_simple_dialog("Concluido", "Foto eliminada com sucesso.")
        self.load_losses_table()

    def export_losses_pdf(self, *args):
        dialog = DateRangeDialog(database=self.db, callback=self._generate_losses_pdf)
        dialog.open()

    def _generate_losses_pdf(self, start_dt, end_dt):
        if self._exporting_pdf:
            self._show_simple_dialog("Aguarde", "Ja existe uma exportacao de perdas em andamento.")
            return

        self._exporting_pdf = True

        def worker():
            result = {"ok": True, "path": None, "error": None}
            try:
                metrics = self.db.calculate_loss_metrics(start_dt, end_dt) or {}
                records = self.db.get_loss_records(start_dt, end_dt, limit=300)
                data = {"metrics": metrics, "records": records}
                filters = {
                    "start_date": start_dt,
                    "end_date": end_dt,
                    "product": "Todos os Produtos",
                    "category": "Todas as Categorias",
                }
                pdf_path = self._ensure_loss_report().generate(data, filters)
                result["path"] = str(pdf_path)
            except Exception as exc:
                result["ok"] = False
                result["error"] = str(exc)

            Clock.schedule_once(lambda _dt, payload=result: self._finish_losses_pdf_export(payload), 0)

        Thread(target=worker, daemon=True).start()

    def _finish_losses_pdf_export(self, result):
        self._exporting_pdf = False
        if not (result or {}).get("ok"):
            self._show_simple_dialog(
                "Erro",
                f"Falha ao gerar PDF de perdas: {(result or {}).get('error') or 'erro desconhecido'}",
            )
            return
        self._show_pdf_success((result or {}).get("path"))

    def _show_pdf_success(self, pdf_path):
        dialog = NativeDialog(
            title="PDF Gerado",
            text=f"Arquivo criado em:\n{pdf_path}",
            buttons=[
                NativeFlatButton(text="FECHAR", on_release=lambda x: dialog.dismiss()),
                NativeButton(
                    text="ABRIR",
                    md_bg_color=_theme_color("info", (0.15, 0.45, 0.75, 1)),
                    on_release=lambda x: self._open_pdf(dialog, pdf_path),
                ),
            ],
        )
        dialog.open()

    def _open_pdf(self, dialog, pdf_path):
        dialog.dismiss()
        self._ensure_pdf_viewer().view_pdf(pdf_path)

    def _show_simple_dialog(self, title, message):
        dialog = NativeDialog(
            title=title,
            text=message,
            buttons=[NativeFlatButton(text="OK", on_release=lambda x: dialog.dismiss())],
        )
        dialog.open()
