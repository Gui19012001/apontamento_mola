# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import requests
from requests.auth import HTTPBasicAuth

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput

NAVY=(0.00,0.12,0.25,1); NAVY2=(0.04,0.20,0.36,1); WHITE=(1,1,1,1)
BLACK=(0.05,0.05,0.05,1); GRAY=(0.42,0.45,0.49,1); GREEN=(0.12,0.52,0.28,1)
RED=(0.78,0.12,0.12,1); AMBER=(0.87,0.55,0.06,1)
APP_DIR=Path(__file__).resolve().parent


def load_simple_env(path: Path)->Dict[str,str]:
    out={}
    if not path.exists(): return out
    try: raw=path.read_text(encoding='utf-8')
    except Exception: return out
    for line in raw.splitlines():
        line=line.strip()
        if not line or line.startswith('#') or '=' not in line: continue
        k,v=line.split('=',1); k=k.strip(); v=v.strip().strip('"').strip("'")
        if k: out[k]=v
    return out

ENV=load_simple_env(APP_DIR/'teste.env')
def env(name, default=''): return os.getenv(name,ENV.get(name,default)).strip()
TOTVS_API_BASE=env('TOTVS_API_BASE','http://192.168.2.15:8195/rest/apontmod2').rstrip('/')
TOTVS_USERNAME=env('TOTVS_USERNAME'); TOTVS_PASSWORD=env('TOTVS_PASSWORD')
TOTVS_TENANT_ID=env('TOTVS_TENANT_ID'); TOTVS_TIMEOUT=int(env('TOTVS_TIMEOUT','100') or '100')
TOTVS_GET_ID_PARAM=env('TOTVS_GET_ID_PARAM','op'); TOTVS_GET_ID_MODE=env('TOTVS_GET_ID_MODE','param').lower()
TOTVS_GET_ID_PATH=env('TOTVS_GET_ID_PATH','get_id')


def s(v): return '' if v is None else str(v).strip()
def now_text(): return datetime.now().strftime('%d/%m/%Y %H:%M:%S')
def normalizar_op(v): return re.sub(r'\s+','',s(v))
def parse_operacao(v):
    if not s(v): raise ValueError('Informe a operação.')
    return int(float(s(v)))
def parse_quantidade(v):
    txt=s(v).replace(',','.')
    if not txt: raise ValueError('Informe a quantidade.')
    q=float(txt)
    if q<=0: raise ValueError('A quantidade deve ser maior que zero.')
    return int(q) if q.is_integer() else q

def api_headers():
    h={'Accept':'application/json','Content-Type':'application/json'}
    if TOTVS_TENANT_ID: h['tenantId']=TOTVS_TENANT_ID
    return h

def auth(): return HTTPBasicAuth(TOTVS_USERNAME,TOTVS_PASSWORD)
def response_body(resp):
    try: return resp.json()
    except Exception: return (resp.text or '').strip()
def texto_response(body):
    if isinstance(body,dict):
        for k in ('note','message','mensagem','error','detail','details'):
            if body.get(k): return s(body.get(k))
        return json.dumps(body,ensure_ascii=False,default=str)
    return json.dumps(body,ensure_ascii=False,default=str) if isinstance(body,list) else s(body)

def interpretar_post(resp):
    body=response_body(resp); msg=texto_response(body); upper=msg.upper(); business_error=False
    if isinstance(body,dict): business_error=bool(body.get('error') or body.get('errorId'))
    frases=('OPERACAO NAO CADASTRADA','OPERAÇÃO NÃO CADASTRADA','OP NAO EXISTE','OP NÃO EXISTE',
            'NAO EXISTE QUANTIDADE SUFICIENTE','NÃO EXISTE QUANTIDADE SUFICIENTE')
    if any(x in upper for x in frases): business_error=True
    return (200<=resp.status_code<300 and not business_error), (msg or f'HTTP {resp.status_code}'), body

ROUTE_KEYS_N={re.sub(r'[^a-z0-9]','',x.lower()) for x in ('roteiro','g2_codigo','g2codigo','codigo_roteiro','codigoroteiro','route')}
OPER_KEYS_N={re.sub(r'[^a-z0-9]','',x.lower()) for x in ('operac','operacao','g2_operac','g2operac','operation')}
def norm_key(v): return re.sub(r'[^a-z0-9]','',s(v).lower())
def dict_value(row,wanted):
    for k,v in row.items():
        if norm_key(k) in wanted: return v
    return None

