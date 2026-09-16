# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict

import requests
from requests.auth import HTTPBasicAuth

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, RoundedRectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput

NAVY = (0.025, 0.14, 0.27, 1)
NAVY_2 = (0.04, 0.22, 0.40, 1)
BG = (0.94, 0.96, 0.98, 1)
CARD = (1, 1, 1, 1)
TEXT = (0.08, 0.11, 0.15, 1)
MUTED = (0.38, 0.43, 0.49, 1)
GREEN = (0.08, 0.56, 0.29, 1)
RED = (0.82, 0.13, 0.16, 1)
AMBER = (0.93, 0.56, 0.08, 1)
WHITE = (1, 1, 1, 1)
APP_DIR = Path(__file__).resolve().parent


def load_simple_env(path: Path) -> Dict[str, str]:
    out = {}
    if not path.exists():
        return out
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception:
        return out
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            out[key] = value
    return out


ENV = load_simple_env(APP_DIR / "teste.env")


def env(name, default=""):
    return os.getenv(name, ENV.get(name, default)).strip()


TOTVS_API_BASE = env(
    "TOTVS_API_BASE",
    "http://192.168.2.15:8195/rest/apontmod2",
).rstrip("/")
TOTVS_USERNAME = env("TOTVS_USERNAME")
TOTVS_PASSWORD = env("TOTVS_PASSWORD")
TOTVS_TENANT_ID = env("TOTVS_TENANT_ID")
TOTVS_TIMEOUT = int(env("TOTVS_TIMEOUT", "100") or "100")

# Opcional. O APK não consulta roteiro.
# Se ficar vazio, o campo roteiro não é enviado no POST.
TOTVS_ROTEIRO_PADRAO = env("TOTVS_ROTEIRO_PADRAO", "")


def s(value):
    return "" if value is None else str(value).strip()


def now_text():
    return datetime.now().strftime("%d/%m/%Y %H:%M:%S")


def normalizar_op(value):
    return re.sub(r"\s+", "", s(value))


def parse_operacao(value):
    if not s(value):
        raise ValueError("Informe a operação.")
    operacao = int(float(s(value)))
    if operacao <= 0:
        raise ValueError("A operação deve ser maior que zero.")
    return operacao


def parse_quantidade(value):
    txt = s(value).replace(",", ".")
    if not txt:
        raise ValueError("Informe a quantidade.")
    quantidade = float(txt)
    if quantidade <= 0:
        raise ValueError("A quantidade deve ser maior que zero.")
    return int(quantidade) if quantidade.is_integer() else quantidade


def api_headers():
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if TOTVS_TENANT_ID:
        headers["tenantId"] = TOTVS_TENANT_ID
    return headers


def auth():
    return HTTPBasicAuth(TOTVS_USERNAME, TOTVS_PASSWORD)


def response_body(resp):
    try:
        return resp.json()
    except Exception:
        return (resp.text or "").strip()


def texto_response(body):
    if isinstance(body, dict):
        for key in ("note", "message", "mensagem", "error", "detail", "details"):
            if body.get(key):
                return s(body.get(key))
        return json.dumps(body, ensure_ascii=False, default=str)
    if isinstance(body, list):
        return json.dumps(body, ensure_ascii=False, default=str)
    return s(body)


def interpretar_post(resp):
    body = response_body(resp)
    msg = texto_response(body)
    upper = msg.upper()
    business_error = False
    if isinstance(body, dict):
        business_error = bool(body.get("error") or body.get("errorId"))
    frases = (
        "OPERACAO NAO CADASTRADA",
        "OPERAÇÃO NÃO CADASTRADA",
        "OP NAO EXISTE",
        "OP NÃO EXISTE",
        "NAO EXISTE QUANTIDADE SUFICIENTE",
        "NÃO EXISTE QUANTIDADE SUFICIENTE",
    )
    if any(frase in upper for frase in frases):
        business_error = True
    ok = 200 <= resp.status_code < 300 and not business_error
    return ok, (msg or f"HTTP {resp.status_code}"), body


