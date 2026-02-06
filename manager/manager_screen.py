from kivymd.uix.screen import MDScreen
from kivymd.uix.card import MDCard
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.label import MDLabel
from kivymd.uix.button import MDRaisedButton, MDIconButton
from kivymd.uix.textfield import MDTextField
from kivymd.uix.dialog import MDDialog
from kivymd.uix.list import MDList, OneLineListItem
from kivy.uix.scrollview import ScrollView
from kivy.uix.image import Image
from kivy.uix.popup import Popup
from kivy.uix.widget import Widget
from kivy.uix.scatter import Scatter
from kivy.graphics.texture import Texture
from kivy.clock import Clock
from kivy.app import App
from kivy.metrics import dp
from kivy.lang import Builder
from kivy.properties import StringProperty
from database.database import Database
from datetime import datetime
import cv2
from pyzbar.pyzbar import decode
import numpy as np
from kivy.core.audio import SoundLoader

# Carregar o arquivo KV
Builder.load_file('manager/sales_screen.kv')


class ProductCard(MDCard):
  """Card de produto individual"""
  
  def __init__(self, product_data, add_callback, **kwargs):
    super().__init__(**kwargs)
    self.product_data = product_data
    self.add_callback = add_callback
    self.setup_product()
  
  def setup_product(self):
    """Configurar dados do produto"""
    product_id = self.product_data[0]
    product_name = self.product_data[1]
    product_stock = self.product_data[2]
    product_price = self.product_data[3]
    is_sold_by_weight = self.product_data[5] if len(self.product_data) > 5 else 0
    
    # Preencher labels
    self.ids.product_id_label.text = str(product_id)
    self.ids.product_name_label.text = product_name
    
    # Tipo
    if is_sold_by_weight:
      self.ids.product_type_label.text = "KG"
      self.ids.product_type_label.text_color = [0.8, 0.4, 0.0, 1]
      self.ids.product_price_header.text = "PREÇO/KG"
    else:
      self.ids.product_type_label.text = "UN"
      self.ids.product_type_label.text_color = [0.1, 0.5, 0.8, 1]
      self.ids.product_price_header.text = "PREÇO/UN"
    
    # Estoque com cores
    stock_text = f"{product_stock:.2f}" if is_sold_by_weight else f"{int(product_stock)}"
    self.ids.product_stock_label.text = stock_text
    
    if product_stock > 50:
      self.ids.product_stock_label.text_color = [0.15, 0.7, 0.3, 1] # Verde
    elif product_stock > 20:
      self.ids.product_stock_label.text_color = [0.9, 0.7, 0.1, 1] # Amarelo
    else:
      self.ids.product_stock_label.text_color = [0.9, 0.2, 0.2, 1] # Vermelho
    
    # Preço
    self.ids.product_price_label.text = f"{product_price:.2f} MZN"
  
  def on_add_click(self):
    """Callback ao clicar em adicionar"""
    self.add_callback(self.product_data)


