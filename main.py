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
from kivy.graphics import Color, Line, RoundedRectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.utils import platform

NAVY = (0.015, 0.075, 0.15, 1)
NAVY_2 = (0.025, 0.145, 0.29, 1)
NAVY_3 = (0.035, 0.22, 0.41, 1)
BLUE = (0.00, 0.38, 0.72, 1)
BLUE_SOFT = (0.90, 0.95, 0.99, 1)
BG = (0.93, 0.955, 0.98, 1)
CARD = (1, 1, 1, 1)
TEXT = (0.06, 0.10, 0.15, 1)
MUTED = (0.39, 0.46, 0.54, 1)
BORDER = (0.79, 0.85, 0.92, 1)
GREEN = (0.06, 0.56, 0.29, 1)
RED = (0.82, 0.12, 0.16, 1)
AMBER = (0.93, 0.57, 0.07, 1)
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


def force_android_keyboard():
    if platform != "android":
        return
    try:
        from jnius import autoclass

        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        Context = autoclass("android.content.Context")
        InputMethodManager = autoclass("android.view.inputmethod.InputMethodManager")

        activity = PythonActivity.mActivity
        imm = activity.getSystemService(Context.INPUT_METHOD_SERVICE)
        view = activity.getCurrentFocus()
        if view is None:
            view = activity.getWindow().getDecorView()
        try:
            view.requestFocus()
        except Exception:
            pass
        imm.showSoftInput(view, InputMethodManager.SHOW_FORCED)
        imm.toggleSoftInput(InputMethodManager.SHOW_FORCED, 0)
    except Exception:
        pass


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
                "Confira no TOTVS antes de tentar novamente."
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
            conn.execute(
                "DELETE FROM historico WHERE UPPER(COALESCE(status, '')) <> 'APONTADO'"
            )
            conn.commit()

    def incluir_sucesso(self, op, operacao, quantidade, result):
        if s(result.get("status")).upper() != "APONTADO":
            return None
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
                    "",
                    int(operacao),
                    float(quantidade),
                    "APONTADO",
                    result.get("http_status"),
                    result.get("mensagem", ""),
                    json.dumps(result.get("payload"), ensure_ascii=False, default=str),
                    json.dumps(result.get("body"), ensure_ascii=False, default=str),
                    None,
                ),
            )
            conn.commit()
            return int(cur.lastrowid)

    def listar(self, limit=40):
        with self.con() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT * FROM historico
                WHERE UPPER(COALESCE(status, '')) = 'APONTADO'
                ORDER BY id DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
            return [dict(row) for row in rows]


class Surface(BoxLayout):
    def __init__(self, bg=BG, **kwargs):
        super().__init__(**kwargs)
        with self.canvas.before:
            Color(*bg)
            self._rect = RoundedRectangle(pos=self.pos, size=self.size, radius=[0])
        self.bind(pos=self._sync, size=self._sync)

    def _sync(self, *_):
        self._rect.pos = self.pos
        self._rect.size = self.size


class Card(BoxLayout):
    def __init__(self, bg=CARD, radius=16, border=BORDER, border_width=1, **kwargs):
        super().__init__(**kwargs)
        self._radius = radius
        with self.canvas.before:
            Color(*bg)
            self._bg_rect = RoundedRectangle(
                pos=self.pos,
                size=self.size,
                radius=[dp(radius)],
            )
            Color(*border)
            self._border = Line(
                rounded_rectangle=(self.x, self.y, self.width, self.height, dp(radius)),
                width=border_width,
            )
        self.bind(pos=self._sync_bg, size=self._sync_bg)

    def _sync_bg(self, *_):
        self._bg_rect.pos = self.pos
        self._bg_rect.size = self.size
        self._border.rounded_rectangle = (
            self.x,
            self.y,
            self.width,
            self.height,
            dp(self._radius),
        )


class IberoTextInput(TextInput):
    def on_touch_down(self, touch):
        result = super().on_touch_down(touch)
        if self.collide_point(*touch.pos):
            Clock.schedule_once(lambda *_: force_android_keyboard(), 0.12)
            Clock.schedule_once(lambda *_: force_android_keyboard(), 0.42)
        return result


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


def mk_button(text, bg=NAVY_2, height=dp(58), font_size=17, width=None):
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


