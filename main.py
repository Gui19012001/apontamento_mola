# -*- coding: utf-8 -*-
from __future__ import annotations

import json, os, re, sqlite3, threading, time
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

import requests
from requests.auth import HTTPBasicAuth

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, Line, RoundedRectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.utils import platform


# ========================= TEMA IBERO =========================
NAVY=(0.01,0.05,0.11,1); NAVY2=(0.02,0.12,0.23,1); NAVY3=(0.03,0.21,0.39,1)
BLUE=(0.00,0.40,0.75,1); BLUE_SOFT=(0.915,0.958,0.992,1)
BG=(0.94,0.965,0.985,1); CARD=(1,1,1,1); TEXT=(0.055,0.09,0.14,1)
MUTED=(0.39,0.45,0.53,1); BORDER=(0.77,0.835,0.90,1)
GREEN=(0.04,0.58,0.28,1); RED=(0.83,0.11,0.15,1); AMBER=(0.94,0.57,0.06,1)
WHITE=(1,1,1,1); APP_DIR=Path(__file__).resolve().parent


# ========================= CONFIG =========================
def load_env(path: Path)->Dict[str,str]:
    out={}
    if not path.exists(): return out
    try: raw=path.read_text(encoding="utf-8")
    except Exception: return out
    for line in raw.splitlines():
        line=line.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        k,v=line.split("=",1); out[k.strip()]=v.strip().strip('"').strip("'")
    return out

ENV=load_env(APP_DIR/"teste.env")
def env(name, default=""): return os.getenv(name, ENV.get(name,default)).strip()

TOTVS_API_BASE=env("TOTVS_API_BASE","http://192.168.2.15:8195/rest/apontmod2").rstrip("/")
TOTVS_USERNAME=env("TOTVS_USERNAME")
TOTVS_PASSWORD=env("TOTVS_PASSWORD")
TOTVS_TENANT_ID=env("TOTVS_TENANT_ID")
TOTVS_TIMEOUT=int(env("TOTVS_TIMEOUT","100") or "100")


# ========================= HELPERS =========================
def s(v): return "" if v is None else str(v).strip()
def now_text(): return datetime.now().strftime("%d/%m/%Y %H:%M:%S")
def normalizar_op(v): return re.sub(r"\s+","",s(v)).upper()

def parse_operacao(v):
    if not s(v): raise ValueError("Informe a operação.")
    n=int(float(s(v)))
    if n<=0: raise ValueError("A operação deve ser maior que zero.")
    return n

def parse_quantidade(v):
    txt=s(v).replace(",",".")
    if not txt: raise ValueError("Informe a quantidade.")
    q=float(txt)
    if q<=0: raise ValueError("A quantidade deve ser maior que zero.")
    return int(q) if q.is_integer() else q

def api_headers():
    h={"Accept":"application/json","Content-Type":"application/json"}
    if TOTVS_TENANT_ID: h["tenantId"]=TOTVS_TENANT_ID
    return h

def response_body(resp):
    try: return resp.json()
    except Exception: return (resp.text or "").strip()

def response_message(body):
    if isinstance(body,dict):
        for k in ("note","message","mensagem","error","erro","detail","details"):
            if body.get(k): return s(body.get(k))
        return json.dumps(body,ensure_ascii=False,default=str)
    if isinstance(body,list): return json.dumps(body,ensure_ascii=False,default=str)
    return s(body)

def interpretar_post(resp):
    body=response_body(resp); msg=response_message(body); upper=msg.upper()
    business_error=isinstance(body,dict) and bool(body.get("error") or body.get("errorId") or body.get("erro"))
    for x in ("OPERACAO NAO CADASTRADA","OPERAÇÃO NÃO CADASTRADA","OP NAO EXISTE","OP NÃO EXISTE",
              "NAO EXISTE QUANTIDADE SUFICIENTE","NÃO EXISTE QUANTIDADE SUFICIENTE","SEM SALDO","FALHA AO APONTAR"):
        if x in upper: business_error=True
    return (200<=resp.status_code<300 and not business_error), (msg or f"HTTP {resp.status_code}"), body