def collect_dicts(obj):
    out=[]
    def walk(x):
        if isinstance(x,dict):
            out.append(x)
            for v in x.values(): walk(v)
        elif isinstance(x,list):
            for i in x: walk(i)
    walk(obj); return out

def extrair_roteiro(body,operacao):
    matched=[]; todos=[]
    for row in collect_dicts(body):
        rota=dict_value(row,ROUTE_KEYS_N)
        if rota is None or not s(rota): continue
        rt=s(rota); todos.append(rt); opv=dict_value(row,OPER_KEYS_N)
        if opv is not None:
            try:
                if int(float(s(opv)))==int(operacao): matched.append(rt)
            except Exception: pass
    def uniq(vals):
        out=[]
        for v in vals:
            if v not in out: out.append(v)
        return out
    matched=uniq(matched); todos=uniq(todos)
    if len(matched)==1: return matched[0],'roteiro localizado pela operação'
    if len(matched)>1: raise ValueError(f'Mais de um roteiro para operação {operacao}: {", ".join(matched)}')
    if len(todos)==1: return todos[0],'único roteiro retornado pela OP'
    if not todos: raise ValueError('A API de consulta não retornou o código do roteiro. O TI precisa retornar o roteiro no GET /get_id.')
    raise ValueError(f'A OP retornou múltiplos roteiros ({", ".join(todos)}) sem vínculo único com a operação {operacao}.')

def montar_url_get_id(op):
    base=f"{TOTVS_API_BASE}/{TOTVS_GET_ID_PATH.strip('/')}"
    if TOTVS_GET_ID_MODE=='raw': return f'{base}?={quote(op)}',None
    return base,{TOTVS_GET_ID_PARAM or 'op':op}

def consultar_roteiro(op,operacao):
    if not TOTVS_USERNAME or not TOTVS_PASSWORD: raise RuntimeError('Credenciais TOTVS não configuradas.')
    url,params=montar_url_get_id(op)
    resp=requests.get(url,params=params,headers=api_headers(),auth=auth(),timeout=TOTVS_TIMEOUT)
    body=response_body(resp)
    if not 200<=resp.status_code<300: raise RuntimeError(f'GET roteiro HTTP {resp.status_code}: {texto_response(body)}')
    roteiro,criterio=extrair_roteiro(body,operacao)
    return roteiro,{'url':resp.url,'status_code':resp.status_code,'body':body,'criterio':criterio}

def apontar_totvs(op,roteiro,operacao,quantidade):
    payload={'op':op,'roteiro':s(roteiro),'operac':int(operacao),'quant':quantidade,'lote':''}
    url=f'{TOTVS_API_BASE}/new'
    try:
        resp=requests.post(url,json=payload,headers=api_headers(),auth=auth(),timeout=TOTVS_TIMEOUT)
        ok,msg,body=interpretar_post(resp)
        return {'status':'APONTADO' if ok else 'ERRO','http_status':resp.status_code,'mensagem':msg,'payload':payload,'body':body,'url':url}
    except requests.exceptions.Timeout:
        return {'status':'VERIFICAR','http_status':None,'mensagem':'Timeout aguardando a resposta. Isto NÃO confirma falha. Confira no TOTVS antes de reapontar.','payload':payload,'body':None,'url':url}
    except requests.exceptions.ConnectionError as exc:
        return {'status':'ERRO','http_status':None,'mensagem':'Falha de conexão com a API TOTVS: '+s(exc),'payload':payload,'body':None,'url':url}
    except Exception as exc:
        return {'status':'ERRO','http_status':None,'mensagem':s(exc),'payload':payload,'body':None,'url':url}

