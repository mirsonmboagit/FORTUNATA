from kivy.animation import Animation
from kivy.clock import Clock
from kivy.graphics import Color, RoundedRectangle
from kivy.metrics import dp
from kivymd.icon_definitions import md_icons
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDIconButton, MDFlatButton
from kivymd.uix.card import MDCard
from kivymd.uix.label import MDLabel
from kivymd.uix.progressbar import MDProgressBar
import random


def animate_banner_in(widget):
    """Anima entrada do banner da esquerda"""
    target_x = getattr(widget, "_target_x", widget.x)
    widget.x = -widget.width
    widget.opacity = 1
    Animation(x=target_x, d=0.35, t="out_cubic").start(widget)


def animate_banner_out(widget):
    """Anima saída do banner para direita"""
    if not widget:
        return

    auto_event = getattr(widget, "_auto_dismiss_ev", None)
    if auto_event:
        auto_event.cancel()

    def _finish(*args):
        parent = widget.parent
        if parent:
            parent.remove_widget(widget)

    parent = widget.parent
    exit_x = getattr(widget, "_exit_x", None)
    if exit_x is None and parent:
        exit_x = parent.width + widget.width
    if exit_x is None:
        exit_x = widget.x + widget.width

    anim = Animation(x=exit_x, d=0.25, t="in_cubic")
    anim.bind(on_complete=_finish)
    anim.start(widget)


def _get_stock_message_variant(item_name, stock, unit, days_left):
    """Gera mensagens variadas e naturais para stock baixo"""
    
    # Mensagens ultra-urgentes (< 1 dia)
    if days_left < 0:
        variants = [
            f"{item_name} Stock esgotado",
            f"{item_name} - Sem nenhuma unidade",
            f"{item_name} precisa reposição já",
            f"{item_name} está crítico",
            f"{item_name} acabou, pense em recompor",
        ]
    # Mensagens urgentes (1-2 dias)
    elif days_left < 10:
        variants = [
            f"{item_name} acaba em breve",
            f"{item_name} - urgente",
            f"{item_name} está no limite",
            f"{item_name} precisa de atenção já",
            f"{item_name} crítico para os proximos dias",
        ]
    # Mensagens de atenção (2-3 dias)
    elif days_left < 15:
        variants = [
            f"{item_name} - {int(days_left)} dias restantes",
            f"{item_name} acabando em breve",
            f"{item_name} stock baixo",
            f"{item_name} atenção necessária",
            f"{item_name} vendendo rápido",
        ]
    # Mensagens de monitoramento (3+ dias)
    else:
        variants = [
            f"{item_name} - monitorar stock",
            f"{item_name} abaixo do ideal",
            f"{item_name} precisa atenção",
            f"{item_name} stock reduzido",
            f"{item_name} em baixa",
        ]
    
    return random.choice(variants)


def _get_expiry_message_variant(item_name, days_left, date_str):
    """Gera mensagens variadas para vencimento"""
    
    # Crítico (0-2 dias)
    if days_left <= 2:
        variants = [
            f"{item_name} vence em {days_left} dias",
            f"{item_name} vencimento iminente",
            f"{item_name} - vende urgente",
            f"{item_name} último prazo",
            f"{item_name} vence já ({date_str}), pense numa promoção",
        ]
    # Muito urgente (3-5 dias)
    elif days_left <= 5:
        variants = [
            f"{item_name} vence em {days_left} dias",
            f"{item_name} - priorizar venda",
            f"{item_name} vence breve",
            f"{item_name} atenção validade",
            f"{item_name} vende rápido, pense numa redução de preço",
        ]
    # Urgente (6-7 dias)
    elif days_left <= 7:
        variants = [
            f"{item_name} vence esta semana, coloque como destaque e faça um plano de promoção",
            f"{item_name} - {days_left} dias restam",
            f"{item_name} monitorar validade",
            f"{item_name} vence em breve",
            f"{item_name} atenção necessária",
        ]
    # Atenção (8-15 dias)
    else:
        variants = [
            f"{item_name} vence em {days_left} dias",
            f"{item_name} validade próxima",
            f"{item_name} - acompanhar",
            f"{item_name} vencimento em {date_str}",
            f"{item_name} monitorar data",
        ]
    
    return random.choice(variants)