class SalesScreen(MDScreen):
  current_date = StringProperty("")
  current_time = StringProperty("")

  def __init__(self, **kwargs):
    super().__init__(**kwargs)
    self.db = Database()
    self.cart_items = []
    self.total_amount = 0.0
    self.products_dict = {}
    self.scanning = False
    self.camera_active = False
    self.current_camera = 0
    self.camera_capture = None
    self.scanner_sound_success = None
    self.scanner_sound_error = None
    self.last_barcode = None
    self.last_barcode_time = 0
    
    # Propriedades para o header
    self.current_date = datetime.now().strftime("%d/%m/%Y")
    self.current_time = datetime.now().strftime("%H:%M")
    
    Clock.schedule_once(self.post_init, 0.1)
  
  def post_init(self, dt):
    """Inicialização após o KV estar carregado"""
    self.load_scanner_sounds()
    self.load_products()
    self.test_barcode_database()
    
    # Atualizar relógio a cada minuto
    Clock.schedule_interval(self.update_time, 60)
  
  def update_time(self, dt):
    """Atualizar hora"""
    self.current_time = datetime.now().strftime("%H:%M")
  
  def _log_action(self, action, details=""):
    """Log de ações"""
    app = App.get_running_app()
    username = getattr(app, "current_user", None)
    role = getattr(app, "current_role", None) or "manager"
    if username:
      self.db.log_action(username, role, action, details)
  
  def load_scanner_sounds(self):
    """Carregar sons do scanner"""
    try:
      self.scanner_sound_success = SoundLoader.load('sounds/beep.wav')
      self.scanner_sound_error = SoundLoader.load('sounds/beeperror.mp3')
      
      if not self.scanner_sound_success or not self.scanner_sound_error:
        print("⚠ Arquivos de som não encontrados")
    except Exception as e:
      print(f"❌ Erro ao carregar sons: {e}")
      self.scanner_sound_success = None
      self.scanner_sound_error = None
  
  def play_scanner_sound(self, success=True):
    """Reproduzir som do scanner"""
    try:
      if success and self.scanner_sound_success:
        self.scanner_sound_success.play()
      elif not success and self.scanner_sound_error:
        self.scanner_sound_error.play()
    except Exception as e:
      print(f"❌ Erro ao reproduzir som: {e}")
  
  def test_barcode_database(self):
    """Teste: verificar produtos com código de barras"""
    try:
      print("\n" + "="*70)
      print("📊 TESTE - Produtos com Código de Barras")
      print("="*70)
      
      self.db.cursor.execute("""
        SELECT id, description, barcode, existing_stock, is_sold_by_weight
        FROM products
        WHERE barcode IS NOT NULL AND barcode != ''
        ORDER BY id
      """)
      
      produtos = self.db.cursor.fetchall()
      
      if produtos:
        print(f"✓ {len(produtos)} produto(s) com código de barras:\n")
        for p in produtos:
          tipo = "KG" if (len(p) > 4 and p[4]) else "UN"
          print(f"  ID: {p[0]:4d} | Barcode: '{p[2]:15s}' | {p[1]:30s} | "
             f"Estoque: {p[3]} | Tipo: {tipo}")
      else:
        print("⚠ NENHUM produto possui código de barras!")
      
      print("="*70 + "\n")
      
    except Exception as e:
      print(f"❌ Erro no teste: {e}")
  
  def load_products(self):
    """Carregar produtos"""
    try:
      products = self.db.get_products_for_sale()
      self.products_dict = {}
      
      print("\n" + "="*70)
      print("📦 PRODUTOS CARREGADOS")
      print("="*70)
      
      for p in products:
        self.products_dict[p[0]] = p
        barcode_display = f"'{p[4]}'" if p[4] else "SEM CÓDIGO"
        tipo = "KG" if (len(p) > 5 and p[5]) else "UN"
        print(f"ID: {p[0]:4d} | {p[1]:35s} | Estoque: {p[2]:7.2f} | "
           f"Preço: {p[3]:8.2f} | Tipo: {tipo} | Barcode: {barcode_display}")
      
      print(f"\n✓ Total: {len(self.products_dict)} produtos")
      print("="*70 + "\n")
      
      self.display_products(products)
      
    except Exception as e:
      print(f"❌ Erro ao carregar produtos: {e}")
      import traceback
      traceback.print_exc()
  
  def display_products(self, products):
    """Exibir produtos na lista"""
    products_list = self.ids.products_list
    products_list.clear_widgets()
    
    if not products:
      empty_label = MDLabel(
        text='Nenhum produto disponível',
        halign='center',
        theme_text_color="Secondary",
        italic=True,
        size_hint_y=None,
        height=dp(50)
      )
      products_list.add_widget(empty_label)
      self.ids.products_count_label.text = '0 itens'
      return
    
    self.ids.products_count_label.text = f'{len(products)} itens'
    
    for product in products:
      try:
        card = ProductCard(product, self.add_to_cart)
        products_list.add_widget(card)
      except Exception as e:
        print(f"❌ Erro ao exibir produto: {e}")
        continue
  
  def on_search(self, instance, text):
    """Filtrar produtos por nome, ID ou código"""
    if not text:
      self.load_products()
      return
    
    try:
      products = self.db.get_products_for_sale()
      text_lower = text.lower().strip()
      
      filtered = [
        p for p in products
        if (text_lower in str(p[1]).lower() or # nome
          text_lower in str(p[0]) or # ID
          (p[4] and text_lower in str(p[4]).lower())) # barcode
      ]
      
      self.display_products(filtered)
      
    except Exception as e:
      print(f"❌ Erro na pesquisa: {e}")
  
  def on_search_enter(self, instance):
    """Ao pressionar Enter, busca por código de barras exato"""
    text = instance.text.strip()
    if not text:
      return
    
    print(f"\n{'='*70}")
    print(f"🔍 BUSCA POR ENTER - Código: '{text}'")
    print(f"{'='*70}")
    
    try:
      product = self.db.get_product_by_barcode(text)
      
      if product:
        print(f"✓ PRODUTO ENCONTRADO!")
        print(f"  ID: {product[0]} | Nome: {product[1]}")
        print(f"{'='*70}\n")
        
        self.add_to_cart(product)
        self.show_message(f'✓ {product[1]} adicionado!')
        instance.text = ''
      else:
        print(f"❌ Código não encontrado")
        print(f"{'='*70}\n")
        
    except Exception as e:
      print(f"❌ Erro: {e}")
      import traceback
      traceback.print_exc()
  
  def add_to_cart(self, product):
    """Adicionar produto ao carrinho"""
    try:
      product_id = product[0]
      product_name = product[1]
      product_stock = product[2]
      product_price = product[3]
      is_sold_by_weight = product[5] if len(product) > 5 else 0
      
      # Produto vendido por KG - abrir popup de pesagem
      if is_sold_by_weight:
        self.show_weight_popup(product)
        return
      
      # Produto por unidade - lógica normal
      for item in self.cart_items:
        if item['id'] == product_id:
          if item['qty'] + 1 <= product_stock:
            item['qty'] += 1
            item['total'] = item['qty'] * item['price']
            self.update_cart_display()
            return
          else:
            self.show_message("⚠ Estoque insuficiente!")
            return
      
      self.cart_items.append({
        'id': product_id,
        'name': product_name,
        'qty': 1,
        'price': product_price,
        'total': product_price,
        'max_stock': product_stock,
        'is_weight': False,
        'weight_kg': 0
      })
      
      self.update_cart_display()
      
    except Exception as e:
      print(f"❌ Erro ao adicionar ao carrinho: {e}")
      import traceback
      traceback.print_exc()
  
  def show_weight_popup(self, product):
    """Popup de balança para produtos vendidos por KG"""
    product_id = product[0]
    product_name = product[1]
    product_stock = product[2]
    product_price_per_kg = product[3]
    
    content = MDBoxLayout(
      orientation='vertical',
      padding=dp(20),
      spacing=dp(12),
      size_hint_y=None,
      height=dp(560)
    )
    
    # Header
    header = MDCard(
      orientation='vertical',
      size_hint_y=None,
      height=dp(70),
      md_bg_color=[0.15, 0.65, 0.25, 1],
      padding=dp(12),
      radius=[dp(10)]
    )
    
    title = MDLabel(
      text='⚖ BALANÇA DIGITAL',
      font_style="H5",
      bold=True,
      theme_text_color="Custom",
      text_color=[1, 1, 1, 1],
      halign='center'
    )
    
    product_label = MDLabel(
      text=product_name,
      font_style="Body1",
      theme_text_color="Custom",
      text_color=[1, 1, 1, 0.9],
      halign='center'
    )
    
    header.add_widget(title)
    header.add_widget(product_label)
    
    # Info
    info_card = MDCard(
      orientation='vertical',
      size_hint_y=None,
      height=dp(80),
      padding=dp(12),
      spacing=dp(6)
    )
    
    price_label = MDLabel(
      text=f'Preço por KG: {product_price_per_kg:.2f} MZN',
      bold=True,
      font_size=dp(15)
    )
    
    stock_label = MDLabel(
      text=f'Estoque disponível: {product_stock:.2f} kg',
      font_size=dp(14)
    )
    
    info_card.add_widget(price_label)
    info_card.add_widget(stock_label)
    
    # Input de peso
    weight_input = MDTextField(
      hint_text='Digite o peso em KG',
      input_filter='float',
      mode='rectangle',
      size_hint_y=None,
      height=dp(56),
      font_size=dp(18)
    )

    # Input de preco total
    price_input = MDTextField(
      hint_text='Ou digite o valor total (MZN)',
      input_filter='float',
      mode='rectangle',
      size_hint_y=None,
      height=dp(56),
      font_size=dp(18)
    )
    
    # Preview do cálculo
    calc_card = MDCard(
      orientation='vertical',
      size_hint_y=None,
      height=dp(90),
      padding=dp(12),
      spacing=dp(4),
      md_bg_color=[0.95, 0.95, 0.95, 1]
    )
    
    calc_title = MDLabel(
      text='CÁLCULO:',
      font_size=dp(12),
      bold=True,
      theme_text_color="Secondary"
    )
    
    calc_formula = MDLabel(
      text='',
      font_size=dp(14),
      id='calc_formula'
    )
    
    calc_result = MDLabel(
      text='',
      font_size=dp(17),
      bold=True,
      theme_text_color="Custom",
      text_color=[0.12, 0.65, 0.25, 1],
      id='calc_result'
    )
    
    calc_card.add_widget(calc_title)
    calc_card.add_widget(calc_formula)
    calc_card.add_widget(calc_result)
    
    # Funções de atualização do cálculo (peso <-> preço)
    updating = {'active': False}

    def _set_calc(weight):
      if weight <= 0:
        calc_formula.text = 'Peso deve ser maior que 0'
        calc_result.text = ''
        calc_formula.text_color = [0.9, 0.3, 0.3, 1]
        return False

      if weight > product_stock:
        calc_formula.text = f'Maximo: {product_stock:.2f} kg'
        calc_result.text = ''
        calc_formula.text_color = [0.9, 0.3, 0.3, 1]
        return False

      total_price = weight * product_price_per_kg
      calc_formula.text = f'{weight:.2f} KG x {product_price_per_kg:.2f} MZN/KG ='
      calc_formula.text_color = [0.2, 0.2, 0.2, 1]
      calc_result.text = f'TOTAL: {total_price:.2f} MZN'
      return True

    def update_from_weight(instance, value):
      if updating['active']:
        return
      updating['active'] = True
      try:
        if not value or value.strip() == '':
          price_input.text = ''
          calc_formula.text = ''
          calc_result.text = ''
          return
        weight = float(value)
        total_price = weight * product_price_per_kg
        price_input.text = f'{total_price:.2f}'
        _set_calc(weight)
      except ValueError:
        calc_formula.text = 'Digite um numero valido'
        calc_formula.text_color = [0.9, 0.3, 0.3, 1]
        calc_result.text = ''
      finally:
        updating['active'] = False

    def update_from_price(instance, value):
      if updating['active']:
        return
      updating['active'] = True
      try:
        if not value or value.strip() == '':
          weight_input.text = ''
          calc_formula.text = ''
          calc_result.text = ''
          return
        total_price = float(value)
        if product_price_per_kg <= 0:
          return
        weight = total_price / product_price_per_kg
        weight_input.text = f'{weight:.3f}'
        _set_calc(weight)
      except ValueError:
        calc_formula.text = 'Digite um numero valido'
        calc_formula.text_color = [0.9, 0.3, 0.3, 1]
        calc_result.text = ''
      finally:
        updating['active'] = False

    weight_input.bind(text=update_from_weight)
    price_input.bind(text=update_from_price)
    
    # Botões
    buttons_box = MDBoxLayout(
      size_hint_y=None,
      height=dp(50),
      spacing=dp(10)
    )
    
    cancel_btn = MDRaisedButton(
      text='✗ CANCELAR',
      md_bg_color=[0.7, 0.3, 0.3, 1]
    )
    
    add_btn = MDRaisedButton(
      text='✓ ADICIONAR',
      md_bg_color=[0.12, 0.62, 0.22, 1]
    )
    
    buttons_box.add_widget(cancel_btn)
    buttons_box.add_widget(add_btn)
    
    # Montagem
    content.add_widget(header)
    content.add_widget(info_card)
    content.add_widget(weight_input)
    content.add_widget(price_input)
    content.add_widget(calc_card)
    content.add_widget(Widget())
    content.add_widget(buttons_box)
    
    # Dialog
    dialog = MDDialog(
      title='',
      type='custom',
      content_cls=content,
      size_hint=(0.8, None),
      height=dp(620)
    )
    
    # Ações dos botões
    cancel_btn.bind(on_release=lambda x: dialog.dismiss())
    
    def add_weighted_product(instance):
      try:
        weight_text = weight_input.text.strip()
        price_text = price_input.text.strip()

        if not weight_text and price_text:
          if product_price_per_kg > 0:
            weight = float(price_text) / product_price_per_kg
            weight_text = f"{weight:.3f}"
            weight_input.text = weight_text
          else:
            weight_text = ''

        if not weight_text:
          self.show_message('Digite o peso ou o valor!')
          return

        weight = float(weight_text)

        if weight <= 0:
          self.show_message('Peso deve ser maior que 0!')
          return

        if weight > product_stock:
          self.show_message(f'Estoque insuficiente!\nMaximo: {product_stock:.2f} kg')
          return
        
        total_price = weight * product_price_per_kg
        
        # Verificar se produto já está no carrinho
        for item in self.cart_items:
          if item['id'] == product_id and item['is_weight']:
            new_weight = item['weight_kg'] + weight
            
            if new_weight > product_stock:
              self.show_message(f'Estoque insuficiente!\nMaximo: {product_stock:.2f} kg')
              return
            
            item['weight_kg'] = new_weight
            item['qty'] = new_weight
            item['total'] = new_weight * product_price_per_kg
            
            dialog.dismiss()
            self.update_cart_display()
            self.show_message(f'{weight:.2f} kg adicionado!\nTotal: {item["weight_kg"]:.2f} kg')
            return
        
        # Adicionar novo item por peso
        self.cart_items.append({
          'id': product_id,
          'name': product_name,
          'qty': weight,
          'price': product_price_per_kg,
          'total': total_price,
          'max_stock': product_stock,
          'is_weight': True,
          'weight_kg': weight
        })
        
        dialog.dismiss()
        self.update_cart_display()
        self.show_message(f'{weight:.2f} kg adicionado!\nTotal: {total_price:.2f} MZN')
        
      except ValueError:
        self.show_message('Peso invalido!')
      except Exception as e:
        print(f"Erro: {e}")
        import traceback
        traceback.print_exc()
        self.show_message('Erro ao adicionar!')
    
    add_btn.bind(on_release=add_weighted_product)
    
    dialog.open()
  
  def update_cart_display(self):
    """Atualizar exibição do carrinho"""
    cart_list = self.ids.cart_list
    cart_list.clear_widgets()
    self.total_amount = 0

    if not self.cart_items:
      self.ids.cart_count_label.text = '0 itens'
    else:
      self.ids.cart_count_label.text = f'{len(self.cart_items)} itens'

    for i, item in enumerate(self.cart_items):
      bg_color = [0.95, 0.97, 0.98, 1] if i % 2 == 0 else [1, 1, 1, 1]

      row = MDCard(
        orientation='horizontal',
        size_hint_y=None,
        height=dp(34),
        padding=[dp(4), dp(2), dp(4), dp(2)],
        spacing=dp(4),
        elevation=0,
        radius=[dp(6)],
        md_bg_color=bg_color
      )

      id_label = MDLabel(
        text=str(item['id']),
        halign='center',
        size_hint_x=0.10,
        font_size=dp(11),
        theme_text_color="Primary"
      )

      name = item['name'][:20] + '...' if len(item['name']) > 20 else item['name']
      name_label = MDLabel(
        text=name,
        halign='left',
        size_hint_x=0.40,
        font_size=dp(11),
        theme_text_color="Primary",
        shorten=True,
        shorten_from="right"
      )

      if item.get('is_weight', False):
        qty_widget = MDLabel(
          text=f"{item['weight_kg']:.2f} kg",
          halign='center',
          size_hint_x=0.18,
          font_size=dp(11),
          theme_text_color="Custom",
          text_color=[0.55, 0.35, 0.0, 1],
          bold=True
        )
      else:
        qty_widget = MDTextField(
          text=str(int(item['qty'])),
          input_filter='int',
          mode='rectangle',
          size_hint_x=0.18,
          size_hint_y=None,
          height=dp(28),
          font_size=dp(11),
          halign='center',
          line_color_normal=[0.75, 0.75, 0.75, 1],
          line_color_focus=[0.2, 0.5, 0.8, 1],
          fill_color=[0.96, 0.96, 0.96, 1],
          text_color_normal=[0.15, 0.15, 0.15, 1],
          text_color_focus=[0.15, 0.15, 0.15, 1],
          hint_text_color=[0.5, 0.5, 0.5, 1]
        )
        qty_widget.bind(text=lambda inst, val, idx=i: self.update_qty(idx, val))

      total_label = MDLabel(
        text=f'{item["total"]:.2f}',
        halign='right',
        size_hint_x=0.22,
        font_size=dp(11),
        theme_text_color="Custom",
        text_color=[0.12, 0.65, 0.25, 1],
        bold=True
      )

      remove_btn = MDIconButton(
        icon='delete',
        theme_text_color="Custom",
        text_color=[0.85, 0.2, 0.2, 1],
        size_hint_x=0.10,
        pos_hint={'center_y': 0.5},
        on_release=lambda btn, idx=i: self.remove_from_cart(idx)
      )

      row.add_widget(id_label)
      row.add_widget(name_label)
      row.add_widget(qty_widget)
      row.add_widget(total_label)
      row.add_widget(remove_btn)

      cart_list.add_widget(row)
      self.total_amount += item['total']

    self.ids.total_label.text = f'{self.total_amount:.2f} MZN'
    self.calculate_change()
  
  def increase_qty(self, index):
    """Aumentar quantidade de um item"""
    try:
      if index >= len(self.cart_items):
        return
      
      item = self.cart_items[index]
      
      if item.get('is_weight', False):
        return
      
      if item['qty'] + 1 <= item['max_stock']:
        item['qty'] += 1
        item['total'] = item['qty'] * item['price']
        self.update_cart_display()
      else:
        self.show_message("⚠ Estoque insuficiente!")
        
    except Exception as e:
      print(f"❌ Erro: {e}")
  
  def decrease_qty(self, index):
    """Diminuir quantidade de um item"""
    try:
      if index >= len(self.cart_items):
        return
      
      item = self.cart_items[index]
      
      if item.get('is_weight', False):
        return
      
      if item['qty'] > 1:
        item['qty'] -= 1
        item['total'] = item['qty'] * item['price']
        self.update_cart_display()
      else:
        self.remove_from_cart(index)
        
    except Exception as e:
      print(f"❌ Erro: {e}")
  
  def update_qty(self, index, value):
    """Atualizar quantidade"""
    try:
      if not value or value.strip() == '':
        return
      qty = int(value)
      if qty <= 0:
        return
      if index >= len(self.cart_items):
        return
      
      if self.cart_items[index].get('is_weight', False):
        return
      
      if qty > self.cart_items[index]['max_stock']:
        self.show_message("⚠ Quantidade excede estoque!")
        return
      
      self.cart_items[index]['qty'] = qty
      self.cart_items[index]['total'] = qty * self.cart_items[index]['price']
      Clock.schedule_once(lambda dt: self.update_cart_display(), 0.5)
      
    except ValueError:
      pass
    except Exception as e:
      print(f"❌ Erro: {e}")
  
  def remove_from_cart(self, index):
    """Remover item do carrinho"""
    try:
      if 0 <= index < len(self.cart_items):
        self.cart_items.pop(index)
        self.update_cart_display()
    except Exception as e:
      print(f"❌ Erro: {e}")
  
  def clear_cart(self, *args):
    """Limpar carrinho"""
    self.cart_items.clear()
    self.update_cart_display()

  def open_sales_history(self, *args):
    """Abrir histórico de vendas"""
    if not self.manager:
      return

    self.manager.current = 'sales_history'
    if 'sales_history' in self.manager.screen_names:
      history_screen = self.manager.get_screen('sales_history')
      Clock.schedule_once(lambda dt: history_screen.load_all_sales(), 0.1)
  
  def calculate_change(self, *args):
    """Calcular troco"""
    try:
      paid_text = self.ids.paid_input.text
      paid = float(paid_text) if paid_text else 0
      change = paid - self.total_amount
      
      if change >= 0:
        self.ids.change_label.text = f'{change:.2f} MZN'
        self.ids.change_label.text_color = [0.16, 0.66, 0.16, 1]
      else:
        self.ids.change_label.text = 'INSUFICIENTE'
        self.ids.change_label.text_color = [0.88, 0.22, 0.22, 1]
        
    except ValueError:
      self.ids.change_label.text = '0.00 MZN'
    except Exception as e:
      self.ids.change_label.text = '0.00 MZN'
  
  # ==========================================
  # SCANNER DE CÓDIGO DE BARRAS
  # ==========================================
  
  def toggle_scanner(self, *args):
    """Ligar/desligar scanner"""
    if not self.scanning:
      self.scanning = True
      self.ids.scan_btn.text = 'PARAR'
      self.ids.scan_btn.md_bg_color = [0.88, 0.26, 0.26, 1]
      self.ids.scanner_status.text = 'Iniciando...'
      self.ids.scanner_status.text_color = [0.9, 0.7, 0.1, 1]
      Clock.schedule_once(self.init_camera, 0.1)
    else:
      self.scanning = False
      self.ids.scan_btn.text = 'INICIAR'
      self.ids.scan_btn.md_bg_color = [0.16, 0.66, 0.26, 1]
      self.ids.scanner_status.text = 'Inativo'
      self.ids.scanner_status.text_color = [0.5, 0.5, 0.5, 1]
      Clock.unschedule(self.update_camera)
      self.release_camera()
  
  def release_camera(self):
    """Liberar recursos da câmera"""
    if self.camera_capture is not None:
      try:
        self.camera_capture.release()
      except:
        pass
      self.camera_capture = None
    
    if hasattr(self.ids, 'camera_image'):
      self.ids.camera_image.texture = None
  
  def init_camera(self, dt):
    """Inicializar câmera"""
    try:
      self.release_camera()
      
      self.camera_capture = cv2.VideoCapture(self.current_camera)
      
      if self.camera_capture.isOpened():
        self.camera_capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.camera_capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        
        self.ids.scanner_status.text = f'Ativo (Cam {self.current_camera})'
        self.ids.scanner_status.text_color = [0.16, 0.72, 0.22, 1]
        
        self.last_barcode = None
        self.last_barcode_time = 0
        
        Clock.schedule_interval(self.update_camera, 1.0 / 20.0)
      else:
        self.ids.scanner_status.text = 'Câmera não encontrada'
        self.ids.scanner_status.text_color = [0.9, 0.2, 0.2, 1]
        self.scanning = False
        self.ids.scan_btn.text = 'INICIAR'
        self.ids.scan_btn.md_bg_color = [0.16, 0.66, 0.26, 1]
        
    except Exception as e:
      print(f"❌ Erro ao inicializar câmera: {e}")
      self.ids.scanner_status.text = 'Erro na câmera'
      self.ids.scanner_status.text_color = [0.9, 0.2, 0.2, 1]
      self.scanning = False
  
  def update_camera(self, dt):
    """Atualizar frame da câmera e detectar códigos"""
    if not self.scanning or self.camera_capture is None:
      return
    
    try:
      ret, frame = self.camera_capture.read()
      
      if not ret or frame is None:
        return
      
      frame = cv2.convertScaleAbs(frame, alpha=1.2, beta=10)
      
      import time
      current_time = time.time()
      
      codes = decode(frame)
      
      if codes:
        for code in codes:
          try:
            barcode_raw = code.data.decode('utf-8')
            barcode_value = ''.join(c for c in barcode_raw if c.isprintable()).strip()
            
            if (barcode_value == self.last_barcode and 
                (current_time - self.last_barcode_time) < 2):
              continue
            
            self.last_barcode = barcode_value
            self.last_barcode_time = current_time
            
            self.ids.scanner_status.text = 'Buscando...'
            self.ids.scanner_status.text_color = [0.2, 0.5, 0.8, 1]
            
            product = self.db.get_product_by_barcode(barcode_value)
            
            if product:
              self.add_to_cart(product)
              self.play_scanner_sound(success=True)
              self.ids.scanner_status.text = f'✓ {product[1][:15]}'
              self.ids.scanner_status.text_color = [0.16, 0.72, 0.22, 1]
            else:
              self.play_scanner_sound(success=False)
              self.ids.scanner_status.text = '✗ Não encontrado'
              self.ids.scanner_status.text_color = [0.88, 0.32, 0.22, 1]
            
            pts = code.polygon
            if len(pts) == 4:
              pts = [(p.x, p.y) for p in pts]
              cv2.polylines(frame, [np.array(pts, dtype=np.int32)], 
                           True, (0, 255, 0), 3)
            
            x, y, w, h = code.rect
            cv2.putText(frame, barcode_value, (x, y - 10), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            
          except Exception as e:
            print(f"❌ Erro ao processar código: {e}")
            continue
      else:
        if (current_time - self.last_barcode_time) > 2.5:
          self.ids.scanner_status.text = 'Ativo'
          self.ids.scanner_status.text_color = [0.16, 0.72, 0.22, 1]
      
      buf = cv2.flip(frame, 0).tobytes()
      texture = Texture.create(
        size=(frame.shape[1], frame.shape[0]), 
        colorfmt='bgr'
      )
      texture.blit_buffer(buf, colorfmt='bgr', bufferfmt='ubyte')
      self.ids.camera_image.texture = texture
      
    except Exception as e:
      print(f"❌ Erro no update_camera: {e}")
  
  def switch_camera(self, *args):
    """Trocar para próxima câmera disponível"""
    was_scanning = self.scanning
    
    if self.scanning:
      self.scanning = False
      Clock.unschedule(self.update_camera)
      self.release_camera()
    
    self.current_camera = (self.current_camera + 1) % 4
    
    if was_scanning:
      self.scanning = True
      self.ids.scan_btn.text = 'PARAR'
      self.ids.scan_btn.md_bg_color = [0.88, 0.26, 0.26, 1]
      self.ids.scanner_status.text = f'Trocando para cam {self.current_camera}...'
      self.ids.scanner_status.text_color = [0.9, 0.7, 0.1, 1]
      Clock.schedule_once(self.init_camera, 0.1)
  
  # ==========================================
  # FINALIZAÇÃO E OUTROS
  # ==========================================
  
  def finalize_sale(self, *args):
    """Finalizar venda"""
    if not self.cart_items:
      self.show_message("⚠ Carrinho vazio!")
      return
    
    try:
      paid_text = self.ids.paid_input.text
      paid = float(paid_text) if paid_text else 0
      
      if paid < self.total_amount:
        self.show_message("⚠ Pagamento insuficiente!")
        return
    except ValueError:
      self.show_message("⚠ Valor de pagamento inválido!")
      return
    
    change = paid - self.total_amount
    
    try:
      items_count = len(self.cart_items)
      for item in self.cart_items:
        self.db.add_sale(item['id'], item['qty'], item['price'])
      
      self.show_message("✓ Venda finalizada com sucesso!")
      details = (
        f"Itens: {items_count} | Total: {self.total_amount:.2f} MZN | "
        f"Pago: {paid:.2f} | Troco: {change:.2f}"
      )
      self._log_action("SALE", details)
      Clock.schedule_once(lambda dt: self.reset_sale(), 2)
      
    except Exception as e:
      print(f"❌ Erro ao finalizar venda: {e}")
      self.show_message("❌ Erro ao finalizar venda!")
  
  def reset_sale(self):
    """Resetar venda"""
    self.cart_items.clear()
    self.ids.paid_input.text = ''
    self.update_cart_display()
    self.load_products()
  
  def print_receipt(self, *args):
    """Imprimir recibo"""
    if not self.cart_items:
      self.show_message("⚠ Nada para imprimir!")
      return
    
    receipt_text = "=" * 40 + "\n"
    receipt_text += "   RECIBO DE VENDA\n"
    receipt_text += "=" * 40 + "\n"
    receipt_text += f"Data: {datetime.now().strftime('%d/%m/%Y %H:%M')}\n"
    receipt_text += "-" * 40 + "\n"
    
    for item in self.cart_items:
      receipt_text += f"{item['name']}\n"
      
      if item.get('is_weight', False):
        receipt_text += f" {item['weight_kg']:.2f} kg x {item['price']:.2f} = {item['total']:.2f} MZN\n"
      else:
        receipt_text += f" {int(item['qty'])} un x {item['price']:.2f} = {item['total']:.2f} MZN\n"
    
    receipt_text += "-" * 40 + "\n"
    receipt_text += f"TOTAL: {self.total_amount:.2f} MZN\n"
    
    try:
      paid = float(self.ids.paid_input.text) if self.ids.paid_input.text else 0
      change = paid - self.total_amount
      receipt_text += f"Pago: {paid:.2f} MZN\n"
      receipt_text += f"Troco: {change:.2f} MZN\n"
    except:
      pass
    
    receipt_text += "=" * 40 + "\n"
    receipt_text += "    Obrigado!\n"
    receipt_text += "=" * 40
    
    self.show_receipt_popup(receipt_text)
  
  def show_receipt_popup(self, receipt_text):
    """Mostrar popup do recibo"""
    content = MDBoxLayout(
      orientation='vertical',
      padding=dp(20),
      spacing=dp(15),
      size_hint_y=None,
      height=dp(500)
    )
    
    scroll = ScrollView()
    receipt_label = MDLabel(
      text=receipt_text,
      size_hint_y=None,
      font_size=dp(14),
      halign='left'
    )
    receipt_label.bind(texture_size=receipt_label.setter('size'))
    scroll.add_widget(receipt_label)
    
    btn_layout = MDBoxLayout(
      size_hint_y=None,
      height=dp(50),
      spacing=dp(10)
    )
    
    save_btn = MDRaisedButton(
      text='💾 SALVAR',
      md_bg_color=[0.2, 0.5, 0.8, 1]
    )
    
    close_btn = MDRaisedButton(
      text='✗ FECHAR',
      md_bg_color=[0.5, 0.5, 0.5, 1]
    )
    
    btn_layout.add_widget(save_btn)
    btn_layout.add_widget(close_btn)
    
    content.add_widget(scroll)
    content.add_widget(btn_layout)
    
    dialog = MDDialog(
      title='📄 Recibo de Venda',
      type='custom',
      content_cls=content,
      size_hint=(0.7, 0.8)
    )
    
    close_btn.bind(on_release=lambda x: dialog.dismiss())
    save_btn.bind(on_release=lambda x: self.save_receipt(receipt_text, dialog))
    
    dialog.open()
  
  def save_receipt(self, receipt_text, dialog):
    """Salvar recibo em arquivo"""
    try:
      filename = f"recibo_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
      with open(filename, 'w', encoding='utf-8') as f:
        f.write(receipt_text)
      
      self.show_message(f"✓ Recibo salvo: {filename}")
      self._log_action("SAVE_RECEIPT", f"Recibo salvo: {filename}")
      dialog.dismiss()
      
    except Exception as e:
      print(f"❌ Erro ao salvar recibo: {e}")
      self.show_message("❌ Erro ao salvar recibo!")
  
  def cancel_sale(self, *args):
    """Cancelar venda"""
    if not self.cart_items:
      self.show_message("⚠ Carrinho vazio!")
      return
    
    items_count = len(self.cart_items)
    total = self.total_amount
    
    self.cart_items.clear()
    self.ids.paid_input.text = ''
    self.update_cart_display()
    
    self.show_message("✓ Venda cancelada!")
    self._log_action("CANCEL_SALE", f"Itens: {items_count} | Total: {total:.2f} MZN")
  
  def show_message(self, message):
    """Mostrar mensagem temporária"""
    dialog = MDDialog(
      text=message,
      size_hint=(0.4, None),
      height=dp(150)
    )
    dialog.open()
    Clock.schedule_once(lambda dt: dialog.dismiss(), 2)
  
  def go_back(self, *args):
    """Voltar para tela anterior"""
    if self.scanning:
      self.scanning = False
      Clock.unschedule(self.update_camera)
      self.release_camera()
    
    self._log_action("LOGOUT", "Logout from sales")
    self.manager.current = 'login'
  
  def on_leave(self):
    """Ao sair da tela"""
    if self.scanning:
      self.scanning = False
      Clock.unschedule(self.update_camera)
      self.release_camera()
