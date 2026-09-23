# -*- coding: utf-8 -*-
from __future__ import annotations

import json, os, re, sqlite3, threading, time
from datetime import datetime
from pathlib import Path
from typing import Dict

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
from kivy.uix.progressbar import ProgressBar
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.utils import platform

NAVY=(0.01,0.05,0.11,1); NAVY2=(0.02,0.12,0.23,1); NAVY3=(0.03,0.21,0.39,1)
BLUE=(0.00,0.40,0.75,1); BLUE_SOFT=(0.915,0.958,0.992,1)
BG=(0.94,0.965,0.985,1); CARD=(1,1,1,1); TEXT=(0.055,0.09,0.14,1)
MUTED=(0.39,0.45,0.53,1); BORDER=(0.77,0.835,0.90,1)
GREEN=(0.04,0.58,0.28,1); RED=(0.83,0.11,0.15,1); AMBER=(0.94,0.57,0.06,1)
WHITE=(1,1,1,1); APP_DIR=Path(__file__).resolve().parent

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
def env(name,default=""): return os.getenv(name,ENV.get(name,default)).strip()

TOTVS_API_BASE=env("TOTVS_API_BASE","http://192.168.2.15:8195/rest/apontmod2").rstrip("/")
TOTVS_USERNAME=env("TOTVS_USERNAME"); TOTVS_PASSWORD=env("TOTVS_PASSWORD")
TOTVS_TENANT_ID=env("TOTVS_TENANT_ID"); TOTVS_TIMEOUT=int(env("TOTVS_TIMEOUT","100") or "100")

def s(v): return "" if v is None else str(v).strip()
def now_text(): return datetime.now().strftime("%d/%m/%Y %H:%M:%S")
def now_api(): return datetime.now().strftime("%H:%M:%S")

def hora_api_from_text(v):
    txt=s(v)
    if not txt: return now_api()
    for fmt in ("%d/%m/%Y %H:%M:%S","%Y-%m-%d %H:%M:%S"):
        try: return datetime.strptime(txt,fmt).strftime("%H:%M:%S")
        except Exception: pass
    m=re.search(r"(\d{2}:\d{2}:\d{2})",txt)
    return m.group(1) if m else now_api()

def normalizar_op(v): return re.sub(r"\s+","",s(v)).upper()

def parse_operacao(v):
    if not s(v): raise ValueError("Informe a operação.")
    n=int(float(s(v)))
    if n<=0: raise ValueError("A operação deve ser maior que zero.")
    return n

def parse_qtd(v,nome="quantidade"):
    txt=s(v).replace(",",".")
    if not txt: raise ValueError(f"Informe a {nome}.")
    q=float(txt)
    if q<=0: raise ValueError(f"A {nome} deve ser maior que zero.")
    return int(q) if q.is_integer() else q

def fmt_num(v):
    try:
        n=float(v or 0)
        return str(int(n)) if n.is_integer() else f"{n:.2f}".replace(".",",")
    except Exception:
        return s(v)

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
    err=isinstance(body,dict) and bool(body.get("error") or body.get("errorId") or body.get("erro"))
    for x in ("OPERACAO NAO CADASTRADA","OPERAÇÃO NÃO CADASTRADA","OP NAO EXISTE","OP NÃO EXISTE",
              "NAO EXISTE QUANTIDADE SUFICIENTE","NÃO EXISTE QUANTIDADE SUFICIENTE","SEM SALDO","FALHA AO APONTAR"):
        if x in upper: err=True
    return 200<=resp.status_code<300 and not err, msg or f"HTTP {resp.status_code}", body

def force_android_keyboard():
    if platform!="android": return
    try:
        from jnius import autoclass
        PA=autoclass("org.kivy.android.PythonActivity")
        Context=autoclass("android.content.Context")
        IMM=autoclass("android.view.inputmethod.InputMethodManager")
        activity=PA.mActivity
        imm=activity.getSystemService(Context.INPUT_METHOD_SERVICE)
        view=activity.getWindow().getDecorView()
        try: shown=bool(imm.showSoftInput(view,IMM.SHOW_IMPLICIT))
        except Exception: shown=False
        if not shown:
            try: imm.toggleSoftInput(IMM.SHOW_FORCED,0)
            except Exception: pass
    except Exception: pass

