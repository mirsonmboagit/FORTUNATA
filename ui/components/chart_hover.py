class MatplotlibHoverController:
    def __init__(self, theme_getter):
        self._theme_getter = theme_getter
        self._canvas_widget = None
        self._figure = None
        self._hover_items = []
        self._annotation = None
        self._motion_cid = None
        self._leave_cid = None
        self._active_item = None
        self._artist_defaults = {}

    def detach(self):
        self._set_active_item(None)
        canvas = self._canvas_widget
        for cid in (self._motion_cid, self._leave_cid):
            if canvas is None or cid is None:
                continue
            try:
                canvas.mpl_disconnect(cid)
            except Exception:
                pass
        if self._annotation is not None:
            try:
                self._annotation.remove()
            except Exception:
                pass
        self._annotation = None
        self._motion_cid = None
        self._leave_cid = None
        self._hover_items = []
        self._figure = None
        self._canvas_widget = None
        self._artist_defaults = {}

    def attach(self, canvas_widget, figure, hover_items):
        self.detach()
        self._canvas_widget = canvas_widget
        self._figure = figure
        self._hover_items = list(hover_items or [])
        if canvas_widget is None or figure is None or not self._hover_items or not getattr(figure, "axes", None):
            return

        axis = figure.axes[0]
        annotation = axis.annotate(
            "",
            xy=(0, 0),
            xytext=(14, 14),
            textcoords="offset points",
            ha="left",
            va="bottom",
            fontsize=8.8,
            zorder=50,
            bbox={
                "boxstyle": "round,pad=0.52",
                "fc": self._theme("card", (1, 1, 1, 0.98)),
                "ec": self._theme("divider", (0.82, 0.85, 0.9, 1)),
                "alpha": 0.96,
            },
        )
        annotation.set_visible(False)
        annotation.set_color(self._theme("text_primary", (0.2, 0.2, 0.2, 1)))
        self._annotation = annotation
        self._motion_cid = canvas_widget.mpl_connect("motion_notify_event", self._on_motion)
        self._leave_cid = canvas_widget.mpl_connect("figure_leave_event", self._hide_annotation)

    def _theme(self, name, fallback):
        return self._theme_getter(name, fallback)

    def _request_redraw(self):
        canvas = self._canvas_widget
        if canvas is None:
            return
        redraw = getattr(canvas, "draw_idle", None) or getattr(canvas, "draw", None)
        if callable(redraw):
            redraw()

    def _resolve_text(self, item):
        text = item.get("text", "")
        if callable(text):
            try:
                text = text()
            except Exception:
                text = ""
        return str(text or "").strip()

    def _resolve_position(self, item):
        position = item.get("position")
        if callable(position):
            try:
                position = position()
            except Exception:
                position = None
        if position is not None:
            return position

        artist = item.get("artist")
        if (
            artist is not None
            and hasattr(artist, "get_x")
            and hasattr(artist, "get_y")
            and hasattr(artist, "get_width")
            and hasattr(artist, "get_height")
        ):
            width = float(artist.get_width() or 0.0)
            height = float(artist.get_height() or 0.0)
            if abs(width) >= abs(height):
                return (artist.get_x() + width, artist.get_y() + (height / 2.0))
            return (artist.get_x() + (width / 2.0), artist.get_y() + height)
        return (0, 0)

    def _resolve_item_value(self, item, key, fallback=None):
        value = item.get(key, fallback)
        if callable(value):
            try:
                value = value()
            except Exception:
                value = fallback
        return value

    def _compose_text(self, item):
        title = str(self._resolve_item_value(item, "title", "") or "").strip()
        lines = self._resolve_item_value(item, "lines", [])
        footer = str(self._resolve_item_value(item, "footer", "") or "").strip()

        text_parts = []
        if title:
            text_parts.append(title)

        if isinstance(lines, (list, tuple)):
            for line in lines:
                line_text = str(line or "").strip()
                if line_text:
                    text_parts.append(line_text)
        else:
            line_text = str(lines or "").strip()
            if line_text:
                text_parts.append(line_text)

        if footer:
            text_parts.append(footer)

        text = "\n".join(text_parts).strip()
        if text:
            return text
        return self._resolve_text(item)

    def _resolve_accent_color(self, item):
        accent = self._resolve_item_value(item, "accent_color")
        if accent is None:
            return self._theme("primary", (0.10, 0.35, 0.65, 1))
        return accent

    def _apply_annotation_theme(self, item=None):
        if self._annotation is None:
            return
        self._annotation.set_color(self._theme("text_primary", (0.2, 0.2, 0.2, 1)))
        patch = self._annotation.get_bbox_patch()
        if patch is not None:
            try:
                patch.set_facecolor(self._theme("card", (1, 1, 1, 0.98)))
                patch.set_edgecolor(self._resolve_accent_color(item or {}))
                patch.set_linewidth(1.35)
            except Exception:
                pass

    def _update_annotation_anchor(self, event):
        if self._annotation is None:
            return
        canvas_width = float(getattr(self._canvas_widget, "width", 0) or 0)
        canvas_height = float(getattr(self._canvas_widget, "height", 0) or 0)
        if canvas_width > 0 and float(getattr(event, "x", 0) or 0) > (canvas_width * 0.68):
            self._annotation.set_position((-14, 14))
            self._annotation.set_ha("right")
        else:
            self._annotation.set_position((14, 14))
            self._annotation.set_ha("left")
        if canvas_height > 0 and float(getattr(event, "y", 0) or 0) > (canvas_height * 0.70):
            x_offset, _y_offset = self._annotation.get_position()
            self._annotation.set_position((x_offset, -14))
            self._annotation.set_va("top")
        else:
            x_offset, _y_offset = self._annotation.get_position()
            self._annotation.set_position((x_offset, 14))
            self._annotation.set_va("bottom")

    def _normalize_numeric(self, value, fallback=0.0):
        try:
            return float(value)
        except Exception:
            return float(fallback)

    def _capture_artist_defaults(self, artist):
        key = id(artist)
        if key in self._artist_defaults:
            return self._artist_defaults[key]
        defaults = {}
        for getter_name, field_name in (
            ("get_alpha", "alpha"),
            ("get_linewidth", "linewidth"),
            ("get_edgecolor", "edgecolor"),
            ("get_zorder", "zorder"),
        ):
            getter = getattr(artist, getter_name, None)
            if callable(getter):
                try:
                    defaults[field_name] = getter()
                except Exception:
                    defaults[field_name] = None
        self._artist_defaults[key] = defaults
        return defaults

    def _restore_artist_style(self, item):
        artist = (item or {}).get("artist")
        if artist is None:
            return
        defaults = self._capture_artist_defaults(artist)
        for setter_name, field_name in (
            ("set_alpha", "alpha"),
            ("set_linewidth", "linewidth"),
            ("set_edgecolor", "edgecolor"),
            ("set_zorder", "zorder"),
        ):
            setter = getattr(artist, setter_name, None)
            if not callable(setter):
                continue
            try:
                setter(defaults.get(field_name))
            except Exception:
                continue

    def _highlight_artist(self, item):
        artist = (item or {}).get("artist")
        if artist is None:
            return
        defaults = self._capture_artist_defaults(artist)
        accent = self._resolve_accent_color(item or {})

        setter = getattr(artist, "set_alpha", None)
        if callable(setter):
            try:
                setter(self._normalize_numeric(item.get("hover_alpha"), 1.0))
            except Exception:
                pass

        setter = getattr(artist, "set_linewidth", None)
        if callable(setter):
            try:
                base_width = self._normalize_numeric(defaults.get("linewidth"), 0.8)
                target_width = item.get("hover_linewidth")
                if target_width is None:
                    target_width = max(base_width + 0.9, 1.5)
                setter(float(target_width))
            except Exception:
                pass

        setter = getattr(artist, "set_edgecolor", None)
        if callable(setter):
            try:
                setter(item.get("hover_edgecolor") or accent)
            except Exception:
                pass

        setter = getattr(artist, "set_zorder", None)
        if callable(setter):
            try:
                base_zorder = self._normalize_numeric(defaults.get("zorder"), 1.0)
                setter(base_zorder + self._normalize_numeric(item.get("hover_zorder_delta"), 2.0))
            except Exception:
                pass

    def _set_active_item(self, item):
        if item is self._active_item:
            return False
        if self._active_item is not None:
            self._restore_artist_style(self._active_item)
        self._active_item = item
        if item is not None:
            self._highlight_artist(item)
        return True

    def _hide_annotation(self, *_args):
        changed = self._set_active_item(None)
        if self._annotation is None or not self._annotation.get_visible():
            if changed:
                self._request_redraw()
            return
        self._annotation.set_visible(False)
        self._request_redraw()

    def _on_motion(self, event):
        if self._annotation is None or event is None or event.inaxes is None:
            self._hide_annotation()
            return

        for item in self._hover_items:
            artist = item.get("artist")
            if artist is None:
                continue
            try:
                contains, _details = artist.contains(event)
            except Exception:
                contains = False
            if not contains:
                continue

            text = self._compose_text(item)
            if not text:
                continue

            style_changed = self._set_active_item(item)
            self._annotation.xy = self._resolve_position(item)
            self._annotation.set_text(text)
            self._apply_annotation_theme(item)
            self._update_annotation_anchor(event)
            self._annotation.set_visible(True)
            if style_changed or not self._annotation.get_visible():
                self._request_redraw()
            else:
                self._request_redraw()
            return

        self._hide_annotation()