# ==========================================================
# API: SOMENTE POST /new
# Não existe GET/consulta de roteiro antes do apontamento.
# ==========================================================
def apontar_totvs(op, operacao, quantidade):
    if not TOTVS_USERNAME or not TOTVS_PASSWORD:
        return {
            "status": "ERRO",
            "http_status": None,
            "mensagem": "Credenciais TOTVS não configuradas no APK.",
            "payload": {},
            "body": None,
        }

    payload = {
        "op": op,
        "operac": int(operacao),
        "quant": quantidade,
        "lote": "",
    }
    if TOTVS_ROTEIRO_PADRAO:
        payload["roteiro"] = TOTVS_ROTEIRO_PADRAO

    url = f"{TOTVS_API_BASE}/new"
    try:
        resp = requests.post(
            url,
            json=payload,
            headers=api_headers(),
            auth=auth(),
            timeout=TOTVS_TIMEOUT,
        )
        ok, msg, body = interpretar_post(resp)
        return {
            "status": "APONTADO" if ok else "ERRO",
            "http_status": resp.status_code,
            "mensagem": msg,
            "payload": payload,
            "body": body,
            "url": url,
        }
    except requests.exceptions.Timeout:
        return {
            "status": "VERIFICAR",
            "http_status": None,
            "mensagem": (
                "A API não respondeu dentro do tempo limite. "
                "O POST pode ter chegado ao TOTVS. Confira antes de reapontar."
            ),
            "payload": payload,
            "body": None,
            "url": url,
        }
    except requests.exceptions.ConnectionError as exc:
        return {
            "status": "ERRO",
            "http_status": None,
            "mensagem": "Falha de conexão com a API TOTVS: " + s(exc),
            "payload": payload,
            "body": None,
            "url": url,
        }
    except Exception as exc:
        return {
            "status": "ERRO",
            "http_status": None,
            "mensagem": s(exc),
            "payload": payload,
            "body": None,
            "url": url,
        }


class HistoricoDB:
    def __init__(self, path):
        self.path = path
        self.init()

    def con(self):
        return sqlite3.connect(self.path, timeout=10)

    def init(self):
        with self.con() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS historico (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    data_hora TEXT NOT NULL,
                    op TEXT NOT NULL,
                    roteiro TEXT,
                    operacao INTEGER NOT NULL,
                    quantidade REAL NOT NULL,
                    status TEXT NOT NULL,
                    http_status INTEGER,
                    mensagem TEXT,
                    payload_json TEXT,
                    resposta_json TEXT,
                    tentativa_de INTEGER
                )
                """
            )
            conn.commit()

    def incluir(self, op, operacao, quantidade, result, tentativa_de=None):
        payload = result.get("payload") or {}
        roteiro = s(payload.get("roteiro")) if isinstance(payload, dict) else ""
        with self.con() as conn:
            cur = conn.execute(
                """
                INSERT INTO historico(
                    data_hora, op, roteiro, operacao, quantidade,
                    status, http_status, mensagem,
                    payload_json, resposta_json, tentativa_de
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    now_text(),
                    op,
                    roteiro,
                    int(operacao),
                    float(quantidade),
                    result.get("status", "ERRO"),
                    result.get("http_status"),
                    result.get("mensagem", ""),
                    json.dumps(result.get("payload"), ensure_ascii=False, default=str),
                    json.dumps(result.get("body"), ensure_ascii=False, default=str),
                    tentativa_de,
                ),
            )
            conn.commit()
            return int(cur.lastrowid)

    def listar(self, limit=40):
        with self.con() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM historico ORDER BY id DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
            return [dict(row) for row in rows]


class Card(BoxLayout):
    def __init__(self, bg=CARD, radius=14, **kwargs):
        super().__init__(**kwargs)
        with self.canvas.before:
            Color(*bg)
            self._bg_rect = RoundedRectangle(
                pos=self.pos,
                size=self.size,
                radius=[dp(radius)],
            )
        self.bind(pos=self._sync_bg, size=self._sync_bg)

    def _sync_bg(self, *_):
        self._bg_rect.pos = self.pos
        self._bg_rect.size = self.size