def build_auto_banner_data(insights):
    """
    Gera dados dos banners com mensagens dinâmicas e naturais.
    Sem limite de itens, cores adaptativas, ícones contextuais.
    """
    banners = []
    low_stock = insights.get("low_stock", [])
    exp7 = insights.get("expiring_7", [])
    exp15 = insights.get("expiring_15", [])
    
    # ============ BANNER DE STOCK BAIXO ============
    if low_stock:
        messages = []
        urgency_levels = []
        
        # Processar todos os itens de stock baixo
        for item in low_stock:
            if isinstance(item, (list, tuple)) and len(item) >= 4:
                name = item[0]
                stock = item[1]
                is_weight = item[2]
                days_left = item[3]
            else:
                continue
            
            unit = "kG" if is_weight else "Unidades"
            msg = _get_stock_message_variant(name, stock, unit, days_left)
            messages.append(msg)
            urgency_levels.append(days_left)
        
        # Limitar exibição inicial mas manter todos nos detalhes
        displayed_messages = messages[:5]  # Top 5 mais críticos
        
        # Determinar urgência geral (baseado no mais crítico)
        min_days = min(urgency_levels) if urgency_levels else 999
        
        # Escolher cor, ícone e título baseado na urgência
        if min_days < 1:
            bg_color = (1, 0.4, 0.4, 1)  # Vermelho forte
            icon = "alert-circle"
            title_variants = ["STOCK CRÍTICO", "URGENTE", "ATENÇÃO MÁXIMA"]
        elif min_days < 2:
            bg_color = (1, 0.65, 0.3, 1)  # Laranja
            icon = "alert"
            title_variants = ["Stock Muito Baixo", "Atenção Urgente", "Repor Já"]
        elif min_days < 3:
            bg_color = (1, 0.85, 0.4, 1)  # Amarelo-laranja
            icon = "alert-outline"
            title_variants = ["Stock Baixo", "Atenção Stock", "Monitorar"]
        else:
            bg_color = (0.97, 0.94, 0.76, 1)  # Amarelo claro
            icon = "information-outline"
            title_variants = ["Monitorar Stock", "Stock Reduzido", "Atenção"]
        
        banners.append({
            "kind": "stock",
            "icon": icon,
            "bg_color": bg_color,
            "title": random.choice(title_variants),
            "messages": displayed_messages,
            "all_messages": messages,  # Todos para os detalhes
            "count": len(low_stock),
            "urgency": min_days,
        })
    
    # ============ BANNER DE VENCIMENTO ============
    if exp7 or exp15:
        messages = []
        urgency_levels = []
        
        # Processar itens de 7 dias (mais críticos primeiro)
        for name, days_left, date_str, stock, unit in exp7:
            msg = _get_expiry_message_variant(name, days_left, date_str)
            messages.append(msg)
            urgency_levels.append(days_left)
        
        # Processar itens de 15 dias
        for name, days_left, date_str, stock, unit in exp15:
            msg = _get_expiry_message_variant(name, days_left, date_str)
            messages.append(msg)
            urgency_levels.append(days_left)
        
        # Limitar exibição inicial
        displayed_messages = messages[:5]
        
        # Determinar urgência
        min_days = min(urgency_levels) if urgency_levels else 999
        
        # Escolher apresentação
        if min_days <= 2:
            bg_color = (0.96, 0.5, 0.5, 1)  # Vermelho claro
            icon = "alert-octagon"
            title_variants = ["VENCIMENTO CRÍTICO", "PERDA IMINENTE", "URGENTE"]
        elif min_days <= 5:
            bg_color = (1, 0.7, 0.5, 1)  # Laranja claro
            icon = "alert-octagon-outline"
            title_variants = ["Vencimento Próximo", "Atenção Validades", "Priorizar Venda"]
        elif min_days <= 7:
            bg_color = (1, 0.85, 0.65, 1)  # Amarelo-laranja claro
            icon = "calendar-alert"
            title_variants = ["Produtos a Vencer", "Monitorar Validades", "Esta Semana"]
        else:
            bg_color = (1, 0.92, 0.75, 1)  # Amarelo muito claro
            icon = "calendar-clock"
            title_variants = ["Validades Próximas", "Acompanhar", "Próximos Dias"]
        
        banners.append({
            "kind": "expiry",
            "icon": icon,
            "bg_color": bg_color,
            "title": random.choice(title_variants),
            "messages": displayed_messages,
            "all_messages": messages,
            "count": len(exp7) + len(exp15),
            "urgency": min_days,
        })

    # ============ BANNER POSITIVO (TUDO OK) ============
    if not low_stock and not exp7 and not exp15:
        banners.append(build_positive_banner("all"))
    
    # Ordenar banners por urgência (mais urgente primeiro)
    banners.sort(key=lambda x: x.get("urgency", 999))
    
    return banners


