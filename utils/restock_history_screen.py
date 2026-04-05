from datetime import datetime, timedelta
from collections import deque
from threading import Thread
from time import perf_counter

from kivy.app import App
from kivy.clock import Clock
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.properties import BooleanProperty
from kivy.uix.widget import Widget
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen

from database.provider import get_db


Builder.load_file("utils/restock_history_screen.kv")


def _theme_color(name, fallback):
    app = App.get_running_app()
    tokens = getattr(app, "theme_tokens", {}) if app else {}
    return tokens.get(name, fallback)


class RestockHistoryScreen(MDScreen):
    ENTER_CACHE_SECONDS = 5
    compact_mode = BooleanProperty(False)

    def __init__(self, db=None, **kwargs):
        super().__init__(**kwargs)
        self.db = db or get_db()
        self._render_ev = None
        self._pending_rows = deque()
        self._render_index = 0
        self._display_rows = []
        self._page_size = 60
        self._current_page = 1
        self._last_loaded_at = 0.0
        self._load_token = 0
        self.back_target = "restock"

    def on_kv_post(self, base_widget):
        self._update_responsive_layout()

    def on_enter(self):
        self.request_enter_refresh()

    def on_size(self, *args):
        Clock.schedule_once(lambda dt: self._update_responsive_layout(), 0)

    def request_enter_refresh(self, force=False, delay=0.05):
        stale = (perf_counter() - self._last_loaded_at) >= self.ENTER_CACHE_SECONDS
        if not force and self._display_rows and not stale:
            return
        Clock.schedule_once(lambda dt: self.load_restock_table(), delay)

    def go_back(self):
        if self.manager:
            target = self.back_target if getattr(self, "back_target", None) in self.manager.screen_names else "restock"
            self.manager.current = target

    def _set_header_state(self, widget, visible, size_hint_x):
        if widget is None:
            return
        widget.opacity = 1 if visible else 0
        widget.disabled = not visible
        widget.size_hint_x = size_hint_x

    def _update_responsive_layout(self):
        if not hasattr(self, "ids") or "header_date" not in self.ids:
            return
        width = self.width or dp(1200)
        compact = width < dp(1040)
        if compact != self.compact_mode:
            self.compact_mode = compact
            if self._display_rows:
                self._populate_restock_list(list(self._display_rows), already_aggregated=True)
        self._apply_header_layout()

    def _apply_header_layout(self):
        if not hasattr(self, "ids") or "header_date" not in self.ids:
            return
        if self.compact_mode:
            self.ids.header_date.size_hint_x = 0.18
            self.ids.header_product.size_hint_x = 0.42
            self.ids.header_qty.size_hint_x = 0.14
            self._set_header_state(self.ids.header_unit_cost, False, 0)
            self.ids.header_total.size_hint_x = 0.16
            self.ids.header_user.size_hint_x = 0.10
        else:
            self.ids.header_date.size_hint_x = 0.16
            self.ids.header_product.size_hint_x = 0.34
            self.ids.header_qty.size_hint_x = 0.10
            self._set_header_state(self.ids.header_unit_cost, True, 0.14)
            self.ids.header_total.size_hint_x = 0.14
            self.ids.header_user.size_hint_x = 0.12

    def load_restock_table(self, *args):
        if not hasattr(self, "ids") or "restock_list" not in self.ids:
            return

        self._load_token += 1
        token = self._load_token
        if "load_more_btn" in self.ids:
            self.ids.load_more_btn.disabled = True

        end_dt = datetime.now()
        start_dt = end_dt - timedelta(days=365)

        def worker():
            try:
                rows = self.db.get_restock_records(start_dt, end_dt, limit=300) or []
                aggregated = self._aggregate_restock_rows(rows)
            except Exception as exc:
                print(f"Erro ao carregar reposicoes: {exc}")
                aggregated = []
            Clock.schedule_once(
                lambda dt, data=aggregated, tok=token: self._apply_loaded_restock(data, tok),
                0,
            )

        Thread(target=worker, daemon=True).start()

    def _apply_loaded_restock(self, rows, token):
        if token != self._load_token:
            return
        self._last_loaded_at = perf_counter()
        self._populate_restock_list(rows, already_aggregated=True)

    def _populate_restock_list(self, rows, already_aggregated=False):
        self.ids.restock_list.clear_widgets()
        rows = rows or []
        if not already_aggregated:
            rows = self._aggregate_restock_rows(rows)

        if not rows:
            self.ids.restock_empty.opacity = 1
            self.ids.restock_empty.height = dp(80)
            self.ids.restock_empty.disabled = False
            if self._render_ev:
                Clock.unschedule(self._render_ev)
                self._render_ev = None
            self._pending_rows = deque()
            if "load_more_btn" in self.ids:
                self.ids.load_more_btn.opacity = 0
                self.ids.load_more_btn.disabled = True
            return

        self.ids.restock_empty.opacity = 0
        self.ids.restock_empty.height = 0
        self.ids.restock_empty.disabled = True

        self._display_rows = rows
        self._current_page = 1
        self._render_page(reset=True)

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
        if self._render_ev:
            Clock.unschedule(self._render_ev)
            self._render_ev = None
        self._pending_rows = deque(rows or [])
        if reset:
            self.ids.restock_list.clear_widgets()
            self._render_index = 0
        if not self._pending_rows:
            return
        self._render_ev = Clock.schedule_interval(self._render_next_batch, 0)

    def _render_next_batch(self, dt):
        batch_size = 30
        for _ in range(min(batch_size, len(self._pending_rows))):
            row = self._pending_rows.popleft()
            self.ids.restock_list.add_widget(self._create_restock_row(row, self._render_index))
            self._render_index += 1
        if not self._pending_rows:
            self._render_ev = None
            return False
        return True

    def _aggregate_restock_rows(self, rows):
        grouped = {}
        for row in rows:
            created_at, product, qty, unit, unit_cost, total_cost, created_by, note = row
            product_name = (product or "Produto").strip()
            key = product_name.lower()
            qty_val = float(qty or 0)
            total_val = float(total_cost or 0)

            if key not in grouped:
                grouped[key] = {
                    "product": product_name,
                    "qty": 0.0,
                    "total": 0.0,
                    "unit": unit,
                    "users": set(),
                    "latest_date": created_at,
                    "latest_dt": self._safe_parse_date(created_at),
                }

            g = grouped[key]
            g["qty"] += qty_val
            g["total"] += total_val
            if unit and not g["unit"]:
                g["unit"] = unit
            g["users"].add(created_by or "N/A")

            dt = self._safe_parse_date(created_at)
            if dt and (g["latest_dt"] is None or dt > g["latest_dt"]):
                g["latest_dt"] = dt
                g["latest_date"] = created_at

        aggregated = []
        for g in grouped.values():
            qty = g["qty"]
            total = g["total"]
            unit_cost = (total / qty) if qty else 0
            users = list(g["users"])
            user_label = users[0] if len(users) == 1 else "Varios"
            aggregated.append((
                g["latest_date"],
                g["product"],
                qty,
                g["unit"] or "UN",
                unit_cost,
                total,
                user_label,
                "",
            ))

        aggregated.sort(key=lambda r: self._safe_parse_date(r[0]) or datetime.min, reverse=True)
        return aggregated

    def _safe_parse_date(self, value):
        try:
            return datetime.fromisoformat(str(value))
        except Exception:
            return None

    def _create_restock_row(self, row, index):
        created_at, product, qty, unit, unit_cost, total_cost, created_by, note = row
        bg_even = _theme_color("surface_alt", [0.98, 0.99, 1, 1])
        bg_odd = _theme_color("card", [1, 1, 1, 1])
        text_primary = _theme_color("text_primary", [0.2, 0.2, 0.2, 1])
        text_secondary = _theme_color("text_secondary", [0.5, 0.5, 0.5, 1])
        bg = bg_even if index % 2 == 0 else bg_odd

        try:
            dt = datetime.fromisoformat(str(created_at))
            date_str = dt.strftime("%d/%m/%y\n%H:%M")
        except Exception:
            date_str = str(created_at)[:16]

        try:
            qty_val = float(qty)
            if unit == "UN" and qty_val.is_integer():
                qty_str = f"{int(qty_val)} {unit}"
            else:
                qty_str = f"{qty_val:.2f} {unit}"
        except Exception:
            qty_str = f"{qty} {unit}"

        unit_cost_str = f"{float(unit_cost or 0):.2f} MZN"
        total_cost_str = f"{float(total_cost or 0):.2f} MZN"
        if self.compact_mode:
            date_hint, product_hint, qty_hint, total_hint, user_hint = 0.18, 0.42, 0.14, 0.16, 0.10
        else:
            date_hint, product_hint, qty_hint, unit_hint, total_hint, user_hint = 0.16, 0.34, 0.10, 0.14, 0.14, 0.12

        line = MDBoxLayout(
            size_hint_y=None,
            height=dp(48),
            padding=[dp(16), dp(8)],
            spacing=dp(0),
            md_bg_color=bg,
        )

        line.add_widget(MDLabel(
            text=date_str,
            size_hint_x=date_hint,
            halign="left",
            font_size=dp(10),
            theme_text_color="Custom",
            text_color=text_secondary,
        ))
        line.add_widget(MDLabel(
            text=str(product),
            size_hint_x=product_hint,
            halign="left",
            font_size=dp(11),
            theme_text_color="Custom",
            text_color=text_primary,
            shorten=True,
            shorten_from="right",
        ))
        line.add_widget(MDLabel(
            text=qty_str,
            size_hint_x=qty_hint,
            halign="center",
            font_size=dp(11),
            theme_text_color="Custom",
            text_color=text_secondary,
        ))
        if not self.compact_mode:
            line.add_widget(MDLabel(
                text=unit_cost_str,
                size_hint_x=unit_hint,
                halign="right",
                font_size=dp(11),
                theme_text_color="Custom",
                text_color=text_secondary,
            ))
        line.add_widget(MDLabel(
            text=total_cost_str,
            size_hint_x=total_hint,
            halign="right",
            font_size=dp(11),
            theme_text_color="Custom",
            text_color=_theme_color("success", [0.2, 0.7, 0.3, 1]),
        ))
        line.add_widget(MDLabel(
            text=created_by or "N/A",
            size_hint_x=user_hint,
            halign="right",
            font_size=dp(11),
            theme_text_color="Custom",
            text_color=text_secondary,
            shorten=True,
            shorten_from="right",
        ))

        container = MDBoxLayout(
            orientation="vertical",
            size_hint_y=None,
            height=dp(49),
            spacing=0,
        )
        container.add_widget(line)
        container.add_widget(Widget(size_hint_y=None, height=dp(1)))
        return container