# ========================= TECLADO ANDROID =========================
def force_android_keyboard():
    """
    Abre o teclado sem ficar alternando abre/fecha.
    O fallback SHOW_FORCED só roda quando SHOW_IMPLICIT falha.
    """
    if platform!="android": return
    try:
        from jnius import autoclass
        PythonActivity=autoclass("org.kivy.android.PythonActivity")
        Context=autoclass("android.content.Context")
        IMM=autoclass("android.view.inputmethod.InputMethodManager")
        activity=PythonActivity.mActivity
        imm=activity.getSystemService(Context.INPUT_METHOD_SERVICE)
        view=activity.getWindow().getDecorView()
        try: shown=bool(imm.showSoftInput(view, IMM.SHOW_IMPLICIT))
        except Exception: shown=False
        if not shown:
            try: imm.toggleSoftInput(IMM.SHOW_FORCED,0)
            except Exception: pass
    except Exception:
        pass


# ========================= TOTVS =========================
def apontar_totvs(op,operacao,quantidade):
    if not TOTVS_USERNAME or not TOTVS_PASSWORD:
        return {"status":"ERRO","http_status":None,"mensagem":"Credenciais TOTVS não configuradas.",
                "payload":{},"body":None}
    payload={"op":normalizar_op(op),"operac":int(operacao),"quant":quantidade,"lote":""}
    url=f"{TOTVS_API_BASE}/new"
    try:
        resp=requests.post(url,json=payload,headers=api_headers(),
                           auth=HTTPBasicAuth(TOTVS_USERNAME,TOTVS_PASSWORD),
                           timeout=TOTVS_TIMEOUT)
        ok,msg,body=interpretar_post(resp)
        return {"status":"APONTADO" if ok else "ERRO","http_status":resp.status_code,
                "mensagem":msg,"payload":payload,"body":body,"url":url}
    except requests.exceptions.Timeout:
        return {"status":"VERIFICAR","http_status":None,
                "mensagem":"A API não respondeu dentro do tempo limite. O POST pode ter chegado ao TOTVS. Confira antes de reapontar.",
                "payload":payload,"body":None,"url":url}
    except requests.exceptions.ConnectionError as exc:
        return {"status":"ERRO","http_status":None,"mensagem":"Falha de conexão com a API TOTVS: "+s(exc),
                "payload":payload,"body":None,"url":url}
    except Exception as exc:
        return {"status":"ERRO","http_status":None,"mensagem":s(exc),
                "payload":payload,"body":None,"url":url}