def build_positive_banner(kind="all"):
    if kind == "stock":
        return {
            "kind": "stock_ok",
            "icon": "check-circle",
            "bg_color": (0.74, 0.92, 0.78, 1),
            "title": "Stock em Ordem",
            "messages": [
                "Nenhum item com stock baixo.",
                "Níveis dentro do esperado.",
            ],
            "count": 0,
            "urgency": 999,
        }
    if kind == "expiry":
        return {
            "kind": "expiry_ok",
            "icon": "check-circle",
            "bg_color": (0.74, 0.92, 0.78, 1),
            "title": "Validades em Ordem",
            "messages": [
                "Nenhum produto a vencer nos próximos 15 dias.",
                "Sem riscos imediatos de vencimento.",
            ],
            "count": 0,
            "urgency": 999,
        }
    return {
        "kind": "positive",
        "icon": "check-circle",
        "bg_color": (0.74, 0.92, 0.78, 1),
        "title": "Tudo em Ordem",
        "messages": [
            "Sem itens com stock baixo.",
            "Nenhum produto a vencer nos próximos 15 dias.",
        ],
        "count": 0,
        "urgency": 999,
    }


def build_banner_details_sections(insights, kind, max_lines=None):
    """
    Constrói seções detalhadas para expandir no banner.
    Sem limite de linhas - mostra tudo que for relevante.
    """
    sections = []
    recommendations_stock = insights.get("recommendations_stock") or []
    recommendations_expiry = insights.get("recommendations_expiry") or []
    recommendations_all = insights.get("recommendations") or []

    def _add_recommendations(lines):
        if not lines:
            return
        sections.append(("Recomendações", lines[:5]))
    
    if kind == "stock":
        # Recomendações (sempre primeiro)
        _add_recommendations(recommendations_stock or recommendations_all)

        # Produtos críticos (todos)
        low_stock = insights.get("low_stock") or []
        if low_stock:
            lines = []
            for item in low_stock:
                if isinstance(item, (list, tuple)) and len(item) >= 4:
                    name = item[0]
                    stock = item[1]
                    is_weight = item[2]
                    days_left = item[3]
                    unit = "kg" if is_weight else "un"
                    lines.append(f"{name}: {stock:.1f} {unit} (~{days_left:.1f} dias)")
            if lines:
                sections.append(("Produtos Críticos", lines))

        # Previsão de ruptura
        forecast = insights.get("stock_forecast") or []
        if forecast:
            lines = []
            for item in forecast:
                if item.get("days_left") is None:
                    continue
                name = item.get("name")
                days_left = item.get("days_left")
                lines.append(f"{name} - acaba em ~{days_left:.1f} dias")
            if lines:
                sections.append(("Previsão de Ruptura", lines))

        # Insights da IA
        ai_notes = insights.get("ai_urgente_hoje", []) + insights.get("ai_atencao_proximos_dias", [])
        if ai_notes:
            sections.append(("Análise Inteligente", ai_notes))
        
        # Recomendações
        if recommendations_stock:
            sections.append(("Recomendações", recommendations_stock))

    elif kind == "expiry":
        # Recomendações (sempre primeiro)
        _add_recommendations(recommendations_expiry or recommendations_all)

        # Vencimento crítico (7 dias)
        exp7 = insights.get("expiring_7") or []
        if exp7:
            lines = []
            for name, days_left, date_str, stock, unit in exp7:
                lines.append(f"{name}: {days_left} dias - {stock:.0f} {unit} (vence {date_str})")
            if lines:
                sections.append(("Vencimento Crítico (≤7 dias)", lines))

        # Vencimento em 15 dias
        exp15 = insights.get("expiring_15") or []
        if exp15:
            lines = []
            for name, days_left, date_str, stock, unit in exp15:
                lines.append(f"{name}: {days_left} dias - {stock:.0f} {unit} (vence {date_str})")
            if lines:
                sections.append(("Vencimento Próximo (8-15 dias)", lines))

        # Risco de vencimento (análise)
        expiry_risk = insights.get("expiry_risk") or []
        if expiry_risk:
            lines = []
            for item in expiry_risk:
                name = item.get("name")
                days_to_expiry = item.get("days_to_expiry")
                days_to_sell = item.get("days_to_sell")
                loss_profit = item.get("loss_profit")
                if days_to_expiry is not None and days_to_sell is not None:
                    lines.append(
                        f"{name}: vence {days_to_expiry}d, vende ~{days_to_sell:.0f}d "
                        f"(perda ~{loss_profit:.0f} MZN)"
                    )
            if lines:
                sections.append(("Análise de Risco", lines))

        # Insights da IA
        ai_notes = insights.get("ai_urgente_hoje", []) + insights.get("ai_atencao_proximos_dias", [])
        ai_expiry = [note for note in ai_notes if any(word in note.lower() for word in ['venc', 'valid', 'expir'])]
        if ai_expiry:
            sections.append(("Análise Inteligente", ai_expiry))
        
        # Oportunidades (promoções, etc)
        ai_opportunities = insights.get("ai_oportunidades", [])
        if ai_opportunities:
            sections.append(("Oportunidades", ai_opportunities))
        
        # Recomendações
        if recommendations_expiry:
            sections.append(("Recomendações", recommendations_expiry))

    return sections


