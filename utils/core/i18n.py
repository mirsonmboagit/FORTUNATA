from __future__ import annotations

import json
import locale
import os
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any

from utils.config.paths import ROOT_DIR


DEFAULT_LANGUAGE = "pt"
LOCALES_DIR = ROOT_DIR / "locales"
TEXT_TRANSLATIONS_FILE = LOCALES_DIR / "texts.json"

SUPPORTED_LANGUAGES = (
    {"code": "pt", "name": "Português", "native_name": "Português", "short": "PT"},
    {"code": "en", "name": "English", "native_name": "English", "short": "EN"},
    {"code": "fr", "name": "French", "native_name": "Français", "short": "FR"},
    {"code": "de", "name": "German", "native_name": "Deutsch", "short": "DE"},
    {"code": "es", "name": "Spanish", "native_name": "Español", "short": "ES"},
    {"code": "zh", "name": "Chinese", "native_name": "中文（普通话）", "short": "ZH"},
)

_LANGUAGE_CODES = {item["code"] for item in SUPPORTED_LANGUAGES}
_LANGUAGE_INDEX = {item["code"]: item for item in SUPPORTED_LANGUAGES}


def detect_system_language(fallback: str = DEFAULT_LANGUAGE) -> str:
    """Devolve o idioma preferido do sistema operativo, se for suportado.

    No Windows, ``GetUserDefaultLocaleName`` respeita o idioma configurado
    para a conta ativa, mesmo quando as variáveis de ambiente não existem.
    Em outros sistemas usa as definições de locale disponíveis no Python.
    """
    candidates: list[str] = []
    try:
        if os.name == "nt":
            import ctypes

            buffer = ctypes.create_unicode_buffer(85)
            if ctypes.windll.kernel32.GetUserDefaultLocaleName(buffer, len(buffer)):
                candidates.append(buffer.value)
    except Exception:
        pass
    try:
        current_locale = locale.getlocale()[0]
        if current_locale:
            candidates.append(current_locale)
    except Exception:
        pass
    candidates.extend(
        value
        for value in (os.getenv("LC_ALL"), os.getenv("LC_MESSAGES"), os.getenv("LANG"))
        if value
    )
    for candidate in candidates:
        code = normalize_language(candidate, fallback="")
        if code in _LANGUAGE_CODES:
            return code
    return normalize_language(fallback)

_PORTUGUESE_WORD_CORRECTIONS = {
    "acao": "ação",
    "acoes": "ações",
    "acucar": "açúcar",
    "administracao": "administração",
    "analise": "análise",
    "analises": "análises",
    "aplicacao": "aplicação",
    "aplicacoes": "aplicações",
    "aprovacao": "aprovação",
    "aprovacoes": "aprovações",
    "aparencia": "aparência",
    "ate": "até",
    "atencao": "atenção",
    "autenticacao": "autenticação",
    "automacao": "automação",
    "automacoes": "automações",
    "automatica": "automática",
    "automaticas": "automáticas",
    "automatico": "automático",
    "automaticos": "automáticos",
    "avancada": "avançada",
    "avancadas": "avançadas",
    "avancado": "avançado",
    "avancados": "avançados",
    "basica": "básica",
    "basico": "básico",
    "botao": "botão",
    "botoes": "botões",
    "calculo": "cálculo",
    "calculos": "cálculos",
    "camera": "câmara",
    "cameras": "câmaras",
    "cartao": "cartão",
    "catalogo": "catálogo",
    "codigo": "código",
    "codigos": "códigos",
    "configuracao": "configuração",
    "configuracoes": "configurações",
    "conexao": "conexão",
    "conexoes": "conexões",
    "concluida": "concluída",
    "conteudo": "conteúdo",
    "conferencia": "conferência",
    "conferencias": "conferências",
    "confusao": "confusão",
    "correcao": "correção",
    "correcoes": "correções",
    "critica": "crítica",
    "criticas": "críticas",
    "critico": "crítico",
    "criticos": "críticos",
    "decisao": "decisão",
    "definicao": "definição",
    "definicoes": "definições",
    "dependencia": "dependência",
    "dependencias": "dependências",
    "disponivel": "disponível",
    "disponiveis": "disponíveis",
    "ecra": "ecrã",
    "edicao": "edição",
    "educacao": "educação",
    "estrategica": "estratégica",
    "estrategico": "estratégico",
    "estavel": "estável",
    "estoque": "stock",
    "evidencia": "evidência",
    "evidencias": "evidências",
    "exclusao": "exclusão",
    "exportacao": "exportação",
    "fisico": "físico",
    "fisica": "física",
    "faturacao": "faturação",
    "forcar": "forçar",
    "funcao": "função",
    "funcoes": "funções",
    "geracao": "geração",
    "gerenciamento": "gestão",
    "grafico": "gráfico",
    "graficos": "gráficos",
    "ha": "há",
    "historico": "histórico",
    "impressao": "impressão",
    "indisponivel": "indisponível",
    "informacao": "informação",
    "informacoes": "informações",
    "inicio": "início",
    "instalacao": "instalação",
    "instalacoes": "instalações",
    "integracao": "integração",
    "integracoes": "integrações",
    "isencao": "isenção",
    "invalido": "inválido",
    "invalidos": "inválidos",
    "ja": "já",
    "ligacao": "ligação",
    "lider": "líder",
    "manutencao": "manutenção",
    "maximo": "máximo",
    "media": "média",
    "medio": "médio",
    "memoria": "memória",
    "metrica": "métrica",
    "metricas": "métricas",
    "minimo": "mínimo",
    "modulo": "módulo",
    "modulos": "módulos",
    "movimentacao": "movimentação",
    "movimentacoes": "movimentações",
    "monitorizacao": "monitorização",
    "nao": "não",
    "necessaria": "necessária",
    "necessarias": "necessárias",
    "necessario": "necessário",
    "necessarios": "necessários",
    "negocio": "negócio",
    "negocios": "negócios",
    "notificacao": "notificação",
    "notificacoes": "notificações",
    "numero": "número",
    "observacao": "observação",
    "observacoes": "observações",
    "obrigatoria": "obrigatória",
    "obrigatorias": "obrigatórias",
    "obrigatorio": "obrigatório",
    "obrigatorios": "obrigatórios",
    "ocorrencia": "ocorrência",
    "ocorrencias": "ocorrências",
    "oleos": "óleos",
    "operacao": "operação",
    "operacoes": "operações",
    "pagina": "página",
    "paginas": "páginas",
    "padrao": "padrão",
    "paineis": "painéis",
    "periodo": "período",
    "periodos": "períodos",
    "permissao": "permissão",
    "permissoes": "permissões",
    "possivel": "possível",
    "preco": "preço",
    "precos": "preços",
    "preparacao": "preparação",
    "previsao": "previsão",
    "previo": "prévio",
    "propria": "própria",
    "proprias": "próprias",
    "proprio": "próprio",
    "proprios": "próprios",
    "proxima": "próxima",
    "proximo": "próximo",
    "rapida": "rápida",
    "rapido": "rápido",
    "recomendacao": "recomendação",
    "recomendacoes": "recomendações",
    "referencia": "referência",
    "relatorio": "relatório",
    "relatorios": "relatórios",
    "reposicao": "reposição",
    "reposicoes": "reposições",
    "restauracao": "restauração",
    "revisao": "revisão",
    "rotulo": "rótulo",
    "saboes": "sabões",
    "saida": "saída",
    "saidas": "saídas",
    "sao": "são",
    "saude": "saúde",
    "secao": "secção",
    "seleccao": "selecção",
    "selecao": "seleção",
    "seguranca": "segurança",
    "sensivel": "sensível",
    "sensiveis": "sensíveis",
    "serao": "serão",
    "servicos": "serviços",
    "sessao": "sessão",
    "senha": "palavra-passe",
    "senhas": "palavras-passe",
    "sincrono": "síncrono",
    "sincronizacao": "sincronização",
    "sugestao": "sugestão",
    "sugestoes": "sugestões",
    "tambem": "também",
    "tecnica": "técnica",
    "tecnicas": "técnicas",
    "tecnico": "técnico",
    "tecnicos": "técnicos",
    "termica": "térmica",
    "temporaria": "temporária",
    "unica": "única",
    "unico": "único",
    "unitaria": "unitária",
    "unitario": "unitário",
    "usuario": "utilizador",
    "usuarios": "utilizadores",
    "validacao": "validação",
    "valido": "válido",
    "validos": "válidos",
    "vigencia": "vigência",
    "vigencias": "vigências",
    "visivel": "visível",
    "visiveis": "visíveis",
    "visao": "visão",
    "voce": "você",
}

