import re
import sqlite3
import bcrypt
import pandas as pd
import streamlit as st
from datetime import date, datetime
from streamlit_option_menu import option_menu
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode

st.set_page_config(page_title="Controle Financeiro", page_icon="💰", layout="wide")

# =====================
# AUTENTICAÇÃO
# =====================
AUTH_USERNAME = st.secrets.get("AUTH_USERNAME", "rafael")
AUTH_PASSWORD_BCRYPT = st.secrets.get(
    "AUTH_PASSWORD_BCRYPT",
    "$2b$12$abcdefghijklmnopqrstuv1234567890abcdefghijklmnopqrstuv12"
)

def check_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False

def login_view():
    st.title("🔐 Login – Controle Financeiro Familiar")
    with st.form("login_form"):
        u = st.text_input("Usuário")
        p = st.text_input("Senha", type="password")
        submitted = st.form_submit_button("Entrar")
        if submitted:
            if u == AUTH_USERNAME and check_password(p, AUTH_PASSWORD_BCRYPT):
                st.session_state["auth_ok"] = True
                st.rerun()
            else:
                st.toast("Usuário ou senha inválidos ⚠️", icon="⚠️")

if "auth_ok" not in st.session_state or not st.session_state["auth_ok"]:
    login_view()
    st.stop()

# Botão de logout
logout_col = st.columns(8)[-1]
with logout_col:
    if st.button("Sair", type="secondary"):
        st.session_state.clear()
        st.rerun()

# =====================
# BANCO DE DADOS
# =====================
if "conn" not in st.session_state:
    st.session_state.conn = sqlite3.connect("data.db", check_same_thread=False)
conn = st.session_state.conn
cursor = conn.cursor()

cursor.execute("""
    CREATE TABLE IF NOT EXISTS contas (
        id INTEGER PRIMARY KEY,
        nome TEXT UNIQUE
    )
""")
try:
    cursor.execute("ALTER TABLE contas ADD COLUMN dia_vencimento INTEGER")
except sqlite3.OperationalError:
    pass

cursor.execute("""
    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY,
        date TEXT,
        description TEXT,
        value REAL,
        account TEXT
    )
""")
conn.commit()

# =====================
# HELPERS
# =====================
def parse_money(val) -> float | None:
    if pd.isna(val):
        return None
    s = str(val).strip()
    s = re.sub(r"[^\d,.-]", "", s)
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    if s.endswith("-"):
        s = "-" + s[:-1]
    try:
        return float(s)
    except ValueError:
        return None

def parse_date(val):
    try:
        return datetime.strptime(str(val).strip(), "%d/%m/%Y").date()
    except Exception:
        return pd.NaT

def seletor_mes_ano(label="Período", data_default=None):
    """Seletor simples de mês e ano"""
    if data_default is None:
        data_default = date.today()
    anos = list(range(2020, datetime.today().year + 2))
    meses = {
        1: "Janeiro", 2: "Fevereiro", 3: "Março",
        4: "Abril", 5: "Maio", 6: "Junho",
        7: "Julho", 8: "Agosto", 9: "Setembro",
        10: "Outubro", 11: "Novembro", 12: "Dezembro"
    }
    col1, col2 = st.columns(2)
    with col1:
        ano_sel = st.selectbox(f"{label} - Ano", anos, index=anos.index(data_default.year))
    with col2:
        mes_sel = st.selectbox(f"{label} - Mês", list(meses.keys()),
                               format_func=lambda x: meses[x],
                               index=data_default.month-1)
    return mes_sel, ano_sel

# =====================
# MENU LATERAL
# =====================
with st.sidebar:
    menu = option_menu(
        "Menu",
        ["📊 Dashboard", "📑 Lançamentos", "📥 Importação", "⚙️ Contas"],
        icons=["bar-chart", "list-columns", "cloud-upload", "gear"],
        menu_icon="cast",
        default_index=0,
        orientation="vertical"
    )

# =====================
# DASHBOARD
# =====================
if menu == "📊 Dashboard":
    st.header("📊 Dashboard Financeiro")

    df_lanc = pd.read_sql_query("SELECT date, description, value, account FROM transactions", conn)
    if df_lanc.empty:
        st.info("Nenhum lançamento encontrado.")
    else:
        st.subheader("Selecione o mês e ano")
        mes_sel, ano_sel = seletor_mes_ano("Dashboard", date.today())

        df_lanc["date"] = pd.to_datetime(df_lanc["date"], errors="coerce")
        df_lanc = df_lanc.dropna(subset=["date"])
        df_mes = df_lanc[(df_lanc["date"].dt.month == mes_sel) & (df_lanc["date"].dt.year == ano_sel)]

        if df_mes.empty:
            st.warning(f"Nenhum lançamento encontrado para {mes_sel:02d}/{ano_sel}.")
        else:
            entradas = df_mes[df_mes["value"] > 0]["value"].sum()
            saidas = df_mes[df_mes["value"] < 0]["value"].sum()
            saldo = entradas + saidas

            st.subheader(f"Resumo {mes_sel:02d}/{ano_sel}")
            col1, col2, col3 = st.columns(3)
            col1.metric("Entradas", f"R$ {entradas:,.2f}")
            col2.metric("Saídas", f"R$ {saidas:,.2f}")
            col3.metric("Saldo", f"R$ {saldo:,.2f}")