def _build_details_box(sections):
    """Constrói caixa de detalhes expandível"""
    details_box = MDBoxLayout(
        orientation="vertical",
        spacing=dp(6),
        padding=[dp(16), dp(8), dp(16), dp(12)],
        size_hint_y=None,
        height=0,
        opacity=0,
    )
    
    for title, items in sections:
        # Título da seção
        details_box.add_widget(
            MDLabel(
                text=f"[b]{title}[/b]",
                markup=True,
                theme_text_color="Custom",
                text_color=(0.15, 0.15, 0.15, 1),
                font_size=dp(13),
                size_hint_y=None,
                height=dp(20),
            )
        )
        
        # Items da seção
        for item in items:
            details_box.add_widget(
                MDLabel(
                    text=f"  • {item}",
                    theme_text_color="Custom",
                    text_color=(0.3, 0.3, 0.3, 1),
                    font_size=dp(12),
                    size_hint_y=None,
                    height=dp(18),
                    shorten=True,
                    shorten_from="right",
                )
            )
        
        # Espaçamento entre seções
        if sections.index((title, items)) < len(sections) - 1:
            details_box.add_widget(
                MDLabel(size_hint_y=None, height=dp(4))
            )
    
    # Calcular altura necessária
    details_box._target_height = _calc_details_height(details_box)
    return details_box


def _calc_details_height(details_box):
    """Calcula altura necessária para os detalhes"""
    total = 0
    for child in details_box.children:
        total += child.height
    if details_box.children:
        total += details_box.spacing * max(len(details_box.children) - 1, 0)
    total += details_box.padding[1] + details_box.padding[3]
    return max(total, dp(60))


