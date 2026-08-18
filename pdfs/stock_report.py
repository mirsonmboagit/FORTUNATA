from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib.units import inch
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
import pandas as pd
from .base_report import BasePDFReport


class StockReport(BasePDFReport):
    """
    Gera relatório de estoque em PDF com análise completa.
    Apresenta dados de movimentação e controle de inventário.
    """
    
    def generate(self, data, filters):
        """
        Gera o relatório de estoque.
        
        Args:
            data: DataFrame com colunas: description, category, entrada, 
                  saida, sold_stock, remanescente
            filters: Dict com start_date, end_date, product, category
        
        Returns:
            String com o caminho do arquivo PDF gerado
        """
        pdf_path = self._get_timestamp_filename("relatorio_estoque")
        doc = SimpleDocTemplate(
            pdf_path, 
            pagesize=landscape(A4), 
            topMargin=0.5*inch, 
            bottomMargin=0.5*inch,
            leftMargin=0.4*inch,
            rightMargin=0.4*inch
        )
        
        elements = []
        
        self._create_header(
            elements,
            "RELATÓRIO DE ESTOQUE",
            "Situação do estoque no período",
            filters
        )
        
        elements.append(Spacer(1, 14))
        self._add_stock_summary(elements, data)
        elements.append(Spacer(1, 16))
        self._add_stock_status_chart(elements, data)
        elements.append(Spacer(1, 20))
        self._add_critical_stock_alert(elements, data)
        elements.append(Spacer(1, 16))
        self._add_expiry_alerts(elements, data)
        elements.append(PageBreak())
        self._add_stock_details(elements, data)
        self._create_footer(elements)
        
        doc.build(elements)
        return pdf_path
    
    def _add_stock_summary(self, elements, data):
        """Adiciona seção de resumo de estoque expandido."""
        styles = getSampleStyleSheet()
        
        title_style = ParagraphStyle(
            'StockTitle',
            parent=styles['Heading2'],
            fontSize=14,
            textColor=colors.HexColor('#27ae60'),
            spaceAfter=10,
            fontName='Helvetica-Bold'
        )
        elements.append(Paragraph("Resumo do estoque", title_style))
        
        # Cálculos expandidos
        total_entrada = data['entrada'].sum()
        total_saida = data['saida'].sum()
        total_remanescente = data['remanescente'].sum()
        esgotados = len(data[data['remanescente'] == 0])
        criticos = len(data[(data['remanescente'] > 0) & (data['remanescente'] < data['entrada'] * 0.30)])
        baixos = len(data[(data['remanescente'] >= data['entrada'] * 0.30) & (data['remanescente'] < data['entrada'] * 0.60)])
        percentagem_vendida = (data['sold_stock'].sum() / total_entrada * 100) if total_entrada > 0 else 0
        produtos_a_repor = criticos + baixos
        
        summary_data = [
            ['RESUMO', 'VALOR'],
            ['Produtos no relatório', f"{len(data)}"],
            ['Unidades adicionadas', f"{int(total_entrada):,}"],
            ['Unidades vendidas', f"{int(data['sold_stock'].sum()):,}"],
            ['Unidades em estoque', f"{int(total_remanescente):,}"],
            ['Percentagem já vendida', f"{percentagem_vendida:.2f}%"],
            ['Produtos sem estoque', f"{esgotados}"],
            ['Produtos com estoque baixo', f"{produtos_a_repor}"],
        ]
        
        summary_table = Table(summary_data, colWidths=[5.3*inch, 4.9*inch])
        
        summary_table.setStyle(TableStyle([
            # Cabeçalho
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#27ae60')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 11),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            
            # Corpo
            ('BACKGROUND', (0, 1), (-1, -1), colors.white),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f0f8f0')]),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#bdc3c7')),
            ('LINEBELOW', (0, 0), (-1, 0), 1.5, colors.HexColor('#27ae60')),
            
            # Alinhamento
            ('FONTNAME', (0, 1), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('ALIGN', (1, 1), (1, -1), 'RIGHT'),
            
            # Destaques
            ('TEXTCOLOR', (1, 3), (1, 5), colors.HexColor('#2980b9')),
            ('FONTNAME', (1, 3), (1, 5), 'Helvetica-Bold'),
            
            # Alertas de estoque
            ('TEXTCOLOR', (1, 6), (1, 6), colors.HexColor('#e74c3c')),
            ('TEXTCOLOR', (1, 7), (1, 7), colors.HexColor('#e67e22')),
            ('FONTNAME', (1, 6), (1, 7), 'Helvetica-Bold'),
            
            # Padding
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('LEFTPADDING', (0, 0), (-1, -1), 12),
            ('RIGHTPADDING', (0, 0), (-1, -1), 12),
        ]))
        
        elements.append(summary_table)
    
    def _add_stock_status_chart(self, elements, data):
        chart_items = [
            {
                'label': 'Esgotado',
                'value': len(data[data['remanescente'] == 0]),
                'color': '#e74c3c',
            },
            {
                'label': 'Critico',
                'value': len(data[(data['remanescente'] > 0) & (data['remanescente'] < data['entrada'] * 0.30)]),
                'color': '#e67e22',
            },
            {
                'label': 'Baixo',
                'value': len(data[(data['remanescente'] >= data['entrada'] * 0.30) & (data['remanescente'] < data['entrada'] * 0.60)]),
                'color': '#f39c12',
            },
            {
                'label': 'Medio',
                'value': len(data[(data['remanescente'] >= data['entrada'] * 0.60) & (data['remanescente'] < data['entrada'] * 0.80)]),
                'color': '#3498db',
            },
            {
                'label': 'Alto',
                'value': len(data[data['remanescente'] >= data['entrada'] * 0.80]),
                'color': '#27ae60',
            },
        ]
        elements.append(
            self._build_bar_chart(
                "Estado do estoque",
                chart_items,
                value_formatter=lambda value: f"{int(round(value))} produtos",
                accent_color="#27ae60",
                sort_items=False,
                max_items=None,
            )
        )

    def _add_critical_stock_alert(self, elements, data):
        """Adiciona alerta de produtos com estoque crítico ou esgotado."""
        styles = getSampleStyleSheet()
        
        # Filtrar produtos críticos e esgotados
        critical_stock = data[
            (data['remanescente'] == 0) | 
            (data['remanescente'] < data['entrada'] * 0.30)
        ].sort_values('remanescente')
        
        if len(critical_stock) == 0:
            return
        
        title_style = ParagraphStyle(
            'AlertTitle',
            parent=styles['Heading2'],
            fontSize=14,
            textColor=colors.HexColor('#e74c3c'),
            spaceAfter=10,
            fontName='Helvetica-Bold'
        )
        elements.append(Paragraph(
            f"Produtos para repor: {len(critical_stock)}",
            title_style
        ))
        
        alert_data = [[
            'Produto', 'Categoria', 'Entrada', 'Vendido', 
            'Estoque\nAtual', 'Situação', 'O que fazer'
        ]]
        
        for _, row in critical_stock.head(10).iterrows():
            status, prioridade, acao = self._get_stock_alert_info(row['remanescente'], row['entrada'])
            
            alert_data.append([
                str(row['description'])[:26],
                str(row['category'])[:12] if pd.notna(row['category']) else 'N/A',
                f"{int(row['entrada'])}",
                f"{int(row['sold_stock'])}",
                f"{int(row['remanescente'])}",
                status,
                acao
            ])
        
        alert_table = Table(alert_data, colWidths=[
            2.4*inch, 1.2*inch, 0.9*inch, 0.9*inch, 
            0.9*inch, 1.0*inch, 2.4*inch
        ])
        
        alert_table.setStyle(TableStyle([
            # Cabeçalho
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#c0392b')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('VALIGN', (0, 0), (-1, 0), 'MIDDLE'),
            
            # Corpo
            ('ALIGN', (0, 1), (1, -1), 'LEFT'),
            ('ALIGN', (2, 1), (5, -1), 'CENTER'),
            ('ALIGN', (-1, 1), (-1, -1), 'LEFT'),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor('#fadbd8'), colors.HexColor('#f5eaea')]),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            
            # Bordas
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#95a5a6')),
            ('LINEBELOW', (0, 0), (-1, 0), 1.5, colors.HexColor('#c0392b')),
            
            # Padding
            ('TOPPADDING', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('TOPPADDING', (0, 1), (-1, -1), 9),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 9),
            ('LEFTPADDING', (0, 0), (-1, -1), 7),
            ('RIGHTPADDING', (0, 0), (-1, -1), 7),
        ]))
        
        # Aplicar cores por status
        for i in range(1, len(alert_data)):
            status = alert_data[i][5]
            if status == "Esgotado":
                alert_table.setStyle(TableStyle([
                    ('TEXTCOLOR', (5, i), (5, i), colors.HexColor('#e74c3c')),
                    ('FONTNAME', (5, i), (5, i), 'Helvetica-Bold'),
                ]))
            elif status == "Crítico":
                alert_table.setStyle(TableStyle([
                    ('TEXTCOLOR', (5, i), (5, i), colors.HexColor('#e67e22')),
                    ('FONTNAME', (5, i), (5, i), 'Helvetica-Bold'),
                ]))
        
        elements.append(alert_table)

    def _add_expiry_alerts(self, elements, data):
        """Adiciona secao de alertas de vencimento com niveis e cores."""
        if "expiry_has_alert" not in data.columns:
            return

        expiry_rows = data[data["expiry_has_alert"] == True].copy()
        if expiry_rows.empty:
            return

        expiry_rows = expiry_rows.sort_values(
            by=["expiry_days_left", "description"],
            ascending=[True, True],
            na_position="last",
        )

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "ExpiryAlertTitle",
            parent=styles["Heading2"],
            fontSize=14,
            textColor=colors.HexColor("#8B1A1A"),
            spaceAfter=10,
            fontName="Helvetica-Bold",
        )
        elements.append(
            Paragraph(
                f"Produtos perto da validade: {len(expiry_rows)}",
                title_style,
            )
        )

        table_data = [["Produto", "Categoria", "Validade", "Dias restantes", "Situação"]]
        for _, row in expiry_rows.head(24).iterrows():
            expiry_day = self._format_expiry_date(row.get("expiry_date"))
            days_left = row.get("expiry_days_left")
            days_text = "--"
            if pd.notna(days_left):
                try:
                    days_text = str(int(days_left))
                except Exception:
                    days_text = str(days_left)
            table_data.append(
                [
                    str(row.get("description", ""))[:30],
                    str(row.get("category", ""))[:14] if pd.notna(row.get("category")) else "N/A",
                    expiry_day,
                    days_text,
                    str(row.get("expiry_alert_label", "Sem alerta")),
                ]
            )

        table = Table(
            table_data,
            colWidths=[3.2 * inch, 1.4 * inch, 1.3 * inch, 0.8 * inch, 1.7 * inch],
        )
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2F3A4A")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, 0), 9),
                    ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                    ("ALIGN", (0, 1), (1, -1), "LEFT"),
                    ("ALIGN", (2, 1), (-1, -1), "CENTER"),
                    ("FONTSIZE", (0, 1), (-1, -1), 8),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8F9FA")]),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#BDC3C7")),
                    ("TOPPADDING", (0, 0), (-1, -1), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ]
            )
        )

        for row_idx in range(1, len(table_data)):
            level = str(table_data[row_idx][4]).strip().lower()
            badge_color, text_color = self._expiry_level_colors(level)
            table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (4, row_idx), (4, row_idx), badge_color),
                        ("TEXTCOLOR", (4, row_idx), (4, row_idx), text_color),
                        ("FONTNAME", (4, row_idx), (4, row_idx), "Helvetica-Bold"),
                    ]
                )
            )

        elements.append(table)
    
    def _add_stock_details(self, elements, data):
        """Adiciona seção de detalhamento completo do estoque."""
        styles = getSampleStyleSheet()
        
        title_style = ParagraphStyle(
            'DetailsTitle',
            parent=styles['Heading2'],
            fontSize=14,
            textColor=colors.HexColor('#16a085'),
            spaceAfter=10,
            fontName='Helvetica-Bold'
        )
        elements.append(Paragraph("Detalhes do estoque", title_style))
        
        detail_data = [[
            'Produto', 'Categoria', 'Entrada', 'Saída', 
            'Vendido', 'Em\nEstoque', 'Situação'
        ]]
        
        for _, row in data.iterrows():
            status = self._calculate_stock_status(row['remanescente'], row['entrada'])
            
            detail_data.append([
                str(row['description'])[:26],
                str(row['category'])[:13] if pd.notna(row['category']) else 'N/A',
                f"{int(row['entrada']):,}",
                f"{int(row['saida']):,}",
                f"{int(row['sold_stock']):,}",
                f"{int(row['remanescente']):,}",
                status
            ])
        
        detail_table = Table(detail_data, colWidths=[
            2.6*inch, 1.3*inch, 1.0*inch, 1.0*inch, 
            1.0*inch, 1.2*inch, 1.2*inch
        ])
        
        detail_table.setStyle(TableStyle([
            # Cabeçalho
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#16a085')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('VALIGN', (0, 0), (-1, 0), 'MIDDLE'),
            
            # Corpo
            ('ALIGN', (0, 1), (1, -1), 'LEFT'),
            ('ALIGN', (2, 1), (-1, -1), 'CENTER'),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#e8f6f3')]),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            
            # Bordas
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#95a5a6')),
            ('LINEBELOW', (0, 0), (-1, 0), 1.5, colors.HexColor('#16a085')),
            
            # Destaque de estoque atual
            ('TEXTCOLOR', (5, 1), (5, -1), colors.HexColor('#2980b9')),
            ('FONTNAME', (5, 1), (5, -1), 'Helvetica-Bold'),
            
            # Padding
            ('TOPPADDING', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('TOPPADDING', (0, 1), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 8),
            ('LEFTPADDING', (0, 0), (-1, -1), 7),
            ('RIGHTPADDING', (0, 0), (-1, -1), 7),
        ]))
        
        # Aplicar cores condicionais ao Status
        for i in range(1, len(detail_data)):
            status = detail_data[i][-1]
            if status == "Esgotado":
                detail_table.setStyle(TableStyle([
                    ('BACKGROUND', (6, i), (6, i), colors.HexColor('#e74c3c')),
                    ('TEXTCOLOR', (6, i), (6, i), colors.white),
                    ('FONTNAME', (6, i), (6, i), 'Helvetica-Bold'),
                ]))
            elif status == "Crítico":
                detail_table.setStyle(TableStyle([
                    ('BACKGROUND', (6, i), (6, i), colors.HexColor('#e67e22')),
                    ('TEXTCOLOR', (6, i), (6, i), colors.white),
                    ('FONTNAME', (6, i), (6, i), 'Helvetica-Bold'),
                ]))
            elif status == "Baixo":
                detail_table.setStyle(TableStyle([
                    ('BACKGROUND', (6, i), (6, i), colors.HexColor('#f39c12')),
                    ('TEXTCOLOR', (6, i), (6, i), colors.white),
                ]))
            elif status == "Médio":
                detail_table.setStyle(TableStyle([
                    ('BACKGROUND', (6, i), (6, i), colors.HexColor('#3498db')),
                    ('TEXTCOLOR', (6, i), (6, i), colors.white),
                ]))
            else:  # Alto
                detail_table.setStyle(TableStyle([
                    ('BACKGROUND', (6, i), (6, i), colors.HexColor('#27ae60')),
                    ('TEXTCOLOR', (6, i), (6, i), colors.white),
                ]))
        
        elements.append(detail_table)
    
    def _calculate_stock_status(self, remanescente, entrada):
        """
        Calcula o status do estoque baseado na quantidade remanescente.
        
        Args:
            remanescente: Quantidade em estoque
            entrada: Quantidade inicial
        
        Returns:
            String com o status (Esgotado, Crítico, Baixo, Médio, Alto)
        """
        if remanescente == 0:
            return 'Esgotado'
        elif remanescente < entrada * 0.30:
            return 'Crítico'
        elif remanescente < entrada * 0.60:
            return 'Baixo'
        elif remanescente < entrada * 0.80:
            return 'Médio'
        else:
            return 'Alto'
    
    def _get_stock_alert_info(self, remanescente, entrada):
        """
        Retorna informações de alerta para produtos críticos.
        
        Args:
            remanescente: Quantidade em estoque
            entrada: Quantidade inicial
        
        Returns:
            Tuple (status, prioridade, ação)
        """
        if remanescente == 0:
            return ('Esgotado', 'URGENTE', 'Reposição imediata')
        elif remanescente < entrada * 0.05:
            return ('Crítico', 'ALTA', 'Reposição em 24h')
        elif remanescente < entrada * 0.30:
            return ('Crítico', 'MÉDIA', 'Reposição em 72h')
        else:
            return ('Baixo', 'BAIXA', 'Monitorar estoque')

    @staticmethod
    def _format_expiry_date(value):
        if not value or (isinstance(value, float) and pd.isna(value)):
            return "N/A"
        raw = str(value)
        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y"):
            try:
                return pd.to_datetime(raw, format=fmt, errors="raise").strftime("%d/%m/%Y")
            except Exception:
                continue
        try:
            return pd.to_datetime(raw).strftime("%d/%m/%Y")
        except Exception:
            return raw[:10]

    @staticmethod
    def _expiry_level_colors(level):
        level = str(level or "").lower()
        if level == "leve":
            return colors.HexColor("#808080"), colors.white
        if level == "medio":
            return colors.HexColor("#EBC21A"), colors.black
        if level == "alto":
            return colors.HexColor("#F2861A"), colors.white
        if level == "critico":
            return colors.HexColor("#DB3833"), colors.white
        if level == "vencido":
            return colors.HexColor("#731212"), colors.white
        return colors.HexColor("#73808C"), colors.white
