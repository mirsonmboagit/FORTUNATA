from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, RoundedRectangle, Line
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget

Window.minimum_width = 1050
Window.minimum_height = 650
Window.clearcolor = (0.025,0.035,0.045,1)

BG=(.025,.035,.045,1); HEADER=(.045,.075,.105,1); CARD=(.045,.075,.105,1)
CARD2=(.055,.09,.125,1); CARD3=(.065,.105,.145,1); TEXT=(.94,.96,.98,1)
MUTED=(.56,.63,.72,1); GREEN=(.02,.72,.43,1); BLUE=(.04,.45,.86,1)
ORANGE=(.93,.52,.04,1); RED=(.48,.12,.16,1); BORDER=(.12,.19,.26,1)

def bg(w,color,r=12,border=None):
    with w.canvas.before:
        Color(*color); w._r=RoundedRectangle(pos=w.pos,size=w.size,radius=[dp(r)])
        if border:
            Color(*border); w._l=Line(rounded_rectangle=(w.x,w.y,w.width,w.height,dp(r)),width=1)
    def u(*_):
        w._r.pos=w.pos; w._r.size=w.size
        if border: w._l.rounded_rectangle=(w.x,w.y,w.width,w.height,dp(r))
    w.bind(pos=u,size=u)

class Card(BoxLayout):
    def __init__(self,color=CARD,radius=12,border=None,**kw):
        super().__init__(**kw); bg(self,color,radius,border)

class Btn(Button):
    def __init__(self,bgcolor=CARD3,**kw):
        super().__init__(**kw); self.background_normal=''; self.background_down=''; self.background_color=(0,0,0,0)
        self.color=TEXT; self.font_size=sp(13); bg(self,bgcolor,9)

class Input(TextInput):
    def __init__(self,hint='',**kw):
        super().__init__(**kw); self.hint_text=hint; self.font_size=sp(13); self.foreground_color=TEXT
        self.hint_text_color=MUTED; self.background_color=(0,0,0,0); self.cursor_color=GREEN
        self.padding=[dp(14),dp(10)]; bg(self,(.055,.075,.10,1),9,BORDER)