def create_auto_banner(banner_data, show_timer=True, insights=None):
    """
    Cria banner com layout melhorado e mais profissional.
    
    Args:
        banner_data: Dados do banner (título, mensagens, cores, etc)
        show_timer: Se deve mostrar barra de progresso
        insights: Dados completos para detalhes expandíveis
    """
    
    # Card principal
    card = MDCard(
        orientation="vertical",
        padding=0,
        spacing=0,
        size_hint=(None, None),
        size_hint_y=None,
        height=dp(120),
        md_bg_color=banner_data["bg_color"],
        radius=[12, 12, 12, 12],
        elevation=4,
    )
    
    # ============ HEADER ============
    header = MDBoxLayout(
        orientation="horizontal",
        padding=[dp(20), dp(22), dp(24), dp(10)],
        spacing=dp(14),
        size_hint_y=None,
        height=dp(48),
    )
    
    # Ícone
    icon_text = md_icons.get(banner_data["icon"], md_icons.get("alert", ""))
    icon = MDLabel(
        text=icon_text,
        font_style="Icon",
        theme_text_color="Custom",
        text_color=(0.2, 0.2, 0.2, 1),
        font_size=dp(26),
        size_hint=(None, None),
        size=(dp(32), dp(32)),
        halign="center",
        valign="middle",
    )
    icon.bind(size=lambda inst, val: setattr(inst, "text_size", val))
    
    # Título
    title_text = banner_data.get("title", "Alerta")
    title = MDLabel(
        text=f"[b]{title_text}[/b]",
        markup=True,
        theme_text_color="Custom",
        text_color=(0.15, 0.15, 0.15, 1),
        font_size=dp(15),
        halign="left",
        valign="middle",
    )
    title.bind(size=lambda inst, val: setattr(inst, "text_size", (val[0], None)))
    
    # Badge com contador
    count = banner_data.get("count", 0)
    if count > 0:
        badge = MDLabel(
            text=str(count),
            bold=True,
            theme_text_color="Custom",
            text_color=(1, 1, 1, 1),
            font_size=dp(11),
            size_hint=(None, None),
            size=(dp(22), dp(22)),
            halign="center",
            valign="middle",
        )
        badge.bind(size=lambda inst, val: setattr(inst, "text_size", val))
        
        with badge.canvas.before:
            Color(0.2, 0.2, 0.2, 0.85)
            badge._bg_rect = RoundedRectangle(
                pos=badge.pos,
                size=badge.size,
                radius=[dp(11)]
            )
        badge.bind(pos=lambda *x: setattr(badge._bg_rect, 'pos', badge.pos))
        badge.bind(size=lambda *x: setattr(badge._bg_rect, 'size', badge.size))
    else:
        badge = None
    
    # Botão fechar
    close_btn = MDIconButton(
        icon="close",
        theme_text_color="Custom",
        text_color=(0.35, 0.35, 0.35, 1),
        size_hint=(None, None),
        size=(dp(32), dp(32)),
        pos_hint={"center_y": 0.5},
        on_release=lambda x: animate_banner_out(card),
    )
    
    header.add_widget(icon)
    header.add_widget(title)
    if badge:
        header.add_widget(badge)
    header.add_widget(MDLabel())  # Spacer
    header.add_widget(close_btn)
    
    # ============ CORPO COM MENSAGENS ============
    messages = banner_data.get("messages", [])
    body = MDBoxLayout(
        orientation="vertical",
        padding=[dp(16), 0, dp(16), dp(10)],
        spacing=dp(5),
        size_hint_y=None,
    )
    
    body_height = 0
    for msg in messages:
        bullet = MDLabel(
            text=f"• {msg}",
            theme_text_color="Custom",
            text_color=(0.25, 0.25, 0.25, 1),
            font_size=dp(13),
            size_hint_y=None,
            height=dp(20),
            shorten=True,
            shorten_from="right",
        )
        bullet.bind(size=lambda inst, val: setattr(inst, "text_size", (val[0], None)))
        body.add_widget(bullet)
        body_height += dp(19)
    
    body_height += dp(10) + max((len(messages) - 1) * dp(5), 0)
    body.height = body_height
    
    # ============ BOTÃO "VER DETALHES" ============
    details_sections = banner_data.get("details_sections") or []
    if not details_sections and insights:
        kind = banner_data.get("kind")
        details_sections = build_banner_details_sections(insights, kind)

    toggle_btn_widget = None
    toggle_container = None
    
    # Criar o botão se houver detalhes
    if details_sections:
        # Criar container do botão
        toggle_btn_widget = MDBoxLayout(
            orientation="horizontal",
            spacing=dp(8),
            size_hint=(None, None),
            width=dp(190),
            height=dp(34),
        )
        
        # Ícone do botão
        btn_icon = MDLabel(
            text=md_icons.get("chevron-down", ""),
            font_style="Icon",
            theme_text_color="Custom",
            text_color=(0.15, 0.15, 0.15, 1),
            font_size=dp(20),
            size_hint=(None, None),
            size=(dp(24), dp(24)),
            halign="center",
            valign="middle",
        )
        btn_icon.bind(size=lambda inst, val: setattr(inst, "text_size", val))
        
        # Texto do botão
        btn_text = MDLabel(
            text="Ver mais",
            theme_text_color="Custom",
            text_color=(0.15, 0.15, 0.15, 1),
            font_size=dp(12.5),
            bold=True,
            halign="left",
            valign="middle",
        )
        btn_text.bind(size=lambda inst, val: setattr(inst, "text_size", (val[0], None)))
        
        # Badge "novo" se houver muitos itens
        item_count = sum(len(items) for _, items in details_sections) if details_sections else 0
        badge_new = None
        if item_count > 5:
            badge_new = MDLabel(
                text=f"+{item_count}",
                theme_text_color="Custom",
                text_color=(1, 1, 1, 1),
                font_size=dp(10),
                bold=True,
                size_hint=(None, None),
                size=(dp(28), dp(18)),
                halign="center",
                valign="middle",
            )
            badge_new.bind(size=lambda inst, val: setattr(inst, "text_size", val))
            
            with badge_new.canvas.before:
                Color(0.9, 0.3, 0.2, 0.9)
                badge_new._bg = RoundedRectangle(
                    pos=badge_new.pos,
                    size=badge_new.size,
                    radius=[dp(9)]
                )
            badge_new.bind(pos=lambda *x: setattr(badge_new._bg, 'pos', badge_new.pos))
            badge_new.bind(size=lambda *x: setattr(badge_new._bg, 'size', badge_new.size))
        
        toggle_btn_widget.add_widget(btn_icon)
        toggle_btn_widget.add_widget(btn_text)
        if badge_new:
            toggle_btn_widget.add_widget(badge_new)
        
        # Adicionar fundo ao botão
        with toggle_btn_widget.canvas.before:
            Color(0, 0, 0, 0.08)
            toggle_btn_widget._bg_rect = RoundedRectangle(
                pos=toggle_btn_widget.pos,
                size=toggle_btn_widget.size,
                radius=[dp(8)]
            )
        toggle_btn_widget.bind(pos=lambda *x: setattr(toggle_btn_widget._bg_rect, 'pos', toggle_btn_widget.pos))
        toggle_btn_widget.bind(size=lambda *x: setattr(toggle_btn_widget._bg_rect, 'size', toggle_btn_widget.size))
        
        # Container do botão com padding
        toggle_container = MDBoxLayout(
            orientation="horizontal",
            padding=[dp(16), dp(4), dp(16), dp(10)],
            size_hint_y=None,
            height=dp(44),
        )
        toggle_container.add_widget(toggle_btn_widget)
        toggle_container.add_widget(MDLabel())  # Spacer
        
        # Salvar referências
        toggle_btn_widget._icon = btn_icon
        toggle_btn_widget._text = btn_text
    
    # ============ MONTAR CARD ============
    card.add_widget(header)
    card.add_widget(body)
    
    # ADICIONAR O BOTÃO AQUI (SEMPRE)
    if toggle_container:
        card.add_widget(toggle_container)
    
    # Barra de progresso
    progress = None
    if show_timer:
        progress = MDProgressBar(
            value=100,
            max=100,
            size_hint_y=None,
            height=dp(3),
            color=(0.3, 0.3, 0.3, 0.5),
        )
        card.add_widget(progress)
    
    # Calcular altura total
    total_height = dp(48) + body_height
    if toggle_container:
        total_height += dp(44)  # Altura do container do botão
    if progress:
        total_height += dp(3)
    
    card.height = total_height
    card._base_height = total_height
    card._body = body
    card._progress = progress
    card._toggle_btn = toggle_btn_widget
    card._toggle_container = toggle_container
    card._details_sections = details_sections
    card._details_expanded = False
    
    # Configurar toggle de detalhes (SEMPRE se houver botão)
    if toggle_btn_widget and details_sections:
        _setup_details_toggle(card, toggle_btn_widget, details_sections)
    
    return card


