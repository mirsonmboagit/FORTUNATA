from kivy.lang import Builder
from kivy.app import App
from kivy.clock import Clock
from kivy.graphics.texture import Texture
from kivy.metrics import dp
from kivy.core.audio import SoundLoader
from kivy.animation import Animation
from kivymd.uix.screen import MDScreen
from kivymd.uix.list import TwoLineListItem
from kivymd.uix.dialog import MDDialog
from kivymd.uix.button import MDFlatButton, MDRaisedButton
from kivymd.uix.menu import MDDropdownMenu
from kivy.properties import ObjectProperty
from database.database import Database
from datetime import date, datetime
import time
import cv2
from pyzbar.pyzbar import decode
import numpy as np
import os

Builder.load_file("utils/losses_screen.kv")

def _theme_color(name, fallback):
    app = App.get_running_app()
    tokens = getattr(app, "theme_tokens", {}) if app else {}
    return tokens.get(name, fallback)

LOSS_TYPES = [
    ("DANIFICADO", "DAMAGE"),
    ("EXPIRADO", "EXPIRED"),
    ("ROUBO", "THEFT"),
    ("AJUSTE", "ADJUSTMENT"),
]



class LossesScreen(MDScreen):
    db = ObjectProperty(None)
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.products = []
        self.selected_product = None
        self.selected_loss_type = None
        self.loss_menu = None
        # Scanner
        self.scanning = False
        self.camera = None
        self.current_camera_index = 0
        self.sound_ok = None
        self.sound_error = None
        self.last_scan_code = None
        self.last_scan_time = 0
        
        # UI State
        self.current_step = 1  # 1 = selecionar produto, 2 = preencher perda
        
        Clock.schedule_once(self.init_screen, 0.1)

    def init_screen(self, dt):
        """Inicializa a tela"""
        self.load_sounds()
        self.load_products()
        self.set_scanner_status("Pronto para escanear", _theme_color("text_secondary", [0.5, 0.5, 0.5, 1]))
        self.update_ui_state()

    def on_enter(self):
        """Quando entra na tela"""
        self.load_products()
        self.clear_form()
        self.update_ui_state()

    def on_leave(self):
        """Quando sai da tela"""
        self.stop_scanner()

    def go_back(self):
        """Volta para tela anterior"""
        app = App.get_running_app()
        role = getattr(app, "current_role", "manager")
        self.manager.current = "admin" if role == "admin" else "manager"

    def open_losses_history(self, *args):
        """Abre a tela de histórico de perdas"""
        if not self.manager:
            return
        self.manager.current = "losses_history"
        if "losses_history" in self.manager.screen_names:
            screen = self.manager.get_screen("losses_history")
            Clock.schedule_once(lambda dt: screen.load_losses_table(), 0.1)

    def export_losses_pdf(self, *args):
        """Abrir seleção de período e gerar PDF de perdas."""
        dialog = DateRangeDialog(database=self.db, callback=self._generate_losses_pdf)
        dialog.open()

    def _generate_losses_pdf(self, start_dt, end_dt):
        """Gera PDF profissional de perdas."""
        try:
            metrics = self.db.calculate_loss_metrics(start_dt, end_dt) or {}
            records = self.db.get_loss_records(start_dt, end_dt, limit=200)
            data = {
                "metrics": metrics,
                "records": records,
            }
            filters = {
                "start_date": start_dt,
                "end_date": end_dt,
                "product": "Todos os Produtos",
                "category": "Todas as Categorias",
            }
            pdf_path = self.loss_report.generate(data, filters)
            self._show_pdf_success(pdf_path)
        except Exception as e:
            self.show_dialog("Erro", f"Falha ao gerar PDF de perdas: {e}")

    def _show_pdf_success(self, pdf_path):
        """Mostra confirmação e opção de abrir PDF."""
        dialog = MDDialog(
            title="PDF Gerado",
            text=f"Arquivo criado em:\n{pdf_path}",
            buttons=[
                MDFlatButton(text="FECHAR", on_release=lambda x: dialog.dismiss()),
                MDRaisedButton(
                    text="ABRIR",
                    md_bg_color=_theme_color("info", (0.15, 0.45, 0.75, 1)),
                    on_release=lambda x: self._open_pdf(dialog, pdf_path),
                ),
            ],
        )
        dialog.open()

    def _open_pdf(self, dialog, pdf_path):
        dialog.dismiss()
        self.pdf_viewer.view_pdf(pdf_path)

    # ========== UI STATE MANAGEMENT (NOVO) ==========
    def update_ui_state(self):
        """Atualiza visibilidade dos cards baseado no estado"""
        if self.current_step == 1:
            # Step 1: Selecionar produto
            self._show_card(self.ids.search_card, 360)
            self._hide_card(self.ids.loss_form_card)
            self._hide_card(self.ids.selected_product_card)
            
            # Atualizar indicadores
            self.ids.step1_icon.icon = "numeric-1-circle"
            self.ids.step1_icon.text_color = _theme_color("info", [0.15, 0.65, 0.85, 1])
            self.ids.step1_label.bold = True
            self.ids.step1_label.theme_text_color = "Primary"
            
            self.ids.step2_icon.icon = "numeric-2-circle-outline"
            self.ids.step2_icon.text_color = _theme_color("text_secondary", [0.5, 0.5, 0.5, 1])
            self.ids.step2_label.bold = False
            self.ids.step2_label.theme_text_color = "Hint"
            
        elif self.current_step == 2:
            # Step 2: Preencher perda
            self._hide_card(self.ids.search_card)
            self._show_card(self.ids.loss_form_card, 480)
            self._show_card(self.ids.selected_product_card, 80)
            
            # Atualizar indicadores
            self.ids.step1_icon.icon = "check-circle"
            self.ids.step1_icon.text_color = _theme_color("success", [0.2, 0.7, 0.3, 1])
            self.ids.step1_label.bold = False
            self.ids.step1_label.theme_text_color = "Secondary"
            
            self.ids.step2_icon.icon = "numeric-2-circle"
            self.ids.step2_icon.text_color = _theme_color("info", [0.15, 0.65, 0.85, 1])
            self.ids.step2_label.bold = True
            self.ids.step2_label.theme_text_color = "Primary"

    def _show_card(self, card, height):
        """Anima card para aparecer"""
        anim = Animation(height=height, opacity=1, duration=0.3, t='out_cubic')
        anim.start(card)

    def _hide_card(self, card):
        """Anima card para desaparecer"""
        anim = Animation(height=0, opacity=0, duration=0.3, t='out_cubic')
        anim.start(card)

    # ========== SONS ==========
    def load_sounds(self):
        """Carrega sons do scanner"""
        try:
            self.sound_ok = SoundLoader.load("sounds/beep.wav")
            self.sound_error = SoundLoader.load("sounds/beeperror.mp3")
        except:
            self.sound_ok = None
            self.sound_error = None

    def play_sound(self, success=True):
        """Toca som de sucesso ou erro"""
        try:
            if success and self.sound_ok:
                self.sound_ok.play()
            elif not success and self.sound_error:
                self.sound_error.play()
        except:
            pass

    # ========== SCANNER ==========
    def set_scanner_status(self, text, color):
        """Atualiza status do scanner"""
        if "scanner_status" in self.ids:
            self.ids.scanner_status.text = text
            self.ids.scanner_status.text_color = color

    def toggle_scanner(self):
        """Liga/desliga o scanner"""
        if self.scanning:
            self.stop_scanner()
        else:
            self.start_scanner()

    def start_scanner(self):
        """Inicia o scanner"""
        self.scanning = True
        self.ids.scan_btn.icon = "barcode-off"
        self.ids.scan_btn.md_bg_color = _theme_color("danger", [0.9, 0.3, 0.3, 1])
        self.set_scanner_status("Iniciando...", _theme_color("warning", [0.9, 0.7, 0.1, 1]))
        Clock.schedule_once(self.open_camera, 0.1)

    def stop_scanner(self):
        """Para o scanner"""
        self.scanning = False
        self.ids.scan_btn.icon = "barcode-scan"
        self.ids.scan_btn.md_bg_color = _theme_color("success", [0.2, 0.65, 0.3, 1])
        self.set_scanner_status("Scanner parado", _theme_color("text_secondary", [0.5, 0.5, 0.5, 1]))
        Clock.unschedule(self.scan_frame)
        self.close_camera()

    def open_camera(self, dt):
        """Abre a câmera"""
        try:
            self.close_camera()
            self.camera = cv2.VideoCapture(self.current_camera_index)
            
            if self.camera.isOpened():
                self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                self.set_scanner_status("✓ Escaneando...", _theme_color("success", [0.2, 0.7, 0.3, 1]))
                self.last_scan_code = None
                self.last_scan_time = 0
                Clock.schedule_interval(self.scan_frame, 1/20)
            else:
                self.set_scanner_status("✗ Câmera não encontrada", _theme_color("danger", [0.9, 0.2, 0.2, 1]))
                self.stop_scanner()
        except Exception as e:
            print(f"Erro ao abrir câmera: {e}")
            self.set_scanner_status("✗ Erro na câmera", _theme_color("danger", [0.9, 0.2, 0.2, 1]))
            self.stop_scanner()

    def close_camera(self):
        """Fecha a câmera"""
        if self.camera:
            try:
                self.camera.release()
            except:
                pass
            self.camera = None
        if "camera_image" in self.ids:
            self.ids.camera_image.texture = None

    def scan_frame(self, dt):
        """Escaneia um frame da câmera"""
        if not self.scanning or not self.camera:
            return

        try:
            ret, frame = self.camera.read()
            if not ret:
                return

            # Melhorar contraste
            frame = cv2.convertScaleAbs(frame, alpha=1.2, beta=10)
            
            # Procurar códigos de barras
            codes = decode(frame)
            if codes:
                self.process_barcode(codes[0], frame)
            
            # Mostrar frame na tela
            self.show_frame(frame)
            
        except Exception as e:
            print(f"Erro ao escanear: {e}")

    def process_barcode(self, code, frame):
        """Processa código de barras encontrado"""
        try:
            # Decodificar
            barcode = code.data.decode("utf-8").strip()
            
            # Evitar duplicatas
            now = time.time()
            if barcode == self.last_scan_code and (now - self.last_scan_time) < 2:
                return
            
            self.last_scan_code = barcode
            self.last_scan_time = now
            
            # Buscar produto
            product = self.find_product_by_barcode(barcode)
            
            if product:
                # Encontrou!
                self.ids.search_input.text = barcode
                self.select_product(product)
                self.play_sound(success=True)
                name = product[1][:25]
                self.set_scanner_status(f"✓ {name}", _theme_color("success", [0.2, 0.7, 0.3, 1]))
                
                # Desenhar quadrado verde
                pts = code.polygon
                if len(pts) == 4:
                    pts = [(p.x, p.y) for p in pts]
                    cv2.polylines(frame, [np.array(pts, dtype=np.int32)], True, (0, 255, 0), 3)
            else:
                # Não encontrou
                self.play_sound(success=False)
                self.set_scanner_status("✗ Produto não encontrado", _theme_color("danger", [0.9, 0.3, 0.2, 1]))
                
        except Exception as e:
            print(f"Erro ao processar código: {e}")

    def show_frame(self, frame):
        """Mostra frame na tela"""
        try:
            buf = cv2.flip(frame, 0).tobytes()
            texture = Texture.create(
                size=(frame.shape[1], frame.shape[0]),
                colorfmt="bgr"
            )
            texture.blit_buffer(buf, colorfmt="bgr", bufferfmt="ubyte")
            self.ids.camera_image.texture = texture
        except:
            pass

    def switch_camera(self):
        """Troca para próxima câmera"""
        was_scanning = self.scanning
        if was_scanning:
            self.stop_scanner()
        
        self.current_camera_index = (self.current_camera_index + 1) % 4
        
        if was_scanning:
            Clock.schedule_once(lambda dt: self.start_scanner(), 0.1)

    # ========== PRODUTOS ==========
    def load_products(self):
        """Carrega produtos do banco"""
        try:
            self.db.cursor.execute("""
                SELECT id, description, existing_stock, sale_price,
                       unit_purchase_price, barcode, is_sold_by_weight,
                       expiry_date, status
                FROM products
                WHERE existing_stock > 0
            """)
            self.products = self.db.cursor.fetchall() or []
            self.show_products(self.products)
        except Exception as e:
            print(f"Erro ao carregar produtos: {e}")
            self.products = []

    def show_products(self, products):
        """Mostra produtos na lista"""
        if "products_list" not in self.ids:
            return
            
        self.ids.products_list.clear_widgets()
        
        if not products:
            empty = TwoLineListItem(
                text="Nenhum produto disponível",
                secondary_text="Stock vazio ou filtro aplicado"
            )
            self.ids.products_list.add_widget(empty)
            return
        
        for p in products:
            pid, name, stock, price, cost, barcode, is_weight, exp, status = p
            unit = "KG" if is_weight else "UN"
            
            # Status tag
            tag = ""
            if status == "EXPIRADO":
                tag = " • ⚠️ EXPIRADO"
            elif status == "PERTO_DO_PRAZO":
                tag = " • ⏰ PERTO DO PRAZO"
            
            # Criar item clicável
            def on_item_click(instance, product=p):
                self.select_product(product)
            
            item = TwoLineListItem(
                text=name,
                secondary_text=f"Stock: {stock:.1f} {unit} • {price:.2f} MZN{tag}"
            )
            item.bind(on_release=on_item_click)
            
            self.ids.products_list.add_widget(item)

    def on_search(self, text):
        """Filtra produtos pela pesquisa"""
        if not text:
            text = ""
        
        query = text.strip().lower()
        
        if not query:
            self.show_products(self.products)
            return
        
        # Filtrar produtos
        filtered = []
        for p in self.products:
            if len(p) < 9:
                continue
                
            pid, name, stock, price, cost, barcode, is_weight, exp, status = p
            
            # Buscar em: ID, nome ou código de barras
            search_in_id = str(pid).lower()
            search_in_name = (name or "").lower()
            search_in_barcode = str(barcode).lower() if barcode else ""
            
            if (query in search_in_id or 
                query in search_in_name or 
                query in search_in_barcode):
                filtered.append(p)
        
        self.show_products(filtered)

    def on_search_enter(self):
        """Quando usuário pressiona Enter na busca"""
        query = self.ids.search_input.text.strip().lower()
        if not query:
            return
        
        # Buscar produtos filtrados
        filtered = []
        for p in self.products:
            if len(p) < 9:
                continue
                
            pid, name, stock, price, cost, barcode, is_weight, exp, status = p
            search_in_id = str(pid).lower()
            search_in_name = (name or "").lower()
            search_in_barcode = str(barcode).lower() if barcode else ""
            
            if (query in search_in_id or 
                query in search_in_name or 
                query in search_in_barcode):
                filtered.append(p)
        
        # Se encontrou exatamente 1, selecionar automaticamente
        if len(filtered) == 1:
            self.select_product(filtered[0])
        elif len(filtered) > 1:
            # Se encontrou vários, mostrar mensagem
            self.show_dialog("🔍 Busca", f"Encontrados {len(filtered)} produtos. Clique em um ou refine a busca.")
        else:
            self.show_dialog("🔍 Busca", "Nenhum produto encontrado.")

    def find_product_by_barcode(self, barcode):
        """Busca produto pelo código de barras"""
        for p in self.products:
            if len(p) > 5 and p[5] and str(p[5]).strip() == str(barcode).strip():
                return p
        return None

    def select_product(self, product):
        """Seleciona um produto e avança para step 2"""
        self.selected_product = product
        pid, name, stock, price, cost, barcode, is_weight, exp, status = product
        unit = "KG" if is_weight else "UN"
        
        # Atualizar UI do produto selecionado
        self.ids.selected_name.text = name
        self.ids.selected_stock.text = f"Stock: {stock:.1f} {unit}"
        self.ids.selected_unit.text = f"Unidade: {unit}"
        self.ids.selected_price.text = f"Preço: {price:.2f} MZN"
        
        # Configurar input de quantidade
        self.ids.qty_input.text = "1"
        self.ids.qty_input.input_filter = "float" if is_weight else "int"
        
        # Auto-preencher se expirado
        if status == "EXPIRADO":
            self.set_loss_type("EXPIRADO", "EXPIRED")
            self.ids.reason_input.text = "Produto expirado automaticamente detectado"
        else:
            # Limpar tipo e motivo anteriores
            self.selected_loss_type = None
            self.ids.loss_type_btn.text = "Selecionar Tipo"
            self.ids.reason_input.text = ""
        
        self.update_summary()
        
        # Avançar para step 2
        self.current_step = 2
        self.update_ui_state()

    def clear_selection(self):
        """Limpa seleção e volta para step 1"""
        self.selected_product = None
        self.current_step = 1
        self.update_ui_state()
        self.clear_form()

    # ========== TIPO DE PERDA ==========
    def open_loss_menu(self):
        """Abre menu de tipos de perda"""
        if not self.loss_menu:
            items = []
            for label, code in LOSS_TYPES:
                items.append({
                    "text": label,
                    "on_release": lambda x=label, y=code: self.set_loss_type(x, y)
                })
            self.loss_menu = MDDropdownMenu(
                caller=self.ids.loss_type_btn,
                items=items,
                width_mult=3
            )
        self.loss_menu.open()

    def set_loss_type(self, label, code):
        """Define tipo de perda e auto-preenche motivo"""
        self.selected_loss_type = code
        self.ids.loss_type_btn.text = label
        
        # Auto-preencher motivo baseado no tipo
        if code == "EXPIRED" and not self.ids.reason_input.text:
            self.ids.reason_input.text = "Produto expirado"
        elif code == "DAMAGE" and not self.ids.reason_input.text:
            self.ids.reason_input.text = "Produto danificado durante armazenamento"
        elif code == "THEFT" and not self.ids.reason_input.text:
            self.ids.reason_input.text = "Perda por roubo"
        elif code == "ADJUSTMENT" and not self.ids.reason_input.text:
            self.ids.reason_input.text = "Ajuste de inventário"
        
        if self.loss_menu:
            self.loss_menu.dismiss()

    # ========== RESUMO ==========
    def on_qty_change(self, text):
        """Quando quantidade muda"""
        self.update_summary()

    def update_summary(self):
        """Atualiza resumo financeiro"""
        if not self.selected_product:
            self.ids.cost_label.text = "0.00 MZN"
            self.ids.revenue_label.text = "0.00 MZN"
            return
        
        qty = self.get_qty()
        if qty is None or qty <= 0:
            self.ids.cost_label.text = "0.00 MZN"
            self.ids.revenue_label.text = "0.00 MZN"
            return
        
        price = float(self.selected_product[3] or 0)
        cost = float(self.selected_product[4] or 0)
        
        total_cost = cost * qty
        total_revenue = price * qty
        
        self.ids.cost_label.text = f"{total_cost:.2f} MZN"
        self.ids.revenue_label.text = f"{total_revenue:.2f} MZN"

    def get_qty(self):
        """Pega quantidade digitada"""
        try:
            text = self.ids.qty_input.text.strip()
            if not text:
                return None
            return float(text)
        except:
            return None

    # ========== REGISTRO ==========
    def register_loss(self):
        """Registra a perda"""
        # Validações
        if not self.selected_product:
            self.show_dialog("❌ Erro", "Nenhum produto selecionado")
            return
        
        if not self.selected_loss_type:
            self.show_dialog("❌ Erro", "Selecione o tipo de perda")
            return
        
        qty = self.get_qty()
        if not qty or qty <= 0:
            self.show_dialog("❌ Erro", "Quantidade inválida ou vazia")
            return
        
        pid, name, stock, price, cost, barcode, is_weight, exp, status = self.selected_product
        
        # Validar quantidade inteira para unidades
        if not is_weight and not float(qty).is_integer():
            self.show_dialog("❌ Erro", "Quantidade deve ser um número inteiro para produtos por unidade")
            return
        
        # Validar stock
        if qty > float(stock):
            self.show_dialog("❌ Erro", f"Quantidade maior que stock disponível ({stock:.1f})")
            return
        
        # Motivo obrigatório
        reason = self.ids.reason_input.text.strip()
        if not reason:
            self.show_dialog("❌ Erro", "Motivo é obrigatório")
            return
        
        # Registrar no banco
        try:
            note = self.ids.note_input.text.strip()
            evidence = self.ids.evidence_input.text.strip() or None
            
            app = App.get_running_app()
            user = getattr(app, "current_user", None)
            role = getattr(app, "current_role", "manager")
            
            movement_id = self.db.record_stock_movement(
                pid, self.selected_loss_type, qty, "OUT",
                reason=reason,
                note=note,
                evidence_path=evidence,
                created_by=user,
                created_role=role,
                unit_cost=cost,
                unit_price=price,
            )
            
            if movement_id:
                stock_before = float(stock)
                stock_after = stock_before - float(qty)
                self._append_loss_log({
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                    "movement_id": movement_id,
                    "product_id": pid,
                    "product_name": name,
                    "barcode": barcode,
                    "loss_type": self.selected_loss_type,
                    "qty": float(qty),
                    "unit": "KG" if is_weight else "UN",
                    "reason": reason,
                    "note": note,
                    "evidence_path": evidence,
                    "user": user,
                    "role": role,
                    "unit_cost": float(cost or 0),
                    "unit_price": float(price or 0),
                    "total_cost": float(cost or 0) * float(qty),
                    "total_price": float(price or 0) * float(qty),
                    "stock_before": stock_before,
                    "stock_after": stock_after,
                })
                self.show_dialog("✅ Sucesso", "Perda registrada com sucesso!")
                if user:
                    self.db.log_action(user, role, "REGISTER_LOSS", 
                                      f"{self.selected_loss_type} | {name} | {qty}")
                self.clear_form()
                self.load_products()
                
                # Voltar para step 1
                self.current_step = 1
                self.update_ui_state()
            else:
                self.show_dialog("❌ Erro", "Erro ao registrar perda no banco de dados")
                
        except Exception as e:
            print(f"Erro: {e}")
            self.show_dialog("❌ Erro", f"Erro ao registrar perda: {str(e)}")

    # ========== HELPERS ==========
    def _append_loss_log(self, entry):
        """Grava um registro simples em losses_log.py"""
        try:
            log_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "losses_log.py"))
            if not os.path.exists(log_path):
                with open(log_path, "w", encoding="utf-8") as f:
                    f.write("# Auto-generated loss log entries\n")
                    f.write("LOGS = []\n")
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"LOGS.append({entry!r})\n")
        except Exception as e:
            print(f"Erro ao salvar log de perda: {e}")

    def clear_form(self):
        """Limpa o formulário"""
        self.selected_product = None
        self.selected_loss_type = None
        self.ids.loss_type_btn.text = "Selecionar Tipo"
        self.ids.qty_input.text = ""
        self.ids.reason_input.text = ""
        self.ids.note_input.text = ""
        self.ids.evidence_input.text = ""
        self.ids.selected_name.text = "Produto Selecionado"
        self.ids.selected_stock.text = "Stock: --"
        self.ids.selected_unit.text = "Tipo: --"
        self.ids.selected_price.text = "Preço: --"
        self.ids.search_input.text = ""
        self.update_summary()

    def show_dialog(self, title, message):
        """Mostra mensagem"""
        dialog = MDDialog(
            title=title,
            text=message,
            buttons=[MDFlatButton(text="OK", on_release=lambda x: dialog.dismiss())]
        )
        dialog.open()
