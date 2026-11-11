"""Localização partilhada pelos documentos PDF."""
from __future__ import annotations

from typing import Any

from utils.config.app_config import get_app_settings
from utils.core.i18n import normalize_language, translate_text


_PDF_TEXT = {
    "Período": {"en": "Period", "fr": "Période", "es": "Período", "zh": "期间"},
    "Produto": {"en": "Product", "fr": "Produit", "es": "Producto", "zh": "产品"},
    "Categoria": {"en": "Category", "fr": "Catégorie", "es": "Categoría", "zh": "类别"},
    "Vendedor": {"en": "Seller", "fr": "Vendeur", "es": "Vendedor", "zh": "销售员"},
    "Criado em": {"en": "Created on", "fr": "Créé le", "es": "Creado el", "zh": "创建于"},
    "Tipo": {"en": "Type", "fr": "Type", "es": "Tipo", "zh": "类型"},
    "Todos os produtos": {"en": "All products", "fr": "Tous les produits", "es": "Todos los productos", "zh": "所有产品"},
    "Todas as categorias": {"en": "All categories", "fr": "Toutes les catégories", "es": "Todas las categorías", "zh": "所有类别"},
    "Todos os vendedores": {"en": "All sellers", "fr": "Tous les vendeurs", "es": "Todos los vendedores", "zh": "所有销售员"},
    "Relatório": {"en": "Report", "fr": "Rapport", "es": "Informe", "zh": "报告"},
    "Relatório Completo": {"en": "Complete Report", "fr": "Rapport complet", "es": "Informe completo", "zh": "完整报告"},
    "RELATÓRIO DE VENDAS": {"en": "SALES REPORT", "fr": "RAPPORT DES VENTES", "es": "INFORME DE VENTAS", "zh": "销售报告"},
    "RELATÓRIO DE ESTOQUE": {"en": "STOCK REPORT", "fr": "RAPPORT DE STOCK", "es": "INFORME DE INVENTARIO", "zh": "库存报告"},
    "RELATÓRIO DE LUCRO": {"en": "PROFIT REPORT", "fr": "RAPPORT DES BÉNÉFICES", "es": "INFORME DE GANANCIAS", "zh": "利润报告"},
    "RELATÓRIO DE PERDAS": {"en": "LOSS REPORT", "fr": "RAPPORT DES PERTES", "es": "INFORME DE PÉRDIDAS", "zh": "损失报告"},
    "Resumo": {"en": "Summary", "fr": "Résumé", "es": "Resumen", "zh": "摘要"},
    "Resumo do período": {"en": "Period summary", "fr": "Résumé de la période", "es": "Resumen del período", "zh": "期间摘要"},
    "Resumo de vendas": {"en": "Sales summary", "fr": "Résumé des ventes", "es": "Resumen de ventas", "zh": "销售摘要"},
    "Resumo do estoque": {"en": "Stock summary", "fr": "Résumé du stock", "es": "Resumen del inventario", "zh": "库存摘要"},
    "Produtos": {"en": "Products", "fr": "Produits", "es": "Productos", "zh": "产品"},
    "Quantidade": {"en": "Quantity", "fr": "Quantité", "es": "Cantidad", "zh": "数量"},
    "Valor": {"en": "Value", "fr": "Valeur", "es": "Valor", "zh": "数值"},
    "Data": {"en": "Date", "fr": "Date", "es": "Fecha", "zh": "日期"},
    "Entrada": {"en": "Incoming", "fr": "Entrée", "es": "Entrada", "zh": "入库"},
    "Saída": {"en": "Outgoing", "fr": "Sortie", "es": "Salida", "zh": "出库"},
    "Vendido": {"en": "Sold", "fr": "Vendu", "es": "Vendido", "zh": "已售"},
    "Estoque": {"en": "Stock", "fr": "Stock", "es": "Inventario", "zh": "库存"},
    "Status": {"en": "Status", "fr": "Statut", "es": "Estado", "zh": "状态"},
    "Ação": {"en": "Action", "fr": "Action", "es": "Acción", "zh": "操作"},
    "Unidades vendidas": {"en": "Units sold", "fr": "Unités vendues", "es": "Unidades vendidas", "zh": "售出数量"},
    "Receita": {"en": "Revenue", "fr": "Recettes", "es": "Ingresos", "zh": "收入"},
    "Lucro": {"en": "Profit", "fr": "Bénéfice", "es": "Ganancia", "zh": "利润"},
    "Lucro total": {"en": "Total profit", "fr": "Bénéfice total", "es": "Ganancia total", "zh": "总利润"},
    "Esgotados": {"en": "Out of stock", "fr": "Ruptures de stock", "es": "Agotados", "zh": "缺货"},
    "Esgotado": {"en": "Out of stock", "fr": "Rupture de stock", "es": "Agotado", "zh": "缺货"},
    "Disponível": {"en": "Available", "fr": "Disponible", "es": "Disponible", "zh": "可用"},
    "Baixo": {"en": "Low", "fr": "Faible", "es": "Bajo", "zh": "低"},
    "Muito baixo": {"en": "Very low", "fr": "Très faible", "es": "Muy bajo", "zh": "很低"},
    "Situação": {"en": "Status", "fr": "Statut", "es": "Estado", "zh": "状态"},
    "Ação sugerida": {"en": "Suggested action", "fr": "Action suggérée", "es": "Acción sugerida", "zh": "建议操作"},
    "Sem dados": {"en": "No data", "fr": "Aucune donnée", "es": "Sin datos", "zh": "无数据"},
    "Sem dados para resumir.": {"en": "No data to summarize.", "fr": "Aucune donnée à résumer.", "es": "No hay datos para resumir.", "zh": "没有可汇总的数据。"},
    "Não há dados para mostrar neste gráfico.": {"en": "There is no data to display in this chart.", "fr": "Aucune donnée à afficher dans ce graphique.", "es": "No hay datos para mostrar en este gráfico.", "zh": "此图表没有可显示的数据。"},
    "Uso interno": {"en": "Internal use", "fr": "Usage interne", "es": "Uso interno", "zh": "内部使用"},
    "Relatório gerado em": {"en": "Report generated on", "fr": "Rapport généré le", "es": "Informe generado el", "zh": "报告生成于"},
}


def current_pdf_language() -> str:
    try:
        from kivy.app import App
        app = App.get_running_app()
        if app and getattr(app, "language", None):
            return normalize_language(app.language)
    except Exception:
        pass
    try:
        return normalize_language(get_app_settings().get("language"))
    except Exception:
        return "pt"


def pdf_text(value: Any, language: Any = None) -> str:
    source = str(value or "")
    lang = normalize_language(language or current_pdf_language())
    if lang == "pt" or not source:
        return source
    translated = _PDF_TEXT.get(source, {}).get(lang)
    if translated:
        return translated.upper() if source.strip().isupper() else translated
    return translate_text(source, lang)


def pdf_font(language: Any = None, *, bold: bool = False) -> str:
    return "STSong-Light" if normalize_language(language or current_pdf_language()) == "zh" else ("Helvetica-Bold" if bold else "Helvetica")