def _visible_widgets(container):
    widgets = getattr(container, "_ai_banner_widgets", []) if container else []
    return [w for w in widgets if w and w.parent and not getattr(w, "_is_hidden", False)]


def _set_banner_hidden(widget, hidden):
    if not widget:
        return
    widget._is_hidden = bool(hidden)
    if hidden:
        widget.opacity = 0
        widget.disabled = True
        widget.pos = (-widget.width * 2, widget.y)
    else:
        widget.opacity = 1
        widget.disabled = False


def _force_collapse_banner(widget):
    if not widget:
        return
    if getattr(widget, "_details_expanded", False):
        details_box = getattr(widget, "_details_box", None)
        if details_box:
            Animation.cancel_all(details_box)
            if details_box.parent:
                details_box.parent.remove_widget(details_box)
        widget._details_expanded = False
        toggle_btn = getattr(widget, "_toggle_btn", None)
        if toggle_btn:
            if hasattr(toggle_btn, "_icon"):
                toggle_btn._icon.text = md_icons.get("chevron-down", "")
            if hasattr(toggle_btn, "_text"):
                toggle_btn._text.text = "Ver mais"
        base_height = getattr(widget, "_base_height", None)
        if base_height is not None:
            widget.height = base_height


def _pause_auto_dismiss(widget):
    if not widget:
        return
    auto_event = getattr(widget, "_auto_dismiss_ev", None)
    if auto_event:
        auto_event.cancel()
        widget._auto_dismiss_ev = None
    progress = getattr(widget, "_progress", None)
    if progress:
        Animation.cancel_all(progress)
    widget._auto_paused = True


