import streamlit as st
import pandas as pd
import datetime
import pytz
import os
from supabase import create_client
from dotenv import load_dotenv
from pathlib import Path
import streamlit.components.v1 as components
import time
import json

# ==============================
# CONFIGURAÇÃO GERAL
# ==============================
env_path = Path(__file__).parent / "teste.env"
load_dotenv(dotenv_path=env_path)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
TZ = pytz.timezone("America/Sao_Paulo")

st.set_page_config(page_title="Apontamento MOLA", layout="wide")


# ==============================
# FUNÇÕES SUPABASE - MOLA
# ==============================
def salvar_apontamento_mola(numero_serie: str, op: str, usuario: str):
    if not numero_serie or not op:
        return False, "Número de série e OP obrigatórios."

    check = supabase.table("apontamentos_mola") \
        .select("*") \
        .eq("numero_serie", numero_serie) \
        .eq("op", op) \
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
        data = supabase.table("apontamentos_mola") \
            .select("*") \
            .order("data_hora", desc=True) \
            .limit(100) \
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

def carregar_checklists():
    try:
        response = supabase.table("checklists").select("*").execute()
        df = pd.DataFrame(response.data)
        return df
    except Exception as e:
        st.error(f"Erro ao carregar checklists: {e}")
        return pd.DataFrame()

def salvar_checklist(numero_serie, respostas: dict, usuario: str):
    """
    Salva um checklist na tabela 'checklists'.
    - numero_serie: str
    - respostas: dict (ex.: {"ETIQUETA": {"status": "Conforme","obs": None}, ...})
    - usuario: str
    """
    try:
        payload = {
            "numero_serie": numero_serie,
            "usuario": usuario,
            "data_hora": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            # Salva o dicionário de respostas como campo JSON (dependendo do seu schema supabase)
            "respostas": respostas
        }
        supabase.table("checklists").insert(payload).execute()
        # opcional: invalida cache se estiver usando caching custom
        return True, None
    except Exception as e:
        return False, str(e)



# ==============================
# CALLBACK DO LEITOR
# ==============================
def processar_leitura():
    leitura = st.session_state.get("input_leitor", "").strip()
    if not leitura:
        return

    if len(leitura) == 9:
        st.session_state["numero_serie"] = leitura
        st.session_state["mensagem_erro"] = None

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
                st.session_state["numero_serie"] = ""
                st.session_state["op"] = ""
            else:
                st.session_state["mensagem_erro"] = erro

    st.session_state["input_leitor"] = ""


# ================================
# Conversão do status
# ================================
def status_emoji_para_texto(emoji):
    mapa = {"✅": "Conforme", "❌": "Não Conforme", "🟡": "N/A"}
    return mapa.get(emoji, "Indefinido")


