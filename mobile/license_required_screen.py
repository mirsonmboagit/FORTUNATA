"""Tela temporaria que evita acesso movel fora da politica de licencas."""

from __future__ import annotations

from kivy.metrics import dp
from ui.components.native_widgets import NativeBoxLayout, NativeLabel, NativeScreen


class MobileLicenseRequiredScreen(NativeScreen):
    """O APK nao abre vendas enquanto nao tiver um cofre seguro equivalente."""

    def on_pre_enter(self, *args):
        if self.children:
            return
        layout = NativeBoxLayout(
            orientation="vertical",
            padding=dp(28),
            spacing=dp(14),
            pos_hint={"center_x": 0.5, "center_y": 0.5},
            size_hint=(0.9, None),
            height=dp(230),
        )
        layout.add_widget(NativeLabel(
            text="Acesso movel ainda nao ativado",
            font_style="H6",
            halign="center",
            size_hint_y=None,
            height=dp(44),
        ))
        layout.add_widget(NativeLabel(
            text=(
                "Para proteger as licencas e as contas dos clientes, esta versao "
                "do APK aguarda o conector movel seguro. Use o aplicativo desktop "
                "ativado pelo superadmin."
            ),
            halign="center",
            theme_text_color="Secondary",
            text_size=(dp(340), None),
        ))
        self.add_widget(layout)