def _resume_auto_dismiss(widget):
    if not widget or not getattr(widget, "_auto_paused", False):
        return
    widget._auto_paused = False
    auto_dismiss_seconds = getattr(widget, "_auto_dismiss_seconds", None)
    show_timer = getattr(widget, "_auto_show_timer", False)
    if not auto_dismiss_seconds:
        return
    progress = getattr(widget, "_progress", None)
    if progress and show_timer:
        progress.value = 100
        Animation(value=0, d=auto_dismiss_seconds, t="linear").start(progress)
    widget._auto_dismiss_ev = Clock.schedule_once(
        lambda dt, ww=widget: animate_banner_out(ww),
        auto_dismiss_seconds,
    )


def _setup_details_toggle(card, toggle_btn, details_sections):
    """Configura expansão/colapso de detalhes com animação do botão"""
    details_box = _build_details_box(details_sections)
    
    def _recenter():
        """Recentra banners após expansão"""
        container = getattr(card, "_banner_container", None)
        widgets = _visible_widgets(container)
        if container and widgets:
            position_banners_center(container, widgets, reset_x=False)
    
    def _toggle_siblings(show):
        container = getattr(card, "_banner_container", None)
        widgets = getattr(container, "_ai_banner_widgets", None) if container else None
        if not widgets or len(widgets) <= 1:
            return
        for w in widgets:
            if w is card:
                continue
            if show:
                _set_banner_hidden(w, False)
                _resume_auto_dismiss(w)
            else:
                _force_collapse_banner(w)
                _pause_auto_dismiss(w)
                _set_banner_hidden(w, True)

    def _on_touch_down(instance, touch):
        """Handler para clique no botão"""
        if instance.collide_point(*touch.pos):
            _toggle()
            return True
        return False
    
    def _toggle(*args):
        if card._details_expanded:
            # COLAPSAR
            anim = Animation(height=0, opacity=0, d=0.2, t="in_out_cubic")
            anim.start(details_box)
            
            Animation(height=card._base_height, d=0.2, t="in_out_cubic").start(card)
            
            # Animar ícone do botão
            if hasattr(toggle_btn, '_icon'):
                toggle_btn._icon.text = md_icons.get("chevron-down", "")
                toggle_btn._text.text = "Ver mais"
            
            def _finish(*_):
                if details_box.parent:
                    details_box.parent.remove_widget(details_box)
                card._details_expanded = False
                _toggle_siblings(True)
                Clock.schedule_once(lambda dt: _recenter(), 0.05)
            
            anim.bind(on_complete=_finish)
            
        else:
            # EXPANDIR
            # Inserir details_box antes do toggle_container
            if card._toggle_container and card._toggle_container in card.children:
                toggle_index = card.children.index(card._toggle_container)
                card.add_widget(details_box, index=toggle_index + 1)
            else:
                card.add_widget(details_box)
            
            target_h = details_box._target_height
            card_target = card._base_height + target_h
            
            Animation(height=target_h, opacity=1, d=0.25, t="out_cubic").start(details_box)
            Animation(height=card_target, d=0.25, t="out_cubic").start(card)
            
            # Animar ícone do botão
            if hasattr(toggle_btn, '_icon'):
                toggle_btn._icon.text = md_icons.get("chevron-up", "")
                toggle_btn._text.text = "Ver menos"
            
            card._details_expanded = True
            _toggle_siblings(False)
            
            Clock.schedule_once(lambda dt: _recenter(), 0.3)
    
    # Bind do evento de toque
    toggle_btn.bind(on_touch_down=_on_touch_down)
    card._details_box = details_box
    card._toggle_details = _toggle