_PORTUGUESE_PHRASE_CORRECTIONS = (
    (re.compile(r"\be (?=obrigat[óo]ri[oa]s?\b)", re.IGNORECASE), "é "),
    (re.compile(r"\be (?=mantid[ao]s?\b)", re.IGNORECASE), "é "),
    (re.compile(r"\be (?=feita\b)", re.IGNORECASE), "é "),
    (re.compile(r"\be (?=criada\b)", re.IGNORECASE), "é "),
    (re.compile(r"\be (?=usada\b)", re.IGNORECASE), "é "),
    (re.compile(r"\bResponda as perguntas\b", re.IGNORECASE), "Responda às perguntas"),
    (re.compile(r"\bresponda as perguntas\b"), "responda às perguntas"),
    (re.compile(r"\bFaça login\b", re.IGNORECASE), "Inicie sessão"),
    (re.compile(r"\bfazer login\b", re.IGNORECASE), "iniciar sessão"),
    (re.compile(r"\bno momento\b", re.IGNORECASE), "agora"),
    (re.compile(r"\bapoio a tomada de decisão\b", re.IGNORECASE), "apoio à tomada de decisão"),
    (
        re.compile(
            r"\besta\b(?=\s+(a|acima|abaixo|ativa|ativo|bloqueada|com|configurada|disponivel|"
            r"indisponivel|insegura|lenta|no|na|nos|nas|pronta|pronto|sem|vazia|vazio)\b)"
        ),
        "está",
    ),
)


def _strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text)
    return "".join(char for char in normalized if unicodedata.category(char) != "Mn")


def _match_case(source: str, corrected: str) -> str:
    if source.isupper():
        return corrected.upper()
    if source[:1].isupper():
        return corrected[:1].upper() + corrected[1:]
    return corrected


def correct_portuguese_text(text: Any) -> str:
    result = str(text or "")
    if not result.strip():
        return result
    for pattern, replacement in _PORTUGUESE_PHRASE_CORRECTIONS:
        result = pattern.sub(replacement, result)
    for source, corrected in _PORTUGUESE_WORD_CORRECTIONS.items():
        result = re.sub(
            rf"\b{re.escape(source)}\b",
            lambda match, value=corrected: _match_case(match.group(0), value),
            result,
            flags=re.IGNORECASE,
        )
    return result


def has_portuguese_correction(text: Any) -> bool:
    source = str(text or "")
    return bool(source.strip() and correct_portuguese_text(source) != source)


def normalize_language(value: Any, fallback: str = DEFAULT_LANGUAGE) -> str:
    code = str(value or "").strip().lower().replace("_", "-")
    if "-" in code:
        code = code.split("-", 1)[0]
    if code in _LANGUAGE_CODES:
        return code
    return fallback if fallback in _LANGUAGE_CODES else DEFAULT_LANGUAGE


def language_options() -> list[dict[str, str]]:
    return [dict(item) for item in SUPPORTED_LANGUAGES]


def language_label(code: Any, *, include_short: bool = False) -> str:
    language = _LANGUAGE_INDEX.get(normalize_language(code), _LANGUAGE_INDEX[DEFAULT_LANGUAGE])
    if include_short:
        return f"{language['native_name']} ({language['short']})"
    return language["native_name"]


def language_short(code: Any) -> str:
    return _LANGUAGE_INDEX.get(normalize_language(code), _LANGUAGE_INDEX[DEFAULT_LANGUAGE])["short"]


@lru_cache(maxsize=None)
def _load_catalog(code: str) -> dict[str, str]:
    normalized = normalize_language(code)
    path = LOCALES_DIR / f"{normalized}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    return {str(key): str(value) for key, value in (data or {}).items()}


def reload_translations() -> None:
    _load_catalog.cache_clear()
    _load_text_catalog.cache_clear()


def translate(key: str, locale_code: Any = None, default: str | None = None, **kwargs: Any) -> str:
    """Translate a catalogue key for ``locale_code``.

    ``language`` deliberately is not the name of the locale argument: it is a
    very common placeholder in translated messages (for example
    ``"Language updated to {language}."``).  Keeping it available in
    ``kwargs`` prevents a language switch from raising a duplicate-argument
    error while formatting that message.
    """
    lang = normalize_language(locale_code)
    key = str(key or "")
    catalog = _load_catalog(lang)
    fallback_catalog = _load_catalog(DEFAULT_LANGUAGE)
    text = catalog.get(key) or fallback_catalog.get(key) or default or key
    if lang == DEFAULT_LANGUAGE:
        text = correct_portuguese_text(text)
    if kwargs:
        try:
            return text.format(**kwargs)
        except Exception:
            return text
    return text


def _normalize_text_source(text: Any) -> str:
    collapsed = " ".join(
        str(text or "")
        .replace("\\n", "\n")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .split()
    )
    return _strip_accents(collapsed).casefold()