def mk_input(hint, input_filter=None, input_type="text"):
    return IberoTextInput(
        hint_text=hint,
        multiline=False,
        size_hint_y=None,
        height=dp(66),
        font_size=22,
        foreground_color=TEXT,
        hint_text_color=(0.48, 0.56, 0.64, 1),
        background_color=(0.955, 0.975, 0.995, 1),
        cursor_color=BLUE,
        padding=[dp(16), dp(17)],
        input_filter=input_filter,
        input_type=input_type,
        write_tab=False,
    )


class ApontamentoRoteiroApp(App):
    title = "IBERO • Apontamento por Operação TESTE"

    def build(self):
        Window.clearcolor = NAVY
        try:
            Window.softinput_mode = "below_target"
        except Exception:
            pass

        Path(self.user_data_dir).mkdir(parents=True, exist_ok=True)
        self.db = HistoricoDB(str(Path(self.user_data_dir) / "historico_roteiro.db"))

        root = BoxLayout(orientation="vertical", padding=0, spacing=0)

        header = Surface(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(88),
            padding=[dp(24), dp(10)],
            spacing=dp(12),
            bg=NAVY,
        )
        brand = BoxLayout(orientation="vertical", spacing=0)
        brand.add_widget(mk_label("IBERO", WHITE, 30, True, "left", dp(42)))
        brand.add_widget(
            mk_label(
                "MANUFATURA  •  APONTAMENTO POR OPERAÇÃO",
                (0.70, 0.83, 0.94, 1),
                14,
                True,
                "left",
                dp(25),
            )
        )
        header.add_widget(brand)

        badge = Card(
            orientation="vertical",
            size_hint=(None, None),
            size=(dp(126), dp(46)),
            padding=[dp(10), dp(5)],
            bg=NAVY_3,
            border=BLUE,
            radius=12,
        )
        badge.add_widget(mk_label("AMBIENTE TESTE", WHITE, 13, True, "center", dp(32)))
        header.add_widget(badge)
        root.add_widget(header)
        root.add_widget(Surface(size_hint_y=None, height=dp(5), bg=BLUE))

        content = Surface(
            orientation="horizontal",
            padding=dp(16),
            spacing=dp(16),
            bg=BG,
        )

        left = Card(
            orientation="vertical",
            padding=dp(18),
            spacing=dp(7),
            size_hint_x=0.43,
            bg=CARD,
            radius=18,
        )
        left.add_widget(mk_label("NOVO APONTAMENTO", NAVY, 23, True, "left", dp(40)))
        left.add_widget(
            mk_label(
                "Bipe a OP, informe operação e quantidade e envie ao TOTVS.",
                MUTED,
                13,
                False,
                "left",
                dp(32),
            )
        )

        flow = Card(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(40),
            padding=[dp(10), dp(3)],
            spacing=dp(8),
            bg=BLUE_SOFT,
            border=(0.75, 0.86, 0.95, 1),
            radius=10,
        )
        flow.add_widget(mk_label("1  OP", NAVY_2, 12, True, "center", dp(30)))
        flow.add_widget(mk_label("›", BLUE, 18, True, "center", dp(30)))
        flow.add_widget(mk_label("2  OPERAÇÃO", NAVY_2, 12, True, "center", dp(30)))
        flow.add_widget(mk_label("›", BLUE, 18, True, "center", dp(30)))
        flow.add_widget(mk_label("3  QUANTIDADE", NAVY_2, 12, True, "center", dp(30)))
        left.add_widget(flow)

        left.add_widget(mk_label("OP", NAVY_2, 14, True, "left", dp(25)))
        self.op_input = mk_input("Bipe ou digite a OP")
        left.add_widget(self.op_input)

        left.add_widget(mk_label("OPERAÇÃO", NAVY_2, 14, True, "left", dp(25)))
        self.oper_input = mk_input("Ex.: 10", "int", "number")
        left.add_widget(self.oper_input)

        left.add_widget(mk_label("QUANTIDADE", NAVY_2, 14, True, "left", dp(25)))
        self.quant_input = mk_input("Ex.: 54", None, "number")
        left.add_widget(self.quant_input)

        left.add_widget(BoxLayout(size_hint_y=None, height=dp(3)))
        self.apontar_btn = mk_button("APONTAR AGORA", NAVY_2, dp(68), 19)
        self.apontar_btn.bind(on_release=self.on_apontar)
        left.add_widget(self.apontar_btn)

        self.status_card = Card(
            orientation="vertical",
            padding=[dp(12), dp(4)],
            size_hint_y=None,
            height=dp(58),
            bg=BLUE_SOFT,
            border=(0.75, 0.86, 0.95, 1),
            radius=11,
        )
        self.status_label = mk_label(
            "PRONTO PARA APONTAR", NAVY_2, 14, True, "center", dp(46)
        )
        self.status_card.add_widget(self.status_label)
        left.add_widget(self.status_card)
        content.add_widget(left)

        right = Card(
            orientation="vertical",
            padding=dp(16),
            spacing=dp(8),
            size_hint_x=0.57,
            bg=CARD,
            radius=18,
        )
        history_header = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(52),
            spacing=dp(10),
        )
        titles = BoxLayout(orientation="vertical", spacing=0)
        titles.add_widget(mk_label("HISTÓRICO CONFIRMADO", NAVY, 21, True, "left", dp(30)))
        titles.add_widget(
            mk_label(
                "Somente apontamentos aceitos pelo TOTVS",
                MUTED,
                12,
                False,
                "left",
                dp(20),
            )
        )
        history_header.add_widget(titles)
        refresh_btn = mk_button("ATUALIZAR", NAVY_3, dp(40), 12, dp(110))
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

        self.op_input.bind(on_text_validate=lambda *_: self.focus_field(self.oper_input, True))
        self.oper_input.bind(on_text_validate=lambda *_: self.focus_field(self.quant_input, True))
        self.quant_input.bind(on_text_validate=self.on_apontar)

        Clock.schedule_once(lambda *_: setattr(self.op_input, "focus", True), 0.45)
        Clock.schedule_once(lambda *_: self.refresh_history(), 0.2)
        return root

    def focus_field(self, widget, show_keyboard=False):
        for field in (self.op_input, self.oper_input, self.quant_input):
            field.focus = False

        def aplicar(*_):
            widget.focus = True
            try:
                widget.cursor = (len(widget.text), 0)
            except Exception:
                pass
            if show_keyboard:
                Clock.schedule_once(lambda *_: force_android_keyboard(), 0.10)
                Clock.schedule_once(lambda *_: force_android_keyboard(), 0.38)
                Clock.schedule_once(lambda *_: force_android_keyboard(), 0.75)

        Clock.schedule_once(aplicar, 0.06)

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
            args=(op, operacao, quantidade),
            daemon=True,
        ).start()

    def worker(self, op, operacao, quantidade):
        result = apontar_totvs(op, operacao, quantidade)
        if s(result.get("status")).upper() == "APONTADO":
            try:
                self.db.incluir_sucesso(op, operacao, quantidade, result)
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
        http = result.get("http_status")

        if status == "APONTADO":
            self.status_label.text = "✓  APONTAMENTO REALIZADO"
            self.status_label.color = GREEN
            self.refresh_history()
            self.popup(
                "APONTADO",
                f"Apontamento realizado com sucesso.\n\n{msg}\n\nHTTP: {http if http is not None else '-'}",
                GREEN,
            )
            self.op_input.text = ""
            self.oper_input.text = ""
            self.quant_input.text = ""
            self.focus_field(self.op_input, False)
            return

        if status == "VERIFICAR":
            self.status_label.text = "!  VERIFICAR NO TOTVS"
            self.status_label.color = AMBER
            self.popup(
                "VERIFICAR",
                f"{msg}\n\nHTTP: {http if http is not None else '-'}",
                AMBER,
            )
        else:
            self.status_label.text = "✕  APONTAMENTO NÃO REALIZADO"
            self.status_label.color = RED
            self.popup(
                "ERRO",
                f"{msg}\n\nHTTP: {http if http is not None else '-'}",
                RED,
            )

        self.focus_field(self.op_input, True)

    def set_busy(self, busy, text=None):
        self.apontar_btn.disabled = bool(busy)
        self.apontar_btn.text = "ENVIANDO..." if busy else "APONTAR AGORA"
        if text:
            self.status_label.text = text
            self.status_label.color = BLUE

    def refresh_history(self):
        self.history_box.clear_widgets()
        rows = self.db.listar(40)
        if not rows:
            empty = Card(
                orientation="vertical",
                padding=dp(16),
                size_hint_y=None,
                height=dp(104),
                bg=(0.965, 0.98, 0.995, 1),
                border=(0.80, 0.88, 0.95, 1),
                radius=12,
            )
            empty.add_widget(
                mk_label(
                    "Nenhum apontamento confirmado neste tablet.",
                    MUTED,
                    14,
                    False,
                    "center",
                    dp(58),
                )
            )
            empty.add_widget(
                mk_label(
                    "Erros e tentativas não são gravados no histórico.",
                    NAVY_3,
                    12,
                    True,
                    "center",
                    dp(25),
                )
            )
            self.history_box.add_widget(empty)
            return

        for row in rows:
            self.history_box.add_widget(self.make_history_item(row))

    def make_history_item(self, row):
        item = Card(
            orientation="horizontal",
            padding=[0, dp(8), dp(10), dp(8)],
            spacing=dp(10),
            size_hint_y=None,
            height=dp(92),
            bg=(0.972, 0.985, 0.997, 1),
            border=(0.78, 0.87, 0.95, 1),
            radius=12,
        )

        item.add_widget(Surface(size_hint_x=None, width=dp(7), bg=BLUE))

        info = BoxLayout(orientation="vertical", spacing=0)
        info.add_widget(
            mk_label(
                f"{row.get('op', '')}   •   OPERAÇÃO {row.get('operacao', '')}",
                NAVY,
                17,
                True,
                "left",
                dp(31),
            )
        )
        qtd = row.get("quantidade", "")
        qtd_txt = f"{qtd:g}" if isinstance(qtd, (int, float)) else s(qtd)
        info.add_widget(
            mk_label(f"Quantidade apontada: {qtd_txt}", TEXT, 13, False, "left", dp(24))
        )
        info.add_widget(
            mk_label(s(row.get("data_hora")), MUTED, 12, False, "left", dp(22))
        )
        item.add_widget(info)

        actions = BoxLayout(
            orientation="vertical",
            spacing=dp(5),
            size_hint_x=None,
            width=dp(136),
            padding=[0, dp(4), 0, dp(4)],
        )
        ok_btn = mk_button("✓ APONTADO", GREEN, dp(34), 12, dp(136))
        ok_btn.bind(on_release=lambda *_args, r=row: self.show_details(r))
        actions.add_widget(ok_btn)
        detail_btn = mk_button("DETALHES", NAVY_3, dp(34), 12, dp(136))
        detail_btn.bind(on_release=lambda *_args, r=row: self.show_details(r))
        actions.add_widget(detail_btn)
        item.add_widget(actions)
        return item

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
        self.popup("DETALHES DO APONTAMENTO", text, NAVY_3, large=True)

    def popup(self, title, message, color=NAVY_2, large=False):
        modal = ModalView(
            size_hint=(0.80, 0.80 if large else 0.58),
            auto_dismiss=False,
            background_color=(0, 0, 0, 0.62),
        )
        card = Card(
            orientation="vertical",
            padding=dp(22),
            spacing=dp(10),
            bg=CARD,
            radius=18,
            border=(0.68, 0.78, 0.88, 1),
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
            body.bind(width=lambda inst, *_: setattr(inst, "text_size", (inst.width, None)))
            body.bind(
                texture_size=lambda inst, value: setattr(inst, "height", value[1] + dp(20))
            )
            scroll.add_widget(body)
            card.add_widget(scroll)
        else:
            card.add_widget(mk_label(message, TEXT, 16, False, "center", dp(150)))

        close = mk_button("FECHAR", NAVY_2, dp(58), 16)

        def fechar(*_):
            modal.dismiss()
            if self.op_input.focus or self.oper_input.focus or self.quant_input.focus:
                Clock.schedule_once(lambda *_: force_android_keyboard(), 0.18)

        close.bind(on_release=fechar)
        card.add_widget(close)
        modal.add_widget(card)
        modal.open()


if __name__ == "__main__":
    ApontamentoRoteiroApp().run()