def position_banners_center(container, widgets, spacing=dp(14), reset_x=True):
    """Posiciona banners centralizados verticalmente no container"""
    if not widgets:
        return
    
    if container.width <= 0 or container.height <= 0:
        Clock.schedule_once(
            lambda dt: position_banners_center(container, widgets, spacing, reset_x), 0.05
        )
        return

    total_height = sum(w.height for w in widgets) + spacing * (len(widgets) - 1)
    start_y = (container.height - total_height) / 2.0

    banner_width = min(container.width * 0.96, dp(720))  # Máximo 720dp
    
    for idx, widget in enumerate(widgets):
        widget.width = banner_width
        widget._target_x = (container.width - banner_width) / 2.0
        widget._exit_x = container.width + banner_width
        
        y = start_y + (len(widgets) - 1 - idx) * (widget.height + spacing)
        
        if reset_x:
            widget.pos = (-widget.width, y)
        else:
            widget.pos = (getattr(widget, "_target_x", widget.x), y)


def render_auto_banners(
    container, 
    banner_data_list, 
    insights=None,
    auto_dismiss_seconds=15, 
    show_timer=True,
    stagger_seconds=2.0
):
    """
    Renderiza banners automáticos com animações.
    
    Args:
        container: Widget container onde os banners serão adicionados
        banner_data_list: Lista de dados dos banners
        insights: Dados completos para detalhes expandíveis
        auto_dismiss_seconds: Tempo até auto-fechar (0 = não fechar)
        show_timer: Se deve mostrar barra de progresso
    """
    container.clear_widgets()
    widgets = []
    
    for data in banner_data_list:
        widget = create_auto_banner(data, show_timer=show_timer, insights=insights)
        widget._banner_container = container
        widget._auto_dismiss_seconds = auto_dismiss_seconds
        widget._auto_show_timer = bool(show_timer)
        widget._auto_paused = False
        container.add_widget(widget)
        widgets.append(widget)

    container._ai_banner_widgets = widgets
    position_banners_center(container, widgets)
    
    # Animar entrada de cada banner com delay escalonado
    for idx, widget in enumerate(widgets):
        delay = idx * stagger_seconds
        
        def _start(dt, w=widget):
            animate_banner_in(w)
            
            # Iniciar timer de progresso
            progress = getattr(w, "_progress", None)
            if progress and show_timer and auto_dismiss_seconds:
                progress.value = 100
                Animation(value=0, d=auto_dismiss_seconds, t="linear").start(progress)
            
            # Agendar auto-dismiss
            if auto_dismiss_seconds:
                w._auto_dismiss_ev = Clock.schedule_once(
                    lambda dt2, ww=w: animate_banner_out(ww),
                    auto_dismiss_seconds,
                )
        
        Clock.schedule_once(_start, delay)
