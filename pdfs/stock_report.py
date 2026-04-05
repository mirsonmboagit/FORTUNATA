from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib.units import inch
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from num2words import num2words
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
            "Controle Completo e Análise de Movimentação de Inventário",
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
        elements.append(Paragraph("Resumo Consolidado de Estoque", title_style))
        
        # Cálculos expandidos
        total_entrada = data['entrada'].sum()
        total_saida = data['saida'].sum()
        total_remanescente = data['remanescente'].sum()
        taxa_rotatividade = (total_saida / total_entrada * 100) if total_entrada > 0 else 0
        
        # Análise de status
        esgotados = len(data[data['remanescente'] == 0])
        criticos = len(data[(data['remanescente'] > 0) & (data['remanescente'] < data['entrada'] * 0.15)])
        baixos = len(data[(data['remanescente'] >= data['entrada'] * 0.15) & (data['remanescente'] < data['entrada'] * 0.30)])
        medios = len(data[(data['remanescente'] >= data['entrada'] * 0.30) & (data['remanescente'] < data['entrada'] * 0.60)])
        altos = len(data[data['remanescente'] >= data['entrada'] * 0.60])
        
        # Taxa de vendas
        taxa_vendas = (data['sold_stock'].sum() / total_entrada * 100) if total_entrada > 0 else 0
        
        summary_data = [
            ['MÉTRICA', 'VALOR', 'POR EXTENSO'],
            ['Total de Produtos', f"{len(data)}", num2words(len(data), lang='pt')],
            ['Estoque Total Inicial (Entrada)', f"{int(total_entrada):,}", num2words(int(total_entrada), lang='pt')],
            ['Total de Saídas do Estoque', f"{int(total_saida):,}", num2words(int(total_saida), lang='pt')],
            ['Total Vendido', f"{int(data['sold_stock'].sum()):,}", num2words(int(data['sold_stock'].sum()), lang='pt')],
            ['Estoque Remanescente Atual', f"{int(total_remanescente):,}", num2words(int(total_remanescente), lang='pt')],
            ['Taxa de Rotatividade', f"{taxa_rotatividade:.2f}%", f"{num2words(int(taxa_rotatividade), lang='pt')} por cento"],
            ['Taxa de Vendas (Vendas/Entrada)', f"{taxa_vendas:.2f}%", f"{num2words(int(taxa_vendas), lang='pt')} por cento"],
            ['', '', ''],
            ['Produtos Esgotados', f"{esgotados}", num2words(esgotados, lang='pt')],
            ['Produtos em Estoque Crítico', f"{criticos}", num2words(criticos, lang='pt')],
            ['Produtos em Estoque Baixo', f"{baixos}", num2words(baixos, lang='pt')],
            ['Produtos em Estoque Médio', f"{medios}", num2words(medios, lang='pt')],
            ['Produtos em Estoque Alto', f"{altos}", num2words(altos, lang='pt')],
        ]
        
        summary_table = Table(summary_data, colWidths=[3.5*inch, 2.5*inch, 4.2*inch])
        
        summary_table.setStyle(TableStyle([
            # Cabeçalho
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#27ae60')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 11),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            
            # Separador
            ('BACKGROUND', (0, 8), (-1, 8), colors.HexColor('#ecf0f1')),
            ('LINEABOVE', (0, 8), (-1, 8), 1.5, colors.HexColor('#95a5a6')),
            
            # Corpo
            ('BACKGROUND', (0, 1), (-1, -1), colors.white),
            ('ROWBACKGROUNDS', (0, 1), (-1, 7), [colors.white, colors.HexColor('#f0f8f0')]),
            ('ROWBACKGROUNDS', (0, 9), (-1, -1), [colors.white, colors.HexColor('#f0f8f0')]),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#bdc3c7')),
            ('LINEBELOW', (0, 0), (-1, 0), 1.5, colors.HexColor('#27ae60')),
            
            # Alinhamento
            ('FONTNAME', (0, 1), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('ALIGN', (1, 1), (1, -1), 'RIGHT'),
            ('ALIGN', (2, 1), (2, -1), 'LEFT'),
            
            # Destaques
            ('TEXTCOLOR', (1, 5), (1, 5), colors.HexColor('#2980b9')),
            ('TEXTCOLOR', (1, 6), (1, 7), colors.HexColor('#8e44ad')),
            ('FONTNAME', (1, 5), (1, 7), 'Helvetica-Bold'),
            
            # Alertas de estoque
            ('TEXTCOLOR', (1, 9), (1, 9), colors.HexColor('#e74c3c')),  # Esgotados
            ('TEXTCOLOR', (1, 10), (1, 10), colors.HexColor('#e67e22')),  # Críticos
            ('FONTNAME', (1, 9), (1, 10), 'Helvetica-Bold'),
            
            # Padding
            ('TOPPADDING', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
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
                'value': len(data[(data['remanescente'] > 0) & (data['remanescente'] < data['entrada'] * 0.15)]),
                'color': '#e67e22',
            },
            {
                'label': 'Baixo',
                'value': len(data[(data['remanescente'] >= data['entrada'] * 0.15) & (data['remanescente'] < data['entrada'] * 0.30)]),
                'color': '#f39c12',
            },
            {
                'label': 'Medio',
                'value': len(data[(data['remanescente'] >= data['entrada'] * 0.30) & (data['remanescente'] < data['entrada'] * 0.60)]),
                'color': '#3498db',
            },
            {
                'label': 'Alto',
                'value': len(data[data['remanescente'] >= data['entrada'] * 0.60]),
                'color': '#27ae60',
            },
        ]
        elements.append(
            self._build_bar_chart(
                "Grafico de Barras: Distribuicao do Estado do Estoque",
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
            (data['remanescente'] < data['entrada'] * 0.15)
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
            f"⚠️ ALERTA: {len(critical_stock)} Produtos Requerem Atenção Imediata",
            title_style
        ))
        
        alert_data = [[
            'Produto', 'Categoria', 'Entrada', 'Vendido', 
            'Estoque\nAtual', 'Status', 'Prioridade', 'Ação Recomendada'
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
                prioridade,
                acao
            ])
        
        alert_table = Table(alert_data, colWidths=[
            2.4*inch, 1.2*inch, 0.9*inch, 0.9*inch, 
            0.9*inch, 1.0*inch, 1.0*inch, 1.9*inch
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
            ('ALIGN', (2, 1), (-2, -1), 'CENTER'),
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
                f"Alertas de Vencimento (janela de 90 dias): {len(expiry_rows)} produto(s)",
                title_style,
            )
        )

        table_data = [["Produto", "Categoria", "Validade", "Dias", "Nivel"]]
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
        elements.append(Paragraph("Detalhamento Completo do Inventário", title_style))
        
        detail_data = [[
            'Produto', 'Categoria', 'Entrada', 'Saída', 
            'Vendido', 'Remanes-\ncente', 'Rotati-\nvidade%', 'Status'
        ]]
        
        for _, row in data.iterrows():
            status = self._calculate_stock_status(row['remanescente'], row['entrada'])
            rotatividade = (row['sold_stock'] / row['entrada'] * 100) if row['entrada'] > 0 else 0
            
            detail_data.append([
                str(row['description'])[:26],
                str(row['category'])[:13] if pd.notna(row['category']) else 'N/A',
                f"{int(row['entrada']):,}",
                f"{int(row['saida']):,}",
                f"{int(row['sold_stock']):,}",
                f"{int(row['remanescente']):,}",
                f"{rotatividade:.1f}%",
                status
            ])
        
        detail_table = Table(detail_data, colWidths=[
            2.6*inch, 1.3*inch, 1.0*inch, 1.0*inch, 
            1.0*inch, 1.1*inch, 1.0*inch, 1.0*inch
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
            
            # Destaque rotatividade
            ('TEXTCOLOR', (6, 1), (6, -1), colors.HexColor('#8e44ad')),
            ('FONTNAME', (6, 1), (6, -1), 'Helvetica-Bold'),
            
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
                    ('BACKGROUND', (7, i), (7, i), colors.HexColor('#e74c3c')),
                    ('TEXTCOLOR', (7, i), (7, i), colors.white),
                    ('FONTNAME', (7, i), (7, i), 'Helvetica-Bold'),
                ]))
            elif status == "Crítico":
                detail_table.setStyle(TableStyle([
                    ('BACKGROUND', (7, i), (7, i), colors.HexColor('#e67e22')),
                    ('TEXTCOLOR', (7, i), (7, i), colors.white),
                    ('FONTNAME', (7, i), (7, i), 'Helvetica-Bold'),
                ]))
            elif status == "Baixo":
                detail_table.setStyle(TableStyle([
                    ('BACKGROUND', (7, i), (7, i), colors.HexColor('#f39c12')),
                    ('TEXTCOLOR', (7, i), (7, i), colors.white),
                ]))
            elif status == "Médio":
                detail_table.setStyle(TableStyle([
                    ('BACKGROUND', (7, i), (7, i), colors.HexColor('#3498db')),
                    ('TEXTCOLOR', (7, i), (7, i), colors.white),
                ]))
            else:  # Alto
                detail_table.setStyle(TableStyle([
                    ('BACKGROUND', (7, i), (7, i), colors.HexColor('#27ae60')),
                    ('TEXTCOLOR', (7, i), (7, i), colors.white),
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
        elif remanescente < entrada * 0.15:
            return 'Crítico'
        elif remanescente < entrada * 0.30:
            return 'Baixo'
        elif remanescente < entrada * 0.60:
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
        elif remanescente < entrada * 0.15:
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