# ========================= HISTÓRICO =========================
class HistoricoDB:
    """
    A assinatura de uma tentativa é OP + operação + quantidade.

    - ERRO/VERIFICAR aparece no histórico.
    - Novo ERRO da mesma assinatura atualiza a linha existente.
    - Quando a mesma assinatura finalmente der APONTADO, a linha muda
      para APONTADO; portanto o erro desaparece.
    - APONTADO novo, sem erro pendente, cria uma nova linha.
    """
    def __init__(self,path):
        self.path=path
        self.init()

    def con(self):
        c=sqlite3.connect(self.path,timeout=10)
        c.row_factory=sqlite3.Row
        return c

    def init(self):
        with self.con() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS historico(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                data_hora TEXT NOT NULL, op TEXT NOT NULL, roteiro TEXT,
                operacao INTEGER NOT NULL, quantidade REAL NOT NULL,
                status TEXT NOT NULL, http_status INTEGER, mensagem TEXT,
                payload_json TEXT, resposta_json TEXT, tentativa_de INTEGER,
                tentativas INTEGER NOT NULL DEFAULT 1,
                atualizado_em TEXT, atualizado_ts REAL)""")
            cols={r[1] for r in c.execute("PRAGMA table_info(historico)").fetchall()}
            if "tentativas" not in cols:
                c.execute("ALTER TABLE historico ADD COLUMN tentativas INTEGER NOT NULL DEFAULT 1")
            if "atualizado_em" not in cols:
                c.execute("ALTER TABLE historico ADD COLUMN atualizado_em TEXT")
            if "atualizado_ts" not in cols:
                c.execute("ALTER TABLE historico ADD COLUMN atualizado_ts REAL")
            c.commit()

    def _pending(self,c,op,oper,qtd):
        return c.execute("""SELECT * FROM historico
            WHERE op=? AND operacao=? AND ABS(quantidade-?)<0.000001
              AND UPPER(status) IN ('ERRO','VERIFICAR')
            ORDER BY id DESC LIMIT 1""",(normalizar_op(op),int(oper),float(qtd))).fetchone()

    def salvar(self,op,oper,qtd,result,retry_id:Optional[int]=None):
        op=normalizar_op(op); oper=int(oper); qtd=float(qtd)
        status=s(result.get("status","ERRO")).upper()
        now=now_text(); ts=time.time()
        pj=json.dumps(result.get("payload"),ensure_ascii=False,default=str)
        rj=json.dumps(result.get("body"),ensure_ascii=False,default=str)

        with self.con() as c:
            alvo=None
            if retry_id:
                alvo=c.execute("""SELECT * FROM historico
                    WHERE id=? AND op=? AND operacao=? AND ABS(quantidade-?)<0.000001
                    LIMIT 1""",(int(retry_id),op,oper,qtd)).fetchone()
                if alvo is not None and s(alvo["status"]).upper()=="APONTADO":
                    alvo=None
            if alvo is None:
                alvo=self._pending(c,op,oper,qtd)

            if alvo is not None:
                tent=int(alvo["tentativas"] or 1)+1
                c.execute("""UPDATE historico SET
                    data_hora=?, status=?, http_status=?, mensagem=?,
                    payload_json=?, resposta_json=?, tentativas=?,
                    atualizado_em=?, atualizado_ts=? WHERE id=?""",
                    (now,status,result.get("http_status"),result.get("mensagem",""),
                     pj,rj,tent,now,ts,int(alvo["id"])))
                c.commit()
                return int(alvo["id"])

            cur=c.execute("""INSERT INTO historico(
                data_hora,op,roteiro,operacao,quantidade,status,http_status,mensagem,
                payload_json,resposta_json,tentativa_de,tentativas,atualizado_em,atualizado_ts)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (now,op,"",oper,qtd,status,result.get("http_status"),result.get("mensagem",""),
                 pj,rj,retry_id,1,now,ts))
            c.commit()
            return int(cur.lastrowid)

    def listar(self,limit=40):
        with self.con() as c:
            rows=c.execute("""SELECT * FROM historico
                ORDER BY COALESCE(atualizado_ts,CAST(id AS REAL)) DESC LIMIT ?""",
                (int(limit),)).fetchall()
            return [dict(r) for r in rows]


# ========================= UI BASICS =========================
class Surface(BoxLayout):
    def __init__(self,bg=BG,**kwargs):
        super().__init__(**kwargs)
        with self.canvas.before:
            Color(*bg); self._rect=RoundedRectangle(pos=self.pos,size=self.size,radius=[0])
        self.bind(pos=self._sync,size=self._sync)
    def _sync(self,*_): self._rect.pos=self.pos; self._rect.size=self.size

class Card(BoxLayout):
    def __init__(self,bg=CARD,radius=14,border=BORDER,**kwargs):
        super().__init__(**kwargs); self._radius=radius
        with self.canvas.before:
            Color(*bg); self._bg=RoundedRectangle(pos=self.pos,size=self.size,radius=[dp(radius)])
            Color(*border); self._line=Line(rounded_rectangle=(self.x,self.y,self.width,self.height,dp(radius)),width=1)
        self.bind(pos=self._sync,size=self._sync)
    def _sync(self,*_):
        self._bg.pos=self.pos; self._bg.size=self.size
        self._line.rounded_rectangle=(self.x,self.y,self.width,self.height,dp(self._radius))