def mk_label(text="", color=TEXT, size=16, bold=False, halign="left", height=dp(36)):
    label = Label(
        text=text,
        color=color,
        font_size=size,
        bold=bold,
        halign=halign,
        valign="middle",
        size_hint_y=None,
        height=height,
    )
    label.bind(width=lambda inst, *_: setattr(inst, "text_size", (inst.width, None)))
    return label


def mk_button(text, bg=NAVY, height=dp(58), font_size=17, width=None):
    kwargs = {
        "text": text,
        "size_hint_y": None,
        "height": height,
        "background_normal": "",
        "background_down": "",
        "background_color": bg,
        "color": WHITE,
        "bold": True,
        "font_size": font_size,
    }
    if width is not None:
        kwargs["size_hint_x"] = None
        kwargs["width"] = width
    return Button(**kwargs)


def mk_input(hint, input_filter=None):
    return TextInput(
        hint_text=hint,
        multiline=False,
        size_hint_y=None,
        height=dp(62),
        font_size=21,
        foreground_color=TEXT,
        background_color=(0.975, 0.982, 0.99, 1),
        cursor_color=NAVY,
        padding=[dp(14), dp(16)],
        input_filter=input_filter,
    )


def status_color(status):
    status = s(status).upper()
    if status == "APONTADO":
        return GREEN
    if status == "VERIFICAR":
        return AMBER
    return RED


