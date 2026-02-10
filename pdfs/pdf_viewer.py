import os
import platform
import subprocess
from kivy.uix.popup import Popup
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.label import MDLabel
from kivymd.uix.button import (
    MDRaisedButton,
    MDFlatButton,
    MDRectangleFlatButton,
    MDIconButton,
)
from kivymd.uix.card import MDCard
from kivymd.uix.dialog import MDDialog
from kivy.uix.scrollview import ScrollView
from kivy.uix.image import Image as KivyImage
from kivy.graphics import Color, RoundedRectangle
from kivy.graphics.texture import Texture
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.clock import Clock
from kivy.app import App
from PIL import Image as PILImage
import io


def _theme_color(name, fallback):
    app = App.get_running_app()
    tokens = getattr(app, "theme_tokens", {}) if app else {}
    return tokens.get(name, fallback)


class PDFViewer:
    """
    Visualizador de PDFs otimizado com ajuste automático e navegação fluida.
    Suporta visualização interna de alta qualidade e abertura em navegador externo.
    """
    
    def __init__(self, error_callback=None):
        """
        Inicializa o visualizador de PDF.
        
        Args:
            error_callback: Função callback para exibir mensagens de erro
        """
        self.error_callback = error_callback
        self.current_popup = None
        self.pdf_document = None
        self.page_state = {'current': 0, 'zoom': 1.0}
        self.pdf_image = None
        self.pdf_container = None
        self.page_label = None
        self.options_dialog = None
        self.pymupdf_dialog = None
    
    def view_pdf(self, pdf_path):
        """
        Inicia visualização do PDF com opções para o usuário.
        
        Args:
            pdf_path: Caminho completo para o arquivo PDF
        """
        if not os.path.exists(pdf_path):
            if self.error_callback:
                self.error_callback(f'Arquivo não encontrado:\n{pdf_path}')
            return
        
        self._show_viewer_options(pdf_path)
    
    def _show_viewer_options(self, pdf_path):
        """Exibe popup com opções de visualização do PDF."""
        if getattr(self, "options_dialog", None):
            self.options_dialog.dismiss()

        filename = os.path.basename(pdf_path)

        content = MDBoxLayout(
            orientation="vertical",
            spacing=dp(12),
            padding=[dp(16), dp(12), dp(16), dp(8)],
            size_hint_y=None,
        )
        content.bind(minimum_height=content.setter("height"))

        content.add_widget(MDLabel(
            text="Como deseja visualizar o PDF?",
            font_style="Subtitle1",
            bold=True,
            halign="left",
            theme_text_color="Custom",
            text_color=_theme_color('text_primary', (0.2, 0.2, 0.2, 1)),
            size_hint_y=None,
            height=dp(24),
        ))

        content.add_widget(MDLabel(
            text=filename,
            font_style="Caption",
            halign="left",
            theme_text_color="Custom",
            text_color=_theme_color('text_secondary', (0.5, 0.5, 0.5, 1)),
            size_hint_y=None,
            height=dp(18),
            shorten=True,
            shorten_from="right",
        ))

        self.options_dialog = MDDialog(
            title="Visualizar PDF",
            type="custom",
            content_cls=content,
            size_hint=(None, None),
            size=(min(dp(520), Window.width * 0.9), dp(220)),
            buttons=[
                MDFlatButton(
                    text="Cancelar",
                    on_release=lambda x: self.options_dialog.dismiss(),
                ),
                MDRectangleFlatButton(
                    text="Abrir no navegador",
                    on_release=lambda x: [
                        self._open_in_browser(pdf_path),
                        self.options_dialog.dismiss(),
                    ],
                ),
                MDRaisedButton(
                    text="Visualizador interno",
                    md_bg_color=_theme_color('primary', (0.15, 0.52, 0.76, 1)),
                    on_release=lambda x: [
                        self._view_internal(pdf_path),
                        self.options_dialog.dismiss(),
                    ],
                ),
            ],
        )
        self.options_dialog.open()
    
    def _view_internal(self, pdf_path):
        """
        Abre PDF no visualizador interno otimizado.
        
        Args:
            pdf_path: Caminho para o arquivo PDF
        """
        try:
            import fitz
        except ImportError:
            self._show_pymupdf_install_message(pdf_path)
            return
        
        try:
            # Abrir documento PDF
            self.pdf_document = fitz.open(pdf_path)
            total_pages = len(self.pdf_document)
            
            if total_pages == 0:
                self.pdf_document.close()
                if self.error_callback:
                    self.error_callback('O PDF está vazio ou corrompido.')
                return
            
            # Resetar estado
            self.page_state = {'current': 0, 'zoom': 1.0}
            
            # Criar janela do visualizador
            self._create_pdf_viewer_window(pdf_path, total_pages)
            
        except Exception as e:
            if self.error_callback:
                self.error_callback(f'Erro ao visualizar PDF:\n{str(e)}')
    
    def _open_in_browser(self, pdf_path):
        """
        Abre PDF no navegador padrão do sistema.
        
        Args:
            pdf_path: Caminho para o arquivo PDF
        """
        try:
            system = platform.system()
            absolute_path = os.path.abspath(pdf_path)
            
            if system == 'Windows':
                # Tenta Edge primeiro, depois navegador padrão
                edge_path = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
                
                if os.path.exists(edge_path):
                    subprocess.Popen([edge_path, absolute_path])
                else:
                    os.startfile(absolute_path)
            
            elif system == 'Darwin':  # macOS
                subprocess.call(['open', absolute_path])
            
            else:  # Linux
                subprocess.call(['xdg-open', absolute_path])
                
        except Exception as e:
            if self.error_callback:
                self.error_callback(f'Erro ao abrir navegador:\n{str(e)}')
    
    def _create_pdf_viewer_window(self, pdf_path, total_pages):
        """
        Cria janela principal do visualizador interno.
        
        Args:
            pdf_path: Caminho do arquivo PDF
            total_pages: Total de páginas do documento
        """
        viewer_popup = Popup(
            title='',
            separator_height=0,
            size_hint=(0.96, 0.96),
            background='',
            background_color=(0, 0, 0, 0.2),
            auto_dismiss=False
        )
        
        self.current_popup = viewer_popup
        
        # Layout principal
        main_layout = MDBoxLayout(
            orientation='vertical',
            spacing=dp(12),
            padding=[dp(16), dp(16)]
        )

        container = MDCard(
            orientation='vertical',
            spacing=0,
            padding=[0, 0],
            elevation=4,
            radius=[dp(12)],
            md_bg_color=_theme_color('card', (1, 1, 1, 1))
        )

        header = MDCard(
            orientation='horizontal',
            size_hint_y=None,
            height=dp(52),
            padding=[dp(12), 0],
            spacing=dp(8),
            radius=[dp(12), dp(12), 0, 0],
            elevation=0,
            md_bg_color=_theme_color('primary', (0.15, 0.52, 0.76, 1)),
        )

        title = MDLabel(
            text="Visualizador de PDF",
            font_style="Subtitle1",
            bold=True,
            halign="left",
            valign="middle",
            theme_text_color="Custom",
            text_color=_theme_color('on_primary', (1, 1, 1, 1)),
        )
        title.bind(size=lambda inst, _: setattr(inst, "text_size", inst.size))

        close_btn = MDIconButton(
            icon="close",
            theme_text_color="Custom",
            text_color=_theme_color('on_primary', (1, 1, 1, 1)),
            md_bg_color=_theme_color('card_alt', (1, 1, 1, 0.15)),
            pos_hint={"center_y": 0.5},
            on_release=lambda x: self._close_viewer(viewer_popup),
        )

        header.add_widget(title)
        header.add_widget(close_btn)

        # Barra de controles
        controls = self._create_controls(pdf_path, total_pages, viewer_popup)

        # Área de visualização do PDF
        pdf_scroll, pdf_image, pdf_container = self._create_pdf_display_area()

        body = MDBoxLayout(
            orientation='vertical',
            spacing=dp(12),
            padding=[dp(12), dp(12)]
        )
        body.add_widget(controls)
        body.add_widget(pdf_scroll)

        container.add_widget(header)
        container.add_widget(body)
        main_layout.add_widget(container)
        
        # Guardar referências
        self.pdf_image = pdf_image
        self.pdf_container = pdf_container
        
        # Renderizar primeira página após o popup abrir
        Clock.schedule_once(lambda dt: self._render_page_with_fit(), 0.1)
        
        viewer_popup.content = main_layout
        viewer_popup.open()
    
    def _create_controls(self, pdf_path, total_pages, viewer_popup):
        """
        Cria barra de controles superior.
        
        Args:
            pdf_path: Caminho do PDF
            total_pages: Total de p?ginas
            viewer_popup: Refer?ncia ao popup
        
        Returns:
            MDCard com controles
        """
        controls = MDCard(
            size_hint_y=None,
            height=dp(64),
            spacing=dp(10),
            padding=[dp(12), dp(8)],
            elevation=1,
            radius=[dp(8)],
            md_bg_color=_theme_color('surface_alt', (0.97, 0.97, 0.97, 1)),
        )

        info_box = MDBoxLayout(
            orientation='vertical',
            size_hint_x=0.4,
            spacing=dp(2)
        )

        filename = os.path.basename(pdf_path)
        filename_label = MDLabel(
            text=filename,
            font_style='Body2',
            bold=True,
            halign='left',
            theme_text_color='Custom',
            text_color=_theme_color('text_primary', (0.2, 0.2, 0.2, 1)),
            shorten=True,
            shorten_from='right',
        )
        filename_label.bind(size=lambda inst, _: setattr(inst, "text_size", inst.size))
        info_box.add_widget(filename_label)

        self.page_label = MDLabel(
            text=f'P?gina 1 de {total_pages}',
            font_style='Caption',
            halign='left',
            theme_text_color='Custom',
            text_color=_theme_color('text_secondary', (0.5, 0.5, 0.5, 1)),
        )
        self.page_label.bind(size=lambda inst, _: setattr(inst, "text_size", inst.size))
        info_box.add_widget(self.page_label)

        nav_box = MDBoxLayout(
            size_hint_x=0.6,
            spacing=dp(6)
        )

        nav_box.add_widget(self._create_icon_button(
            "chevron-left",
            lambda x: self._nav_page(-1, total_pages),
            (0.15, 0.52, 0.76, 1)
        ))
        nav_box.add_widget(self._create_icon_button(
            "chevron-right",
            lambda x: self._nav_page(1, total_pages),
            (0.15, 0.52, 0.76, 1)
        ))
        nav_box.add_widget(self._create_icon_button(
            "minus",
            lambda x: self._zoom_page(-0.25),
            (0.8, 0.4, 0.1, 1)
        ))
        nav_box.add_widget(self._create_icon_button(
            "fullscreen",
            lambda x: self._fit_to_window(),
            (0.2, 0.65, 0.33, 1)
        ))
        nav_box.add_widget(self._create_icon_button(
            "plus",
            lambda x: self._zoom_page(0.20),
            (0.8, 0.4, 0.1, 1)
        ))

        controls.add_widget(info_box)
        controls.add_widget(nav_box)

        return controls

    def _create_icon_button(self, icon_name, callback, color):
        """Cria botao de icone com estilo consistente."""
        btn = MDIconButton(
            icon=icon_name,
            theme_text_color="Custom",
            text_color=color,
            md_bg_color=_theme_color('card', (1, 1, 1, 1)),
        )
        btn.bind(on_release=callback)
        return btn

    def _create_pdf_display_area(self):
        """
        Cria área de exibição do PDF com scroll.
        
        Returns:
            Tupla (ScrollView, KivyImage, MDBoxLayout container)
        """
        # ScrollView com barras personalizadas
        pdf_scroll = ScrollView(
            size_hint=(1, 1), 
            do_scroll_x=True, 
            do_scroll_y=True, 
            bar_width=dp(14),
            bar_color=[0.15, 0.52, 0.76, 0.8],
            bar_inactive_color=[0.7, 0.7, 0.7, 0.5],
            scroll_type=['bars', 'content']
        )
        
        # Container do PDF com fundo branco
        pdf_container = MDBoxLayout(
            orientation='vertical', 
            size_hint=(None, None), 
            padding=[dp(20), dp(20)]
        )
        
        with pdf_container.canvas.before:
            Color(1, 1, 1, 1)
            bg = RoundedRectangle(
                pos=pdf_container.pos, 
                size=pdf_container.size, 
                radius=[dp(6)]
            )
            # Sombra sutil
            Color(0.8, 0.8, 0.8, 0.3)
            shadow = RoundedRectangle(
                pos=(pdf_container.x + dp(2), pdf_container.y - dp(2)), 
                size=pdf_container.size, 
                radius=[dp(6)]
            )
        
        pdf_container._bg = bg
        pdf_container._shadow = shadow
        
        def update_container_graphics(instance, value):
            instance._bg.pos = instance.pos
            instance._bg.size = instance.size
            instance._shadow.pos = (instance.x + dp(2), instance.y - dp(2))
            instance._shadow.size = instance.size
        
        pdf_container.bind(pos=update_container_graphics, size=update_container_graphics)
        
        # Imagem do PDF
        pdf_image = KivyImage(
            size_hint=(None, None),
            allow_stretch=True,
            keep_ratio=True
        )
        
        pdf_container.add_widget(pdf_image)
        pdf_scroll.add_widget(pdf_container)
        
        return pdf_scroll, pdf_image, pdf_container
    
    def _render_page_with_fit(self):
        """Renderiza página com ajuste automático à janela."""
        if not self.pdf_document:
            return
        
        try:
            page_num = self.page_state['current']
            page = self.pdf_document[page_num]
            
            # Obter dimensões da página original
            page_rect = page.rect
            page_width = page_rect.width
            page_height = page_rect.height
            
            # Calcular zoom para ajustar à janela (85% da área disponível)
            available_width = Window.width * 0.85
            available_height = Window.height * 0.75
            
            zoom_width = available_width / page_width
            zoom_height = available_height / page_height
            
            # Usar o menor zoom para garantir que cabe
            optimal_zoom = min(zoom_width, zoom_height) * 0.75

            
            # Limitar zoom entre 0.3 e 3.0
            optimal_zoom = max(0.3, min(3.0, optimal_zoom))
            
            self.page_state['zoom'] = optimal_zoom
            self._render_page()
            
        except Exception as e:
            print(f"Erro ao ajustar página: {e}")
            self._render_page()
    
    def _render_page(self):
        """
        Renderiza a página atual do PDF com alta qualidade.
        """
        if not self.pdf_document or not self.pdf_image or not self.pdf_container:
            return
        
        try:
            import fitz
            
            page_num = self.page_state['current']
            total_pages = len(self.pdf_document)
            
            # Atualizar label de página
            if self.page_label:
                zoom_percent = int(self.page_state['zoom'] * 100)
                self.page_label.text = f'Página {page_num + 1} de {total_pages} • {zoom_percent}%'
            
            # Obter página
            page = self.pdf_document[page_num]
            
            # Matriz de transformação com alta resolução
            zoom = self.page_state['zoom']
            # Multiplicar por 2 para melhor qualidade de renderização
            mat = fitz.Matrix(zoom * 2.0, zoom * 2.0)
            
            # Renderizar página com alta qualidade
            pix = page.get_pixmap(matrix=mat, alpha=False)
            
            # Converter para PIL Image
            img_data = pix.tobytes("png")
            img = PILImage.open(io.BytesIO(img_data))
            
            # Garantir formato RGBA
            if img.mode != 'RGBA':
                img = img.convert('RGBA')
            
            # Criar textura Kivy
            img_width, img_height = img.size
            texture = Texture.create(size=(img_width, img_height), colorfmt='rgba')
            texture.blit_buffer(img.tobytes(), colorfmt='rgba', bufferfmt='ubyte')
            texture.flip_vertical()
            
            # Aplicar textura
            self.pdf_image.texture = texture
            self.pdf_image.size = (img_width, img_height)
            
            # Ajustar container
            self.pdf_container.size = (
                img_width + dp(40), 
                img_height + dp(40)
            )
            
        except Exception as e:
            print(f"Erro ao renderizar página: {e}")
            if self.error_callback:
                self.error_callback(f'Erro ao renderizar página:\n{str(e)}')
    
    def _nav_page(self, direction, total_pages):
        """
        Navega entre páginas do PDF.
        
        Args:
            direction: -1 para anterior, 1 para próxima
            total_pages: Total de páginas do documento
        """
        new_page = self.page_state['current'] + direction
        
        if 0 <= new_page < total_pages:
            self.page_state['current'] = new_page
            self._render_page()
    
    def _zoom_page(self, amount):
        """
        Aplica zoom na página.
        
        Args:
            amount: Valor a adicionar ao zoom (positivo ou negativo)
        """
        new_zoom = self.page_state['zoom'] + amount
        
        # Limitar zoom entre 30% e 300%
        if 0.3 <= new_zoom <= 3.0:
            self.page_state['zoom'] = new_zoom
            self._render_page()
    
    def _fit_to_window(self):
        """Ajusta página para caber perfeitamente na janela."""
        self._render_page_with_fit()
    
    def _close_viewer(self, popup):
        """
        Fecha o visualizador e libera recursos.
        
        Args:
            popup: Popup a ser fechado
        """
        try:
            if self.pdf_document:
                self.pdf_document.close()
                self.pdf_document = None
        except Exception as e:
            print(f"Erro ao fechar PDF: {e}")
        
        self.pdf_image = None
        self.pdf_container = None
        self.page_label = None
        popup.dismiss()
    
    def _show_pymupdf_install_message(self, pdf_path):
        """
        Mostra mensagem para instalar PyMuPDF.
        
        Args:
            pdf_path: Caminho do PDF (para abrir em navegador como alternativa)
        """
        if getattr(self, "pymupdf_dialog", None):
            self.pymupdf_dialog.dismiss()

        instructions = (
            "Para usar o visualizador interno de PDF,\\n"
            "instale a biblioteca PyMuPDF:\\n\\n"
            "pip install PyMuPDF --break-system-packages"
        )

        content = MDBoxLayout(
            orientation='vertical',
            spacing=dp(10),
            padding=[dp(16), dp(12), dp(16), dp(8)],
            size_hint_y=None,
        )
        content.bind(minimum_height=content.setter('height'))

        title = MDLabel(
            text='Biblioteca PyMuPDF nao instalada',
            font_style='Subtitle1',
            bold=True,
            halign='left',
            theme_text_color='Custom',
            text_color=_theme_color('warning', (0.9, 0.5, 0.1, 1)),
            size_hint_y=None,
            height=dp(24),
        )
        content.add_widget(title)

        message = MDLabel(
            text=instructions,
            font_style='Body2',
            halign='left',
            valign='middle',
            theme_text_color='Custom',
            text_color=_theme_color('text_primary', (0.3, 0.3, 0.3, 1)),
            size_hint_y=None,
        )
        message.bind(size=lambda inst, _: setattr(inst, 'text_size', (inst.width, None)))
        message.bind(texture_size=lambda inst, value: setattr(inst, 'height', value[1]))
        content.add_widget(message)

        self.pymupdf_dialog = MDDialog(
            title='Dependencia necessaria',
            type='custom',
            content_cls=content,
            size_hint=(None, None),
            size=(min(dp(560), Window.width * 0.9), dp(260)),
            buttons=[
                MDFlatButton(
                    text='Fechar',
                    on_release=lambda x: self.pymupdf_dialog.dismiss(),
                ),
                MDRaisedButton(
                    text='Abrir no navegador',
                    md_bg_color=_theme_color('primary', (0.15, 0.52, 0.76, 1)),
                    on_release=lambda x: [
                        self._open_in_browser(pdf_path),
                        self.pymupdf_dialog.dismiss(),
                    ],
                ),
            ],
        )
        self.pymupdf_dialog.open()
