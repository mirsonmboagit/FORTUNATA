"""
Tokens de tema padrão — profissionais e neutros (azul / cinza).

O login NECTAR NÃO usa estes tokens para o fundo botânico.
As cores floresta/creme ficam só na LoginScreen (propriedades locais).
"""

from __future__ import annotations


def detect_system_theme() -> str:
    """Tenta detetar o tema do sistema operativo. Fallback: Light."""
    try:
        import sys

        if sys.platform.startswith("win"):
            try:
                import winreg

                key = winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
                )
                value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
                winreg.CloseKey(key)
                return "Light" if int(value) == 1 else "Dark"
            except Exception:
                pass
        elif sys.platform == "darwin":
            try:
                import subprocess

                result = subprocess.run(
                    ["defaults", "read", "-g", "AppleInterfaceStyle"],
                    capture_output=True,
                    text=True,
                    timeout=1.5,
                )
                if "Dark" in (result.stdout or ""):
                    return "Dark"
                return "Light"
            except Exception:
                pass
    except Exception:
        pass
    return "Light"


# ---------------------------------------------------------------------------
# Dark — profissional (azul-ardósia)
# ---------------------------------------------------------------------------
_DEFAULT_DARK = {
    "surface":        [0.11, 0.13, 0.16, 1.0],
    "surface_alt":    [0.14, 0.16, 0.20, 1.0],
    "surface_sunken": [0.08, 0.09, 0.11, 1.0],
    "card":           [0.15, 0.17, 0.21, 1.0],
    "card_alt":       [0.18, 0.20, 0.25, 1.0],
    "background":     [0.11, 0.13, 0.16, 1.0],

    "primary":        [0.18, 0.42, 0.72, 1.0],
    "primary_hover":  [0.24, 0.50, 0.82, 1.0],
    "primary_dark":   [0.12, 0.32, 0.58, 1.0],
    "primary_light":  [0.35, 0.58, 0.88, 1.0],
    "on_primary":     [1.0, 1.0, 1.0, 1.0],

    "text_primary":   [0.94, 0.95, 0.97, 1.0],
    "text_secondary": [0.65, 0.68, 0.74, 1.0],
    "text_muted":     [0.50, 0.53, 0.58, 1.0],

    "outline":        [0.32, 0.36, 0.42, 1.0],
    "divider":        [1.0, 1.0, 1.0, 0.10],
    "border":         [0.32, 0.36, 0.42, 1.0],

    "success":        [0.22, 0.62, 0.40, 1.0],
    "warning":        [0.90, 0.62, 0.18, 1.0],
    "danger":         [0.82, 0.28, 0.30, 1.0],
    "info":           [0.28, 0.58, 0.82, 1.0],
    "badge":          [0.82, 0.28, 0.30, 1.0],

    "accent":         [0.35, 0.58, 0.88, 1.0],
    "gold":           [0.75, 0.60, 0.28, 1.0],
    "chip_bg":        [0.20, 0.24, 0.30, 0.95],
}


# ---------------------------------------------------------------------------
# Light — profissional (branco / azul)
# ---------------------------------------------------------------------------
_DEFAULT_LIGHT = {
    "surface":        [0.96, 0.97, 0.98, 1.0],
    "surface_alt":    [0.93, 0.94, 0.96, 1.0],
    "surface_sunken": [0.90, 0.91, 0.93, 1.0],
    "card":           [1.0, 1.0, 1.0, 1.0],
    "card_alt":       [0.97, 0.98, 0.99, 1.0],
    "background":     [0.96, 0.97, 0.98, 1.0],

    "primary":        [0.12, 0.35, 0.65, 1.0],
    "primary_hover":  [0.16, 0.42, 0.75, 1.0],
    "primary_dark":   [0.08, 0.26, 0.52, 1.0],
    "primary_light":  [0.28, 0.52, 0.82, 1.0],
    "on_primary":     [1.0, 1.0, 1.0, 1.0],

    "text_primary":   [0.12, 0.15, 0.20, 1.0],
    "text_secondary": [0.38, 0.42, 0.48, 1.0],
    "text_muted":     [0.52, 0.55, 0.60, 1.0],

    "outline":        [0.72, 0.75, 0.80, 1.0],
    "divider":        [0.0, 0.0, 0.0, 0.10],
    "border":         [0.72, 0.75, 0.80, 1.0],

    "success":        [0.18, 0.55, 0.35, 1.0],
    "warning":        [0.85, 0.58, 0.12, 1.0],
    "danger":         [0.78, 0.22, 0.24, 1.0],
    "info":           [0.18, 0.48, 0.72, 1.0],
    "badge":          [0.78, 0.22, 0.24, 1.0],

    "accent":         [0.18, 0.42, 0.72, 1.0],
    "gold":           [0.70, 0.55, 0.22, 1.0],
    "chip_bg":        [0.92, 0.94, 0.96, 0.95],
}


def get_theme_tokens(style: str) -> dict:
    """Devolve tokens padrão profissionais para 'Dark' ou 'Light'."""
    style = "Dark" if str(style or "").strip().lower() == "dark" else "Light"
    base = _DEFAULT_DARK if style == "Dark" else _DEFAULT_LIGHT
    return {key: list(value) for key, value in base.items()}