class POS(App):
    title='MIRSON MBOA - PDV'
    products=[
        ('AGUA NAMAACHA-1,5L','7894900012345',40),
        ('CUSTARD POWDER MOIRS-250G','6001234567890',140),
        ('REFRIGERANTE COCA-COLA 350ML','5449000000996',50),
        ('LEITE UHT 1L','7891000101010',95),
        ('ARROZ 5KG','7896005200012',420),
        ('AÇÚCAR 1KG','7898901234567',85),
    ]
    def build(self):
        self.cart={}; self.method='Dinheiro'; self.popup=None
        root=BoxLayout(orientation='vertical',padding=[dp(12),dp(10)],spacing=dp(10))
        root.add_widget(self.header())
        main=BoxLayout(spacing=dp(12))
        left=BoxLayout(orientation='vertical',spacing=dp(10))
        left.add_widget(self.searchbar()); self.cartbox=Card(orientation='vertical',color=(.035,.065,.095,1),radius=15); left.add_widget(self.cartbox)
        main.add_widget(left); main.add_widget(self.payment())
        root.add_widget(main); root.add_widget(self.bottom()); self.refresh(); return root

    def header(self):
        h=Card(orientation='horizontal',size_hint_y=None,height=dp(70),padding=[dp(14),dp(8)],spacing=dp(12),color=HEADER,radius=13)
        logo=Card(size_hint_x=None,width=dp(52),color=(.02,.40,.72,1),radius=10); logo.add_widget(Label(text='▥',font_size=sp(25),color=TEXT)); h.add_widget(logo)
        b=BoxLayout(orientation='vertical',size_hint_x=None,width=dp(260)); b.add_widget(Label(text='MIRSON MBOA',bold=True,font_size=sp(18),color=TEXT,halign='left')); b.add_widget(Label(text='PDV - Sistema de Vendas',font_size=sp(11),color=MUTED,halign='left')); h.add_widget(b); h.add_widget(Widget())
        for a,v in [('Atendente','mirson'),('Última alteração','16/09/2026 19:36')]:
            x=BoxLayout(orientation='vertical',size_hint_x=None,width=dp(150)); x.add_widget(Label(text=a,color=MUTED,font_size=sp(10),halign='left')); x.add_widget(Label(text=v,color=TEXT,bold=True,font_size=sp(13),halign='left')); h.add_widget(x)
        h.add_widget(Btn(text='●  Local',bgcolor=(.02,.23,.18,1),size_hint_x=None,width=dp(105)))
        for t,c in [('◔',CARD3),('ⓘ',CARD3),('⟳',CARD3),('⇥',RED)]: h.add_widget(Btn(text=t,bgcolor=c,size_hint_x=None,width=dp(45),font_size=sp(18)))
        return h

    def searchbar(self):
        w=Card(orientation='horizontal',size_hint_y=None,height=dp(70),padding=[dp(10),dp(10)],spacing=dp(8),color=CARD,radius=14)
        self.search=Input('Pesquise um produto pelo nome, código ou código de barras...',multiline=False); self.search.bind(text=self.searching); w.add_widget(self.search)
        s=Btn(text='▥',bgcolor=GREEN,size_hint_x=None,width=dp(55),font_size=sp(22)); s.bind(on_release=self.scan); w.add_widget(s)
        a=Btn(text='+   Adicionar   ▼',size_hint_x=None,width=dp(150)); a.bind(on_release=lambda *_: self.search.focus.__class__); w.add_widget(a)
        return w

    def payment(self):
        p=Card(orientation='vertical',size_hint_x=None,width=dp(385),padding=[dp(14),dp(12)],spacing=dp(9),color=CARD,radius=15)
        p.add_widget(Label(text='▤   Pagamento',color=TEXT,bold=True,font_size=sp(18),size_hint_y=None,height=dp(35),halign='left'))
        total=Card(orientation='vertical',size_hint_y=None,height=dp(104),padding=[dp(14),dp(8)],color=(.015,.28,.22,1),radius=12); total.add_widget(Label(text='Total a pagar',color=TEXT,font_size=sp(13),halign='left')); self.total=Label(text='0.00 MT',color=TEXT,bold=True,font_size=sp(27),halign='left'); total.add_widget(self.total); p.add_widget(total)
        sm=Card(orientation='vertical',size_hint_y=None,height=dp(105),padding=[dp(12),dp(7)],spacing=dp(4),color=CARD2,radius=10)
        r=BoxLayout(); r.add_widget(Label(text='Subtotal',color=TEXT,halign='left')); self.sub=Label(text='0.00 MT',color=TEXT,bold=True,halign='right'); r.add_widget(self.sub); sm.add_widget(r)
        r=BoxLayout(); r.add_widget(Label(text='Desconto',color=TEXT,halign='left')); self.disc=Input('0.00',multiline=False,input_filter='float',size_hint_x=None,width=dp(100)); self.disc.bind(text=lambda *_: self.update()); r.add_widget(self.disc); self.discv=Label(text='0.00 MT',color=GREEN,size_hint_x=None,width=dp(80),halign='right'); r.add_widget(self.discv); sm.add_widget(r); p.add_widget(sm)
        p.add_widget(Label(text='Forma de pagamento                 Alt+1..4',color=TEXT,bold=True,font_size=sp(12),size_hint_y=None,height=dp(28),halign='left'))
        methods=BoxLayout(size_hint_y=None,height=dp(46),spacing=dp(6)); self.mbuttons={}
        for n in ['Dinheiro','Cartão','M-Pesa','E-MOLA']:
            b=Btn(text=n,bgcolor=BLUE if n=='Dinheiro' else CARD3); b.bind(on_release=lambda _,x=n:self.method_set(x)); self.mbuttons[n]=b; methods.add_widget(b)
        p.add_widget(methods)
        rv=Card(orientation='horizontal',size_hint_y=None,height=dp(68),padding=[dp(8),dp(7)],spacing=dp(7),color=CARD2,radius=10)
        q=BoxLayout(orientation='vertical'); q.add_widget(Label(text='Valor recebido',color=TEXT,bold=True,font_size=sp(11),halign='left')); self.received=Input('Valor pago (obrigatório)',multiline=False,input_filter='float'); self.received.bind(text=lambda *_:self.update()); q.add_widget(self.received); rv.add_widget(q)
        z=BoxLayout(orientation='vertical',size_hint_x=None,width=dp(80)); z.add_widget(Label(text='Troco',color=TEXT,bold=True,font_size=sp(11),halign='left')); self.change=Label(text='0.00 MT',color=GREEN,bold=True,halign='right'); z.add_widget(self.change); rv.add_widget(z); p.add_widget(rv)
        n=Card(orientation='vertical',size_hint_y=None,height=dp(86),padding=[dp(8),dp(6)],spacing=dp(4),color=CARD2,radius=10); n.add_widget(Label(text='Notas rápidas (MT)',color=TEXT,bold=True,font_size=sp(11),halign='left')); nb=BoxLayout(spacing=dp(6));
        for v in [50,100,200,500,1000]:
            b=Btn(text=str(v),bgcolor=BLUE); b.bind(on_release=lambda _,x=v:self.received_set(x)); nb.add_widget(b)
        n.add_widget(nb); p.add_widget(n); return p

    def bottom(self):
        b=Card(orientation='horizontal',size_hint_y=None,height=dp(76),padding=[dp(10),dp(9)],spacing=dp(9),color=HEADER,radius=14)
        for t,v in [('▮ Vendas de Hoje','0'),('▤ Total Vendido','0.00 MT'),('◇ Produto mais vendido','Sem dados')]:
            c=Card(orientation='vertical',size_hint_x=None,width=dp(190),padding=[dp(10),dp(4)],color=CARD2,radius=9); c.add_widget(Label(text=t,color=MUTED,font_size=sp(10),halign='left')); c.add_widget(Label(text=v,color=TEXT,bold=True,font_size=sp(13),halign='left')); b.add_widget(c)
        b.add_widget(Widget())
        for t,c,w in [('▣  Caixa',ORANGE,125),('▤  Recibo',CARD3,125),('×  Cancelar',CARD3,125),('Ⅱ  Suspender',CARD3,125),('✓  Finalizar venda',GREEN,175)]:
            x=Btn(text=t,bgcolor=c,size_hint_x=None,width=dp(w));
            if 'Finalizar' in t:x.bind(on_release=self.finish)
            if 'Cancelar' in t:x.bind(on_release=self.cancel)
            b.add_widget(x)
        return b

    def refresh(self):
        self.cartbox.clear_widgets(); hd=BoxLayout(size_hint_y=None,height=dp(58),padding=[dp(20),0]); hd.add_widget(Label(text='🛒  Carrinho de compras',color=TEXT,bold=True,font_size=sp(17),halign='left')); hd.add_widget(Label(text=f'{sum(self.cart.values())} itens',color=MUTED,halign='right')); self.cartbox.add_widget(hd)
        if not self.cart:
            e=BoxLayout(orientation='vertical',padding=[dp(20),dp(15)],spacing=dp(7)); e.add_widget(Widget()); e.add_widget(Label(text='🛒',color=(.55,.68,.82,1),font_size=sp(55),size_hint_y=None,height=dp(70))); e.add_widget(Label(text='O carrinho está vazio',color=TEXT,bold=True,font_size=sp(21),size_hint_y=None,height=dp(35))); e.add_widget(Label(text='Escaneie, pesquise ou adicione produtos para começar.',color=MUTED,font_size=sp(13),size_hint_y=None,height=dp(30)))
            acts=BoxLayout(size_hint_y=None,height=dp(80),padding=[dp(40),0],spacing=dp(25))
            for ic,t,s,cb in [('▥','Escaneie','o código de barras',self.scan),('⌕','Pesquise','pelo nome ou código',lambda *_:setattr(self.search,'focus',True)),('+','Adicione','manualmente',lambda *_:setattr(self.search,'focus',True))]:
                x=BoxLayout(spacing=dp(8)); q=Btn(text=ic,bgcolor=CARD3,size_hint_x=None,width=dp(48),font_size=sp(19)); q.bind(on_release=cb); x.add_widget(q); z=BoxLayout(orientation='vertical'); z.add_widget(Label(text=t,color=TEXT,font_size=sp(11),halign='left')); z.add_widget(Label(text=s,color=MUTED,font_size=sp(10),halign='left')); x.add_widget(z); acts.add_widget(x)
            e.add_widget(acts); e.add_widget(Widget()); self.cartbox.add_widget(e)
        else:
            sc=ScrollView(); con=BoxLayout(orientation='vertical',padding=dp(12),spacing=dp(7),size_hint_y=None); con.bind(minimum_height=con.setter('height'))
            for code,q in self.cart.items():
                p=next(x for x in self.products if x[1]==code); row=Card(orientation='horizontal',size_hint_y=None,height=dp(62),padding=[dp(10),dp(7)],spacing=dp(7),color=(.055,.08,.11,1),radius=8); inf=BoxLayout(orientation='vertical'); inf.add_widget(Label(text=p[0],color=TEXT,bold=True,font_size=sp(12),halign='left')); inf.add_widget(Label(text=f'{p[2]:.2f} MT / unidade',color=MUTED,font_size=sp(10),halign='left')); row.add_widget(inf)
                minus=Btn(text='−',size_hint_x=None,width=dp(35)); num=Label(text=str(q),color=TEXT,bold=True,size_hint_x=None,width=dp(35)); plus=Btn(text='+',bgcolor=BLUE,size_hint_x=None,width=dp(35)); minus.bind(on_release=lambda _,c=code:self.qty(c,-1)); plus.bind(on_release=lambda _,c=code:self.qty(c,1)); row.add_widget(minus); row.add_widget(num); row.add_widget(plus); row.add_widget(Label(text=f'{p[2]*q:.2f} MT',color=GREEN,bold=True,size_hint_x=None,width=dp(100),halign='right')); rm=Btn(text='×',bgcolor=RED,size_hint_x=None,width=dp(35)); rm.bind(on_release=lambda _,c=code:self.remove(c)); row.add_widget(rm); con.add_widget(row)
            con.add_widget(Widget()); sc.add_widget(con); self.cartbox.add_widget(sc)
        self.update()

    def searching(self,_,text):
        if self.popup:self.popup.dismiss();self.popup=None
        text=text.strip().lower()
        if not text:return
        found=[p for p in self.products if text in p[0].lower() or text in p[1]][:5]
        if not found:return
        box=BoxLayout(orientation='vertical',padding=dp(7),spacing=dp(3)); box.add_widget(Label(text='Sugestões de produtos',color=MUTED,size_hint_y=None,height=dp(25),halign='left'))
        for p in found:
            x=Btn(text=f'{p[0]}    {p[2]:.2f} MT',bgcolor=(.055,.08,.11,1),size_hint_y=None,height=dp(47),halign='left'); x.bind(on_release=lambda _,p=p:self.add(p)); box.add_widget(x)
        self.popup=Popup(title='',content=box,size_hint=(None,None),size=(dp(510),dp(70+50*len(found))),separator_height=0,auto_dismiss=True); Clock.schedule_once(lambda *_:self.popup.open(),0)

    def add(self,p):
        if self.popup:self.popup.dismiss();self.popup=None
        self.search.text=''; self.cart[p[1]]=self.cart.get(p[1],0)+1; self.refresh()
    def scan(self,*_): self.add(self.products[0])
    def qty(self,c,d): self.cart[c]=self.cart.get(c,0)+d; self.cart.pop(c,None) if self.cart.get(c,0)<=0 else None; self.refresh()
    def remove(self,c): self.cart.pop(c,None); self.refresh()
    def update(self):
        sub=sum(next(x for x in self.products if x[1]==c)[2]*q for c,q in self.cart.items())
        try: disc=float(self.disc.text or 0)
        except: disc=0
        total=max(0,sub-disc); self.sub.text=f'{sub:.2f} MT'; self.discv.text=f'{disc:.2f} MT'; self.total.text=f'{total:.2f} MT'
        try: rec=float(self.received.text or 0)
        except: rec=0
        self.change.text=f'{max(0,rec-total):.2f} MT'
    def method_set(self,n):
        self.method=n
        for k,v in self.mbuttons.items():
            v.canvas.before.clear(); bg(v,BLUE if k==n else CARD3,9)
        self.update()
    def received_set(self,v): self.received.text=str(v); self.update()
    def finish(self,*_): self.msg('Finalizar venda','A venda foi finalizada.'); self.cart.clear(); self.received.text=''; self.disc.text=''; self.refresh()
    def cancel(self,*_): self.cart.clear(); self.received.text=''; self.disc.text=''; self.refresh()
    def msg(self,title,text):
        b=BoxLayout(orientation='vertical',padding=dp(15),spacing=dp(10)); b.add_widget(Label(text=text,color=TEXT)); x=Btn(text='OK',bgcolor=BLUE,size_hint_y=None,height=dp(40)); b.add_widget(x); p=Popup(title=title,content=b,size_hint=(None,None),size=(dp(350),dp(180))); x.bind(on_release=p.dismiss); p.open()

if __name__=='__main__': POS().run()