def apontar_totvs(op,operacao,quantidade,recurso,horaini,horafin):
    if not TOTVS_USERNAME or not TOTVS_PASSWORD:
        return {"status":"ERRO","http_status":None,"mensagem":"Credenciais TOTVS não configuradas.","payload":{},"body":None}

    recurso=s(recurso).upper()
    if not recurso:
        return {"status":"ERRO","http_status":None,"mensagem":"Recurso não informado.","payload":{},"body":None}

    payload={
        "op":normalizar_op(op),
        "operacao":int(operacao),
        "quant":quantidade,
        "recurso":recurso,
        "horaini":s(horaini),
        "horafin":s(horafin),
        "lotectl":""
    }

    try:
        resp=requests.post(
            f"{TOTVS_API_BASE}/new",
            json=payload,
            headers=api_headers(),
            auth=HTTPBasicAuth(TOTVS_USERNAME,TOTVS_PASSWORD),
            timeout=TOTVS_TIMEOUT
        )
        ok,msg,body=interpretar_post(resp)
        return {
            "status":"APONTADO" if ok else "ERRO",
            "http_status":resp.status_code,
            "mensagem":msg,
            "payload":payload,
            "body":body
        }
    except requests.exceptions.Timeout:
        return {
            "status":"VERIFICAR",
            "http_status":None,
            "mensagem":"A API não respondeu dentro do tempo limite. Confira no TOTVS antes de reapontar.",
            "payload":payload,
            "body":None
        }
    except requests.exceptions.ConnectionError as exc:
        return {
            "status":"ERRO",
            "http_status":None,
            "mensagem":"Falha de conexão com a API TOTVS: "+s(exc),
            "payload":payload,
            "body":None
        }
    except Exception as exc:
        return {
            "status":"ERRO",
            "http_status":None,
            "mensagem":s(exc),
            "payload":payload,
            "body":None
        }