class ApontamentoRoteiroApp(App):
    title = "Apontamento por Operação TESTE"

    def build(self):
        Window.clearcolor = BG
        try:
            Window.softinput_mode = "below_target"
        except Exception:
            pass

        Path(self.user_data_dir).mkdir(parents=True, exist_ok=True)
        self.db = HistoricoDB(str(Path(self.user_data_dir) / "historico_roteiro.db"))
        self.current_retry_id = None

        root = BoxLayout(orientation="vertical", padding=0, spacing=0)

        header = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(72),
            padding=[dp(22), dp(8)],
        )
        with header.canvas.before:
            Color(*NAVY)
            header._bg = RoundedRectangle(pos=header.pos, size=header.size, radius=[0])
        header.bind(
            pos=lambda inst, *_: setattr(inst._bg, "pos", inst.pos),
            size=lambda inst, *_: setattr(inst._bg, "size", inst.size),
        )

        title_box = BoxLayout(orientation="vertical", spacing=0)
        title_box.add_widget(
            mk_label("APONTAMENTO POR OPERAÇÃO", WHITE, 26, True, "left", dp(38))
        )
        title_box.add_widget(
            mk_label(
                "AMBIENTE DE TESTE • envio direto ao TOTVS",
                (0.78, 0.86, 0.94, 1),
                13,
                False,
                "left",
                dp(22),
            )
        )
        header.add_widget(title_box)
        header.add_widget(
            Label(
                text="TESTE",
                color=WHITE,
                bold=True,
                font_size=15,
                size_hint=(None, None),
                size=(dp(100), dp(38)),
            )
        )
        root.add_widget(header)

        content = BoxLayout(
            orientation="horizontal",
            padding=dp(16),
            spacing=dp(16),
        )

        left = Card(
            orientation="vertical",
            padding=dp(18),
            spacing=dp(8),
            size_hint_x=0.43,
        )
        left.add_widget(mk_label("NOVO APONTAMENTO", NAVY, 21, True, "left", dp(38)))
        left.add_widget(
            mk_label(
                "Preencha os três campos e envie. Não existe consulta prévia.",
                MUTED,
                13,
                False,
                "left",
                dp(34),
            )
        )

        left.add_widget(mk_label("OP", NAVY_2, 15, True, "left", dp(27)))
        self.op_input = mk_input("Ex.: X0222601020")
        left.add_widget(self.op_input)

        left.add_widget(mk_label("OPERAÇÃO", NAVY_2, 15, True, "left", dp(27)))
        self.oper_input = mk_input("Ex.: 20", "int")
        left.add_widget(self.oper_input)

        left.add_widget(mk_label("QUANTIDADE", NAVY_2, 15, True, "left", dp(27)))
        self.quant_input = mk_input("Ex.: 20")
        left.add_widget(self.quant_input)

        left.add_widget(BoxLayout(size_hint_y=None, height=dp(4)))
        self.apontar_btn = mk_button("APONTAR AGORA", NAVY, dp(66), 19)
        self.apontar_btn.bind(on_release=self.on_apontar)
        left.add_widget(self.apontar_btn)

        self.status_card = Card(
            orientation="vertical",
            padding=[dp(14), dp(6)],
            size_hint_y=None,
            height=dp(62),
            bg=(0.965, 0.975, 0.985, 1),
            radius=10,
        )
        self.status_label = mk_label(
            "PRONTO PARA APONTAR", MUTED, 14, True, "center", dp(48)
        )
        self.status_card.add_widget(self.status_label)
        left.add_widget(self.status_card)
        content.add_widget(left)

        right = Card(
            orientation="vertical",
            padding=dp(16),
            spacing=dp(8),
            size_hint_x=0.57,
        )
        history_header = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(46),
            spacing=dp(10),
        )
        history_header.add_widget(
            mk_label("ÚLTIMOS APONTAMENTOS", NAVY, 21, True, "left", dp(46))
        )
        refresh_btn = mk_button("ATUALIZAR", NAVY_2, dp(40), 13, dp(116))
        refresh_btn.bind(on_release=lambda *_: self.refresh_history())
        history_header.add_widget(refresh_btn)
        right.add_widget(history_header)

        self.history_scroll = ScrollView(do_scroll_x=False, bar_width=dp(7))
        self.history_box = BoxLayout(
            orientation="vertical",
            spacing=dp(8),
            size_hint_y=None,
            padding=[0, dp(2), dp(4), dp(8)],
        )
        self.history_box.bind(minimum_height=self.history_box.setter("height"))
        self.history_scroll.add_widget(self.history_box)
        right.add_widget(self.history_scroll)
        content.add_widget(right)
        root.add_widget(content)

        self.op_input.bind(
            on_text_validate=lambda *_: setattr(self.oper_input, "focus", True)
        )
        self.oper_input.bind(
            on_text_validate=lambda *_: setattr(self.quant_input, "focus", True)
        )
        self.quant_input.bind(on_text_validate=self.on_apontar)

        Clock.schedule_once(lambda *_: setattr(self.op_input, "focus", True), 0.5)
        Clock.schedule_once(lambda *_: self.refresh_history(), 0.2)
        return root

    def on_apontar(self, *_):
        if self.apontar_btn.disabled:
            return
        try:
            op = normalizar_op(self.op_input.text)
            if not op:
                raise ValueError("Informe a OP.")
            operacao = parse_operacao(self.oper_input.text)
            quantidade = parse_quantidade(self.quant_input.text)
        except Exception as exc:
            self.popup("VALIDAÇÃO", s(exc), RED)
            return

        self.set_busy(True, "ENVIANDO AO TOTVS...")
        threading.Thread(
            target=self.worker,
            args=(op, operacao, quantidade, self.current_retry_id),
            daemon=True,
        ).start()

    def worker(self, op, operacao, quantidade, tentativa_de):
        result = apontar_totvs(op, operacao, quantidade)
        try:
            self.db.incluir(op, operacao, quantidade, result, tentativa_de)
        except Exception as exc:
            result = dict(result)
            result["mensagem"] = (
                result.get("mensagem", "")
                + f"\nFalha ao salvar histórico local: {exc}"
            )
        Clock.schedule_once(lambda _dt, res=result: self.finish(res), 0)

    def finish(self, result):
        self.set_busy(False)
        status = s(result.get("status", "ERRO")).upper()
        msg = result.get("mensagem", "")
        color = status_color(status)

        if status == "APONTADO":
            self.status_label.text = "APONTAMENTO REALIZADO"
            self.current_retry_id = None
        elif status == "VERIFICAR":
            self.status_label.text = "VERIFICAR NO TOTVS"
        else:
            self.status_label.text = "APONTAMENTO NÃO REALIZADO"

        self.status_label.color = color
        self.refresh_history()
        http = result.get("http_status")
        self.popup(
            status,
            f"{msg}\n\nHTTP: {http if http is not None else '-'}",
            color,
        )

        if status == "APONTADO":
            self.op_input.text = ""
            self.oper_input.text = ""
            self.quant_input.text = ""
            Clock.schedule_once(lambda *_: setattr(self.op_input, "focus", True), 0.2)

    def set_busy(self, busy, text=None):
        self.apontar_btn.disabled = bool(busy)
        self.apontar_btn.text = "ENVIANDO..." if busy else "APONTAR AGORA"
        if text:
            self.status_label.text = text
            self.status_label.color = NAVY_2

    def refresh_history(self):
        self.history_box.clear_widgets()
        rows = self.db.listar(40)
        if not rows:
            empty = Card(
                orientation="vertical",
                padding=dp(16),
                size_hint_y=None,
                height=dp(88),
                bg=(0.97, 0.98, 0.99, 1),
                radius=10,
            )
            empty.add_widget(
                mk_label(
                    "Nenhum apontamento realizado neste tablet.",
                    MUTED,
                    14,
                    False,
                    "center",
                    dp(58),
                )
            )
            self.history_box.add_widget(empty)
            return

        for row in rows:
            self.history_box.add_widget(self.make_history_item(row))

    def make_history_item(self, row):
        status = s(row.get("status")).upper()
        color = status_color(status)
        item = Card(
            orientation="horizontal",
            padding=[dp(12), dp(8)],
            spacing=dp(10),
            size_hint_y=None,
            height=dp(88),
            bg=(0.975, 0.982, 0.99, 1),
            radius=10,
        )

        info = BoxLayout(orientation="vertical", spacing=0)
        info.add_widget(
            mk_label(
                f"{row.get('op', '')}   •   OP {row.get('operacao', '')}",
                TEXT,
                17,
                True,
                "left",
                dp(30),
            )
        )
        qtd = row.get("quantidade", "")
        qtd_txt = f"{qtd:g}" if isinstance(qtd, (int, float)) else s(qtd)
        info.add_widget(mk_label(f"Qtd. {qtd_txt}", MUTED, 13, False, "left", dp(23)))
        info.add_widget(
            mk_label(s(row.get("data_hora")), MUTED, 12, False, "left", dp(22))
        )
        item.add_widget(info)

        actions = BoxLayout(
            orientation="vertical",
            spacing=dp(5),
            size_hint_x=None,
            width=dp(150),
        )
        status_btn = mk_button(status, color, dp(35), 12, dp(150))
        status_btn.bind(on_release=lambda *_args, r=row: self.show_details(r))
        actions.add_widget(status_btn)

        if status in ("ERRO", "VERIFICAR"):
            retry_btn = mk_button("REAPONTAR", NAVY_2, dp(35), 12, dp(150))
            retry_btn.bind(on_release=lambda *_args, r=row: self.retry_row(r))
            actions.add_widget(retry_btn)
        else:
            detail_btn = mk_button("DETALHES", NAVY_2, dp(35), 12, dp(150))
            detail_btn.bind(on_release=lambda *_args, r=row: self.show_details(r))
            actions.add_widget(detail_btn)

        item.add_widget(actions)
        return item

    def retry_row(self, row):
        status = s(row.get("status")).upper()

        def preencher_e_focar():
            self.op_input.text = s(row.get("op"))
            self.oper_input.text = s(row.get("operacao"))
            qtd = row.get("quantidade")
            if isinstance(qtd, float) and qtd.is_integer():
                qtd = int(qtd)
            self.quant_input.text = s(qtd)
            self.current_retry_id = row.get("id")
            self.status_label.text = f"REAPONTAMENTO DO REGISTRO #{row.get('id')}"
            self.status_label.color = NAVY_2
            self.quant_input.focus = True

        if status == "VERIFICAR":
            self.confirmar_reapontamento(preencher_e_focar)
        else:
            preencher_e_focar()

    def confirmar_reapontamento(self, callback):
        modal = ModalView(
            size_hint=(0.72, 0.62),
            auto_dismiss=False,
            background_color=(0, 0, 0, 0.5),
        )
        card = Card(
            orientation="vertical",
            padding=dp(22),
            spacing=dp(12),
            bg=CARD,
            radius=16,
        )
        card.add_widget(
            mk_label("CONFIRMAR REAPONTAMENTO", AMBER, 23, True, "center", dp(48))
        )
        card.add_widget(
            mk_label(
                "O apontamento anterior terminou com status VERIFICAR.\n"
                "O POST pode ter chegado ao TOTVS mesmo sem resposta.\n\n"
                "Confirme no TOTVS antes de enviar novamente.",
                TEXT,
                16,
                False,
                "center",
                dp(118),
            )
        )
        buttons = BoxLayout(
            orientation="horizontal",
            spacing=dp(12),
            size_hint_y=None,
            height=dp(58),
        )
        cancel = mk_button("CANCELAR", MUTED, dp(58), 16)
        confirm = mk_button("REAPONTAR MESMO ASSIM", AMBER, dp(58), 15)
        cancel.bind(on_release=lambda *_: modal.dismiss())

        def confirmar(*_):
            modal.dismiss()
            callback()

        confirm.bind(on_release=confirmar)
        buttons.add_widget(cancel)
        buttons.add_widget(confirm)
        card.add_widget(buttons)
        modal.add_widget(card)
        modal.open()

    def show_details(self, row):
        text = (
            f"ID: {row.get('id')}\n"
            f"Data: {row.get('data_hora')}\n"
            f"OP: {row.get('op')}\n"
            f"Operação: {row.get('operacao')}\n"
            f"Quantidade: {row.get('quantidade')}\n"
            f"Status: {row.get('status')}\n"
            f"HTTP: {row.get('http_status') or '-'}\n\n"
            f"Mensagem:\n{s(row.get('mensagem')) or '-'}\n\n"
            f"Payload:\n{s(row.get('payload_json')) or '-'}\n\n"
            f"Resposta:\n{s(row.get('resposta_json')) or '-'}"
        )
        self.popup("DETALHES DO APONTAMENTO", text, NAVY_2, large=True)

    def popup(self, title, message, color=NAVY, large=False):
        modal = ModalView(
            size_hint=(0.82, 0.82 if large else 0.58),
            auto_dismiss=False,
            background_color=(0, 0, 0, 0.5),
        )
        card = Card(
            orientation="vertical",
            padding=dp(22),
            spacing=dp(10),
            bg=CARD,
            radius=16,
        )
        card.add_widget(mk_label(title, color, 24, True, "center", dp(52)))

        if large:
            scroll = ScrollView(do_scroll_x=False)
            body = Label(
                text=message,
                color=TEXT,
                font_size=15,
                halign="left",
                valign="top",
                size_hint_y=None,
                markup=False,
            )
            body.bind(
                width=lambda inst, *_: setattr(inst, "text_size", (inst.width, None))
            )
            body.bind(
                texture_size=lambda inst, value: setattr(inst, "height", value[1] + dp(20))
            )
            scroll.add_widget(body)
            card.add_widget(scroll)
        else:
            card.add_widget(mk_label(message, TEXT, 16, False, "center", dp(150)))

        close = mk_button("FECHAR", NAVY, dp(58), 16)
        close.bind(on_release=lambda *_: modal.dismiss())
        card.add_widget(close)
        modal.add_widget(card)
        modal.open()


if __name__ == "__main__":
    ApontamentoRoteiroApp().run()