@lru_cache(maxsize=1)
def _load_text_catalog() -> dict[str, dict[str, str]]:
    try:
        data = json.loads(TEXT_TRANSLATIONS_FILE.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    catalog: dict[str, dict[str, str]] = {}
    for source, translations in (data or {}).items():
        normalized_source = _normalize_text_source(source)
        if not normalized_source or not isinstance(translations, dict):
            continue
        catalog[normalized_source] = {
            normalize_language(lang): str(value)
            for lang, value in translations.items()
            if str(value or "").strip()
        }
    return catalog


def has_text_translation(text: Any) -> bool:
    normalized = _normalize_text_source(text)
    return (
        normalized in _load_text_catalog()
        or bool(_translate_runtime_template(str(text or ""), "en"))
        or bool(_translate_dynamic_text(normalized, "en"))
    )


def translate_text(text: Any, language: Any = None) -> str:
    """Traduz texto livre (labels do KV, botoes, menus).

    Ordem:
    1) Se idioma == PT → correccao ortografica
    2) Entrada exacta em locales/texts.json
    3) Padroes dinamicos (contagens, etc.)
    4) Dicionario embutido de frases comuns da UI
    5) Texto original
    """
    source = str(text or "")
    lang = normalize_language(language)
    if not source.strip():
        return source
    if lang == DEFAULT_LANGUAGE:
        return correct_portuguese_text(source)

    # Alert and dashboard messages contain live values (product names, dates
    # and quantities), so they cannot live as exact entries in texts.json.
    # Translate their Portuguese framing before the exact-text lookup, keeping
    # the data supplied by the user/database untouched.
    runtime = _translate_runtime_template(source, lang)
    if runtime:
        return runtime.upper() if source.strip().isupper() else runtime

    normalized_source = _normalize_text_source(source)
    translations = _load_text_catalog().get(normalized_source)
    if translations and translations.get(lang):
        translated = translations[lang]
        return translated.upper() if source.strip().isupper() else translated

    dynamic = _translate_dynamic_text(normalized_source, lang)
    if dynamic:
        return dynamic.upper() if source.strip().isupper() else dynamic

    builtin = _BUILTIN_UI_PHRASES.get(normalized_source)
    if builtin and builtin.get(lang):
        translated = builtin[lang]
        return translated.upper() if source.strip().isupper() else translated

    return source


def _translate_runtime_template(source: str, language: str) -> str:
    """Translate operational Portuguese templates while preserving live data.

    These messages are created from stock and expiry records at runtime.  A
    word-for-word dictionary would either miss the message or translate the
    product name, therefore only the known UI fragments are replaced.
    """
    if language == DEFAULT_LANGUAGE:
        return ""

    text = str(source or "")
    normalized = _normalize_text_source(text)
    portuguese_markers = (
        "stock critico", "restam", "minimo recomendado", "saida media",
        "alertas para verificar", "itens a verificar", "retire da venda",
        "registe perdas", "priorize a reposicao", "vence em", "vencido ha",
        "esgotado", "cobertura", " desde ", " produtos com ", "vendas", "venda acima", "saida acima",
        "media diaria", "stock atual", "faturamento", "margem de hoje",
        "descontos de hoje", "caixa ", "hoje:", "habitual:",
    )
    if not any(marker in normalized for marker in portuguese_markers):
        return ""

    # These engine messages are compared through their accent-free form so
    # older source files with legacy Windows encoding still localise safely.
    engine_static = {
        "vendas de hoje muito abaixo da media.": {
            "en": "Sales today are far below average.", "fr": "Les ventes d'aujourd'hui sont bien inférieures à la moyenne.", "de": "Die heutigen Verkäufe liegen deutlich unter dem Durchschnitt.", "es": "Las ventas de hoy están muy por debajo de la media.", "zh": "今日销售额远低于平均水平。",
        },
        "vendas de hoje abaixo da media.": {
            "en": "Sales today are below average.", "fr": "Les ventes d'aujourd'hui sont inférieures à la moyenne.", "de": "Die heutigen Verkäufe liegen unter dem Durchschnitt.", "es": "Las ventas de hoy están por debajo de la media.", "zh": "今日销售额低于平均水平。",
        },
        "vendas de hoje acima da media.": {
            "en": "Sales today are above average.", "fr": "Les ventes d'aujourd'hui sont supérieures à la moyenne.", "de": "Die heutigen Verkäufe liegen über dem Durchschnitt.", "es": "Las ventas de hoy están por encima de la media.", "zh": "今日销售额高于平均水平。",
        },
        "faturamento de hoje muito abaixo do habitual.": {
            "en": "Revenue today is far below normal.", "fr": "Le chiffre d'affaires d'aujourd'hui est bien inférieur à la normale.", "de": "Der heutige Umsatz liegt deutlich unter dem Üblichen.", "es": "Los ingresos de hoy están muy por debajo de lo habitual.", "zh": "今日营业额远低于正常水平。",
        },
        "faturamento de hoje acima do habitual.": {
            "en": "Revenue today is above normal.", "fr": "Le chiffre d'affaires d'aujourd'hui est supérieur à la normale.", "de": "Der heutige Umsatz liegt über dem Üblichen.", "es": "Los ingresos de hoy están por encima de lo habitual.", "zh": "今日营业额高于正常水平。",
        },
        "margem de hoje abaixo do habitual.": {
            "en": "Today's margin is below normal.", "fr": "La marge d'aujourd'hui est inférieure à la normale.", "de": "Die heutige Marge liegt unter dem Üblichen.", "es": "El margen de hoy está por debajo de lo habitual.", "zh": "今日利润率低于正常水平。",
        },
        "descontos de hoje acima do habitual.": {
            "en": "Today's discounts are above normal.", "fr": "Les remises d'aujourd'hui sont supérieures à la normale.", "de": "Die heutigen Rabatte liegen über dem Üblichen.", "es": "Los descuentos de hoy están por encima de lo habitual.", "zh": "今日折扣高于正常水平。",
        },
    }
    translated_static = engine_static.get(normalized, {}).get(language)
    if translated_static:
        return translated_static

    product_templates = (
        (r"^(.+): saida acima do normal hoje\.$", {
            "en": "{name}: above-normal usage today.", "fr": "{name} : sortie supérieure à la normale aujourd'hui.", "de": "{name}: heute übernormaler Verbrauch.", "es": "{name}: salida por encima de lo normal hoy.", "zh": "{name}：今日消耗高于正常水平。",
        }),
        (r"^(.+): venda acima do normal hoje\.$", {
            "en": "{name}: above-normal sales today.", "fr": "{name} : ventes supérieures à la normale aujourd'hui.", "de": "{name}: heute übernormale Verkäufe.", "es": "{name}: ventas por encima de lo normal hoy.", "zh": "{name}：今日销售高于正常水平。",
        }),
        (r"^(.+): sem vendas ha (\d+) dias\.$", {
            "en": "{name}: no sales for {count} days.", "fr": "{name} : aucune vente depuis {count} jours.", "de": "{name}: seit {count} Tagen keine Verkäufe.", "es": "{name}: sin ventas desde hace {count} días.", "zh": "{name}：已 {count} 天没有销售。",
        }),
    )
    for pattern, templates in product_templates:
        match = re.match(pattern, normalized, re.IGNORECASE)
        if match and templates.get(language):
            original_name = text.split(":", 1)[0].strip()
            return templates[language].format(name=original_name, count=match.group(2) if match.lastindex and match.lastindex > 1 else "")

    alert_summary = re.match(r"^(\d+)\s+alertas?\s+para\s+verificar\.\s*(\d+)\s+criticos?\.$", normalized)
    if alert_summary:
        total, critical = alert_summary.groups()
        return {
            "en": f"{total} alerts to review. {critical} critical.",
            "fr": f"{total} alertes à vérifier. {critical} critiques.",
            "de": f"{total} Warnungen zu prüfen. {critical} kritisch.",
            "es": f"{total} alertas por revisar. {critical} críticos.",
            "zh": f"{total} 条警报待检查。{critical} 条严重。",
        }.get(language, "")

    phrases = {
        "en": {
            "Stock crítico": "Critical stock", "Stock critico": "Critical stock",
            "Mínimo recomendado": "Recommended minimum", "Saída média": "Average daily usage",
            "Itens a verificar": "Items to review", "Resumo": "Summary", "Ação": "Action",
            "Acoes recomendadas": "Recommended actions", "Produtos": "Products",
            "Retire da venda todos os itens vencidos.": "Remove all expired items from sale.",
            "Registe perdas com evidencia e atualize o stock.": "Record losses with evidence and update stock.",
            "Priorize a reposição dos itens esgotados e críticos.": "Prioritize replenishing out-of-stock and critical items.",
            "Confirme preço e prazo com o fornecedor ainda hoje.": "Confirm price and lead time with the supplier today.",
            "Priorize a venda dos itens mais próximos do vencimento.": "Prioritize selling the items closest to expiry.",
            "Considere promoção rápida se o stock for elevado.": "Consider a quick promotion if stock is high.",
            "para verificar": "to review", "críticos": "critical", "crítico": "critical",
            "alertas": "alerts", "alerta": "alert", "unidades": "units", "unidade": "unit",
            "quilogramas": "kilograms", "quilograma": "kilogram", "por dia": "per day",
            "desde": "since", "esgotado": "out of stock", "cobertura": "coverage",
        },
        "fr": {
            "Stock crítico": "Stock critique", "Stock critico": "Stock critique",
            "Mínimo recomendado": "Minimum recommandé", "Saída média": "Sortie moyenne quotidienne",
            "Itens a verificar": "Éléments à vérifier", "Resumo": "Résumé", "Ação": "Action",
            "Acoes recomendadas": "Actions recommandées", "Produtos": "Produits",
            "Retire da venda todos os itens vencidos.": "Retirez de la vente tous les articles expirés.",
            "Registe perdas com evidencia e atualize o stock.": "Enregistrez les pertes avec preuve et mettez le stock à jour.",
            "Priorize a reposição dos itens esgotados e críticos.": "Donnez la priorité au réapprovisionnement des articles épuisés et critiques.",
            "Confirme preço e prazo com o fornecedor ainda hoje.": "Confirmez aujourd'hui le prix et le délai avec le fournisseur.",
            "Priorize a venda dos itens mais próximos do vencimento.": "Priorisez la vente des articles les plus proches de l'expiration.",
            "Considere promoção rápida se o stock for elevado.": "Envisagez une promotion rapide si le stock est élevé.",
            "para verificar": "à vérifier", "críticos": "critiques", "crítico": "critique",
            "alertas": "alertes", "alerta": "alerte", "unidades": "unités", "unidade": "unité",
            "quilogramas": "kilogrammes", "quilograma": "kilogramme", "por dia": "par jour",
            "desde": "depuis", "esgotado": "épuisé", "cobertura": "couverture",
        },
        "de": {
            "Stock crítico": "Kritischer Bestand", "Stock critico": "Kritischer Bestand",
            "Mínimo recomendado": "Empfohlener Mindestbestand", "Saída média": "Durchschnittlicher Tagesverbrauch",
            "Itens a verificar": "Zu prüfende Artikel", "Resumo": "Zusammenfassung", "Ação": "Aktion",
            "Acoes recomendadas": "Empfohlene Maßnahmen", "Produtos": "Produkte",
            "Retire da venda todos os itens vencidos.": "Nehmen Sie alle abgelaufenen Artikel aus dem Verkauf.",
            "Registe perdas com evidencia e atualize o stock.": "Erfassen Sie Verluste mit Nachweis und aktualisieren Sie den Bestand.",
            "Priorize a reposição dos itens esgotados e críticos.": "Priorisieren Sie die Nachbestellung ausverkaufter und kritischer Artikel.",
            "Confirme preço e prazo com o fornecedor ainda hoje.": "Bestätigen Sie heute Preis und Lieferzeit mit dem Lieferanten.",
            "Priorize a venda dos itens mais próximos do vencimento.": "Priorisieren Sie den Verkauf der Artikel mit nahem Ablaufdatum.",
            "Considere promoção rápida se o stock for elevado.": "Erwägen Sie eine schnelle Aktion bei hohem Bestand.",
            "para verificar": "zu prüfen", "críticos": "kritisch", "crítico": "kritisch",
            "alertas": "Warnungen", "alerta": "Warnung", "unidades": "Einheiten", "unidade": "Einheit",
            "quilogramas": "Kilogramm", "quilograma": "Kilogramm", "por dia": "pro Tag",
            "desde": "seit", "esgotado": "ausverkauft", "cobertura": "Reichweite",
        },
        "es": {
            "Stock crítico": "Stock crítico", "Stock critico": "Stock crítico",
            "Mínimo recomendado": "Mínimo recomendado", "Saída média": "Salida media diaria",
            "Itens a verificar": "Artículos por revisar", "Resumo": "Resumen", "Ação": "Acción",
            "Acoes recomendadas": "Acciones recomendadas", "Produtos": "Productos",
            "Retire da venda todos os itens vencidos.": "Retire de la venta todos los artículos vencidos.",
            "Registe perdas com evidencia e atualize o stock.": "Registre las pérdidas con evidencia y actualice el stock.",
            "Priorize a reposição dos itens esgotados e críticos.": "Priorice la reposición de los artículos agotados y críticos.",
            "Confirme preço e prazo com o fornecedor ainda hoje.": "Confirme hoy el precio y el plazo con el proveedor.",
            "Priorize a venda dos itens mais próximos do vencimento.": "Priorice la venta de los artículos más próximos al vencimiento.",
            "Considere promoção rápida se o stock for elevado.": "Considere una promoción rápida si el stock es alto.",
            "para verificar": "por revisar", "críticos": "críticos", "crítico": "crítico",
            "alertas": "alertas", "alerta": "alerta", "unidades": "unidades", "unidade": "unidad",
            "quilogramas": "kilogramos", "quilograma": "kilogramo", "por dia": "por día",
            "desde": "desde", "esgotado": "agotado", "cobertura": "cobertura",
        },
        "zh": {
            "Stock crítico": "库存严重不足", "Stock critico": "库存严重不足",
            "Mínimo recomendado": "建议最低库存", "Saída média": "日均消耗",
            "Itens a verificar": "待检查项目", "Resumo": "摘要", "Ação": "操作",
            "Acoes recomendadas": "建议操作", "Produtos": "商品",
            "Retire da venda todos os itens vencidos.": "将所有过期商品下架。",
            "Registe perdas com evidencia e atualize o stock.": "登记有凭据的损耗并更新库存。",
            "Priorize a reposição dos itens esgotados e críticos.": "优先补充缺货和库存严重不足的商品。",
            "Confirme preço e prazo com o fornecedor ainda hoje.": "今天与供应商确认价格和交期。",
            "Priorize a venda dos itens mais próximos do vencimento.": "优先销售最接近到期日的商品。",
            "Considere promoção rápida se o stock for elevado.": "库存较高时可考虑快速促销。",
            "para verificar": "待检查", "críticos": "严重", "crítico": "严重",
            "alertas": "条警报", "alerta": "条警报", "unidades": "件", "unidade": "件",
            "quilogramas": "千克", "quilograma": "千克", "por dia": "每天",
            "desde": "自", "esgotado": "缺货", "cobertura": "覆盖天数",
        },
    }.get(language)
    if not phrases:
        return ""

    result = text
    # Full sentences first; then generic fragments inside records assembled by
    # the dashboard.  Word boundaries stop us from altering product names.
    for original, translated in sorted(phrases.items(), key=lambda item: len(item[0]), reverse=True):
        result = re.sub(rf"(?<!\w){re.escape(original)}(?!\w)", translated, result, flags=re.IGNORECASE)

    # Portuguese sentence order needs a small grammatical adjustment in the
    # English, French, German and Spanish interfaces.
    quantity_pattern = r"Restam\s+([\d.,]+\s+(?:units?|unidades?|kilograms?|quilogramas?|unités|Einheiten|unidades|件|千克))"
    if language == "en":
        result = re.sub(quantity_pattern, r"\1 remaining", result, flags=re.IGNORECASE)
    elif language == "fr":
        result = re.sub(quantity_pattern, r"Il reste \1", result, flags=re.IGNORECASE)
    elif language == "de":
        result = re.sub(quantity_pattern, r"Noch \1 verfügbar", result, flags=re.IGNORECASE)
    elif language == "es":
        result = re.sub(quantity_pattern, r"Quedan \1", result, flags=re.IGNORECASE)
    elif language == "zh":
        result = re.sub(quantity_pattern, r"剩余 \1", result, flags=re.IGNORECASE)

    # Dynamic analysis messages from AI.engine.  They deliberately keep the
    # terminal and product identifiers captured by the expression.
    runtime_patterns = {
        "en": (
            (r"^Sales today are far below average\.$", "Sales today are far below average."),
            (r"^Vendas de hoje muito abaixo da média\.$", "Sales today are far below average."),
            (r"^Vendas de hoje abaixo da média\.$", "Sales today are below average."),
            (r"^Vendas de hoje acima da média\.$", "Sales today are above average."),
            (r"^Revenue today is far below normal\.$", "Revenue today is far below normal."),
            (r"^Faturamento de hoje muito abaixo do habitual\.$", "Revenue today is far below normal."),
            (r"^Faturamento de hoje acima do habitual\.$", "Revenue today is above normal."),
            (r"^Margem de hoje abaixo do habitual\.$", "Today's margin is below normal."),
            (r"^Descontos de hoje acima do habitual\.$", "Today's discounts are above normal."),
            (r"^Há descontos hoje, mas ainda não há histórico para comparar\.$", "There are discounts today, but no history is available for comparison yet."),
            (r"^(.+): saída acima do normal hoje\.$", r"\1: above-normal usage today."),
            (r"^(.+): venda acima do normal hoje\.$", r"\1: above-normal sales today."),
            (r"^(.+): sem vendas há (\d+) dias\.$", r"\1: no sales for \2 days."),
            (r"^Caixa (.+): sem vendas hoje\.$", r"Register \1: no sales today."),
            (r"^Caixa (.+): sem vendas há (\d+) minutos\.$", r"Register \1: no sales for \2 minutes."),
            (r"\bHoje:\s*", "Today: "), (r"\bMédia semanal:\s*", "Weekly average: "),
            (r"\bMédia diária:\s*", "Daily average: "), (r"\bStock atual:\s*", "Current stock: "),
            (r"\bLimite:\s*", "Limit: "), (r"\bHabitual:\s*", "Usual: "),
            (r"\bDesconto médio de hoje:\s*", "Average discount today: "),
            (r"\bmeticais\b", "MZN"), (r"\bvendas\b", "sales"),
        ),
        "fr": (
            (r"^Vendas de hoje muito abaixo da média\.$", "Les ventes d'aujourd'hui sont bien inférieures à la moyenne."),
            (r"^Vendas de hoje abaixo da média\.$", "Les ventes d'aujourd'hui sont inférieures à la moyenne."),
            (r"^Vendas de hoje acima da média\.$", "Les ventes d'aujourd'hui sont supérieures à la moyenne."),
            (r"^Faturamento de hoje muito abaixo do habitual\.$", "Le chiffre d'affaires d'aujourd'hui est bien inférieur à la normale."),
            (r"^Faturamento de hoje acima do habitual\.$", "Le chiffre d'affaires d'aujourd'hui est supérieur à la normale."),
            (r"^Margem de hoje abaixo do habitual\.$", "La marge d'aujourd'hui est inférieure à la normale."),
            (r"^Descontos de hoje acima do habitual\.$", "Les remises d'aujourd'hui sont supérieures à la normale."),
            (r"^Há descontos hoje, mas ainda não há histórico para comparar\.$", "Il y a des remises aujourd'hui, mais aucun historique n'est encore disponible pour comparer."),
            (r"^(.+): saída acima do normal hoje\.$", r"\1 : sortie supérieure à la normale aujourd'hui."),
            (r"^(.+): venda acima do normal hoje\.$", r"\1 : ventes supérieures à la normale aujourd'hui."),
            (r"^(.+): sem vendas há (\d+) dias\.$", r"\1 : aucune vente depuis \2 jours."),
            (r"^Caixa (.+): sem vendas hoje\.$", r"Caisse \1 : aucune vente aujourd'hui."),
            (r"^Caixa (.+): sem vendas há (\d+) minutos\.$", r"Caisse \1 : aucune vente depuis \2 minutes."),
            (r"\bHoje:\s*", "Aujourd'hui : "), (r"\bMédia semanal:\s*", "Moyenne hebdomadaire : "),
            (r"\bMédia diária:\s*", "Moyenne quotidienne : "), (r"\bStock atual:\s*", "Stock actuel : "),
            (r"\bLimite:\s*", "Limite : "), (r"\bHabitual:\s*", "Habituel : "),
            (r"\bDesconto médio de hoje:\s*", "Remise moyenne aujourd'hui : "),
            (r"\bmeticais\b", "MZN"), (r"\bvendas\b", "ventes"),
        ),
        "de": (
            (r"^Vendas de hoje muito abaixo da média\.$", "Die heutigen Verkäufe liegen deutlich unter dem Durchschnitt."),
            (r"^Vendas de hoje abaixo da média\.$", "Die heutigen Verkäufe liegen unter dem Durchschnitt."),
            (r"^Vendas de hoje acima da média\.$", "Die heutigen Verkäufe liegen über dem Durchschnitt."),
            (r"^Faturamento de hoje muito abaixo do habitual\.$", "Der heutige Umsatz liegt deutlich unter dem Üblichen."),
            (r"^Faturamento de hoje acima do habitual\.$", "Der heutige Umsatz liegt über dem Üblichen."),
            (r"^Margem de hoje abaixo do habitual\.$", "Die heutige Marge liegt unter dem Üblichen."),
            (r"^Descontos de hoje acima do habitual\.$", "Die heutigen Rabatte liegen über dem Üblichen."),
            (r"^Há descontos hoje, mas ainda não há histórico para comparar\.$", "Heute gibt es Rabatte, aber noch keinen Verlauf zum Vergleich."),
            (r"^(.+): saída acima do normal hoje\.$", r"\1: heute übernormaler Verbrauch."),
            (r"^(.+): venda acima do normal hoje\.$", r"\1: heute übernormale Verkäufe."),
            (r"^(.+): sem vendas há (\d+) dias\.$", r"\1: seit \2 Tagen keine Verkäufe."),
            (r"^Caixa (.+): sem vendas hoje\.$", r"Kasse \1: heute keine Verkäufe."),
            (r"^Caixa (.+): sem vendas há (\d+) minutos\.$", r"Kasse \1: seit \2 Minuten keine Verkäufe."),
            (r"\bHoje:\s*", "Heute: "), (r"\bMédia semanal:\s*", "Wochendurchschnitt: "),
            (r"\bMédia diária:\s*", "Tagesdurchschnitt: "), (r"\bStock atual:\s*", "Aktueller Bestand: "),
            (r"\bLimite:\s*", "Grenze: "), (r"\bHabitual:\s*", "Üblich: "),
            (r"\bDesconto médio de hoje:\s*", "Durchschnittlicher heutiger Rabatt: "),
            (r"\bmeticais\b", "MZN"), (r"\bvendas\b", "Verkäufe"),
        ),
        "es": (
            (r"^Vendas de hoje muito abaixo da média\.$", "Las ventas de hoy están muy por debajo de la media."),
            (r"^Vendas de hoje abaixo da média\.$", "Las ventas de hoy están por debajo de la media."),
            (r"^Vendas de hoje acima da média\.$", "Las ventas de hoy están por encima de la media."),
            (r"^Faturamento de hoje muito abaixo do habitual\.$", "Los ingresos de hoy están muy por debajo de lo habitual."),
            (r"^Faturamento de hoje acima do habitual\.$", "Los ingresos de hoy están por encima de lo habitual."),
            (r"^Margem de hoje abaixo do habitual\.$", "El margen de hoy está por debajo de lo habitual."),
            (r"^Descontos de hoje acima do habitual\.$", "Los descuentos de hoy están por encima de lo habitual."),
            (r"^Há descontos hoje, mas ainda não há histórico para comparar\.$", "Hay descuentos hoy, pero todavía no hay historial para comparar."),
            (r"^(.+): saída acima do normal hoje\.$", r"\1: salida por encima de lo normal hoy."),
            (r"^(.+): venda acima do normal hoje\.$", r"\1: ventas por encima de lo normal hoy."),
            (r"^(.+): sem vendas há (\d+) dias\.$", r"\1: sin ventas desde hace \2 días."),
            (r"^Caixa (.+): sem vendas hoje\.$", r"Caja \1: sin ventas hoy."),
            (r"^Caixa (.+): sem vendas há (\d+) minutos\.$", r"Caja \1: sin ventas desde hace \2 minutos."),
            (r"\bHoje:\s*", "Hoy: "), (r"\bMédia semanal:\s*", "Media semanal: "),
            (r"\bMédia diária:\s*", "Media diaria: "), (r"\bStock atual:\s*", "Stock actual: "),
            (r"\bLimite:\s*", "Límite: "), (r"\bHabitual:\s*", "Habitual: "),
            (r"\bDesconto médio de hoje:\s*", "Descuento medio de hoy: "),
            (r"\bmeticais\b", "MZN"), (r"\bvendas\b", "ventas"),
        ),
        "zh": (
            (r"^Vendas de hoje muito abaixo da média\.$", "今日销售额远低于平均水平。"),
            (r"^Vendas de hoje abaixo da média\.$", "今日销售额低于平均水平。"),
            (r"^Vendas de hoje acima da média\.$", "今日销售额高于平均水平。"),
            (r"^Faturamento de hoje muito abaixo do habitual\.$", "今日营业额远低于正常水平。"),
            (r"^Faturamento de hoje acima do habitual\.$", "今日营业额高于正常水平。"),
            (r"^Margem de hoje abaixo do habitual\.$", "今日利润率低于正常水平。"),
            (r"^Descontos de hoje acima do habitual\.$", "今日折扣高于正常水平。"),
            (r"^Há descontos hoje, mas ainda não há histórico para comparar\.$", "今天有折扣，但尚无历史记录可供比较。"),
            (r"^(.+): saída acima do normal hoje\.$", r"\1：今日消耗高于正常水平。"),
            (r"^(.+): venda acima do normal hoje\.$", r"\1：今日销售高于正常水平。"),
            (r"^(.+): sem vendas há (\d+) dias\.$", r"\1：已 \2 天没有销售。"),
            (r"^Caixa (.+): sem vendas hoje\.$", r"收银台 \1：今日没有销售。"),
            (r"^Caixa (.+): sem vendas há (\d+) minutos\.$", r"收银台 \1：已 \2 分钟没有销售。"),
            (r"\bHoje:\s*", "今日："), (r"\bMédia semanal:\s*", "周平均："),
            (r"\bMédia diária:\s*", "日平均："), (r"\bStock atual:\s*", "当前库存："),
            (r"\bLimite:\s*", "限制："), (r"\bHabitual:\s*", "通常："),
            (r"\bDesconto médio de hoje:\s*", "今日平均折扣："),
            (r"\bmeticais\b", "MZN"), (r"\bvendas\b", "笔销售"),
        ),
    }
    for pattern, replacement in runtime_patterns.get(language, ()):
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)

    # Label fragments are intentionally encoded with character classes rather
    # than literal accents: the application still contains a few legacy files
    # saved with a Windows code page.
    detail_labels = {
        "en": ((r"M[^\s:]*dia semanal:\s*", "Weekly average: "), (r"M[^\s:]*dia di[^\s:]*ria:\s*", "Daily average: "), (r"M[^\s:]*dia:\s*", "Average: ")),
        "fr": ((r"M[^\s:]*dia semanal:\s*", "Moyenne hebdomadaire : "), (r"M[^\s:]*dia di[^\s:]*ria:\s*", "Moyenne quotidienne : "), (r"M[^\s:]*dia:\s*", "Moyenne : ")),
        "de": ((r"M[^\s:]*dia semanal:\s*", "Wochendurchschnitt: "), (r"M[^\s:]*dia di[^\s:]*ria:\s*", "Tagesdurchschnitt: "), (r"M[^\s:]*dia:\s*", "Durchschnitt: ")),
        "es": ((r"M[^\s:]*dia semanal:\s*", "Media semanal: "), (r"M[^\s:]*dia di[^\s:]*ria:\s*", "Media diaria: "), (r"M[^\s:]*dia:\s*", "Media: ")),
        "zh": ((r"M[^\s:]*dia semanal:\s*", "周平均："), (r"M[^\s:]*dia di[^\s:]*ria:\s*", "日平均："), (r"M[^\s:]*dia:\s*", "平均：")),
    }
    for pattern, replacement in detail_labels.get(language, ()):
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)

    return result if result != text else ""