class ProducaoDB:
    def __init__(self,path):
        self.path=path; self.init()

    def con(self):
        c=sqlite3.connect(self.path,timeout=10); c.row_factory=sqlite3.Row; return c

    def init(self):
        with self.con() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS producoes(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                op TEXT NOT NULL,
                operacao INTEGER NOT NULL,
                recurso TEXT NOT NULL DEFAULT '',
                planejado REAL NOT NULL,
                produzido REAL NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'INICIADA',
                inicio TEXT NOT NULL,
                ultima_data TEXT NOT NULL,
                fim TEXT,
                http_status INTEGER,
                mensagem TEXT,
                payload_json TEXT,
                resposta_json TEXT,
                tentativas INTEGER NOT NULL DEFAULT 0,
                ativo INTEGER NOT NULL DEFAULT 1,
                atualizado_ts REAL
            )""")
            cols={r[1] for r in c.execute("PRAGMA table_info(producoes)").fetchall()}
            if "recurso" not in cols:
                c.execute("ALTER TABLE producoes ADD COLUMN recurso TEXT NOT NULL DEFAULT ''")
            c.commit()

    def ativa(self):
        with self.con() as c:
            r=c.execute("SELECT * FROM producoes WHERE ativo=1 ORDER BY id DESC LIMIT 1").fetchone()
            return dict(r) if r else None

    def iniciar(self,op,oper,recurso,planejado):
        if self.ativa(): raise ValueError("Já existe uma produção ativa. Conclua ou troque a OP.")
        recurso=s(recurso).upper()
        if not recurso: raise ValueError("Informe o recurso.")
        agora=now_text()
        with self.con() as c:
            cur=c.execute("""INSERT INTO producoes(
                op,operacao,recurso,planejado,produzido,status,inicio,ultima_data,tentativas,ativo,atualizado_ts
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (normalizar_op(op),int(oper),recurso,float(planejado),0.0,"INICIADA",agora,agora,0,1,time.time()))
            c.commit(); return int(cur.lastrowid)

    def atualizar(self,pid,qtd,result):
        qtd=float(qtd); status_api=s(result.get("status","ERRO")).upper(); agora=now_text()
        with self.con() as c:
            row=c.execute("SELECT * FROM producoes WHERE id=?",(int(pid),)).fetchone()
            if row is None: raise ValueError("Produção não encontrada.")
            prod=float(row["produzido"] or 0); plan=float(row["planejado"] or 0)
            tent=int(row["tentativas"] or 0)+1; fim=row["fim"]; ativo=int(row["ativo"] or 0)
            if status_api=="APONTADO":
                prod+=qtd
                if prod>=plan: status="CONCLUÍDO"; fim=agora; ativo=0
                else: status="PARCIAL"
            elif status_api=="VERIFICAR": status="VERIFICAR"
            else: status="ERRO"
            c.execute("""UPDATE producoes SET produzido=?,status=?,ultima_data=?,fim=?,http_status=?,mensagem=?,
                payload_json=?,resposta_json=?,tentativas=?,ativo=?,atualizado_ts=? WHERE id=?""",
                (prod,status,agora,fim,result.get("http_status"),result.get("mensagem",""),
                 json.dumps(result.get("payload"),ensure_ascii=False,default=str),
                 json.dumps(result.get("body"),ensure_ascii=False,default=str),
                 tent,ativo,time.time(),int(pid)))
            c.commit()
            return dict(c.execute("SELECT * FROM producoes WHERE id=?",(int(pid),)).fetchone())

    def cancelar_ativa(self):
        r=self.ativa()
        if not r: return
        agora=now_text()
        with self.con() as c:
            c.execute("UPDATE producoes SET ativo=0,status='CANCELADA',fim=?,ultima_data=?,atualizado_ts=? WHERE id=?",
                      (agora,agora,time.time(),int(r["id"])))
            c.commit()

    def listar(self,limit=40):
        with self.con() as c:
            rows=c.execute("""SELECT * FROM producoes
                ORDER BY COALESCE(atualizado_ts,CAST(id AS REAL)) DESC LIMIT ?""",(int(limit),)).fetchall()
            return [dict(r) for r in rows]

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
        super().__init__(**kwargs); self.background_normal=""; self.background_active=""; self.background_color=WHITE
        with self.canvas.after:
            self._lc=Color(*BORDER)
            self._ol=Line(rounded_rectangle=(self.x,self.y,self.width,self.height,dp(8)),width=1.1)
        self.bind(pos=self._sync,size=self._sync,focus=self._focus)
    def _sync(self,*_): self._ol.rounded_rectangle=(self.x,self.y,self.width,self.height,dp(8))
    def _focus(self,_i,f): self._lc.rgba=BLUE if f else BORDER
    def on_touch_down(self,touch):
        out=super().on_touch_down(touch)
        if self.collide_point(*touch.pos): Clock.schedule_once(lambda *_: force_android_keyboard(),.22)
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

def inputbox(hint,input_filter=None,input_type="text",height=dp(44)):
    return IberoInput(hint_text=hint,multiline=False,size_hint_y=None,height=height,font_size=18,
        foreground_color=TEXT,hint_text_color=(.48,.56,.64,1),cursor_color=BLUE,
        padding=[dp(13),dp(9),dp(13),dp(8)],input_filter=input_filter,input_type=input_type,write_tab=False)

def field(title,w,height=dp(63)):
    b=BoxLayout(orientation="vertical",size_hint_y=None,height=height,spacing=dp(2))
    b.add_widget(label(title,NAVY3,11,True,"left",dp(17))); b.add_widget(w); return b

def status_color(st):
    st=s(st).upper()
    if st in ("CONCLUÍDO","PARCIAL","APONTADO"): return GREEN
    if st in ("INICIADA","VERIFICAR"): return AMBER
    if st=="CANCELADA": return MUTED
    return RED