class IberoInput(TextInput):
    def __init__(self,**kwargs):
        super().__init__(**kwargs)
        self.background_normal=""; self.background_active=""; self.background_color=WHITE
        with self.canvas.after:
            self._lc=Color(*BORDER)
            self._ol=Line(rounded_rectangle=(self.x,self.y,self.width,self.height,dp(8)),width=1.1)
        self.bind(pos=self._sync,size=self._sync,focus=self._focus)
    def _sync(self,*_): self._ol.rounded_rectangle=(self.x,self.y,self.width,self.height,dp(8))
    def _focus(self,_i,f): self._lc.rgba=BLUE if f else BORDER
    def on_touch_down(self,touch):
        out=super().on_touch_down(touch)
        if self.collide_point(*touch.pos):
            Clock.schedule_once(lambda *_: force_android_keyboard(),0.22)
        return out

def label(text="",color=TEXT,size=14,bold=False,halign="left",height=dp(28)):
    x=Label(text=text,color=color,font_size=size,bold=bold,halign=halign,valign="middle",
            size_hint_y=None,height=height)
    x.bind(width=lambda w,*_: setattr(w,"text_size",(w.width,None)))
    return x

def button(text,bg=NAVY2,height=dp(46),font_size=13,width=None):
    kw=dict(text=text,size_hint_y=None,height=height,background_normal="",background_down="",
            background_color=bg,color=WHITE,bold=True,font_size=font_size)
    if width is not None: kw.update(size_hint_x=None,width=width)
    return Button(**kw)

def inputbox(hint,input_filter=None,input_type="text"):
    return IberoInput(hint_text=hint,multiline=False,size_hint_y=None,height=dp(44),font_size=18,
                      foreground_color=TEXT,hint_text_color=(0.48,0.56,0.64,1),cursor_color=BLUE,
                      padding=[dp(13),dp(9),dp(13),dp(8)],input_filter=input_filter,
                      input_type=input_type,write_tab=False)

def field(title,w):
    b=BoxLayout(orientation="vertical",size_hint_y=None,height=dp(63),spacing=dp(2))
    b.add_widget(label(title,NAVY3,11,True,"left",dp(17))); b.add_widget(w); return b

def status_color(st):
    st=s(st).upper()
    return GREEN if st=="APONTADO" else AMBER if st=="VERIFICAR" else RED