def _translate_dynamic_text(normalized_source: str, language: str) -> str:
    alert_match = re.match(r"^(\d+)\s+alerta\(s\)\s+pendente\(s\)$", normalized_source, re.I)
    if alert_match:
        count = alert_match.group(1)
        return {
            "en": f"{count} pending alert(s)",
            "fr": f"{count} alerte(s) en attente",
            "de": f"{count} ausstehende Warnung(en)",
            "es": f"{count} alerta(s) pendiente(s)",
            "zh": f"{count} 条待处理警报",
        }.get(language, "")

    products_match = re.match(r"^(\d+)\s+produtos?$", normalized_source, re.I)
    if products_match:
        count = products_match.group(1)
        return {
            "en": f"{count} products",
            "fr": f"{count} produits",
            "de": f"{count} Produkte",
            "es": f"{count} productos",
            "zh": f"{count} 个商品",
        }.get(language, "")

    items_match = re.match(r"^(\d+)\s+itens?$", normalized_source, re.I)
    if items_match:
        count = items_match.group(1)
        return {
            "en": f"{count} items",
            "fr": f"{count} articles",
            "de": f"{count} Artikel",
            "es": f"{count} items",
            "zh": f"{count} 项",
        }.get(language, "")

    days_match = re.match(r"^(\d+)\s+dias?$", normalized_source, re.I)
    if days_match:
        count = days_match.group(1)
        return {
            "en": f"{count} days",
            "fr": f"{count} jours",
            "de": f"{count} Tage",
            "es": f"{count} dias",
            "zh": f"{count} 天",
        }.get(language, "")

    return ""


