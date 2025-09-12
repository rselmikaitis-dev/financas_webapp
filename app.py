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
    st.title("Login – Controle Financeiro Familiar")
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

# Contas
cursor.execute("""
    CREATE TABLE IF NOT EXISTS contas (
        id INTEGER PRIMARY KEY,
        nome TEXT UNIQUE,
        dia_vencimento INTEGER
    )
""")

# Categorias
cursor.execute("""
    CREATE TABLE IF NOT EXISTS categorias (
        id INTEGER PRIMARY KEY,
        nome TEXT UNIQUE
    )
""")

# Subcategorias
cursor.execute("""
    CREATE TABLE IF NOT EXISTS subcategorias (
        id INTEGER PRIMARY KEY,
        categoria_id INTEGER,
        nome TEXT,
        UNIQUE(categoria_id, nome),
        FOREIGN KEY (categoria_id) REFERENCES categorias(id) ON DELETE CASCADE
    )
""")

# Lançamentos
cursor.execute("""
    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY,
        date TEXT,
        description TEXT,
        value REAL,
        account TEXT,
        subcategoria_id INTEGER,
        FOREIGN KEY (subcategoria_id) REFERENCES subcategorias(id)
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
        ["Dashboard", "Lançamentos", "Importação", "Configurações"],
        menu_icon=None,
        icons=["", "", "", ""],
        default_index=0,
        orientation="vertical"
    )

# =====================
# DASHBOARD
# =====================
if menu == "Dashboard":
    st.header("Dashboard Financeiro")

    df_lanc = pd.read_sql_query("""
        SELECT t.date, t.description, t.value, t.account,
               c.nome as categoria, s.nome as subcategoria
        FROM transactions t
        LEFT JOIN subcategorias s ON t.subcategoria_id = s.id
        LEFT JOIN categorias c ON s.categoria_id = c.id
    """, conn)

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
elif menu == "Lançamentos":
    st.header("Lançamentos por período")

    mes_ref, ano_ref = seletor_mes_ano("Lançamentos", date.today())
    contas = ["Todas"] + [row[0] for row in cursor.execute("SELECT nome FROM contas ORDER BY nome")]
    conta_sel = st.selectbox("Filtrar por conta", contas)

    df_lanc = pd.read_sql_query("""
        SELECT t.date, t.description, t.value, t.account,
               c.nome as categoria, s.nome as subcategoria
        FROM transactions t
        LEFT JOIN subcategorias s ON t.subcategoria_id = s.id
        LEFT JOIN categorias c ON s.categoria_id = c.id
    """, conn)

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
elif menu == "Importação":
    st.header("Importação de Lançamentos")
    st.info("Importação ainda não está vinculando categorias. Fluxo básico de upload e salvar pode ser reativado aqui.")

# =====================
# CONFIGURAÇÕES
# =====================
elif menu == "Configurações":
    st.header("Configurações")
    tab1, tab2, tab3 = st.tabs(["Contas", "Categorias", "Subcategorias"])

    # ---- CONTAS ----
    with tab1:
        st.subheader("Gerenciar Contas")
        cursor.execute("SELECT nome, dia_vencimento FROM contas ORDER BY nome")
        contas_rows = cursor.fetchall()
        df_contas = pd.DataFrame(contas_rows, columns=["Conta", "Dia Vencimento"])

        if not df_contas.empty:
            st.dataframe(df_contas)

        nova = st.text_input("Nome da nova conta:")
        dia_venc = None
        if nova.lower().startswith("cartão de crédito"):
            dia_venc = st.number_input("Dia do vencimento", min_value=1, max_value=31, value=1)

        if st.button("Adicionar conta"):
            if nova.strip():
                try:
                    cursor.execute("INSERT INTO contas (nome, dia_vencimento) VALUES (?, ?)", (nova.strip(), dia_venc))
                    conn.commit()
                    st.success("Conta adicionada!")
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error("Essa conta já existe.")
            else:
                st.error("Digite um nome válido.")

    # ---- CATEGORIAS ----
    with tab2:
        st.subheader("Gerenciar Categorias")
        cursor.execute("SELECT id, nome FROM categorias ORDER BY nome")
        df_cat = pd.DataFrame(cursor.fetchall(), columns=["ID", "Nome"])

        if not df_cat.empty:
            st.dataframe(df_cat)

        nova_cat = st.text_input("Nome da nova categoria:")
        if st.button("Adicionar categoria"):
            if nova_cat.strip():
                try:
                    cursor.execute("INSERT INTO categorias (nome) VALUES (?)", (nova_cat.strip(),))
                    conn.commit()
                    st.success("Categoria adicionada!")
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error("Essa categoria já existe.")
            else:
                st.error("Digite um nome válido.")

    # ---- SUBCATEGORIAS ----
    with tab3:
        st.subheader("Gerenciar Subcategorias")
        cursor.execute("SELECT id, nome FROM categorias ORDER BY nome")
        categorias_opts = cursor.fetchall()

        if not categorias_opts:
            st.info("Cadastre uma categoria primeiro.")
        else:
            cat_map = {c[1]: c[0] for c in categorias_opts}
            cat_sel = st.selectbox("Categoria", list(cat_map.keys()))
            nova_sub = st.text_input("Nome da nova subcategoria:")

            if st.button("Adicionar subcategoria"):
                if nova_sub.strip():
                    try:
                        cursor.execute("INSERT INTO subcategorias (categoria_id, nome) VALUES (?, ?)", (cat_map[cat_sel], nova_sub.strip()))
                        conn.commit()
                        st.success("Subcategoria adicionada!")
                        st.rerun()
                    except sqlite3.IntegrityError:
                        st.error("Essa subcategoria já existe nessa categoria.")
                else:
                    st.error("Digite um nome válido.")

            cursor.execute("""
                SELECT s.id, s.nome, c.nome
                FROM subcategorias s
                JOIN categorias c ON s.categoria_id = c.id
                ORDER BY c.nome, s.nome
            """)
            df_sub = pd.DataFrame(cursor.fetchall(), columns=["ID", "Subcategoria", "Categoria"])
            if not df_sub.empty:
                st.dataframe(df_sub)