class ApontamentoRoteiroApp(App):
    title="IBERO • Apontamento por Operação TESTE"

    def build(self):
        Window.clearcolor=NAVY
        try: Window.softinput_mode="below_target"
        except Exception: pass
        Path(self.user_data_dir).mkdir(parents=True,exist_ok=True)
        self.db=ProducaoDB(str(Path(self.user_data_dir)/"historico_roteiro.db"))
        self._focusing=False

        root=BoxLayout(orientation="vertical")
        head=Surface(orientation="horizontal",size_hint_y=None,height=dp(58),
                     padding=[dp(18),dp(4),dp(18),dp(4)],spacing=dp(8),bg=NAVY)
        brand=BoxLayout(orientation="vertical")
        brand.add_widget(label("IBERO",WHITE,26,True,"left",dp(30)))
        brand.add_widget(label("MANUFATURA  •  APONTAMENTO POR OPERAÇÃO / RECURSO",(0.69,0.82,0.94,1),10,True,"left",dp(17)))
        head.add_widget(brand)
        badge=Card(orientation="vertical",size_hint=(None,None),size=(dp(92),dp(33)),
                   padding=[dp(6),dp(1)],bg=NAVY3,radius=9,border=BLUE)
        badge.add_widget(label("TESTE",WHITE,11,True,"center",dp(26))); head.add_widget(badge)
        root.add_widget(head); root.add_widget(Surface(size_hint_y=None,height=dp(4),bg=BLUE))

        content=Surface(orientation="horizontal",padding=dp(9),spacing=dp(9),bg=BG)
        self.left=Card(orientation="vertical",padding=[dp(13),dp(8),dp(13),dp(8)],
                       spacing=dp(4),size_hint_x=.43,bg=CARD,radius=14)
        self.right=Card(orientation="vertical",padding=[dp(12),dp(8),dp(12),dp(8)],
                        spacing=dp(5),size_hint_x=.57,bg=CARD,radius=14)
        content.add_widget(self.left); self.build_history_panel(); content.add_widget(self.right)
        root.add_widget(content)

        self.render_left()
        Clock.schedule_once(lambda *_: self.refresh_history(),.2)
        return root

    def render_left(self):
        self.left.clear_widgets()
        ativa=self.db.ativa()
        self.render_active(ativa) if ativa else self.render_start()

    def render_start(self):
        self.left.add_widget(label("INICIAR PRODUÇÃO",NAVY,19,True,"left",dp(26)))
        self.left.add_widget(label("Bipe a OP e informe operação, recurso e planejado.",MUTED,10,False,"left",dp(17)))
        flow=Card(orientation="horizontal",size_hint_y=None,height=dp(30),padding=[dp(6),0],
                  spacing=dp(2),bg=BLUE_SOFT,radius=8,border=(.80,.88,.96,1))
        for txt in ("1 OP","›","2 OPERAÇÃO / RECURSO","›","3 PLANEJADO"):
            flow.add_widget(label(txt,BLUE if txt=="›" else NAVY2,13 if txt=="›" else 9,True,"center",dp(23)))
        self.left.add_widget(flow)

        self.op=inputbox("Bipe ou digite a OP")
        self.oper=inputbox("Ex.: 10","int","number")
        self.recurso=inputbox("Ex.: PRE-02")
        self.planejado=inputbox("Ex.: 300",None,"number")

        self.left.add_widget(field("OP",self.op))

        row_or=BoxLayout(orientation="horizontal",size_hint_y=None,height=dp(63),spacing=dp(6))
        row_or.add_widget(field("OPERAÇÃO",self.oper))
        row_or.add_widget(field("RECURSO",self.recurso))
        self.left.add_widget(row_or)

        self.left.add_widget(field("PLANEJADO TOTAL",self.planejado))
        self.start_btn=button("▶  INICIAR PRODUÇÃO",NAVY2,dp(49),15)
        self.start_btn.bind(on_release=self.on_start); self.left.add_widget(self.start_btn)

        c=Card(orientation="vertical",size_hint_y=None,height=dp(38),padding=[dp(8),0],
               bg=BLUE_SOFT,radius=9,border=(.80,.88,.96,1))
        c.add_widget(label("AGUARDANDO START",NAVY3,10,True,"center",dp(31))); self.left.add_widget(c)

        self.op.bind(on_text_validate=lambda *_: self.focus_start(self.oper,True))
        self.oper.bind(on_text_validate=lambda *_: self.focus_start(self.recurso,True))
        self.recurso.bind(on_text_validate=lambda *_: self.focus_start(self.planejado,True))
        self.planejado.bind(on_text_validate=self.on_start)
        for w in (self.op,self.oper,self.recurso,self.planejado): w.bind(focus=self._focus_changed)
        Clock.schedule_once(lambda *_: self.focus_start(self.op,False),.22)

    def render_active(self,a):
        plan=float(a.get("planejado") or 0); prod=float(a.get("produzido") or 0)
        saldo=max(plan-prod,0); pct=0 if plan<=0 else min(prod/plan*100,100)

        self.left.add_widget(label("PRODUÇÃO ATIVA",NAVY,18,True,"left",dp(25)))
        top=Card(orientation="vertical",size_hint_y=None,height=dp(67),padding=[dp(10),dp(4)],
                 bg=(.965,.982,.997,1),radius=10,border=(.78,.87,.95,1))
        top.add_widget(label(a.get("op",""),NAVY,20,True,"left",dp(31)))
        top.add_widget(label(f"OPERAÇÃO {a.get('operacao','')}  •  RECURSO {a.get('recurso') or '-'}  •  INÍCIO {a.get('inicio','')}",MUTED,9,True,"left",dp(21)))
        self.left.add_widget(top)

        metrics=BoxLayout(orientation="horizontal",size_hint_y=None,height=dp(64),spacing=dp(5))
        for title,value,color in (("PLANEJADO",fmt_num(plan),NAVY2),("APONTADO",fmt_num(prod),GREEN),("FALTA",fmt_num(saldo),BLUE)):
            c=Card(orientation="vertical",padding=[dp(7),dp(2)],bg=(.98,.987,.995,1),radius=9,border=(.84,.89,.94,1))
            c.add_widget(label(title,MUTED,8,True,"center",dp(18)))
            c.add_widget(label(value,color,18,True,"center",dp(35))); metrics.add_widget(c)
        self.left.add_widget(metrics)

        pbox=BoxLayout(orientation="vertical",size_hint_y=None,height=dp(43),spacing=dp(2))
        pbox.add_widget(label(f"{pct:.0f}% CONCLUÍDO",NAVY3,9,True,"left",dp(16)))
        pbox.add_widget(ProgressBar(max=100,value=pct,size_hint_y=None,height=dp(14))); self.left.add_widget(pbox)

        self.qtd=inputbox("Quantidade produzida agora",None,"number",dp(46))
        self.left.add_widget(field("QUANTIDADE DESTE APONTAMENTO",self.qtd,dp(65)))
        self.send=button("APONTAR E SOMAR",NAVY2,dp(49),15); self.send.bind(on_release=self.on_apontar)
        self.left.add_widget(self.send)

        controls=BoxLayout(orientation="horizontal",size_hint_y=None,height=dp(39),spacing=dp(5))
        self.status_card=Card(orientation="vertical",padding=[dp(8),0],bg=BLUE_SOFT,radius=9,border=(.80,.88,.96,1))
        txt={"ERRO":"ERRO NO ÚLTIMO ENVIO","VERIFICAR":"VERIFICAR NO TOTVS","PARCIAL":"PARCIAL • CONTINUE APONTANDO"}.get(s(a.get("status")).upper(),"PRODUÇÃO INICIADA")
        self.status=label(txt,status_color(a.get("status")),10,True,"center",dp(32)); self.status_card.add_widget(self.status)
        controls.add_widget(self.status_card)
        kb=button("⌨",NAVY3,dp(39),17,dp(48)); kb.bind(on_release=lambda *_: self.focus_qty(True)); controls.add_widget(kb)
        troca=button("TROCAR OP",MUTED,dp(39),9,dp(82)); troca.bind(on_release=self.confirm_swap); controls.add_widget(troca)
        self.left.add_widget(controls)

        self.qtd.bind(on_text_validate=self.on_apontar); self.qtd.bind(focus=self._focus_changed)
        Clock.schedule_once(lambda *_: self.focus_qty(True),.22)

    def on_start(self,*_):
        try:
            op=normalizar_op(self.op.text)
            if not op: raise ValueError("Informe a OP.")
            oper=parse_operacao(self.oper.text)
            recurso=s(self.recurso.text).upper()
            if not recurso: raise ValueError("Informe o recurso.")
            plan=parse_qtd(self.planejado.text,"quantidade planejada")
            self.db.iniciar(op,oper,recurso,plan)
            self.render_left(); self.refresh_history()
            self.popup("PRODUÇÃO INICIADA",f"OP {op}\nOperação {oper}\nRecurso {recurso}\nPlanejado total: {fmt_num(plan)}",GREEN)
        except Exception as exc:
            self.popup("VALIDAÇÃO",s(exc),RED)

    def on_apontar(self,*_):
        a=self.db.ativa()
        if not a:
            self.popup("SEM PRODUÇÃO ATIVA","Inicie uma OP antes de apontar.",RED); return
        if self.send.disabled: return
        try:
            qtd=parse_qtd(self.qtd.text)
            recurso=s(a.get("recurso")).upper()
            if not recurso:
                raise ValueError("Esta produção foi iniciada em uma versão antiga sem recurso. Troque/reinicie a OP informando o recurso.")
        except Exception as exc:
            self.popup("VALIDAÇÃO",s(exc),RED); return

        horaini=hora_api_from_text(a.get("inicio"))
        horafin=now_api()

        self.set_busy(True,"ENVIANDO AO TOTVS...")
        threading.Thread(
            target=self.worker,
            args=(int(a["id"]),a["op"],int(a["operacao"]),qtd,recurso,horaini,horafin),
            daemon=True
        ).start()

    def worker(self,pid,op,oper,qtd,recurso,horaini,horafin):
        result=apontar_totvs(op,oper,qtd,recurso,horaini,horafin)
        try: result["producao"]=self.db.atualizar(pid,qtd,result)
        except Exception as exc: result["mensagem"]=result.get("mensagem","")+f"\nFalha ao atualizar histórico local: {exc}"
        Clock.schedule_once(lambda _dt,res=result:self.finish(res),0)

    def finish(self,result):
        self.set_busy(False)
        st=s(result.get("status","ERRO")).upper(); msg=result.get("mensagem",""); http=result.get("http_status")
        prod=result.get("producao") or {}
        self.refresh_history(); self.render_left()

        if st=="APONTADO":
            concluido=s(prod.get("status")).upper()=="CONCLUÍDO"
            if concluido:
                title="PLANEJADO CONCLUÍDO"; extra=f"\n\nTotal: {fmt_num(prod.get('produzido'))} / {fmt_num(prod.get('planejado'))}"
            else:
                saldo=max(float(prod.get("planejado") or 0)-float(prod.get("produzido") or 0),0)
                title="APONTAMENTO SOMADO"; extra=f"\n\nAcumulado: {fmt_num(prod.get('produzido'))} / {fmt_num(prod.get('planejado'))}\nFalta: {fmt_num(saldo)}"
            self.popup(title,f"{msg}{extra}\n\nHTTP: {http if http is not None else '-'}",GREEN)
        else:
            self.popup(st,f"{msg}\n\nHTTP: {http if http is not None else '-'}",status_color(st))

    def set_busy(self,busy,text=None):
        if hasattr(self,"send"):
            self.send.disabled=bool(busy); self.send.text="ENVIANDO..." if busy else "APONTAR E SOMAR"
        if text and hasattr(self,"status"):
            self.status.text=text; self.status.color=BLUE

    def confirm_swap(self,*_):
        modal=ModalView(size_hint=(.72,.55),auto_dismiss=False,background_color=(0,0,0,.52))
        card=Card(orientation="vertical",padding=dp(18),spacing=dp(10),bg=CARD,radius=14,border=(.74,.82,.90,1))
        card.add_widget(label("TROCAR OP",AMBER,20,True,"center",dp(38)))
        card.add_widget(label("A produção ativa será encerrada como CANCELADA.\nO acumulado ficará no histórico.\n\nDeseja realmente trocar a OP?",TEXT,13,False,"center",dp(95)))
        actions=BoxLayout(orientation="horizontal",size_hint_y=None,height=dp(45),spacing=dp(8))
        cancel=button("VOLTAR",MUTED,dp(45),12); confirm=button("SIM, TROCAR OP",AMBER,dp(45),12)
        cancel.bind(on_release=lambda *_: modal.dismiss())
        def do_swap(*_):
            modal.dismiss(); self.db.cancelar_ativa(); self.render_left(); self.refresh_history()
        confirm.bind(on_release=do_swap)
        actions.add_widget(cancel); actions.add_widget(confirm); card.add_widget(actions)
        modal.add_widget(card); modal.open()

    def _focus_changed(self,_w,focused):
        if focused and not self._focusing: Clock.schedule_once(lambda *_: force_android_keyboard(),.22)

    def focus_start(self,w,show_keyboard=False):
        self._focusing=True
        for x in (self.op,self.oper,self.recurso,self.planejado):
            if x is not w: x.focus=False
        def go(_dt):
            w.focus=True
            try: w.cursor=(len(w.text),0); w._ensure_keyboard()
            except Exception: pass
            self._focusing=False
            if show_keyboard: Clock.schedule_once(lambda *_: force_android_keyboard(),.18)
        Clock.schedule_once(go,.10)

    def focus_qty(self,show_keyboard=True):
        if not hasattr(self,"qtd"): return
        self._focusing=True
        def go(_dt):
            self.qtd.focus=True
            try: self.qtd.cursor=(len(self.qtd.text),0); self.qtd._ensure_keyboard()
            except Exception: pass
            self._focusing=False
            if show_keyboard: Clock.schedule_once(lambda *_: force_android_keyboard(),.18)
        Clock.schedule_once(go,.08)

    def build_history_panel(self):
        hh=BoxLayout(orientation="horizontal",size_hint_y=None,height=dp(45),spacing=dp(6))
        titles=BoxLayout(orientation="vertical")
        titles.add_widget(label("HISTÓRICO AGLUTINADO",NAVY,17,True,"left",dp(24)))
        titles.add_widget(label("Uma linha por produção • acumulado • saldo restante",MUTED,9,False,"left",dp(15)))
        hh.add_widget(titles)
        ref=button("ATUALIZAR",NAVY3,dp(34),9,dp(94)); ref.bind(on_release=lambda *_: self.refresh_history()); hh.add_widget(ref)
        self.right.add_widget(hh)
        self.scroll=ScrollView(do_scroll_x=False,bar_width=dp(5))
        self.hist=BoxLayout(orientation="vertical",spacing=dp(6),size_hint_y=None,padding=[0,dp(2),dp(2),dp(5)])
        self.hist.bind(minimum_height=self.hist.setter("height")); self.scroll.add_widget(self.hist); self.right.add_widget(self.scroll)

    def refresh_history(self):
        self.hist.clear_widgets(); rows=self.db.listar(40)
        if not rows:
            c=Card(orientation="vertical",padding=dp(12),size_hint_y=None,height=dp(76),
                   bg=(.97,.985,.997,1),radius=9,border=(.83,.90,.95,1))
            c.add_widget(label("Nenhuma produção iniciada neste tablet.",MUTED,12,False,"center",dp(48)))
            self.hist.add_widget(c); return
        for r in rows: self.hist.add_widget(self.history_item(r))

    def history_item(self,r):
        st=s(r.get("status")).upper(); color=status_color(st)
        plan=float(r.get("planejado") or 0); prod=float(r.get("produzido") or 0); saldo=max(plan-prod,0)
        item=Card(orientation="horizontal",padding=[0,dp(6),dp(7),dp(6)],spacing=dp(8),
                  size_hint_y=None,height=dp(108),bg=(.977,.988,.998,1),radius=10,border=(.83,.90,.95,1))
        item.add_widget(Surface(size_hint_x=None,width=dp(6),bg=color))
        info=BoxLayout(orientation="vertical")
        info.add_widget(label(f"{r.get('op','')}   •   OPERAÇÃO {r.get('operacao','')}   •   {r.get('recurso') or '-'}",NAVY,14,True,"left",dp(24)))
        qtyrow=BoxLayout(orientation="horizontal",size_hint_y=None,height=dp(36))
        qtyrow.add_widget(label(f"{fmt_num(prod)} / {fmt_num(plan)}",GREEN if saldo<=0 else NAVY2,17,True,"left",dp(33)))
        qtyrow.add_widget(label(f"FALTA {fmt_num(saldo)}",BLUE if saldo>0 else GREEN,14,True,"right",dp(33)))
        info.add_widget(qtyrow)
        info.add_widget(label(f"ÚLTIMO: {r.get('ultima_data') or '-'}",TEXT,12,True,"left",dp(24)))
        info.add_widget(label(f"INÍCIO: {r.get('inicio') or '-'}   •   {int(r.get('tentativas') or 0)} envios",MUTED,10,False,"left",dp(18)))
        item.add_widget(info)

        act=BoxLayout(orientation="vertical",spacing=dp(5),size_hint_x=None,width=dp(116),padding=[0,dp(12),0,dp(11)])
        b1=button(st,color,dp(34),9,dp(116)); b1.bind(on_release=lambda *_x,row=r:self.show_details(row)); act.add_widget(b1)
        b2=button("DETALHES",NAVY3,dp(34),9,dp(116)); b2.bind(on_release=lambda *_x,row=r:self.show_details(row)); act.add_widget(b2)
        item.add_widget(act); return item

    def show_details(self,r):
        plan=float(r.get("planejado") or 0); prod=float(r.get("produzido") or 0); saldo=max(plan-prod,0)
        txt=(f"ID: {r.get('id')}\nOP: {r.get('op')}\nOperação: {r.get('operacao')}\nRecurso: {r.get('recurso') or '-'}\n\n"
             f"Planejado: {fmt_num(plan)}\nProduzido acumulado: {fmt_num(prod)}\nSaldo: {fmt_num(saldo)}\n\n"
             f"Status atual: {r.get('status')}\nInício: {r.get('inicio')}\nÚltima atualização: {r.get('ultima_data')}\n"
             f"Fim: {r.get('fim') or '-'}\nEnvios realizados: {r.get('tentativas') or 0}\nHTTP: {r.get('http_status') or '-'}\n\n"
             f"Mensagem:\n{s(r.get('mensagem')) or '-'}\n\nÚltimo payload:\n{s(r.get('payload_json')) or '-'}\n\n"
             f"Última resposta:\n{s(r.get('resposta_json')) or '-'}")
        self.popup("DETALHES DA PRODUÇÃO",txt,NAVY3,large=True)

    def popup(self,title,message,color=NAVY2,large=False):
        modal=ModalView(size_hint=(.82,.78 if large else .57),auto_dismiss=False,background_color=(0,0,0,.52))
        card=Card(orientation="vertical",padding=dp(16),spacing=dp(7),bg=CARD,radius=14,border=(.74,.82,.90,1))
        card.add_widget(label(title,color,20,True,"center",dp(38)))
        if large:
            sv=ScrollView(do_scroll_x=False)
            body=Label(text=message,color=TEXT,font_size=12,halign="left",valign="top",size_hint_y=None,markup=False)
            body.bind(width=lambda w,*_:setattr(w,"text_size",(w.width,None)))
            body.bind(texture_size=lambda w,v:setattr(w,"height",v[1]+dp(14)))
            sv.add_widget(body); card.add_widget(sv)
        else:
            card.add_widget(label(message,TEXT,13,False,"center",dp(120)))
        close=button("FECHAR",NAVY2,dp(44),13)
        def close_it(*_):
            modal.dismiss(); Clock.schedule_once(lambda *_x:self.restore_focus(),.22)
        close.bind(on_release=close_it); card.add_widget(close); modal.add_widget(card); modal.open()

    def restore_focus(self):
        if self.db.ativa() and hasattr(self,"qtd"): self.focus_qty(True)
        elif hasattr(self,"op"): self.focus_start(self.op,False)

if __name__=="__main__":
    ApontamentoRoteiroApp().run()
