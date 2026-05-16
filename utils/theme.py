LIGHT_TOKENS = {
    "surface": [0.945, 0.955, 0.968, 1],
    "surface_alt": [0.975, 0.980, 0.986, 1],
    "card": [1, 1, 1, 1],
    "card_alt": [0.925, 0.940, 0.958, 1],
    "divider": [0.08, 0.12, 0.18, 0.13],
    "text_primary": [0.105, 0.145, 0.205, 1],
    "text_secondary": [0.335, 0.385, 0.465, 1],
    "text_muted": [0.540, 0.590, 0.670, 1],
    "primary": [0.055, 0.315, 0.555, 1],
    "on_primary": [1, 1, 1, 1],
    "success": [0.100, 0.585, 0.355, 1],
    "warning": [0.890, 0.565, 0.130, 1],
    "danger": [0.815, 0.230, 0.250, 1],
    "info": [0.130, 0.445, 0.710, 1],
    "badge": [0.845, 0.195, 0.190, 1],
}


DARK_TOKENS = {
    "surface": [0.065, 0.078, 0.095, 1],
    "surface_alt": [0.105, 0.120, 0.145, 1],
    "card": [0.125, 0.142, 0.170, 1],
    "card_alt": [0.165, 0.188, 0.225, 1],
    "divider": [1, 1, 1, 0.10],
    "text_primary": [0.955, 0.965, 0.985, 1],
    "text_secondary": [0.740, 0.780, 0.835, 1],
    "text_muted": [0.570, 0.620, 0.700, 1],
    "primary": [0.235, 0.510, 0.790, 1],
    "on_primary": [1, 1, 1, 1],
    "success": [0.210, 0.710, 0.445, 1],
    "warning": [0.955, 0.690, 0.220, 1],
    "danger": [0.935, 0.390, 0.375, 1],
    "info": [0.320, 0.615, 0.860, 1],
    "badge": [0.935, 0.250, 0.235, 1],
}


def get_theme_tokens(style):
    if style == "Dark":
        return dict(DARK_TOKENS)
    return dict(LIGHT_TOKENS)
