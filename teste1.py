import streamlit as st
import pandas as pd
import datetime
import pytz
import os
from supabase import create_client
from dotenv import load_dotenv
from pathlib import Path
import streamlit.components.v1 as components

# ==============================
# CONFIGURAÇÃO GERAL
# ==============================
env_path = Path(__file__).parent / "teste.env"  # Ajuste se necessário
load_dotenv(dotenv_path=env_path)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
TZ = pytz.timezone("America/Sao_Paulo")

st.set_page_config(page_title="Apontamento MOLA", layout="wide")

# ==============================
# CSS VISUAL DARK
# ==============================
st.markdown("""
    <style>
        .block-container {padding-top: 1rem; padding-bottom: 0rem;}
        header, footer {visibility: hidden;}
        [data-testid="stSidebar"] {background-color: #111827;}
        body {background-color: #0f172a; color: white;}
        h1, h2, h3, h4 {color: white !important;}
        .stTextInput>div>div>input {
            background-color: #1e293b !important;
            color: white !important;
            border-radius: 10px;
            height: 60px;
            font-size: 18px;
            text-align: center;
            border: 2px solid #334155;
        }
        .contador-box {
            background-color: #1e293b;
            border-radius: 12px;
            padding: 10px 20px;
            text-align: center;
            font-size: 22px;
            color: #10b981;
            margin-bottom: 10px;
        }
        .status-box {
            background-color: #1e293b;
            border-radius: 10px;
            padding: 10px 20px;
            font-size: 18px;
        }
    </style>
""", unsafe_allow_html=True)


# ==============================
# FUNÇÕES SUPABASE
# ==============================
def salvar_apontamento_mola(numero_serie: str, op: str, usuario: str):
    if not numero_serie or not op:
        return False, "Número de série e OP obrigatórios."

    check = supabase.table("apontamentos_mola")\
        .select("*")\
        .eq("numero_serie", numero_serie)\
        .eq("op", op)\
        .execute()
    if check.data:
        return False, f"Série {numero_serie} já apontada na OP {op}."

    data_hora = datetime.datetime.now(datetime.timezone.utc).isoformat()

    try:
        supabase.table("apontamentos_mola").insert({
            "numero_serie": numero_serie,
            "op": op,
            "usuario": usuario,
            "data_hora": data_hora
        }).execute()
        st.cache_data.clear()
        return True, None
    except Exception as e:
        return False, str(e)


@st.cache_data(ttl=10)
def carregar_apontamentos():
    try:
        data = supabase.table("apontamentos_mola")\
            .select("*")\
            .order("data_hora", desc=True)\
            .limit(100)\
            .execute()
        df = pd.DataFrame(data.data)
        if not df.empty:
            df["data_hora"] = pd.to_datetime(df["data_hora"], errors="coerce", utc=True)
            df["data_hora"] = df["data_hora"].dt.tz_convert(TZ)
        return df
    except Exception:
        return pd.DataFrame()


def contar_apontamentos_hoje():
    df = carregar_apontamentos()
    if df.empty:
        return 0
    hoje = datetime.datetime.now(TZ).date()
    df["data"] = df["data_hora"].dt.date
    return (df["data"] == hoje).sum()


# ==============================
# CALLBACK DO LEITOR
# ==============================
def processar_leitura():
    leitura = st.session_state.get("input_leitor", "").strip()
    if not leitura:
        return

    # Se for número de série
    if len(leitura) == 9:
        st.session_state["numero_serie"] = leitura
        st.session_state["mensagem_erro"] = None

    # Se for OP
    elif len(leitura) == 11:
        if not st.session_state.get("numero_serie"):
            st.session_state["mensagem_erro"] = "⚠️ Leia primeiro o número de série antes da OP!"
        else:
            st.session_state["op"] = leitura
            sucesso, erro = salvar_apontamento_mola(
                st.session_state.get("numero_serie", ""),
                st.session_state.get("op", ""),
                st.session_state.get("usuario", "Operador_Logado")
            )
            if sucesso:
                st.session_state["sucesso_flag"] = True
                st.session_state["mensagem_erro"] = None
                # Zera os campos após salvar
                st.session_state["numero_serie"] = ""
                st.session_state["op"] = ""
            else:
                st.session_state["mensagem_erro"] = erro

    st.session_state["input_leitor"] = ""