# ========================= APP =========================
class ApontamentoRoteiroApp(App):
    title="IBERO • Apontamento por Operação TESTE"

    def build(self):
        Window.clearcolor=NAVY
        try: Window.softinput_mode="below_target"
        except Exception: pass

        Path(self.user_data_dir).mkdir(parents=True,exist_ok=True)
        self.db=HistoricoDB(str(Path(self.user_data_dir)/"historico_roteiro.db"))
        self.retry_id=None; self._focusing=False

        root=BoxLayout(orientation="vertical",padding=0,spacing=0)

        # Cabeçalho compacto
        head=Surface(orientation="horizontal",size_hint_y=None,height=dp(58),
                     padding=[dp(18),dp(4),dp(18),dp(4)],spacing=dp(8),bg=NAVY)
        brand=BoxLayout(orientation="vertical",spacing=0)
        brand.add_widget(label("IBERO",WHITE,26,True,"left",dp(30)))
        brand.add_widget(label("MANUFATURA  •  APONTAMENTO POR OPERAÇÃO",(0.69,0.82,0.94,1),10,True,"left",dp(17)))
        head.add_widget(brand)
        badge=Card(orientation="vertical",size_hint=(None,None),size=(dp(92),dp(33)),
                   padding=[dp(6),dp(1)],bg=NAVY3,radius=9,border=BLUE)
        badge.add_widget(label("TESTE",WHITE,11,True,"center",dp(26))); head.add_widget(badge)
        root.add_widget(head); root.add_widget(Surface(size_hint_y=None,height=dp(4),bg=BLUE))

        content=Surface(orientation="horizontal",padding=dp(9),spacing=dp(9),bg=BG)

        # Formulário: alturas fixas para caber no landscape sem sobreposição
        left=Card(orientation="vertical",padding=[dp(13),dp(8),dp(13),dp(8)],
                  spacing=dp(3),size_hint_x=.42,bg=CARD,radius=14)
        left.add_widget(label("NOVO APONTAMENTO",NAVY,18,True,"left",dp(25)))
        left.add_widget(label("Bipe a OP e informe operação e quantidade.",MUTED,10,False,"left",dp(16)))

        flow=Card(orientation="horizontal",size_hint_y=None,height=dp(29),
                  padding=[dp(6),0],spacing=dp(2),bg=BLUE_SOFT,radius=8,border=(.80,.88,.96,1))
        for txt in ("1 OP","›","2 OPERAÇÃO","›","3 QUANTIDADE"):
            flow.add_widget(label(txt,BLUE if txt=="›" else NAVY2,13 if txt=="›" else 9,True,"center",dp(23)))
        left.add_widget(flow)

        self.op=inputbox("Bipe ou digite a OP")
        self.oper=inputbox("Ex.: 10","int","number")
        self.qtd=inputbox("Ex.: 54",None,"number")
        left.add_widget(field("OP",self.op)); left.add_widget(field("OPERAÇÃO",self.oper)); left.add_widget(field("QUANTIDADE",self.qtd))

        self.send=button("APONTAR AGORA",NAVY2,dp(48),15); self.send.bind(on_release=self.on_apontar); left.add_widget(self.send)

        foot=BoxLayout(orientation="horizontal",size_hint_y=None,height=dp(39),spacing=dp(5))
        self.status_card=Card(orientation="vertical",padding=[dp(8),0],bg=BLUE_SOFT,radius=9,border=(.80,.88,.96,1))
        self.status=label("PRONTO PARA APONTAR",NAVY3,10,True,"center",dp(32)); self.status_card.add_widget(self.status)
        foot.add_widget(self.status_card)
        kb=button("⌨",NAVY3,dp(39),17,dp(48)); kb.bind(on_release=lambda *_: self.reopen_keyboard()); foot.add_widget(kb)
        left.add_widget(foot); content.add_widget(left)

        # Histórico
        right=Card(orientation="vertical",padding=[dp(12),dp(8),dp(12),dp(8)],
                   spacing=dp(5),size_hint_x=.58,bg=CARD,radius=14)
        hh=BoxLayout(orientation="horizontal",size_hint_y=None,height=dp(37),spacing=dp(6))
        titles=BoxLayout(orientation="vertical",spacing=0)
        titles.add_widget(label("HISTÓRICO DE APONTAMENTOS",NAVY,17,True,"left",dp(23)))
        titles.add_widget(label("Erro não duplica; ao apontar, a mesma linha vira APONTADO.",MUTED,9,False,"left",dp(13)))
        hh.add_widget(titles)
        ref=button("ATUALIZAR",NAVY3,dp(32),9,dp(94)); ref.bind(on_release=lambda *_: self.refresh_history()); hh.add_widget(ref)
        right.add_widget(hh)

        self.scroll=ScrollView(do_scroll_x=False,bar_width=dp(5))
        self.hist=BoxLayout(orientation="vertical",spacing=dp(5),size_hint_y=None,padding=[0,dp(2),dp(2),dp(5)])
        self.hist.bind(minimum_height=self.hist.setter("height")); self.scroll.add_widget(self.hist); right.add_widget(self.scroll)
        content.add_widget(right); root.add_widget(content)

        # Scanner/Enter -> próximo campo
        self.op.bind(on_text_validate=lambda *_: self.focus_field(self.oper,True))
        self.oper.bind(on_text_validate=lambda *_: self.focus_field(self.qtd,True))
        self.qtd.bind(on_text_validate=self.on_apontar)
        for w in (self.op,self.oper,self.qtd): w.bind(focus=self._focus_changed)

        Clock.schedule_once(lambda *_: self.focus_field(self.op,False),.45)
        Clock.schedule_once(lambda *_: self.refresh_history(),.20)
        return root

    # --------------------- teclado ---------------------
    def _focus_changed(self,_w,focused):
        if focused and not self._focusing:
            Clock.schedule_once(lambda *_: force_android_keyboard(),.22)

    def focus_field(self,w,show_keyboard=False):
        self._focusing=True
        for x in (self.op,self.oper,self.qtd):
            if x is not w: x.focus=False
        def go(_dt):
            w.focus=True
            try: w.cursor=(len(w.text),0)
            except Exception: pass
            try: w._ensure_keyboard()
            except Exception: pass
            self._focusing=False
            if show_keyboard: Clock.schedule_once(lambda *_: force_android_keyboard(),.18)
        Clock.schedule_once(go,.10)

    def reopen_keyboard(self):
        active=next((w for w in (self.op,self.oper,self.qtd) if w.focus),None)
        if active is None:
            active=self.qtd if s(self.op.text) and s(self.oper.text) else self.oper if s(self.op.text) else self.op
        self.focus_field(active,True)

    # --------------------- apontamento ---------------------
    def on_apontar(self,*_):
        if self.send.disabled: return
        try:
            op=normalizar_op(self.op.text)
            if not op: raise ValueError("Informe a OP.")
            oper=parse_operacao(self.oper.text); qtd=parse_quantidade(self.qtd.text)
        except Exception as exc:
            self.popup("VALIDAÇÃO",s(exc),RED); return

        self.set_busy(True,"ENVIANDO AO TOTVS...")
        threading.Thread(target=self.worker,args=(op,oper,qtd,self.retry_id),daemon=True).start()

    def worker(self,op,oper,qtd,retry_id):
        result=apontar_totvs(op,oper,qtd)
        try:
            result["historico_id"]=self.db.salvar(op,oper,qtd,result,retry_id)
        except Exception as exc:
            result=dict(result)
            result["mensagem"]=result.get("mensagem","")+f"\nFalha ao atualizar histórico local: {exc}"
        Clock.schedule_once(lambda _dt,res=result:self.finish(res),0)

    def finish(self,result):
        self.set_busy(False)
        st=s(result.get("status","ERRO")).upper(); msg=result.get("mensagem",""); http=result.get("http_status")
        color=status_color(st)

        if st=="APONTADO":
            self.status.text="✓  APONTAMENTO REALIZADO"; self.retry_id=None
        elif st=="VERIFICAR":
            self.status.text="!  VERIFICAR NO TOTVS"; self.retry_id=result.get("historico_id")
        else:
            self.status.text="✕  APONTAMENTO NÃO REALIZADO"; self.retry_id=result.get("historico_id")
        self.status.color=color

        self.refresh_history()
        self.popup(st,f"{msg}\n\nHTTP: {http if http is not None else '-'}",color)

        if st=="APONTADO":
            self.op.text=""; self.oper.text=""; self.qtd.text=""
            Clock.schedule_once(lambda *_: self.focus_field(self.op,False),.22)

    def set_busy(self,busy,text=None):
        self.send.disabled=bool(busy); self.send.text="ENVIANDO..." if busy else "APONTAR AGORA"
        if text: self.status.text=text; self.status.color=BLUE

    # --------------------- histórico ---------------------
    def refresh_history(self):
        self.hist.clear_widgets(); rows=self.db.listar(40)
        if not rows:
            c=Card(orientation="vertical",padding=dp(12),size_hint_y=None,height=dp(72),
                   bg=(.97,.985,.997,1),radius=9,border=(.83,.90,.95,1))
            c.add_widget(label("Nenhuma tentativa registrada neste tablet.",MUTED,11,False,"center",dp(45)))
            self.hist.add_widget(c); return
        for r in rows: self.hist.add_widget(self.history_item(r))

    def history_item(self,r):
        st=s(r.get("status")).upper(); color=status_color(st); tries=int(r.get("tentativas") or 1)
        item=Card(orientation="horizontal",padding=[0,dp(5),dp(7),dp(5)],spacing=dp(7),
                  size_hint_y=None,height=dp(69),bg=(.977,.988,.998,1),radius=9,border=(.83,.90,.95,1))
        item.add_widget(Surface(size_hint_x=None,width=dp(5),bg=color))

        info=BoxLayout(orientation="vertical",spacing=0)
        info.add_widget(label(f"{r.get('op','')}  •  OP {r.get('operacao','')}",NAVY,13,True,"left",dp(22)))
        qtd=r.get("quantidade",""); qtd_txt=f"{qtd:g}" if isinstance(qtd,(int,float)) else s(qtd)
        ttxt="" if tries<=1 else f"  •  {tries} tentativas"
        info.add_widget(label(f"Qtd. {qtd_txt}{ttxt}",MUTED,9,False,"left",dp(18)))
        info.add_widget(label(s(r.get("atualizado_em") or r.get("data_hora")),MUTED,8,False,"left",dp(16)))
        item.add_widget(info)

        act=BoxLayout(orientation="horizontal",spacing=dp(4),size_hint_x=None,width=dp(184),padding=[0,dp(9),0,dp(8)])
        b1=button(st,color,dp(31),9,dp(90)); b1.bind(on_release=lambda *_x,row=r:self.show_details(row)); act.add_widget(b1)
        if st in ("ERRO","VERIFICAR"):
            b2=button("REAPONTAR",NAVY3,dp(31),9,dp(90)); b2.bind(on_release=lambda *_x,row=r:self.retry(row))
        else:
            b2=button("DETALHES",NAVY3,dp(31),9,dp(90)); b2.bind(on_release=lambda *_x,row=r:self.show_details(row))
        act.add_widget(b2); item.add_widget(act)
        return item

    def retry(self,r):
        self.op.text=s(r.get("op")); self.oper.text=s(r.get("operacao"))
        q=r.get("quantidade")
        if isinstance(q,float) and q.is_integer(): q=int(q)
        self.qtd.text=s(q); self.retry_id=r.get("id")
        self.status.text=f"REAPONTAMENTO #{r.get('id')}"; self.status.color=NAVY3
        self.focus_field(self.qtd,True)

    def show_details(self,r):
        txt=(f"ID: {r.get('id')}\nData da última tentativa: {r.get('atualizado_em') or r.get('data_hora')}\n"
             f"OP: {r.get('op')}\nOperação: {r.get('operacao')}\nQuantidade: {r.get('quantidade')}\n"
             f"Status atual: {r.get('status')}\nTentativas: {r.get('tentativas') or 1}\n"
             f"HTTP: {r.get('http_status') or '-'}\n\nMensagem:\n{s(r.get('mensagem')) or '-'}\n\n"
             f"Payload:\n{s(r.get('payload_json')) or '-'}\n\nResposta:\n{s(r.get('resposta_json')) or '-'}")
        self.popup("DETALHES DO APONTAMENTO",txt,NAVY3,large=True)

    # --------------------- popup ---------------------
    def popup(self,title,message,color=NAVY2,large=False):
        modal=ModalView(size_hint=(.82,.78 if large else .55),auto_dismiss=False,background_color=(0,0,0,.52))
        card=Card(orientation="vertical",padding=dp(16),spacing=dp(7),bg=CARD,radius=14,border=(.74,.82,.90,1))
        card.add_widget(label(title,color,20,True,"center",dp(38)))

        if large:
            sv=ScrollView(do_scroll_x=False)
            body=Label(text=message,color=TEXT,font_size=12,halign="left",valign="top",size_hint_y=None,markup=False)
            body.bind(width=lambda w,*_:setattr(w,"text_size",(w.width,None)))
            body.bind(texture_size=lambda w,v:setattr(w,"height",v[1]+dp(14)))
            sv.add_widget(body); card.add_widget(sv)
        else:
            card.add_widget(label(message,TEXT,13,False,"center",dp(108)))

        close=button("FECHAR",NAVY2,dp(44),13)
        def close_it(*_):
            modal.dismiss()
            Clock.schedule_once(lambda *_x:self.reopen_keyboard(),.24)
        close.bind(on_release=close_it); card.add_widget(close); modal.add_widget(card); modal.open()


if __name__=="__main__":
    ApontamentoRoteiroApp().run()