class HistoricoDB:
    def __init__(self,path): self.path=path; self.init()
    def con(self): return sqlite3.connect(self.path,timeout=10)
    def init(self):
        with self.con() as c:
            c.execute('''CREATE TABLE IF NOT EXISTS historico (
                id INTEGER PRIMARY KEY AUTOINCREMENT,data_hora TEXT NOT NULL,op TEXT NOT NULL,
                roteiro TEXT,operacao INTEGER NOT NULL,quantidade REAL NOT NULL,status TEXT NOT NULL,
                http_status INTEGER,mensagem TEXT,payload_json TEXT,resposta_json TEXT,tentativa_de INTEGER)'''); c.commit()
    def incluir(self,op,roteiro,operacao,quantidade,result,tentativa_de=None):
        with self.con() as c:
            cur=c.execute('''INSERT INTO historico(data_hora,op,roteiro,operacao,quantidade,status,http_status,mensagem,payload_json,resposta_json,tentativa_de)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)''',(now_text(),op,roteiro,operacao,float(quantidade),result.get('status','ERRO'),result.get('http_status'),
                result.get('mensagem',''),json.dumps(result.get('payload'),ensure_ascii=False,default=str),json.dumps(result.get('body'),ensure_ascii=False,default=str),tentativa_de)); c.commit(); return int(cur.lastrowid)
    def listar(self,limit=30):
        with self.con() as c:
            c.row_factory=sqlite3.Row
            return [dict(r) for r in c.execute('SELECT * FROM historico ORDER BY id DESC LIMIT ?',(int(limit),)).fetchall()]

def mk_label(text='',color=BLACK,size=16,bold=False,halign='left',height=dp(36)):
    lb=Label(text=text,color=color,font_size=size,bold=bold,halign=halign,valign='middle',size_hint_y=None,height=height)
    lb.bind(width=lambda inst,*_: setattr(inst,'text_size',(inst.width,None))); return lb

def mk_button(text,bg=NAVY,height=dp(50)):
    return Button(text=text,size_hint_y=None,height=height,background_normal='',background_color=bg,color=WHITE,bold=True,font_size=15)

def mk_input(hint,input_filter=None):
    return TextInput(hint_text=hint,multiline=False,size_hint_y=None,height=dp(52),font_size=18,foreground_color=BLACK,background_color=WHITE,cursor_color=NAVY,padding=[dp(12),dp(13)],input_filter=input_filter)

