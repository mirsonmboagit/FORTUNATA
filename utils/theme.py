LIGHT_TOKENS = {
    "surface": [0.96, 0.96, 0.98, 1],
    "surface_alt": [0.98, 0.98, 0.99, 1],
    "card": [1, 1, 1, 1],
    "card_alt": [0.95, 0.96, 0.98, 1],
    "divider": [0, 0, 0, 0.12],
    "text_primary": [0.15, 0.20, 0.30, 1],
    "text_secondary": [0.35, 0.40, 0.50, 1],
    "text_muted": [0.55, 0.60, 0.70, 1],
    "primary": [0.10, 0.35, 0.65, 1],
    "on_primary": [1, 1, 1, 1],
    "success": [0.20, 0.65, 0.30, 1],
    "warning": [0.90, 0.60, 0.15, 1],
    "danger": [0.90, 0.30, 0.30, 1],
    "info": [0.15, 0.45, 0.75, 1],
    "badge": [0.95, 0.26, 0.21, 1],
}


DARK_TOKENS = {
    "surface": [0.08, 0.09, 0.11, 1],
    "surface_alt": [0.12, 0.13, 0.16, 1],
    "card": [0.14, 0.15, 0.18, 1],
    "card_alt": [0.18, 0.20, 0.24, 1],
    "divider": [1, 1, 1, 0.08],
    "text_primary": [0.95, 0.95, 0.97, 1],
    "text_secondary": [0.75, 0.78, 0.82, 1],
    "text_muted": [0.60, 0.64, 0.70, 1],
    "primary": [0.20, 0.45, 0.75, 1],
    "on_primary": [1, 1, 1, 1],
    "success": [0.25, 0.70, 0.40, 1],
    "warning": [0.95, 0.70, 0.20, 1],
    "danger": [0.95, 0.45, 0.40, 1],
    "info": [0.35, 0.60, 0.85, 1],
    "badge": [0.95, 0.26, 0.21, 1],
}


def get_theme_tokens(style):
    if style == "Dark":
        return dict(DARK_TOKENS)
    return dict(LIGHT_TOKENS)
