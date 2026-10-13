from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph,
    Spacer,
    PageBreak,
)
from reportlab.lib.styles import ParagraphStyle
from xml.sax.saxutils import escape
import pandas as pd

from .base_report import BasePDFReport


# Limite de linhas na tabela-mãe: evita PDFs de milhares de linhas
# (o resumo e os tops continuam a usar o dataset completo).
MASTER_TABLE_MAX_ROWS = 120


class CompleteReport(BasePDFReport):
    """
    Relatório completo em PDF (orientação horizontal), otimizado para velocidade.

    Otimizações vs versão anterior
    ─────────────────────────────
    • Células numéricas em texto simples (sem Paragraph) — ganho grande no ReportLab
    • Tabela-mãe limitada a MASTER_TABLE_MAX_ROWS (ordenada por receita)
    • Cálculos feitos em pandas de uma só vez (sem loop Python pesado)
    • Menos estilos ad-hoc criados em cada geração
    """

    def generate(self, data, filters):
        pdf_path = self._get_timestamp_filename("relatorio_completo")
        doc = self._create_document(pdf_path, title="Relatório Completo — NECTAR")
        elements = []

        self._create_header(
            elements,
            "Relatório Completo",
            "Vendas, estoque e lucro",
            filters,
        )

        # Garantir colunas derivadas sem reprocessar se já existirem
        data = self._prepare_dataframe(data)

        elements.append(self._build_period_kpis(data))
        elements.append(Spacer(1, 10))

        self._add_master_table(elements, data)
        elements.append(PageBreak())

        self._add_general_summary(elements, data)
        elements.append(Spacer(1, 12))
        self._add_overview_chart(elements, data)
        self._add_performance_analysis(elements, data)

        self._create_footer(elements)
        doc.build(elements)
        return pdf_path

    # ─────────────────────────────────────────────
    def _prepare_dataframe(self, data):
        if data is None or len(data) == 0:
            return data
        df = data.copy()
        # sold_stock / valor_total_vendas / lucro_total — só se faltarem
        if "sold_stock" not in df.columns and "sold_in_period" in df.columns:
            df["sold_stock"] = df["sold_in_period"]
        if "sold_stock" not in df.columns:
            df["sold_stock"] = 0
        if "sale_price" not in df.columns:
            df["sale_price"] = 0
        if "unit_purchase_price" not in df.columns:
            df["unit_purchase_price"] = 0
        if "valor_total_vendas" not in df.columns:
            df["valor_total_vendas"] = df["sold_stock"].astype(float) * df["sale_price"].astype(float)
        if "lucro_total" not in df.columns:
            df["lucro_total"] = (
                (df["sale_price"].astype(float) - df["unit_purchase_price"].astype(float))
                * df["sold_stock"].astype(float)
            )
        if "entrada" not in df.columns:
            if "existing_stock" in df.columns:
                df["entrada"] = df["existing_stock"].astype(float) + df["sold_stock"].astype(float)
            else:
                df["entrada"] = df["sold_stock"]
        if "remanescente" not in df.columns:
            df["remanescente"] = df["existing_stock"] if "existing_stock" in df.columns else 0
        return df

    def _status_for_values(self, rem, entrada):
        rem = float(rem or 0)
        entrada = float(entrada or 0)
        if rem <= 0:
            return "Esgotado"
        if entrada > 0 and rem < entrada * 0.30:
            return "Muito baixo"
        if entrada > 0 and rem < entrada * 0.60:
            return "Baixo"
        return "Disponível"

    def _name_cell(self, value, max_len=40):
        """Só o nome do produto usa Paragraph (texto longo com wrap)."""
        text = self._truncate_text(value, max_len)
        safe = escape(str(text)).replace("\n", "<br/>")
        return Paragraph(safe, self.styles["TableCell"])

    # ─────────────────────────────────────────────
    def _build_period_kpis(self, data):
        if data is None or len(data) == 0:
            return Spacer(1, 1)

        total_produtos = len(data)
        total_vendido = int(self._to_float(data["sold_stock"].sum()))
        receita = self._to_float(data["valor_total_vendas"].sum())
        lucro = self._to_float(data["lucro_total"].sum())
        esgotados = int((data["remanescente"].astype(float) <= 0).sum())

        return self._build_kpi_row(
            [
                {"label": "Produtos", "value": f"{total_produtos}"},
                {"label": "Unidades vendidas", "value": f"{total_vendido:,}"},
                {"label": "Receita", "value": f"MZN {receita:,.0f}"},
                {"label": "Lucro", "value": f"MZN {lucro:,.0f}"},
                {"label": "Esgotados", "value": f"{esgotados}"},
            ]
        )

    # ─────────────────────────────────────────────
    def _add_master_table(self, elements, data):
        self._create_section_title(elements, "Produtos do período")

        if data is None or len(data) == 0:
            elements.append(
                Paragraph("Não há produtos neste período.", self.styles["BodyClean"])
            )
            return

        total = len(data)
        # Ordenar por receita e limitar — o resumo usa o dataset completo
        table_df = data.nlargest(min(MASTER_TABLE_MAX_ROWS, total), "valor_total_vendas")

        note = (
            f"A mostrar os {len(table_df)} produtos com maior receita "
            f"(de {total} no período). Totais e resumo usam todos os produtos."
            if total > MASTER_TABLE_MAX_ROWS
            else f"{total} produtos no período."
        )
        elements.append(Paragraph(note, self.styles["ReportSubtitle"]))
        elements.append(Spacer(1, 6))

        headers = [
            "Produto",
            "Categoria",
            "Entr.",
            "Vend.",
            "Est.",
            "P.comp.",
            "P.vend.",
            "Receita",
            "Lucro",
            "Situação",
        ]

        # Pré-extrair arrays (muito mais rápido que iterrows célula a célula)
        names = table_df["description"].tolist() if "description" in table_df.columns else [""] * len(table_df)
        cats = table_df["category"].tolist() if "category" in table_df.columns else [""] * len(table_df)
        entradas = table_df["entrada"].astype(float).tolist()
        solds = table_df["sold_stock"].astype(float).tolist()
        rems = table_df["remanescente"].astype(float).tolist()
        buys = table_df["unit_purchase_price"].astype(float).tolist()
        sales = table_df["sale_price"].astype(float).tolist()
        receitas = table_df["valor_total_vendas"].astype(float).tolist()
        lucros = table_df["lucro_total"].astype(float).tolist()

        rows = []
        for i in range(len(table_df)):
            # Números e status = str simples (ReportLab processa em ms, não segundos)
            rows.append(
                [
                    self._truncate_text(names[i], 34),
                    self._truncate_text(cats[i], 20),
                    str(int(entradas[i])),
                    str(int(solds[i])),
                    str(int(rems[i])),
                    f"{buys[i]:.2f}",
                    f"{sales[i]:.2f}",
                    f"{receitas[i]:,.2f}",
                    f"{lucros[i]:,.2f}",
                    self._status_for_values(rems[i], entradas[i]),
                ]
            )

        usable = self._usable_width()
        # Produto | Categoria | Entrada | Vendido | Estoque | P.compra | P.venda | Receita | Lucro | Situação
        # Mais espaço para Produto/Categoria (menos truncamento); números com largura fixa relativa.
        weights = [2.00, 1.30, 0.65, 0.65, 0.65, 0.85, 0.85, 1.05, 0.95, 1.00]
        total_w = sum(weights)
        col_widths = [usable * (w / total_w) for w in weights]

        elements.append(
            self._build_clean_table(
                headers,
                rows,
                col_widths=col_widths,
                numeric_cols={2, 3, 4, 5, 6, 7, 8},
            )
        )

    # ─────────────────────────────────────────────
    def _add_general_summary(self, elements, data):
        self._create_section_title(elements, "Resumo do período")
        elements.append(
            Paragraph(
                "Vendas, estoque e lucro deste período (todos os produtos).",
                self.styles["ReportSubtitle"],
            )
        )
        elements.append(Spacer(1, 6))

        if data is None or len(data) == 0:
            elements.append(Paragraph("Sem dados para resumir.", self.styles["BodyClean"]))
            return

        total_produtos = len(data)
        total_entrada = int(self._to_float(data["entrada"].sum()))
        total_vendido = int(self._to_float(data["sold_stock"].sum()))
        total_estoque = int(self._to_float(data["remanescente"].sum()))
        receita_total = self._to_float(data["valor_total_vendas"].sum())
        lucro_total = self._to_float(data["lucro_total"].sum())
        lucro_medio = lucro_total / total_produtos if total_produtos else 0.0

        rem = data["remanescente"].astype(float)
        ent = data["entrada"].astype(float)
        produtos_esgotados = int((rem <= 0).sum())
        produtos_baixo = int(((rem > 0) & (rem < ent * 0.60)).sum())

        headers = ["Indicador", "Valor", "Significado"]
        rows = [
            ["Produtos no relatório", f"{total_produtos}", "Produtos incluídos no período"],
            ["Unidades adicionadas", f"{total_entrada:,}", "Entradas no estoque"],
            ["Unidades vendidas", f"{total_vendido:,}", "Vendas realizadas"],
            ["Unidades em estoque", f"{total_estoque:,}", "Disponíveis neste momento"],
            ["Total de vendas", f"MZN {receita_total:,.2f}", "Valor vendido"],
            ["Lucro total", f"MZN {lucro_total:,.2f}", "Valor ganho nas vendas"],
            ["Lucro médio por produto", f"MZN {lucro_medio:,.2f}", "Média dos produtos"],
            ["Produtos sem estoque", f"{produtos_esgotados}", "Precisam de reposição"],
            ["Produtos com estoque baixo", f"{produtos_baixo}", "Convém preparar a reposição"],
        ]
        usable = self._usable_width()
        elements.append(
            self._build_clean_table(
                headers,
                rows,
                col_widths=[usable * 0.32, usable * 0.22, usable * 0.46],
                numeric_cols={1},
            )
        )

    # ─────────────────────────────────────────────
    def _add_overview_chart(self, elements, data):
        if data is None or len(data) == 0:
            return
        top_revenue = data.nlargest(min(7, len(data)), "valor_total_vendas")
        chart_items = [
            (row["description"], self._to_float(row["valor_total_vendas"]))
            for _, row in top_revenue.iterrows()
        ]
        elements.append(Spacer(1, 8))
        elements.append(
            self._build_bar_chart(
                "Produtos com mais vendas em valor",
                chart_items,
                value_formatter=lambda value: f"MZN {value:,.2f}",
                accent_color="#0F6CBD",
            )
        )

    # ─────────────────────────────────────────────
    def _add_performance_analysis(self, elements, data):
        elements.append(Spacer(1, 14))
        if data is None or len(data) == 0:
            return

        self._create_section_title(elements, "Produtos com mais lucro")
        top_lucro = data.nlargest(min(5, len(data)), "lucro_total")
        top_rows = []
        for idx, (_, row) in enumerate(top_lucro.iterrows(), 1):
            top_rows.append(
                [
                    str(idx),
                    self._truncate_text(row.get("description"), 48),
                    f"{self._to_float(row.get('valor_total_vendas', 0)):,.2f}",
                    f"{self._to_float(row.get('lucro_total', 0)):,.2f}",
                ]
            )
        usable = self._usable_width()
        elements.append(
            self._build_clean_table(
                ["#", "Produto", "Receita (MZN)", "Lucro (MZN)"],
                top_rows,
                col_widths=[usable * 0.06, usable * 0.50, usable * 0.22, usable * 0.22],
                numeric_cols={0, 2, 3},
            )
        )
        elements.append(Spacer(1, 12))

        self._create_section_title(elements, "Produtos para repor")
        rem = data["remanescente"].astype(float)
        ent = data["entrada"].astype(float)
        critical = data[(rem <= 0) | (rem < ent * 0.30)].head(5)

        if len(critical) == 0:
            elements.append(
                Paragraph(
                    "Não há produtos a repor neste momento.",
                    self.styles["BodyClean"],
                )
            )
            return

        crit_rows = []
        for _, row in critical.iterrows():
            r = self._to_float(row.get("remanescente", 0))
            if r <= 0:
                status, acao = "Sem estoque", "Repor assim que possível"
            else:
                status, acao = "Estoque baixo", "Preparar a reposição"
            crit_rows.append(
                [
                    self._truncate_text(row.get("description"), 40),
                    self._truncate_text(row.get("category"), 18),
                    str(int(r)),
                    status,
                    acao,
                ]
            )
        elements.append(
            self._build_clean_table(
                ["Produto", "Categoria", "Estoque", "Status", "Ação sugerida"],
                crit_rows,
                col_widths=[
                    usable * 0.34,
                    usable * 0.16,
                    usable * 0.10,
                    usable * 0.14,
                    usable * 0.26,
                ],
                numeric_cols={2},
            )
        )