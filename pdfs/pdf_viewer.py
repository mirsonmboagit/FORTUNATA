import importlib
import io
import os
import platform
import subprocess
import sys
from threading import Thread
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


def _theme_color(name, fallback):
    app = App.get_running_app()
    tokens = getattr(app, "theme_tokens", {}) if app else {}
    return tokens.get(name, fallback)


def open_pdf_with_system_default(pdf_path, error_callback=None):
    if not os.path.exists(pdf_path):
        if error_callback:
            error_callback(f"Arquivo nao encontrado:\n{pdf_path}")
        return False

    try:
        absolute_path = os.path.abspath(pdf_path)
        system = platform.system()

        if system == "Windows":
            os.startfile(absolute_path)
        elif system == "Darwin":
            subprocess.Popen(["open", absolute_path])
        else:
            subprocess.Popen(["xdg-open", absolute_path])
        return True
    except Exception as e:
        if error_callback:
            error_callback(f"Erro ao abrir PDF no aplicativo padrao:\n{str(e)}")
        return False


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
        self.install_dialog = None
        self._installing_pymupdf = False
        self._pdf_path = None
        self._pdf_total_pages = 0
        self._document_open_token = 0
        self._render_token = 0
        self._page_texture = None
        self._page_texture_size = None
    
    def view_pdf(self, pdf_path, prefer_direct=False):
        """
        Inicia visualização do PDF com opções para o usuário.
        
        Args:
            pdf_path: Caminho completo para o arquivo PDF
        """
        if not os.path.exists(pdf_path):
            if self.error_callback:
                self.error_callback(f'Arquivo não encontrado:\n{pdf_path}')
            return
        
        if prefer_direct and self._open_preferred_viewer(pdf_path):
            return

        self._show_viewer_options(pdf_path)

    def _open_preferred_viewer(self, pdf_path):
        if not self._has_pymupdf():
            return self._open_in_browser(pdf_path)

        self._view_internal(pdf_path)
        return True

    def _has_pymupdf(self):
        try:
            return importlib.util.find_spec("fitz") is not None
        except Exception:
            return False

    def _can_install_pymupdf(self):
        return (not getattr(sys, "frozen", False)) and bool(getattr(sys, "executable", None))

    def print_pdf(self, pdf_path):
        if not os.path.exists(pdf_path):
            if self.error_callback:
                self.error_callback(f'Arquivo nÃ£o encontrado:\n{pdf_path}')
            return False

        try:
            absolute_path = os.path.abspath(pdf_path)
            system = platform.system()

            if system == 'Windows':
                os.startfile(absolute_path, 'print')
            elif system == 'Darwin':
                subprocess.Popen(['open', absolute_path])
            else:
                subprocess.Popen(['xdg-open', absolute_path])
            return True
        except Exception as e:
            if self.error_callback:
                self.error_callback(f'Erro ao imprimir PDF:\n{str(e)}')
            return False
    
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
                    text="Imprimir agora",
                    on_release=lambda x: [
                        self.print_pdf(pdf_path),
                        self.options_dialog.dismiss(),
                    ],
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
                os.startfile(absolute_path)
            
            elif system == 'Darwin':  # macOS
                subprocess.Popen(['open', absolute_path])
            
            else:  # Linux
                subprocess.Popen(['xdg-open', absolute_path])

            return True
        except Exception as e:
            if self.error_callback:
                self.error_callback(f'Erro ao abrir navegador:\n{str(e)}')
            return False
    
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
            total_pages: Total de páginas
            viewer_popup: Referência ao popup
        
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
            text=f'Página 1 de {total_pages}',
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
            "printer",
            lambda x: self.print_pdf(pdf_path),
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
            fit_mode="contain",
        )
        
        pdf_container.add_widget(pdf_image)
        pdf_scroll.add_widget(pdf_container)
        
        return pdf_scroll, pdf_image, pdf_container
    
    def _view_internal(self, pdf_path):
        if not self._has_pymupdf():
            self._show_pymupdf_install_message(pdf_path)
            return

        open_token = self._document_open_token + 1
        self._document_open_token = open_token

        def worker():
            total_pages = 0
            error = None
            try:
                import fitz

                document = fitz.open(pdf_path)
                try:
                    total_pages = len(document)
                finally:
                    document.close()
                if total_pages <= 0:
                    error = 'O PDF estÃ¡ vazio ou corrompido.'
            except ImportError:
                error = "__missing_pymupdf__"
            except Exception as exc:
                error = str(exc)

            Clock.schedule_once(
                lambda _dt, path=pdf_path, pages=total_pages, err=error, tok=open_token:
                    self._finish_open_document(path, pages, err, tok),
                0,
            )

        Thread(target=worker, daemon=True).start()

    def _finish_open_document(self, pdf_path, total_pages, error, token):
        if token != self._document_open_token:
            return
        if error == "__missing_pymupdf__":
            self._show_pymupdf_install_message(pdf_path)
            return
        if error:
            if self.error_callback:
                self.error_callback(f'Erro ao visualizar PDF:\n{error}')
            return

        self._pdf_path = pdf_path
        self._pdf_total_pages = int(total_pages or 0)
        self.page_state = {'current': 0, 'zoom': 1.0}
        self._create_pdf_viewer_window(pdf_path, self._pdf_total_pages)

    def _render_page_with_fit(self):
        self._render_page_async(fit_to_window=True)

    def _render_page(self):
        self._render_page_async(fit_to_window=False)

    def _render_page_async(self, fit_to_window=False):
        if not self._pdf_path or not self.pdf_image or not self.pdf_container:
            return

        page_num = int(self.page_state.get('current', 0) or 0)
        target_zoom = float(self.page_state.get('zoom', 1.0) or 1.0)
        window_width = Window.width
        window_height = Window.height
        render_token = self._render_token + 1
        self._render_token = render_token

        if self.page_label:
            self.page_label.text = f'Pagina {page_num + 1} de {self._pdf_total_pages} | a carregar...'

        def worker():
            payload = {"error": None}
            document = None
            try:
                import fitz

                document = fitz.open(self._pdf_path)
                total_pages = len(document)
                page = document[page_num]
                zoom = target_zoom
                if fit_to_window:
                    page_rect = page.rect
                    page_width = page_rect.width
                    page_height = page_rect.height
                    available_width = window_width * 0.85
                    available_height = window_height * 0.75
                    zoom_width = available_width / page_width
                    zoom_height = available_height / page_height
                    zoom = min(zoom_width, zoom_height) * 0.75
                    zoom = max(0.3, min(3.0, zoom))

                mat = fitz.Matrix(zoom * 2.0, zoom * 2.0)
                pix = page.get_pixmap(matrix=mat, alpha=False)
                img_data = pix.tobytes("png")
                img = PILImage.open(io.BytesIO(img_data))
                if img.mode != 'RGBA':
                    img = img.convert('RGBA')
                payload = {
                    "page_num": page_num,
                    "total_pages": total_pages,
                    "zoom": zoom,
                    "width": img.size[0],
                    "height": img.size[1],
                    "buffer": img.tobytes(),
                    "error": None,
                }
            except Exception as exc:
                payload = {"error": str(exc)}
            finally:
                if document is not None:
                    try:
                        document.close()
                    except Exception:
                        pass

            Clock.schedule_once(
                lambda _dt, data=payload, tok=render_token: self._apply_rendered_page(data, tok),
                0,
            )

        Thread(target=worker, daemon=True).start()

    def _apply_rendered_page(self, payload, token):
        if token != self._render_token:
            return
        if payload.get("error"):
            if self.error_callback:
                self.error_callback(f'Erro ao renderizar pÃ¡gina:\n{payload["error"]}')
            return
        if not self.pdf_image or not self.pdf_container:
            return

        self._pdf_total_pages = int(payload.get("total_pages") or self._pdf_total_pages or 0)
        self.page_state['zoom'] = float(payload.get("zoom") or self.page_state.get('zoom') or 1.0)
        page_num = int(payload.get("page_num") or 0)

        size = (int(payload["width"]), int(payload["height"]))
        if self._page_texture is None or self._page_texture_size != size:
            # Reutilizar a textura reduz alocacoes ao navegar/zoomar paginas do PDF.
            self._page_texture = Texture.create(size=size, colorfmt='rgba')
            self._page_texture.flip_vertical()
            self._page_texture_size = size
        self._page_texture.blit_buffer(payload["buffer"], colorfmt='rgba', bufferfmt='ubyte')

        self.pdf_image.texture = self._page_texture
        self.pdf_image.size = (int(payload["width"]), int(payload["height"]))
        self.pdf_container.size = (
            int(payload["width"]) + dp(40),
            int(payload["height"]) + dp(40),
        )

        if self.page_label:
            zoom_percent = int(self.page_state['zoom'] * 100)
            self.page_label.text = f'Pagina {page_num + 1} de {self._pdf_total_pages} | {zoom_percent}%'

    def _nav_page(self, direction, total_pages):
        total_pages = int(self._pdf_total_pages or total_pages or 0)
        new_page = int(self.page_state.get('current', 0) or 0) + direction
        if 0 <= new_page < total_pages:
            self.page_state['current'] = new_page
            self._render_page()

    def _zoom_page(self, amount):
        new_zoom = float(self.page_state.get('zoom', 1.0) or 1.0) + amount
        if 0.3 <= new_zoom <= 3.0:
            self.page_state['zoom'] = new_zoom
            self._render_page()

    def _fit_to_window(self):
        self._render_page_with_fit()

    def _close_viewer(self, popup):
        self._document_open_token += 1
        self._render_token += 1
        self._pdf_path = None
        self._pdf_total_pages = 0
        self._page_texture = None
        self._page_texture_size = None
        self.pdf_document = None
        self.pdf_image = None
        self.pdf_container = None
        self.page_label = None
        self.current_popup = None
        popup.dismiss()

    def _show_pymupdf_install_message(self, pdf_path):
        """
        Mostra mensagem para instalar PyMuPDF.
        
        Args:
            pdf_path: Caminho do PDF (para abrir em navegador como alternativa)
        """
        if getattr(self, "pymupdf_dialog", None):
            self.pymupdf_dialog.dismiss()

        if self._can_install_pymupdf():
            instructions = (
                "O visualizador interno usa a biblioteca PyMuPDF.\n\n"
                "Posso instalar esta dependencia agora e abrir o PDF automaticamente."
            )
        else:
            instructions = (
                "Esta versao do app foi iniciada sem suporte para instalar novas "
                "bibliotecas em tempo real.\n\n"
                "Inclua PyMuPDF na instalacao ou na build do projeto para ativar o "
                "visualizador interno."
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
            size=(min(dp(580), Window.width * 0.9), dp(280)),
            buttons=self._build_pymupdf_dialog_buttons(pdf_path),
        )
        self.pymupdf_dialog.open()

    def _build_pymupdf_dialog_buttons(self, pdf_path):
        buttons = [
            MDFlatButton(
                text='Fechar',
                on_release=lambda x: self.pymupdf_dialog.dismiss(),
            ),
            MDRectangleFlatButton(
                text='Abrir no navegador',
                on_release=lambda x: [
                    self._open_in_browser(pdf_path),
                    self.pymupdf_dialog.dismiss(),
                ],
            ),
        ]

        if self._can_install_pymupdf():
            buttons.append(
                MDRaisedButton(
                    text='Instalar e abrir',
                    md_bg_color=_theme_color('primary', (0.15, 0.52, 0.76, 1)),
                    on_release=lambda x: self._install_pymupdf_async(pdf_path),
                )
            )

        return buttons

    def _install_pymupdf_async(self, pdf_path):
        if self._installing_pymupdf:
            return

        if getattr(self, "pymupdf_dialog", None):
            self.pymupdf_dialog.dismiss()
            self.pymupdf_dialog = None

        if not self._can_install_pymupdf():
            self._show_pymupdf_install_message(pdf_path)
            return

        self._installing_pymupdf = True
        self._show_install_progress_dialog()

        def worker():
            error_message = None

            for command in self._build_pymupdf_install_commands():
                try:
                    completed = subprocess.run(
                        command,
                        capture_output=True,
                        text=True,
                        timeout=300,
                    )
                except Exception as exc:
                    error_message = str(exc)
                    continue

                if completed.returncode == 0:
                    importlib.invalidate_caches()
                    error_message = None
                    break

                error_message = self._summarize_install_output(
                    completed.stderr or completed.stdout,
                    completed.returncode,
                )

            Clock.schedule_once(
                lambda _dt, err=error_message: self._finish_pymupdf_install(pdf_path, err),
                0,
            )

        Thread(target=worker, daemon=True).start()

    def _build_pymupdf_install_commands(self):
        base_command = [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "PyMuPDF",
        ]
        commands = [base_command]

        base_prefix = getattr(sys, "base_prefix", sys.prefix)
        real_prefix = getattr(sys, "real_prefix", None)
        in_virtualenv = bool(real_prefix) or (base_prefix != sys.prefix)

        if not in_virtualenv:
            commands.append(base_command[:-1] + ["--user", "PyMuPDF"])

        return commands

    def _summarize_install_output(self, raw_output, returncode):
        text = (raw_output or "").strip()
        if not text:
            return f"pip terminou com codigo {returncode}."

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        summary = " ".join(lines[-3:])
        if len(summary) > 320:
            summary = summary[:317].rstrip() + "..."
        return summary

    def _show_install_progress_dialog(self):
        if getattr(self, "install_dialog", None):
            self.install_dialog.dismiss()

        content = MDBoxLayout(
            orientation='vertical',
            spacing=dp(10),
            padding=[dp(16), dp(12), dp(16), dp(10)],
            size_hint_y=None,
        )
        content.bind(minimum_height=content.setter('height'))

        headline = MDLabel(
            text='A instalar PyMuPDF...',
            font_style='Subtitle1',
            bold=True,
            halign='left',
            theme_text_color='Custom',
            text_color=_theme_color('primary', (0.15, 0.52, 0.76, 1)),
            size_hint_y=None,
            height=dp(24),
        )
        content.add_widget(headline)

        message = MDLabel(
            text=(
                'Isto pode demorar alguns segundos.\n'
                'Assim que a instalacao terminar, o PDF sera aberto automaticamente.'
            ),
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

        self.install_dialog = MDDialog(
            title='Preparando visualizador interno',
            type='custom',
            content_cls=content,
            size_hint=(None, None),
            size=(min(dp(560), Window.width * 0.9), dp(220)),
        )
        self.install_dialog.open()

    def _finish_pymupdf_install(self, pdf_path, error_message):
        self._installing_pymupdf = False

        if getattr(self, "install_dialog", None):
            self.install_dialog.dismiss()
            self.install_dialog = None

        importlib.invalidate_caches()

        if self._has_pymupdf():
            self._view_internal(pdf_path)
            return

        if error_message and self.error_callback:
            self.error_callback(f'Nao foi possivel instalar PyMuPDF:\n{error_message}')

        self._show_pymupdf_install_message(pdf_path)