# ==============================
# PÁGINA PRINCIPAL
# ==============================
def pagina_apontamento_mola():
    st.title("🧩 Apontamento Automático - MOLA")

    qtd_hoje = contar_apontamentos_hoje()
    st.markdown(f"<div class='contador-box'>📅 Apontamentos de Hoje: <b>{qtd_hoje}</b></div>",
                unsafe_allow_html=True)

    st.text_input(
        "Leitor Automático",
        key="input_leitor",
        placeholder="aproxime o leitor de código de barras...",
        label_visibility="collapsed",
        on_change=processar_leitura
    )

    # Mantém foco automático no campo do leitor
    components.html("""
        <script>
        function focarInput(){
            const input = window.parent.document.querySelector('input[id^="input_leitor"]');
            if(input){ input.focus(); }
        }
        focarInput();
        new MutationObserver(focarInput).observe(
            window.parent.document.body,
            {childList: true, subtree: true}
        );
        </script>
    """, height=0)

    col1, col2 = st.columns([3, 1])
    with col1:
        st.markdown(
            f"<div class='status-box'>📦 Série: <b>{st.session_state.get('numero_serie', '-')}</b></div>",
            unsafe_allow_html=True
        )
        st.markdown(
            f"<div class='status-box'>🧾 OP: <b>{st.session_state.get('op', '-')}</b></div>",
            unsafe_allow_html=True
        )
    with col2:
        st.markdown(
            f"<div class='status-box' style='text-align:center;'>👤 Usuário:<br><b>{st.session_state.get('usuario', 'Operador_Logado')}</b></div>",
            unsafe_allow_html=True
        )

    if st.session_state.get("mensagem_erro"):
        st.warning(st.session_state["mensagem_erro"])
        st.session_state["mensagem_erro"] = None

    st.markdown("---")
    st.subheader("🕒 Últimos 10 Apontamentos")

    df = carregar_apontamentos()
    if not df.empty:
        ultimos = df.sort_values("data_hora", ascending=False).head(10)
        ultimos["data_hora_fmt"] = ultimos["data_hora"].dt.strftime("%d/%m %H:%M:%S")
        st.dataframe(
            ultimos[["numero_serie", "op", "usuario", "data_hora_fmt"]],
            hide_index=True, use_container_width=True
        )

        hoje = datetime.datetime.now(TZ).date()
        df["data"] = df["data_hora"].dt.date
        df_hoje = df[df["data"] == hoje]
        if not df_hoje.empty:
            resumo = (
                df_hoje.groupby("op").size().reset_index(name="Quantidade")
                .sort_values("Quantidade", ascending=False)
            )
            st.markdown("### 📦 Quantidade por OP (Hoje)")
            st.dataframe(resumo, hide_index=True, use_container_width=True)
        else:
            st.info("Nenhum apontamento registrado hoje.")
    else:
        st.info("Nenhum apontamento registrado ainda.")


# ==============================
# APP PRINCIPAL
# ==============================
def app():
    if "usuario" not in st.session_state:
        st.session_state["usuario"] = "Operador_Logado"
    if "numero_serie" not in st.session_state:
        st.session_state["numero_serie"] = ""
    if "op" not in st.session_state:
        st.session_state["op"] = ""
    if "mensagem_erro" not in st.session_state:
        st.session_state["mensagem_erro"] = None
    if "sucesso_flag" not in st.session_state:
        st.session_state["sucesso_flag"] = False

    st.sidebar.title("Menu")
    menu = st.sidebar.radio("Navegação", ["Apontamento MOLA", "Dashboard", "Relatórios"])

    if menu == "Apontamento MOLA":
        pagina_apontamento_mola()
    elif menu == "Dashboard":
        st.title("📊 Dashboard de Produção")
        st.info("Em desenvolvimento...")
    elif menu == "Relatórios":
        st.title("📜 Relatórios")
        st.info("Em desenvolvimento...")


# ==============================
# EXECUÇÃO
# ==============================
if __name__ == "__main__":
    app()