# =====================
# LANÇAMENTOS
# =====================
elif menu == "📑 Lançamentos":
    st.header("📑 Lançamentos por período")

    st.subheader("Selecione o mês e ano")
    mes_ref, ano_ref = seletor_mes_ano("Lançamentos", date.today())

    contas = ["Todas"] + [row[0] for row in cursor.execute("SELECT nome FROM contas ORDER BY nome")]
    conta_sel = st.selectbox("Filtrar por conta", contas)

    df_lanc = pd.read_sql_query("SELECT date, description, value, account FROM transactions", conn)
    df_lanc["date"] = pd.to_datetime(df_lanc["date"], errors="coerce")
    df_lanc = df_lanc.dropna(subset=["date"])

    df_filtrado = df_lanc[(df_lanc["date"].dt.month == mes_ref) & (df_lanc["date"].dt.year == ano_ref)]
    if conta_sel != "Todas":
        df_filtrado = df_filtrado[df_filtrado["account"] == conta_sel]

    if df_filtrado.empty:
        st.warning(f"Nenhum lançamento encontrado para {mes_ref:02d}/{ano_ref}.")
    else:
        st.dataframe(
            df_filtrado.sort_values("date", ascending=True),
            use_container_width=True
        )

# =====================
# IMPORTAÇÃO
# =====================
elif menu == "📥 Importação":
    st.header("📥 Importação de Lançamentos")

    cursor.execute("SELECT nome FROM contas ORDER BY nome")
    contas_cadastradas = [row[0] for row in cursor.fetchall()]

    if not contas_cadastradas:
        st.info("Nenhuma conta cadastrada. Cadastre uma conta na seção ⚙️ Contas antes de importar lançamentos.")
    else:
        conta_escolhida = st.selectbox("Conta/cartão", options=contas_cadastradas)

        data_vencimento = None
        if conta_escolhida.lower().startswith("cartão de crédito"):
            cursor.execute("SELECT dia_vencimento FROM contas WHERE nome=?", (conta_escolhida,))
            row = cursor.fetchone()
            if row and row[0]:
                dia_venc = int(row[0])
                st.subheader("Selecione o mês e ano da fatura")
                mes_ref, ano_ref = seletor_mes_ano("Fatura", date.today())
                try:
                    data_vencimento = date(ano_ref, mes_ref, dia_venc)
                except ValueError:
                    st.toast("Data de vencimento inválida ⚠️", icon="⚠️")

        arquivo = st.file_uploader(
            "Selecione o arquivo (3 colunas: Data, Descrição, Valor)",
            type=["xls", "xlsx", "csv"]
        )

        if arquivo is not None:
            try:
                if arquivo.name.lower().endswith(".csv"):
                    df = pd.read_csv(arquivo, sep=None, engine="python")
                elif arquivo.name.lower().endswith(".xls"):
                    try:
                        df = pd.read_excel(arquivo)
                    except Exception:
                        dfs = pd.read_html(arquivo)
                        df = dfs[0]
                else:
                    df = pd.read_excel(arquivo, engine="openpyxl")

                df = df.rename(columns={
                    "data": "Data",
                    "lançamento": "Descrição",
                    "valor (R$)": "Valor"
                })

                df = df.iloc[:, :3]
                df.columns = ["Data", "Descrição", "Valor"]

                df["Data"] = df["Data"].astype(str).apply(parse_date)
                df["Data"] = pd.to_datetime(df["Data"], errors="coerce").dt.strftime("%Y-%m-%d")

                df["ValorNum"] = df["Valor"].apply(parse_money)

                df["Motivo"] = ""
                df.loc[df["Descrição"].astype(str).str.strip().str.upper().str.startswith("SALDO"), "Motivo"] = "Linha de saldo"
                df.loc[df["ValorNum"].isna(), "Motivo"] = "Valor inválido"

                st.markdown(f"### Pré-visualização ({len(df)} linhas no total)")
                st.caption(f"Intervalo de datas: {df['Data'].min()} → {df['Data'].max()}")
                st.dataframe(df, use_container_width=True)

                df_filtrado = df.loc[df["Motivo"] == "", ["Data", "Descrição", "ValorNum"]].copy()
                df_filtrado.rename(columns={"ValorNum": "Valor"}, inplace=True)
            except Exception as e:
                st.toast(f"Erro ao ler/normalizar o arquivo: {e} ⚠️", icon="⚠️")
                st.stop()

            if conta_escolhida.lower().startswith("cartão de crédito"):
                if data_vencimento:
                    df_filtrado["Data"] = pd.to_datetime(data_vencimento).strftime("%Y-%m-%d")
                df_filtrado["Valor"] = df_filtrado["Valor"] * -1

            if st.button(f"Importar para {conta_escolhida}"):
                try:
                    for _, row in df_filtrado.iterrows():
                        cursor.execute(
                            "INSERT INTO transactions (date, description, value, account) VALUES (?, ?, ?, ?)",
                            (
                                row["Data"],
                                str(row["Descrição"]),
                                float(row["Valor"]),
                                conta_escolhida
                            )
                        )
                    conn.commit()
                    st.toast(f"{len(df_filtrado)} lançamentos importados para {conta_escolhida} 💰", icon="📥")
                except Exception as e:
                    st.toast(f"Falha na importação: {e} ⚠️", icon="⚠️")