# ================================
# Checklist de Qualidade (ATUALIZADO)
# ================================
def checklist_molas(numero_serie, usuario):
    st.markdown(f"## ✔️ Checklist de Qualidade – Nº de Série: {numero_serie}")

    # Controle de sessão
    if "checklist_bloqueado" not in st.session_state:
        st.session_state.checklist_bloqueado = False
    if "checklist_cache" not in st.session_state:
        st.session_state.checklist_cache = {}

    perguntas = [
        "Etiqueta do produto – As informações estão corretas / legíveis conforme modelo e gravação do eixo?",
        "Placa do Inmetro está correta / fixada e legível? Número corresponde à viga?",
        "A cor (Letra) do número de série é compatível com a etiqueta? Informe cor:",
        "Os grampos estão conforme a estrutura? Informe dimensão:",
        "Qual o feixe de mola utilizado?",
        "A medida do entre centro dos feixes está correta?",
        "Qual o comprimento do braço fixo utilizado?",
        "Qual o comprimento do braço móvel utilizado?",
        "Os parafusos dos braços estão apertados?",
        "Tampa do cubo, pintura e graxeiras estão conforme?"
    ]

    item_keys = {
        1: "ETIQUETA",
        2: "PLACA_INMETRO",
        3: "COR_DA_VIGA",
        4: "GRAMPO",
        5: "FEIXE_DE_MOLA",
        6: "ENTRE_CENTRO",
        7: "BRACO_FIXO",
        8: "BRACO_MOVEL",
        9: "PARAFUSO_DOS_BRACOS",
        10: "TAMPA_CUBO"
    }

    perguntas_com_observacao = [3, 4, 5, 6, 7, 8]
    resultados, observacoes = {}, {}

    # ======== CSS VISUAL ========
    st.markdown("""
        <style>
        .linha-check {
            display: flex;
            align-items: center;
            justify-content: space-between;
            background-color: #f9fafb;
            border: 1px solid #e3e6e8;
            border-radius: 10px;
            padding: 10px 15px;
            margin-bottom: 10px;
        }
        .texto-check {
            flex: 5;
            font-weight: 600;
            color: #333;
        }
        .radio-check {
            flex: 1.2;
            text-align: center;
        }
        .input-check {
            flex: 2;
        }
        </style>
    """, unsafe_allow_html=True)

    # ======== FORM CHECKLIST ========
    with st.form(key=f"form_checklist_{numero_serie}", clear_on_submit=False):
        for i, pergunta in enumerate(perguntas, start=1):
            col1, col2, col3 = st.columns([3, 1.2, 2], gap="small")

            with col1:
                st.markdown(f"<div class='texto-check'>{i}. {pergunta}</div>", unsafe_allow_html=True)

            with col2:
                escolha = st.radio(
                    "",
                    ["✅", "❌", "🟡"],
                    key=f"resp_{numero_serie}_{i}",
                    horizontal=True,
                    index=None,
                    label_visibility="collapsed"
                )
            resultados[i] = escolha

            with col3:
                if i in perguntas_com_observacao:
                    observacoes[i] = st.text_input(
                        "",
                        key=f"obs_{numero_serie}_{i}",
                        placeholder="Informe valor / tipo / dimensão..."
                    )
                else:
                    observacoes[i] = None

        st.markdown("---")
        submit = st.form_submit_button("💾 Salvar Checklist", use_container_width=True)

    # ======== VALIDAÇÃO E SALVAMENTO ========
    if submit:
        if st.session_state.checklist_bloqueado:
            st.warning("⏳ Salvamento em andamento... aguarde.")
            return

        st.session_state.checklist_bloqueado = True

        faltando = [i for i, resp in resultados.items() if resp is None]
        faltando_obs = [i for i in perguntas_com_observacao if not observacoes[i]]

        if faltando or faltando_obs:
            msg = ""
            if faltando:
                msg += f"⚠️ Responda todas as perguntas! Faltam: {[item_keys[i] for i in faltando]}\n"
            if faltando_obs:
                msg += f"⚠️ Preencha as observações obrigatórias! Faltam: {[item_keys[i] for i in faltando_obs]}"
            st.error(msg)
            st.session_state.checklist_bloqueado = False
            return

        dados_para_salvar = {}
        for i, resp in resultados.items():
            chave_item = item_keys.get(i, f"Item_{i}")
            dados_para_salvar[chave_item] = {
                "status": status_emoji_para_texto(resp),
                "obs": observacoes[i]
            }

        try:
            salvar_checklist(numero_serie, dados_para_salvar, usuario)
            st.success(f"✅ Checklist do Nº de Série {numero_serie} salvo com sucesso!")
            st.session_state.checklist_cache[numero_serie] = dados_para_salvar
            time.sleep(0.5)
        except Exception as e:
            st.error(f"❌ Erro ao salvar checklist: {e}")
        finally:
            st.session_state.checklist_bloqueado = False




# ==============================
# PÁGINA PRINCIPAL - APONTAMENTO
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


# ==========================================
# APP PRINCIPAL
# ==========================================
def app():
    if "usuario" not in st.session_state:
        st.session_state["usuario"] = "Operador_Logado"

    st.sidebar.title("Menu")
    menu = st.sidebar.radio(
        "Navegação",
        ["Apontamento MOLA", "Checklist de Qualidade", "Dashboard", "Relatórios"]
    )

    if menu == "Apontamento MOLA":
        pagina_apontamento_mola()

    elif menu == "Checklist de Qualidade":
        st.title("🧾 Checklist de Qualidade - MOLA")

        # ======================== CHECKLIST AUTOMÁTICO ========================
        df_apont = carregar_apontamentos()
        hoje = datetime.datetime.now(TZ).date()

        if not df_apont.empty:
            start_of_day = TZ.localize(datetime.datetime.combine(hoje, datetime.time.min))
            end_of_day = TZ.localize(datetime.datetime.combine(hoje, datetime.time.max))
            df_hoje = df_apont[
                (df_apont["data_hora"] >= start_of_day) &
                (df_apont["data_hora"] <= end_of_day)
            ].sort_values(by="data_hora", ascending=True)

            codigos_hoje = df_hoje.drop_duplicates(subset="numero_serie")["numero_serie"].tolist()
        else:
            codigos_hoje = []

        df_checks = carregar_checklists()
        codigos_com_checklist = df_checks["numero_serie"].unique() if not df_checks.empty else []

        codigos_disponiveis = [c for c in codigos_hoje if c not in codigos_com_checklist]

        if codigos_disponiveis:
            numero_serie = st.selectbox(
                "Selecione o Nº de Série para Inspeção",
                codigos_disponiveis,
                index=0
            )
            usuario = st.session_state["usuario"]
            checklist_molas(numero_serie, usuario)
        else:
            st.info("Nenhum código disponível para inspeção hoje.")

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