# Frases comuns da UI (fallback quando texts.json ainda nao tem a entrada).
# Chave = texto PT sem acentos, normalizado (espacos colapsados).
_BUILTIN_UI_PHRASES: dict[str, dict[str, str]] = {
    "painel do administrador": {
        "en": "Administrator Dashboard",
        "fr": "Tableau de bord administrateur",
        "de": "Administrator-Dashboard",
        "es": "Panel del administrador",
        "zh": "管理员面板",
    },
    "resumo da loja": {
        "en": "Store overview",
        "fr": "Apercu du magasin",
        "de": "Ladenubersicht",
        "es": "Resumen de la tienda",
        "zh": "店铺概览",
    },
    "a carregar dados...": {
        "en": "Loading data...",
        "fr": "Chargement des donnees...",
        "de": "Daten werden geladen...",
        "es": "Cargando datos...",
        "zh": "正在加载数据...",
    },
    "dados actualizados": {
        "en": "Data updated",
        "fr": "Donnees actualisees",
        "de": "Daten aktualisiert",
        "es": "Datos actualizados",
        "zh": "数据已更新",
    },
    "dados atualizados": {
        "en": "Data updated",
        "fr": "Donnees actualisees",
        "de": "Daten aktualisiert",
        "es": "Datos actualizados",
        "zh": "数据已更新",
    },
    "alertas prioritarios": {
        "en": "Priority alerts",
        "fr": "Alertes prioritaires",
        "de": "Prioritare Warnungen",
        "es": "Alertas prioritarias",
        "zh": "优先警报",
    },
    "destaques": {
        "en": "Highlights",
        "fr": "Faits marquants",
        "de": "Highlights",
        "es": "Destacados",
        "zh": "亮点",
    },
    "resumo": {
        "en": "Summary",
        "fr": "Resume",
        "de": "Zusammenfassung",
        "es": "Resumen",
        "zh": "摘要",
    },
    "acao": {
        "en": "Action", "fr": "Action", "de": "Aktion", "es": "Accion", "zh": "操作",
    },
    "acoes recomendadas": {
        "en": "Recommended actions", "fr": "Actions recommandees", "de": "Empfohlene Massnahmen", "es": "Acciones recomendadas", "zh": "建议操作",
    },
    "descricao completa": {
        "en": "Full description", "fr": "Description complete", "de": "Vollstandige Beschreibung", "es": "Descripcion completa", "zh": "完整说明",
    },
    "pontos observados": {
        "en": "Observed points", "fr": "Points observes", "de": "Beobachtete Punkte", "es": "Puntos observados", "zh": "观察事项",
    },
    "acessos": {
        "en": "Access",
        "fr": "Acces",
        "de": "Zugriff",
        "es": "Accesos",
        "zh": "快捷入口",
    },
    "adicionar": {
        "en": "Add",
        "fr": "Ajouter",
        "de": "Hinzufugen",
        "es": "Anadir",
        "zh": "添加",
    },
    "desempenho": {
        "en": "Performance",
        "fr": "Performance",
        "de": "Leistung",
        "es": "Rendimiento",
        "zh": "业绩",
    },
    "faturacao": {
        "en": "Revenue",
        "fr": "Chiffre d'affaires",
        "de": "Umsatz",
        "es": "Facturacion",
        "zh": "营业额",
    },
    "quantidade": {
        "en": "Quantity",
        "fr": "Quantite",
        "de": "Menge",
        "es": "Cantidad",
        "zh": "数量",
    },
    "tickets": {
        "en": "Tickets",
        "fr": "Tickets",
        "de": "Tickets",
        "es": "Tickets",
        "zh": "票据",
    },
    "7 dias": {
        "en": "7 days",
        "fr": "7 jours",
        "de": "7 Tage",
        "es": "7 dias",
        "zh": "7天",
    },
    "14 dias": {
        "en": "14 days",
        "fr": "14 jours",
        "de": "14 Tage",
        "es": "14 dias",
        "zh": "14天",
    },
    "30 dias": {
        "en": "30 days",
        "fr": "30 jours",
        "de": "30 Tage",
        "es": "30 dias",
        "zh": "30天",
    },
    "90 dias": {
        "en": "90 days",
        "fr": "90 jours",
        "de": "90 Tage",
        "es": "90 dias",
        "zh": "90天",
    },
    "ver grafico de desempenho": {
        "en": "View performance chart",
        "fr": "Voir le graphique de performance",
        "de": "Leistungsdiagramm anzeigen",
        "es": "Ver grafico de rendimiento",
        "zh": "查看业绩图表",
    },
    "resumo do dia": {
        "en": "Today's summary",
        "fr": "Resume du jour",
        "de": "Tagesubersicht",
        "es": "Resumen del dia",
        "zh": "今日摘要",
    },
    "vendas de hoje": {
        "en": "Today's sales",
        "fr": "Ventes du jour",
        "de": "Heutige Verkaufe",
        "es": "Ventas de hoy",
        "zh": "今日销售",
    },
    "total faturado no dia": {
        "en": "Total revenue for the day",
        "fr": "Total facture aujourd'hui",
        "de": "Tagesumsatz",
        "es": "Total facturado del dia",
        "zh": "当日总收入",
    },
    "vendas concluidas": {
        "en": "Completed sales",
        "fr": "Ventes terminees",
        "de": "Abgeschlossene Verkaufe",
        "es": "Ventas completadas",
        "zh": "已完成销售",
    },
    "stock critico": {
        "en": "Critical stock",
        "fr": "Stock critique",
        "de": "Kritischer Bestand",
        "es": "Stock critico",
        "zh": "库存告急",
    },
    "produtos a repor": {
        "en": "Products to restock",
        "fr": "Produits a reapprovisionner",
        "de": "Nachzubestellende Produkte",
        "es": "Productos a reponer",
        "zh": "需补货的商品",
    },
    "perdas": {
        "en": "Losses",
        "fr": "Pertes",
        "de": "Verluste",
        "es": "Perdidas",
        "zh": "损耗",
    },
    "valor registado": {
        "en": "Registered value",
        "fr": "Valeur enregistree",
        "de": "Erfasster Wert",
        "es": "Valor registrado",
        "zh": "已登记金额",
    },
    "atualizar painel": {
        "en": "Refresh panel",
        "fr": "Actualiser le panneau",
        "de": "Panel aktualisieren",
        "es": "Actualizar panel",
        "zh": "刷新面板",
    },
    "recarregar indicadores": {
        "en": "Reload indicators",
        "fr": "Recharger les indicateurs",
        "de": "Kennzahlen neu laden",
        "es": "Recargar indicadores",
        "zh": "重新加载指标",
    },
    "acessos rapidos": {
        "en": "Quick access",
        "fr": "Acces rapides",
        "de": "Schnellzugriff",
        "es": "Accesos rapidos",
        "zh": "快捷入口",
    },
    "gestao de produtos": {
        "en": "Product management", "fr": "Gestion des produits", "de": "Produktverwaltung", "es": "Gestion de productos", "zh": "商品管理",
    },
    "todas as categorias": {
        "en": "All categories", "fr": "Toutes les catégories", "de": "Alle Kategorien", "es": "Todas las categorías", "zh": "所有类别",
    },
    "atualizar": {
        "en": "Refresh", "fr": "Actualiser", "de": "Aktualisieren", "es": "Actualizar", "zh": "刷新",
    },
    "adicionar": {
        "en": "Add", "fr": "Ajouter", "de": "Hinzufügen", "es": "Añadir", "zh": "添加",
    },
    "arquivados": {
        "en": "Archived", "fr": "Archivés", "de": "Archiviert", "es": "Archivados", "zh": "已归档",
    },
    "sugestoes de compras": {
        "en": "Purchase suggestions", "fr": "Suggestions d'achat", "de": "Kaufvorschläge", "es": "Sugerencias de compra", "zh": "采购建议",
    },
    "compras": {
        "en": "Purchases", "fr": "Achats", "de": "Einkauf", "es": "Compras", "zh": "采购",
    },
    "inventario": {
        "en": "Inventory", "fr": "Inventaire", "de": "Inventar", "es": "Inventario", "zh": "库存盘点",
    },
    "anterior": {
        "en": "Previous", "fr": "Précédent", "de": "Zurück", "es": "Anterior", "zh": "上一页",
    },
    "seguinte": {
        "en": "Next", "fr": "Suivant", "de": "Weiter", "es": "Siguiente", "zh": "下一页",
    },
    "produtos": {
        "en": "Products",
        "fr": "Produits",
        "de": "Produkte",
        "es": "Productos",
        "zh": "商品",
    },
    "catalogo e precos": {
        "en": "Catalog and prices",
        "fr": "Catalogue et prix",
        "de": "Katalog und Preise",
        "es": "Catalogo y precios",
        "zh": "目录与价格",
    },
    "reposicao": {
        "en": "Restock",
        "fr": "Reapprovisionnement",
        "de": "Nachbestellung",
        "es": "Reabastecimiento",
        "zh": "补货",
    },
    "entrada de stock": {
        "en": "Stock intake",
        "fr": "Entree de stock",
        "de": "Wareneingang",
        "es": "Entrada de stock",
        "zh": "入库",
    },
    "quebras e ajustes": {
        "en": "Breakage and adjustments",
        "fr": "Casses et ajustements",
        "de": "Bruch und Anpassungen",
        "es": "Roturas y ajustes",
        "zh": "破损与调整",
    },
    "relatorios": {
        "en": "Reports",
        "fr": "Rapports",
        "de": "Berichte",
        "es": "Informes",
        "zh": "报表",
    },
    "pdfs e analises": {
        "en": "PDFs and analytics",
        "fr": "PDF et analyses",
        "de": "PDFs und Analysen",
        "es": "PDFs y analisis",
        "zh": "PDF与分析",
    },
    "utilizadores": {
        "en": "Users",
        "fr": "Utilisateurs",
        "de": "Benutzer",
        "es": "Usuarios",
        "zh": "用户",
    },
    "acessos e permissoes": {
        "en": "Access and permissions",
        "fr": "Acces et permissions",
        "de": "Zugriff und Berechtigungen",
        "es": "Accesos y permisos",
        "zh": "访问与权限",
    },
    "definicoes": {
        "en": "Settings",
        "fr": "Parametres",
        "de": "Einstellungen",
        "es": "Ajustes",
        "zh": "设置",
    },
    "sistema e preferencias": {
        "en": "System and preferences",
        "fr": "Systeme et preferences",
        "de": "System und Einstellungen",
        "es": "Sistema y preferencias",
        "zh": "系统与偏好",
    },
    "abrir": {
        "en": "Open",
        "fr": "Ouvrir",
        "de": "Offnen",
        "es": "Abrir",
        "zh": "打开",
    },
    "sem destaques": {
        "en": "No highlights",
        "fr": "Aucun fait marquant",
        "de": "Keine Highlights",
        "es": "Sin destacados",
        "zh": "暂无亮点",
    },
    "os indicadores aparecem aqui": {
        "en": "Indicators will appear here",
        "fr": "Les indicateurs apparaissent ici",
        "de": "Kennzahlen erscheinen hier",
        "es": "Los indicadores aparecen aqui",
        "zh": "指标将显示在这里",
    },
    "atualizar": {
        "en": "Refresh",
        "fr": "Actualiser",
        "de": "Aktualisieren",
        "es": "Actualizar",
        "zh": "刷新",
    },
    "idioma": {
        "en": "Language",
        "fr": "Langue",
        "de": "Sprache",
        "es": "Idioma",
        "zh": "语言",
    },
    "alertas com ia": {
        "en": "AI alerts",
        "fr": "Alertes IA",
        "de": "KI-Warnungen",
        "es": "Alertas con IA",
        "zh": "AI 警报",
    },
    "recomendacoes com ia": {
        "en": "AI recommendations",
        "fr": "Recommandations IA",
        "de": "KI-Empfehlungen",
        "es": "Recomendaciones con IA",
        "zh": "AI 推荐",
    },
    "alertas de perdas": {
        "en": "Loss alerts",
        "fr": "Alertes de pertes",
        "de": "Verlustwarnungen",
        "es": "Alertas de perdidas",
        "zh": "损耗警报",
    },
    "metricas de perdas": {
        "en": "Loss metrics",
        "fr": "Metriques de pertes",
        "de": "Verlustkennzahlen",
        "es": "Metricas de perdidas",
        "zh": "损耗指标",
    },
    "aprovacoes pendentes": {
        "en": "Pending approvals",
        "fr": "Approbations en attente",
        "de": "Ausstehende Freigaben",
        "es": "Aprobaciones pendientes",
        "zh": "待审批",
    },
    "atividade recente": {
        "en": "Recent activity",
        "fr": "Activite recente",
        "de": "Letzte Aktivitat",
        "es": "Actividad reciente",
        "zh": "最近活动",
    },
    "fechar": {
        "en": "Close",
        "fr": "Fermer",
        "de": "Schliessen",
        "es": "Cerrar",
        "zh": "关闭",
    },
    "cancelar": {
        "en": "Cancel",
        "fr": "Annuler",
        "de": "Abbrechen",
        "es": "Cancelar",
        "zh": "取消",
    },
    "eliminar": {
        "en": "Delete",
        "fr": "Supprimer",
        "de": "Loschen",
        "es": "Eliminar",
        "zh": "删除",
    },
    "hoje": {
        "en": "Today",
        "fr": "Aujourd'hui",
        "de": "Heute",
        "es": "Hoy",
        "zh": "今天",
    },

    "bom dia": {"en": "Good morning", "fr": "Bonjour", "de": "Guten Morgen", "es": "Buenos dias", "zh": "早上好"},
    "boa tarde": {"en": "Good afternoon", "fr": "Bon apres-midi", "de": "Guten Tag", "es": "Buenas tardes", "zh": "下午好"},
    "boa noite": {"en": "Good evening", "fr": "Bonsoir", "de": "Guten Abend", "es": "Buenas noches", "zh": "晚上好"},
    "itens vencidos": {"en": "expired items", "fr": "articles expires", "de": "abgelaufene Artikel", "es": "articulos vencidos", "zh": "过期商品"},
    "produtos esgotados": {"en": "out-of-stock products", "fr": "produits en rupture", "de": "ausverkaufte Produkte", "es": "productos agotados", "zh": "缺货商品"},
    "requerem atencao.": {"en": "need attention.", "fr": "necessitent une attention.", "de": "erfordern Aufmerksamkeit.", "es": "requieren atencion.", "zh": "需要关注。"},
    "hoje": {"en": "Today", "fr": "Aujourd'hui", "de": "Heute", "es": "Hoy", "zh": "今天"},
    "alertas": {"en": "Alerts", "fr": "Alertes", "de": "Warnungen", "es": "Alertas", "zh": "警报"},
    "produtos vencidos": {"en": "Expired products", "fr": "Produits expires", "de": "Abgelaufene Produkte", "es": "Productos vencidos", "zh": "过期商品"},
    "produtos esgotados": {"en": "Out of stock", "fr": "Rupture de stock", "de": "Nicht vorratig", "es": "Agotados", "zh": "缺货"},
    "vencidos": {"en": "expired", "fr": "expires", "de": "abgelaufen", "es": "vencidos", "zh": "已过期"},
    "acao imediata": {"en": "Immediate action", "fr": "Action immediate", "de": "Sofortmassnahme", "es": "Accion inmediata", "zh": "立即处理"},
    "retire os itens vencidos da area de venda.": {
        "en": "Remove expired items from the sales area.",
        "fr": "Retirez les articles expires de la zone de vente.",
        "de": "Entfernen Sie abgelaufene Artikel aus dem Verkaufsbereich.",
        "es": "Retire los articulos vencidos del area de venta.",
        "zh": "从销售区移除过期商品。",
    },
    "resumo indisponivel no momento.": {
        "en": "Summary unavailable right now.",
        "fr": "Resume indisponible pour le moment.",
        "de": "Zusammenfassung derzeit nicht verfugbar.",
        "es": "Resumen no disponible en este momento.",
        "zh": "摘要暂时不可用。",
    },
    "a atualizar dados...": {
        "en": "Updating data...",
        "fr": "Mise a jour des donnees...",
        "de": "Daten werden aktualisiert...",
        "es": "Actualizando datos...",
        "zh": "正在更新数据...",
    },
    "nao foi possivel atualizar os dados agora.": {
        "en": "Could not update data right now.",
        "fr": "Impossible de mettre a jour les donnees maintenant.",
        "de": "Daten konnten jetzt nicht aktualisiert werden.",
        "es": "No se pudieron actualizar los datos ahora.",
        "zh": "目前无法更新数据。",
    },
    "vendas, stock e alertas.": {
        "en": "Sales, stock and alerts.",
        "fr": "Ventes, stock et alertes.",
        "de": "Verkaufe, Bestand und Warnungen.",
        "es": "Ventas, stock y alertas.",
        "zh": "销售、库存与警报。",
    },
    "faturacao geral": {
        "en": "Overall revenue",
        "fr": "Chiffre d'affaires global",
        "de": "Gesamtumsatz",
        "es": "Facturacion general",
        "zh": "总营业额",
    },
    "exigem retirada imediata.": {
        "en": "require immediate removal.",
        "fr": "exigent un retrait immediat.",
        "de": "erfordern sofortige Entfernung.",
        "es": "exigen retirada inmediata.",
        "zh": "需要立即下架。",
    },
    "itens expirados": {
        "en": "Expired items",
        "fr": "Articles expires",
        "de": "Abgelaufene Artikel",
        "es": "Articulos expirados",
        "zh": "过期商品",
    },
    "ha produtos": {
        "en": "Some products",
        "fr": "Certains produits",
        "de": "Einige Produkte",
        "es": "Algunos productos",
        "zh": "部分商品",
    },
    "ja estao sem disponibilidade.": {
        "en": "are already unavailable.",
        "fr": "sont deja indisponibles.",
        "de": "sind bereits nicht verfugbar.",
        "es": "ya no estan disponibles.",
        "zh": "已无货。",
    },
    "ver menos": {"en": "Show less", "fr": "Voir moins", "de": "Weniger anzeigen", "es": "Ver menos", "zh": "收起"},
    "ver mais": {"en": "Show more", "fr": "Voir plus", "de": "Mehr anzeigen", "es": "Ver mas", "zh": "展开"},
    "registar": {"en": "Register", "fr": "Enregistrer", "de": "Erfassen", "es": "Registrar", "zh": "登记"},
    "perda(s)": {"en": "loss(es)", "fr": "perte(s)", "de": "Verlust(e)", "es": "perdida(s)", "zh": "损耗"},


    "registar perda": {"en": "Register loss", "fr": "Enregistrer la perte", "de": "Verlust erfassen", "es": "Registrar perdida", "zh": "登记损耗"},
    "registar": {"en": "Register", "fr": "Enregistrer", "de": "Erfassen", "es": "Registrar", "zh": "登记"},
    "perda(s)": {"en": "loss(es)", "fr": "perte(s)", "de": "Verlust(e)", "es": "perdida(s)", "zh": "损耗"},
    "proxima acao": {"en": "Next action", "fr": "Prochaine action", "de": "Naechste Aktion", "es": "Proxima accion", "zh": "下一步"},
    "estado atual": {"en": "Current status", "fr": "Etat actuel", "de": "Aktueller Status", "es": "Estado actual", "zh": "当前状态"},
    "nenhum produto vencido na leitura atual da home.": {
        "en": "No expired products in the current HOME scan.",
        "fr": "Aucun produit expire dans la lecture actuelle.",
        "de": "Keine abgelaufenen Produkte im aktuellen HOME-Scan.",
        "es": "Ningun producto vencido en la lectura actual.",
        "zh": "当前首页扫描中没有过期商品。",
    },
    "nenhum produto nesta prioridade agora.": {
        "en": "No products in this priority right now.",
        "fr": "Aucun produit dans cette priorite pour le moment.",
        "de": "Derzeit keine Produkte in dieser Prioritaet.",
        "es": "Ningun producto en esta prioridad ahora.",
        "zh": "当前此优先级下没有商品。",
    },
    "abra a reposicao e registe a nova entrada de stock.": {
        "en": "Open restock and register the new stock entry.",
        "fr": "Ouvrez le reapprovisionnement et enregistrez l'entree.",
        "de": "Oeffnen Sie die Nachbestellung und erfassen Sie den Zugang.",
        "es": "Abra la reposicion y registre la nueva entrada.",
        "zh": "打开补货并登记新入库。",
    },
    "registe a perda ou trate da devolucao assim que possível.": {
        "en": "Register the loss or handle the return as soon as possible.",
        "fr": "Enregistrez la perte ou traitez le retour des que possible.",
        "de": "Erfassen Sie den Verlust oder die Rueckgabe so bald wie moeglich.",
        "es": "Registre la perdida o gestione la devolucion cuanto antes.",
        "zh": "尽快登记损耗或处理退货。",
    },
    "stock": {"en": "stock", "fr": "stock", "de": "Bestand", "es": "stock", "zh": "库存"},
    "validade": {"en": "expiry", "fr": "validite", "de": "Haltbarkeit", "es": "caducidad", "zh": "有效期"},


    "ver mais": {"en": "Show more", "fr": "Voir plus", "de": "Mehr anzeigen", "es": "Ver mas", "zh": "展开"},
    "ver menos": {"en": "Show less", "fr": "Voir moins", "de": "Weniger anzeigen", "es": "Ver menos", "zh": "收起"},
    "ha mais": {"en": "There are", "fr": "Il y a encore", "de": "Es gibt noch", "es": "Hay", "zh": "还有"},
    "para consultar nos detalhes.": {
        "en": "more to check in the details.",
        "fr": "de plus a consulter dans les details.",
        "de": "weitere Details zu pruefen.",
        "es": "mas para consultar en los detalles.",
        "zh": "项详情可查看。",
    },
    "vencido em": {"en": "expired on", "fr": "expire le", "de": "abgelaufen am", "es": "vencido el", "zh": "过期于"},
    "vencido ha": {"en": "expired", "fr": "expire depuis", "de": "abgelaufen seit", "es": "vencido hace", "zh": "已过期"},
    "retire da venda.": {"en": "Remove from sale.", "fr": "Retirez de la vente.", "de": "Aus dem Verkauf nehmen.", "es": "Retire de la venta.", "zh": "从销售中下架。"},
    "dia": {"en": "day", "fr": "jour", "de": "Tag", "es": "dia", "zh": "天"},
    "dias": {"en": "days", "fr": "jours", "de": "Tage", "es": "dias", "zh": "天"},
    "unidade": {"en": "unit", "fr": "unite", "de": "Einheit", "es": "unidad", "zh": "件"},
    "unidades": {"en": "units", "fr": "unites", "de": "Einheiten", "es": "unidades", "zh": "件"},
    "quilograma": {"en": "kilogram", "fr": "kilogramme", "de": "Kilogramm", "es": "kilogramo", "zh": "公斤"},
    "quilogramas": {"en": "kilograms", "fr": "kilogrammes", "de": "Kilogramm", "es": "kilogramos", "zh": "公斤"},
    "produtos sem estoque": {"en": "Out of stock products", "fr": "Produits en rupture", "de": "Nicht vorratige Produkte", "es": "Productos sin stock", "zh": "缺货商品"},
    "produtos com estoque baixo": {"en": "Low stock products", "fr": "Produits a stock faible", "de": "Produkte mit niedrigem Bestand", "es": "Productos con stock bajo", "zh": "低库存商品"},
    "alertas de fraude": {"en": "Fraud alerts", "fr": "Alertes de fraude", "de": "Betrugswarnungen", "es": "Alertas de fraude", "zh": "欺诈警报"},
    "stock a acompanhar.": {"en": "Stock to monitor.", "fr": "Stock a surveiller.", "de": "Bestand zu beobachten.", "es": "Stock a seguir.", "zh": "需关注库存。"},
    "vencem em breve": {"en": "Expiring soon", "fr": "Expirent bientot", "de": "Bald ablaufend", "es": "Vencen pronto", "zh": "即将过期"},
    "validade proxima": {"en": "Upcoming expiry", "fr": "Validite proche", "de": "Baldiges Ablaufdatum", "es": "Caducidad proxima", "zh": "临近有效期"},
    "validades a acompanhar": {"en": "Expiries to monitor", "fr": "Validites a suivre", "de": "Ablaufdaten beobachten", "es": "Caducidades a seguir", "zh": "需关注有效期"},
    "quantidade de vendas": {"en": "Sales quantity", "fr": "Quantite de ventes", "de": "Verkaufsmenge", "es": "Cantidad de ventas", "zh": "销售数量"},
    "faturacao geral": {"en": "Overall revenue", "fr": "Chiffre d'affaires global", "de": "Gesamtumsatz", "es": "Facturacion general", "zh": "总营业额"},


    "faturacao": {"en": "Revenue", "fr": "Chiffre d'affaires", "de": "Umsatz", "es": "Facturacion", "zh": "营业额"},
    "qtd. vendas": {"en": "Sales qty", "fr": "Qte ventes", "de": "Verkaufsmenge", "es": "Cant. ventas", "zh": "销售数量"},
    "fluxo stock": {"en": "Stock flow", "fr": "Flux de stock", "de": "Bestandsfluss", "es": "Flujo de stock", "zh": "库存流动"},
    "produtos mais vendidos": {"en": "Top products", "fr": "Meilleurs produits", "de": "Top-Produkte", "es": "Productos mas vendidos", "zh": "畅销商品"},
    "registe a perda ou trate da devolucao assim que possivel.": {
        "en": "Register the loss or handle the return as soon as possible.",
        "fr": "Enregistrez la perte ou traitez le retour des que possible.",
        "de": "Erfassen Sie den Verlust oder die Rueckgabe so bald wie moeglich.",
        "es": "Registre la perdida o gestione la devolucion cuanto antes.",
        "zh": "尽快登记损耗或处理退货。",
    },

    "limpar": {
        "en": "Clear",
        "fr": "Effacer",
        "de": "Leeren",
        "es": "Limpiar",
        "zh": "清除",
    },

    "ocorrencia": {"en": "occurrence", "fr": "occurrence", "de": "Vorkommnis", "es": "ocurrencia", "zh": "项"},
    "ocorrencias": {"en": "occurrences", "fr": "occurrences", "de": "Vorkommnisse", "es": "ocurrencias", "zh": "项"},
    "faturacao": {"en": "Revenue", "fr": "Chiffre d'affaires", "de": "Umsatz", "es": "Facturacion", "zh": "营业额"},
    "qtd. vendas": {"en": "Sales qty", "fr": "Qte ventes", "de": "Verkaufsmenge", "es": "Cant. ventas", "zh": "销售数量"},
    "fluxo stock": {"en": "Stock flow", "fr": "Flux de stock", "de": "Bestandsfluss", "es": "Flujo de stock", "zh": "库存流动"},
    "produtos mais vendidos": {"en": "Top products", "fr": "Meilleurs produits", "de": "Top-Produkte", "es": "Productos mas vendidos", "zh": "畅销商品"},
    "faturacao geral": {"en": "Overall revenue", "fr": "Chiffre d'affaires global", "de": "Gesamtumsatz", "es": "Facturacion general", "zh": "总营业额"},

}


def apply_language_to_widget_tree(root, language: Any = None) -> int:
    """Percorre a arvore de widgets e traduz textos visiveis.

    Devolve quantos textos foram alterados. Use isto ao mudar de idioma
    para cobrir labels/botoes do KV que nao passam por translate(key).
    """
    lang = normalize_language(language)
    changed = 0

    def walk(widget):
        nonlocal changed
        if widget is None:
            return
        for attr in ("text", "hint_text", "title"):
            if not hasattr(widget, attr):
                continue
            try:
                value = getattr(widget, attr)
            except Exception:
                continue
            if not isinstance(value, str) or not value.strip():
                continue
            # Ignorar paths de ficheiros / icones
            if "/" in value or "\\" in value or value.endswith((".png", ".ico", ".jpg", ".svg")):
                continue
            new_value = translate_text(value, lang)
            if new_value != value:
                try:
                    setattr(widget, attr, new_value)
                    changed += 1
                except Exception:
                    pass
        for child in list(getattr(widget, "children", []) or []):
            walk(child)

    walk(root)
    return changed