# =====================
# CONTAS
# =====================
elif menu == "⚙️ Contas":
    st.header("⚙️ Contas")
    cursor.execute("SELECT nome, dia_vencimento FROM contas ORDER BY nome")
    contas_rows = cursor.fetchall()
    df_contas = pd.DataFrame(contas_rows, columns=["Conta", "Dia Vencimento"])

    if df_contas.empty:
        st.info("Nenhuma conta cadastrada ainda.")
    else:
        gb = GridOptionsBuilder.from_dataframe(df_contas)
        gb.configure_default_column(editable=False)
        gb.configure_selection(selection_mode="multiple", use_checkbox=True)
        grid_options = gb.build()

        grid = AgGrid(
            df_contas,
            gridOptions=grid_options,
            update_mode=GridUpdateMode.SELECTION_CHANGED,
            fit_columns_on_grid_load=True,
            height=280,
            theme="balham"
        )

        selected_rows = grid.get("selected_rows", [])
        if isinstance(selected_rows, pd.DataFrame):
            selected_rows = selected_rows.to_dict("records")
        nomes_sel = [r.get("Conta") for r in selected_rows] if selected_rows else []

        st.subheader("Editar conta")
        if len(nomes_sel) == 1:
            old_name = nomes_sel[0]
            cursor.execute("SELECT dia_vencimento FROM contas WHERE nome=?", (old_name,))
            row = cursor.fetchone()
            venc_atual = row[0] if row else None

            new_name = st.text_input("Novo nome", value=old_name, key=f"edit_{old_name}")
            new_dia = None
            if old_name.lower().startswith("cartão de crédito") or new_name.lower().startswith("cartão de crédito"):
                new_dia = st.number_input("Dia do vencimento", min_value=1, max_value=31,
                                          value=int(venc_atual) if venc_atual else 1)

            if st.button("Salvar alteração"):
                new_name_clean = new_name.strip()
                try:
                    cursor.execute("UPDATE contas SET nome=?, dia_vencimento=? WHERE nome=?",
                                   (new_name_clean, new_dia, old_name))
                    cursor.execute("UPDATE transactions SET account=? WHERE account=?",
                                   (new_name_clean, old_name))
                    conn.commit()
                    st.toast(f"Conta atualizada: '{old_name}' → '{new_name_clean}' ✅", icon="✏️")
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.toast(f"Já existe uma conta chamada '{new_name_clean}' ⚠️", icon="⚠️")
        elif len(nomes_sel) > 1:
            st.caption("Selecione apenas **uma** conta para editar.")
        else:
            st.caption("Selecione uma conta no grid para editar.")

        st.subheader("Excluir contas")
        if nomes_sel:
            if st.button("Excluir selecionadas"):
                try:
                    for nome in nomes_sel:
                        cursor.execute("DELETE FROM transactions WHERE account=?", (nome,))
                        cursor.execute("DELETE FROM contas WHERE nome=?", (nome,))
                    conn.commit()
                    st.toast("Contas excluídas com sucesso 🗑️", icon="🗑️")
                    st.rerun()
                except Exception as e:
                    st.toast(f"Erro ao excluir: {e} ⚠️", icon="⚠️")
        else:
            st.caption("Selecione uma ou mais contas no grid para excluir.")

    st.subheader("Adicionar nova conta")
    nova = st.text_input("Nome da nova conta:")
    dia_venc = None
    if nova.lower().startswith("cartão de crédito"):
        dia_venc = st.number_input("Dia do vencimento", min_value=1, max_value=31, value=1)

    if st.button("Adicionar conta"):
        if nova.strip():
            try:
                cursor.execute("INSERT INTO contas (nome, dia_vencimento) VALUES (?, ?)",
                               (nova.strip(), dia_venc))
                conn.commit()
                st.toast(f"Conta '{nova.strip()}' adicionada ➕", icon="💳")
                st.rerun()
            except sqlite3.IntegrityError:
                st.toast("Essa conta já existe ⚠️", icon="⚠️")
        else:
            st.toast("Digite um nome válido ⚠️", icon="⚠️")
