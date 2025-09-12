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

# Tabela contas
cursor.execute("""
    CREATE TABLE IF NOT EXISTS contas (
        id INTEGER PRIMARY KEY,
        nome TEXT UNIQUE,
        dia_vencimento INTEGER
    )
""")

# Tabela categorias
cursor.execute("""
    CREATE TABLE IF NOT EXISTS categorias (
        id INTEGER PRIMARY KEY,
        tipo TEXT,
        subtipo TEXT,
        UNIQUE(tipo, subtipo)
    )
""")

# Tabela lançamentos
cursor.execute("""
    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY,
        date TEXT,
        description TEXT,
        value REAL,
        account TEXT,
        categoria_id INTEGER
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
        ["📊 Dashboard", "📑 Lançamentos", "📥 Importação", "⚙️ Configurações"],
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

    mes_ref, ano_ref = seletor_mes_ano("Lançamentos", date.today())

    contas = ["Todas"] + [row[0] for row in cursor.execute("SELECT nome FROM contas ORDER BY nome")]
    conta_sel = st.selectbox("Filtrar por conta", contas)

    df_lanc = pd.read_sql_query(
        "SELECT t.date, t.description, t.value, t.account, c.tipo, c.subtipo "
        "FROM transactions t LEFT JOIN categorias c ON t.categoria_id = c.id",
        conn
    )
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
    st.info("Importação mantém os mesmos fluxos de antes (sem categoria atribuída ainda).")

# =====================
# CONFIGURAÇÕES
# =====================
elif menu == "⚙️ Configurações":
    st.header("⚙️ Configurações")
    aba = st.radio("Selecione a seção", ["Contas", "Categorias"], horizontal=True)

    # ---- CONTAS ----
    if aba == "Contas":
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

            st.subheader("Editar/Excluir contas")
            if nomes_sel:
                if len(nomes_sel) == 1:
                    old_name = nomes_sel[0]
                    new_name = st.text_input("Novo nome", value=old_name)
                    new_dia = st.number_input("Novo vencimento", min_value=1, max_value=31, value=1)

                    if st.button("Salvar alteração"):
                        try:
                            cursor.execute("UPDATE contas SET nome=?, dia_vencimento=? WHERE nome=?",
                                           (new_name.strip(), new_dia, old_name))
                            cursor.execute("UPDATE transactions SET account=? WHERE account=?",
                                           (new_name.strip(), old_name))
                            conn.commit()
                            st.toast(f"Conta atualizada ✅", icon="✏️")
                            st.rerun()
                        except sqlite3.IntegrityError:
                            st.toast(f"Já existe uma conta chamada '{new_name.strip()}' ⚠️", icon="⚠️")

                if st.button("Excluir selecionadas"):
                    for nome in nomes_sel:
                        cursor.execute("DELETE FROM transactions WHERE account=?", (nome,))
                        cursor.execute("DELETE FROM contas WHERE nome=?", (nome,))
                    conn.commit()
                    st.toast("Contas excluídas 🗑️", icon="🗑️")
                    st.rerun()

    # ---- CATEGORIAS ----
    elif aba == "Categorias":
        cursor.execute("SELECT id, tipo, subtipo FROM categorias ORDER BY tipo, subtipo")
        categorias_rows = cursor.fetchall()
        df_cat = pd.DataFrame(categorias_rows, columns=["ID", "Tipo", "Subtipo"])

        if df_cat.empty:
            st.info("Nenhuma categoria cadastrada ainda.")
        else:
            gb = GridOptionsBuilder.from_dataframe(df_cat[["Tipo", "Subtipo"]])
            gb.configure_default_column(editable=False)
            gb.configure_selection(selection_mode="multiple", use_checkbox=True)
            grid_options = gb.build()

            grid = AgGrid(
                df_cat[["ID", "Tipo", "Subtipo"]],
                gridOptions=grid_options,
                update_mode=GridUpdateMode.SELECTION_CHANGED,
                fit_columns_on_grid_load=True,
                height=280,
                theme="balham"
            )

            selected_rows = grid.get("selected_rows", [])
            if isinstance(selected_rows, pd.DataFrame):
                selected_rows = selected_rows.to_dict("records")
            ids_sel = [r.get("ID") for r in selected_rows] if selected_rows else []

            st.subheader("Adicionar nova categoria")
            tipo = st.text_input("Tipo")
            subtipo = st.text_input("Subtipo")

            if st.button("Adicionar categoria"):
                if tipo.strip() and subtipo.strip():
                    try:
                        cursor.execute("INSERT INTO categorias (tipo, subtipo) VALUES (?, ?)", (tipo.strip(), subtipo.strip()))
                        conn.commit()
                        st.toast("Categoria adicionada ➕", icon="📂")
                        st.rerun()
                    except sqlite3.IntegrityError:
                        st.toast("Essa categoria já existe ⚠️", icon="⚠️")
                else:
                    st.toast("Preencha todos os campos ⚠️", icon="⚠️")

            st.subheader("Editar/Excluir categorias")
            if ids_sel:
                if len(ids_sel) == 1:
                    cat_id = ids_sel[0]
                    old = df_cat[df_cat["ID"] == cat_id].iloc[0]
                    new_tipo = st.text_input("Novo tipo", value=old["Tipo"])
                    new_subtipo = st.text_input("Novo subtipo", value=old["Subtipo"])

                    if st.button("Salvar alteração"):
                        try:
                            cursor.execute("UPDATE categorias SET tipo=?, subtipo=? WHERE id=?",
                                           (new_tipo.strip(), new_subtipo.strip(), cat_id))
                            conn.commit()
                            st.toast("Categoria atualizada ✅", icon="✏️")
                            st.rerun()
                        except sqlite3.IntegrityError:
                            st.toast("Já existe essa categoria ⚠️", icon="⚠️")

                if st.button("Excluir selecionadas"):
                    for cid in ids_sel:
                        cursor.execute("UPDATE transactions SET categoria_id=NULL WHERE categoria_id=?", (cid,))
                        cursor.execute("DELETE FROM categorias WHERE id=?", (cid,))
                    conn.commit()
                    st.toast("Categorias excluídas 🗑️", icon="🗑️")
                    st.rerun()
