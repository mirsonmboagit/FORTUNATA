import sys

LIGHT_TOKENS = {
    # Superfícies limpas com boa separação
    "surface":          [0.970, 0.976, 0.985, 1],
    "surface_alt":      [0.942, 0.953, 0.968, 1],
    "card":             [1.000, 1.000, 1.000, 1],
    "card_alt":         [0.980, 0.986, 0.994, 1],
    "surface_raised":   [1.000, 1.000, 1.000, 1],
    "surface_sunken":   [0.925, 0.938, 0.958, 1],   # inputs com melhor contraste

    # Contornos e divisores mais visíveis
    "divider":          [0.140, 0.180, 0.250, 0.16],
    "outline":          [0.250, 0.310, 0.400, 0.32],
    "outline_strong":   [0.180, 0.250, 0.370, 0.48],

    # Texto com alto contraste (principal correção do tema claro)
    "text_primary":     [0.080, 0.105, 0.155, 1],
    "text_secondary":   [0.300, 0.345, 0.415, 1],
    "text_muted":       [0.450, 0.490, 0.555, 1],
    "manager_ink":      [0.000, 0.000, 0.000, 1],

    # Primary profissional
    "primary":          [0.045, 0.310, 0.570, 1],
    "primary_hover":    [0.065, 0.370, 0.660, 1],
    "focus":            [0.095, 0.440, 0.770, 1],
    "on_primary":       [1.000, 1.000, 1.000, 1],

    # Cores semânticas
    "success":          [0.035, 0.510, 0.310, 1],
    "warning":          [0.770, 0.410, 0.035, 1],
    "danger":           [0.780, 0.170, 0.210, 1],
    "info":             [0.045, 0.410, 0.690, 1],
    "badge":            [0.810, 0.130, 0.180, 1],
}


DARK_TOKENS = {
    # Navy profundo e elegante
    "surface":          [0.025, 0.036, 0.055, 1],
    "surface_alt":      [0.045, 0.062, 0.090, 1],
    "card":             [0.062, 0.088, 0.125, 1],
    "card_alt":         [0.085, 0.118, 0.162, 1],
    "surface_raised":   [0.100, 0.135, 0.182, 1],
    "surface_sunken":   [0.015, 0.024, 0.040, 1],

    "divider":          [0.680, 0.760, 0.860, 0.12],
    "outline":          [0.560, 0.660, 0.780, 0.20],
    "outline_strong":   [0.430, 0.630, 0.860, 0.45],

    "text_primary":     [0.970, 0.980, 0.995, 1],
    "text_secondary":   [0.790, 0.840, 0.900, 1],
    "text_muted":       [0.610, 0.680, 0.760, 1],
    "manager_ink":      [1.000, 1.000, 1.000, 1],

    "primary":          [0.125, 0.450, 0.750, 1],
    "primary_hover":    [0.175, 0.520, 0.830, 1],
    "focus":            [0.290, 0.670, 0.980, 1],
    "on_primary":       [1.000, 1.000, 1.000, 1],

    "success":          [0.150, 0.650, 0.410, 1],
    "warning":          [0.955, 0.610, 0.170, 1],
    "danger":           [0.955, 0.310, 0.350, 1],
    "info":             [0.250, 0.610, 0.935, 1],
    "badge":            [0.945, 0.240, 0.300, 1],
}


def get_theme_tokens(style: str) -> dict:
    """Devolve os tokens do tema solicitado."""
    if style == "Dark":
        return dict(DARK_TOKENS)
    return dict(LIGHT_TOKENS)


def detect_system_theme() -> str:
    """
    Detecta o tema actual do sistema operativo.
    Suporta Windows (AppsUseLightTheme).
    Em caso de erro ou plataforma não suportada, devolve "Light".
    """
    if sys.platform.startswith("win"):
        try:
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
            ) as key:
                value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
                return "Light" if value == 1 else "Dark"
        except Exception:
            pass

    # Futuro: suporte Android / Linux / macOS
    return "Light"