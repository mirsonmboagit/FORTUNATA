from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.units import inch
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from .base_report import BasePDFReport


class SalesReport(BasePDFReport):
    """
    Gera relatório de vendas em PDF com análise profissional.
    Apresenta dados de desempenho de vendas e top produtos.
    """
    
    def generate(self, data, filters):
        """
        Gera o relatório de vendas.
        
        Args:
            data: DataFrame com colunas: description, category, sold_stock, 
                  sale_price, valor_total_vendas
            filters: Dict com start_date, end_date, product, category
        
        Returns:
            String com o caminho do arquivo PDF gerado
        """
        pdf_path = self._get_timestamp_filename("relatorio_vendas")
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
            "RELATÓRIO DE VENDAS",
            "Vendas do período",
            filters
        )
        
        self._add_top_products(elements, data)
        elements.append(Spacer(1, 18))
        self._add_executive_summary(elements, data)
        elements.append(Spacer(1, 16))
        self._add_sales_chart(elements, data)
        self._create_footer(elements)
        
        doc.build(elements)
        return pdf_path
    
    def _add_executive_summary(self, elements, data):
        """Adiciona seção de resumo executivo expandido."""
        styles = getSampleStyleSheet()
        
        # Título
        title_style = ParagraphStyle(
            'SummaryTitle',
            parent=styles['Heading2'],
            fontSize=14,
            textColor=colors.HexColor('#2980b9'),
            spaceAfter=10,
            fontName='Helvetica-Bold'
        )
        elements.append(Paragraph("Resumo de vendas", title_style))
        
        # Cálculos
        total_vendido = data['sold_stock'].sum()
        total_valor = data['valor_total_vendas'].sum()
        media_vendas = data['sold_stock'].mean()
        ticket_medio = total_valor / total_vendido if total_vendido > 0 else 0
        produtos_vendidos = len(data[data['sold_stock'] > 0])
        
        summary_data = [
            ['RESUMO', 'VALOR'],
            ['Produtos no relatório', f"{len(data)}"],
            ['Produtos com vendas', f"{produtos_vendidos}"],
            ['Unidades vendidas', f"{int(total_vendido):,}"],
            ['Total de vendas', f"MZN {total_valor:,.2f}"],
            ['Valor médio por unidade vendida', f"MZN {ticket_medio:.2f}"],
            ['Média vendida por produto', f"{media_vendas:.1f} unidades"],
        ]
        
        summary_table = Table(summary_data, colWidths=[5.3*inch, 4.9*inch])
        
        summary_table.setStyle(TableStyle([
            # Cabeçalho
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2980b9')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 11),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            
            # Corpo
            ('BACKGROUND', (0, 1), (-1, -1), colors.white),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8f9fa')]),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#bdc3c7')),
            ('LINEBELOW', (0, 0), (-1, 0), 1.5, colors.HexColor('#2980b9')),
            
            # Alinhamento
            ('FONTNAME', (0, 1), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('ALIGN', (1, 1), (1, -1), 'RIGHT'),
            
            # Destaques financeiros
            ('TEXTCOLOR', (1, 4), (1, 4), colors.HexColor('#27ae60')),
            ('FONTNAME', (1, 4), (1, 5), 'Helvetica-Bold'),
            
            # Padding
            ('TOPPADDING', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
            ('LEFTPADDING', (0, 0), (-1, -1), 12),
            ('RIGHTPADDING', (0, 0), (-1, -1), 12),
        ]))
        
        elements.append(summary_table)
    
    def _add_sales_chart(self, elements, data):
        sold_data = data[data['sold_stock'] > 0]
        top_sales = sold_data.nlargest(7, 'sold_stock')
        chart_items = [
            (row['description'], row['sold_stock'])
            for _, row in top_sales.iterrows()
        ]
        elements.append(
            self._build_bar_chart(
                "Produtos mais vendidos",
                chart_items,
                value_formatter=lambda value: f"{int(round(value))} un.",
                accent_color="#2980b9",
            )
        )

    def _add_top_products(self, elements, data):
        """Adiciona seção de top 15 produtos mais vendidos (expandido)."""
        styles = getSampleStyleSheet()
        
        title_style = ParagraphStyle(
            'TopProductsTitle',
            parent=styles['Heading2'],
            fontSize=14,
            textColor=colors.HexColor('#27ae60'),
            spaceAfter=10,
            fontName='Helvetica-Bold'
        )
        elements.append(Paragraph("Tabela de Produtos Vendidos", title_style))
        
        sold_data = data[data['sold_stock'] > 0]
        sold_products = sold_data.sort_values(
            ['sold_stock', 'valor_total_vendas'],
            ascending=[False, False],
        )
        if sold_products.empty:
            elements.append(Paragraph(
                "Não foram encontradas vendas no período selecionado.",
                styles['Normal'],
            ))
            return
        
        detail_data = [[
            '#', 'Produto', 'Categoria', 
            'Quantidade\nVendida', 'Preço de\nVenda', 'Total de\nVendas', 'Parte das\nVendas'
        ]]
        
        total_geral = sold_data['valor_total_vendas'].sum()
        
        for idx, (_, row) in enumerate(sold_products.iterrows(), 1):
            participacao = (row['valor_total_vendas'] / total_geral * 100) if total_geral > 0 else 0
            
            detail_data.append([
                str(idx),
                str(row['description'])[:32],
                str(row['category'])[:15] if hasattr(row, 'category') and row['category'] else 'N/A',
                f"{int(row['sold_stock']):,}",
                f"{row['sale_price']:.2f}",
                f"{row['valor_total_vendas']:,.2f}",
                f"{participacao:.1f}%"
            ])
        
        detail_table = Table(
            detail_data,
            colWidths=[0.4*inch, 3.2*inch, 1.5*inch, 1.1*inch, 1.1*inch, 1.6*inch, 0.9*inch],
            repeatRows=1,
        )
        
        detail_table.setStyle(TableStyle([
            # Cabeçalho
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#27ae60')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('VALIGN', (0, 0), (-1, 0), 'MIDDLE'),
            
            # Corpo
            ('ALIGN', (0, 1), (0, -1), 'CENTER'),
            ('ALIGN', (1, 1), (2, -1), 'LEFT'),
            ('ALIGN', (3, 1), (-1, -1), 'CENTER'),
            ('FONTSIZE', (0, 1), (-1, -1), 8.5),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f0f8f0')]),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            
            # Bordas
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#95a5a6')),
            ('LINEBELOW', (0, 0), (-1, 0), 1.5, colors.HexColor('#27ae60')),
            
            # Destaques
            ('TEXTCOLOR', (5, 1), (5, -1), colors.HexColor('#16a085')),
            ('FONTNAME', (5, 1), (5, -1), 'Helvetica-Bold'),
            
            # Padding
            ('TOPPADDING', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('TOPPADDING', (0, 1), (-1, -1), 9),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 9),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ]))
        
        elements.append(detail_table)
