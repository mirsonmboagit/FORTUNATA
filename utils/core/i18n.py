from __future__ import annotations

import json
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
)

_LANGUAGE_CODES = {item["code"] for item in SUPPORTED_LANGUAGES}
_LANGUAGE_INDEX = {item["code"]: item for item in SUPPORTED_LANGUAGES}

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


def translate(key: str, language: Any = None, default: str | None = None, **kwargs: Any) -> str:
    lang = normalize_language(language)
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
    return _strip_accents(collapsed)


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
    return normalized in _load_text_catalog() or bool(_translate_dynamic_text(normalized, "en"))


def translate_text(text: Any, language: Any = None) -> str:
    source = str(text or "")
    lang = normalize_language(language)
    if not source.strip():
        return source
    if lang == DEFAULT_LANGUAGE:
        return correct_portuguese_text(source)

    normalized_source = _normalize_text_source(source)
    translations = _load_text_catalog().get(normalized_source)
    if translations and translations.get(lang):
        translated = translations[lang]
        return translated.upper() if source.strip().isupper() else translated

    dynamic = _translate_dynamic_text(normalized_source, lang)
    if dynamic:
        return dynamic

    return source


def _translate_dynamic_text(normalized_source: str, language: str) -> str:
    alert_match = re.match(r"^(\d+)\s+alerta\(s\)\s+pendente\(s\)$", normalized_source, re.I)
    if alert_match:
        count = alert_match.group(1)
        return {
            "en": f"{count} pending alert(s)",
            "fr": f"{count} alerte(s) en attente",
            "de": f"{count} ausstehende Warnung(en)",
            "es": f"{count} alerta(s) pendiente(s)",
        }.get(language, normalized_source)

    products_match = re.match(r"^(\d+)\s+produtos?$", normalized_source, re.I)
    if products_match:
        count = products_match.group(1)
        return {
            "en": f"{count} products",
            "fr": f"{count} produits",
            "de": f"{count} Produkte",
            "es": f"{count} productos",
        }.get(language, normalized_source)

    items_match = re.match(r"^(\d+)\s+itens?$", normalized_source, re.I)
    if items_match:
        count = items_match.group(1)
        return {
            "en": f"{count} items",
            "fr": f"{count} articles",
            "de": f"{count} Artikel",
            "es": f"{count} items",
        }.get(language, normalized_source)

    return ""