class ApontamentoRoteiroApp(App):
    title='Apontamento por Roteiro TESTE'
    def build(self):
        Window.clearcolor=WHITE
        Path(self.user_data_dir).mkdir(parents=True,exist_ok=True)
        self.db=HistoricoDB(str(Path(self.user_data_dir)/'historico_roteiro.db'))
        self.current_retry_id=None
        root=BoxLayout(orientation='vertical',padding=dp(16),spacing=dp(10))
        root.add_widget(mk_label('APONTAMENTO POR ROTEIRO - TESTE',NAVY,24,True,'center',dp(50)))
        root.add_widget(mk_label('Operador informa somente OP, Operação e Quantidade.',GRAY,14,False,'center',dp(30)))
        form=GridLayout(cols=2,spacing=dp(10),size_hint_y=None,height=dp(190),row_default_height=dp(58),row_force_default=True)
        form.add_widget(mk_label('OP',NAVY,16,True)); self.op_input=mk_input('Ex.: x0222601020'); form.add_widget(self.op_input)
        form.add_widget(mk_label('OPERAÇÃO',NAVY,16,True)); self.oper_input=mk_input('Ex.: 20','int'); form.add_widget(self.oper_input)
        form.add_widget(mk_label('QUANTIDADE',NAVY,16,True)); self.quant_input=mk_input('Ex.: 20'); form.add_widget(self.quant_input)
        root.add_widget(form)
        self.route_label=mk_label('Roteiro identificado: -',NAVY2,15,True,'center',dp(34)); root.add_widget(self.route_label)
        self.status_label=mk_label('Pronto para apontar.',GRAY,14,False,'center',dp(42)); root.add_widget(self.status_label)
        self.apontar_btn=mk_button('APONTAR',NAVY,dp(56)); self.apontar_btn.bind(on_release=self.on_apontar); root.add_widget(self.apontar_btn)
        root.add_widget(mk_label('ÚLTIMOS APONTAMENTOS',NAVY,18,True,'left',dp(38)))
        scroll=ScrollView(do_scroll_x=False); self.history_box=BoxLayout(orientation='vertical',spacing=dp(8),size_hint_y=None,padding=[0,0,dp(4),dp(8)])
        self.history_box.bind(minimum_height=self.history_box.setter('height')); scroll.add_widget(self.history_box); root.add_widget(scroll)
        self.op_input.bind(on_text_validate=lambda *_: setattr(self.oper_input,'focus',True))
        self.oper_input.bind(on_text_validate=lambda *_: setattr(self.quant_input,'focus',True))
        self.quant_input.bind(on_text_validate=self.on_apontar)
        Clock.schedule_once(lambda *_: setattr(self.op_input,'focus',True),0.5); Clock.schedule_once(lambda *_: self.refresh_history(),0.2)
        return root

    def on_apontar(self,*_):
        if self.apontar_btn.disabled: return
        try:
            op=normalizar_op(self.op_input.text)
            if not op: raise ValueError('Informe a OP.')
            oper=parse_operacao(self.oper_input.text); qtd=parse_quantidade(self.quant_input.text)
        except Exception as exc:
            self.popup('VALIDAÇÃO',s(exc),RED); return
        self.set_busy(True,'Consultando roteiro da OP...')
        threading.Thread(target=self.worker,args=(op,oper,qtd,self.current_retry_id),daemon=True).start()

    def worker(self,op,oper,qtd,tentativa_de):
        try:
            roteiro,_=consultar_roteiro(op,oper)
            Clock.schedule_once(lambda _dt,r=roteiro: setattr(self.route_label,'text',f'Roteiro identificado: {r}'),0)
            result=apontar_totvs(op,roteiro,oper,qtd)
            self.db.incluir(op,roteiro,oper,qtd,result,tentativa_de)
        except requests.exceptions.Timeout:
            result={'status':'ERRO','http_status':None,'mensagem':'Timeout ao CONSULTAR o roteiro. Nenhum POST foi enviado.','payload':{},'body':None}
            self.db.incluir(op,'',oper,qtd,result,tentativa_de)
        except Exception as exc:
            result={'status':'ERRO','http_status':None,'mensagem':s(exc),'payload':{},'body':None}
            self.db.incluir(op,'',oper,qtd,result,tentativa_de)
        Clock.schedule_once(lambda _dt,res=result: self.finish(res),0)

    def finish(self,result):
        self.set_busy(False); status=result.get('status','ERRO'); msg=result.get('mensagem','')
        if status=='APONTADO':
            color=GREEN; self.status_label.text='Apontamento realizado com sucesso.'; self.current_retry_id=None
        elif status=='VERIFICAR':
            color=AMBER; self.status_label.text='Resultado indeterminado. Confira antes de reapontar.'
        else:
            color=RED; self.status_label.text='Apontamento não realizado.'
        self.status_label.color=color; self.refresh_history(); self.popup(status,f"{msg}\n\nHTTP: {result.get('http_status') or '-'}",color)
        if status=='APONTADO':
            self.oper_input.text=''; self.quant_input.text=''; self.route_label.text='Roteiro identificado: -'; self.oper_input.focus=True

    def set_busy(self,busy,text=''):
        self.apontar_btn.disabled=busy; self.apontar_btn.text='AGUARDE...' if busy else ('REAPONTAR' if self.current_retry_id else 'APONTAR')
        if busy: self.status_label.text=text; self.status_label.color=NAVY

    def refresh_history(self):
        self.history_box.clear_widgets(); rows=self.db.listar(30)
        if not rows: self.history_box.add_widget(mk_label('Nenhum apontamento registrado neste tablet.',GRAY,14,False,'left',dp(50))); return
        for row in rows: self.history_box.add_widget(self.history_card(row))

    def history_card(self,row):
        status=s(row.get('status')).upper(); color={'APONTADO':GREEN,'ERRO':RED,'VERIFICAR':AMBER}.get(status,GRAY)
        card=BoxLayout(orientation='horizontal',size_hint_y=None,height=dp(84),spacing=dp(8),padding=[dp(8),dp(5)])
        qtd=row.get('quantidade'); qtdtxt=f'{qtd:g}' if isinstance(qtd,(int,float)) else s(qtd)
        info=f"[b]{row.get('op')}[/b]  R{row.get('roteiro') or '-'}  OP {row.get('operacao')}  Qtd {qtdtxt}\n{row.get('data_hora')}   [color={self.rgb_hex(color)}][b]{status}[/b][/color]\n{s(row.get('mensagem'))[:105]}"
        lb=Label(text=info,markup=True,color=BLACK,halign='left',valign='middle',font_size=13); lb.bind(size=lambda inst,*_: setattr(inst,'text_size',(inst.width,None))); card.add_widget(lb)
        actions=BoxLayout(orientation='vertical',size_hint_x=None,width=dp(132),spacing=dp(5))
        det=mk_button('DETALHES',NAVY2,dp(34)); det.bind(on_release=lambda *_,r=row:self.history_detail(r)); actions.add_widget(det)
        if status=='ERRO':
            bt=mk_button('REAPONTAR',RED,dp(34)); bt.bind(on_release=lambda *_,r=row:self.load_retry(r)); actions.add_widget(bt)
        elif status=='VERIFICAR':
            bt=mk_button('REAPONTAR*',AMBER,dp(34)); bt.bind(on_release=lambda *_,r=row:self.confirm_retry_timeout(r)); actions.add_widget(bt)
        else: actions.add_widget(mk_label('OK',GREEN,13,True,'center',dp(34)))
        card.add_widget(actions); return card

    def load_retry(self,row):
        self.op_input.text=s(row.get('op')); self.oper_input.text=s(row.get('operacao')); qtd=row.get('quantidade')
        self.quant_input.text=f'{qtd:g}' if isinstance(qtd,(int,float)) else s(qtd); self.current_retry_id=int(row.get('id'))
        self.route_label.text=f"Roteiro anterior: {row.get('roteiro') or '-'} (será consultado novamente)"; self.apontar_btn.text='REAPONTAR'; self.status_label.text='Dados carregados para nova tentativa.'; self.status_label.color=NAVY

    def confirm_retry_timeout(self,row):
        box=BoxLayout(orientation='vertical',padding=dp(16),spacing=dp(10)); box.add_widget(mk_label('Timeout não confirma falha.\nSomente reapontar após confirmar no TOTVS que NÃO houve gravação.',BLACK,15,False,'center',dp(130)))
        buttons=BoxLayout(spacing=dp(8),size_hint_y=None,height=dp(50)); cancel=mk_button('CANCELAR',GRAY); confirm=mk_button('CONFIRMEI: REAPONTAR',AMBER); buttons.add_widget(cancel); buttons.add_widget(confirm); box.add_widget(buttons)
        modal=ModalView(size_hint=(0.88,0.5),background_color=WHITE,auto_dismiss=False); modal.add_widget(box); cancel.bind(on_release=lambda *_:modal.dismiss())
        def go(*_): modal.dismiss(); self.load_retry(row)
        confirm.bind(on_release=go); modal.open()

    def history_detail(self,row):
        txt=f"Data/Hora: {row.get('data_hora')}\nOP: {row.get('op')}\nRoteiro: {row.get('roteiro') or '-'}\nOperação: {row.get('operacao')}\nQuantidade: {row.get('quantidade')}\nStatus: {row.get('status')}\nHTTP: {row.get('http_status') or '-'}\n\nMensagem:\n{row.get('mensagem') or '-'}"
        self.popup('DETALHES',txt,NAVY)

    def popup(self,title,message,title_color):
        box=BoxLayout(orientation='vertical',padding=dp(16),spacing=dp(10)); box.add_widget(mk_label(title,title_color,22,True,'center',dp(48)))
        scroll=ScrollView(); msg=Label(text=message,color=BLACK,font_size=14,halign='left',valign='top',size_hint_y=None)
        msg.bind(width=lambda inst,*_: setattr(inst,'text_size',(inst.width,None))); msg.bind(texture_size=lambda inst,size:setattr(inst,'height',max(size[1]+dp(20),dp(120)))); scroll.add_widget(msg); box.add_widget(scroll)
        close=mk_button('FECHAR',NAVY,dp(48)); box.add_widget(close); modal=ModalView(size_hint=(0.90,0.72),background_color=WHITE,auto_dismiss=False); modal.add_widget(box); close.bind(on_release=lambda *_:modal.dismiss()); modal.open()

    @staticmethod
    def rgb_hex(color):
        r,g,b,_=color; return f'{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}'

if __name__=='__main__':
    ApontamentoRoteiroApp().run()
