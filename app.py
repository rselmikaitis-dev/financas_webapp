import re
import sqlite3
import bcrypt
import pandas as pd
import streamlit as st
from datetime import date, datetime
from streamlit_option_menu import option_menu
from st_aggrid import GridOptionsBuilder, AgGrid, GridUpdateMode

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
    st.title("Login – Controle Financeiro")
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

# Logout
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
    nome TEXT UNIQUE,
    dia_vencimento INTEGER
)""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS categorias (
    id INTEGER PRIMARY KEY,
    nome TEXT UNIQUE
)""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS subcategorias (
    id INTEGER PRIMARY KEY,
    categoria_id INTEGER,
    nome TEXT,
    UNIQUE(categoria_id, nome),
    FOREIGN KEY (categoria_id) REFERENCES categorias(id) ON DELETE CASCADE
)""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY,
    date TEXT,
    description TEXT,
    value REAL,
    account TEXT,
    subcategoria_id INTEGER,
    FOREIGN KEY (subcategoria_id) REFERENCES subcategorias(id)
)""")
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
    s = str(val).strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            continue
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

def read_table_transactions(conn):
    return pd.read_sql_query("""
        SELECT t.id, t.date, t.description, t.value, t.account,
               c.nome as categoria, s.nome as subcategoria
        FROM transactions t
        LEFT JOIN subcategorias s ON t.subcategoria_id = s.id
        LEFT JOIN categorias   c ON s.categoria_id   = c.id
    """, conn)

# =====================
# MENU
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

    df_lanc = read_table_transactions(conn)
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
            saidas   = df_mes[df_mes["value"] < 0]["value"].sum()
            saldo    = entradas + saidas

            st.subheader(f"Resumo {mes_sel:02d}/{ano_sel}")
            c1, c2, c3 = st.columns(3)
            c1.metric("Entradas", f"R$ {entradas:,.2f}")
            c2.metric("Saídas",   f"R$ {saidas:,.2f}")
            c3.metric("Saldo",    f"R$ {saldo:,.2f}")

# =====================
# IMPORTAÇÃO
# =====================
elif menu == "Importação":
    st.header("Importação de Lançamentos")

    arquivo = st.file_uploader("Selecione o arquivo (CSV, XLSX ou XLS)", type=["csv", "xlsx", "xls"])

    def _read_uploaded(file):
        name = file.name.lower()
        if name.endswith(".csv"):
            return pd.read_csv(file, sep=None, engine="python", dtype=str)
        if name.endswith(".xlsx"):
            return pd.read_excel(file, engine="openpyxl", dtype=str)
        if name.endswith(".xls"):
            try:
                return pd.read_excel(file, engine="xlrd", dtype=str)
            except Exception:
                raise RuntimeError("Para .xls, instale 'xlrd>=2.0' ou converta para CSV/XLSX.")
        raise RuntimeError("Formato não suportado.")

    if arquivo is not None:
        try:
            df = _read_uploaded(arquivo)

            # Normaliza cabeçalhos
            df.columns = [c.strip().lower() for c in df.columns]

            # Mapeamento flexível
            mapa_colunas = {
                "data": ["data", "data lançamento", "data lancamento", "dt", "lançamento"],
                "descrição": ["descrição", "descricao", "histórico", "historico", "detalhe"],
                "valor": ["valor", "valor (r$)", "valor r$", "vlr", "amount"]
            }

            col_map = {}
            for alvo, possiveis in mapa_colunas.items():
                for p in possiveis:
                    if p in df.columns:
                        col_map[alvo] = p
                        break

            obrigatorias = ["data", "valor"]
            faltando = [c for c in obrigatorias if c not in col_map]
            if faltando:
                st.error(f"Arquivo inválido. Faltando colunas obrigatórias: {faltando}")
                st.stop()

            if "descrição" not in col_map:
                df["descrição"] = ""
                col_map["descrição"] = "descrição"

            df = df.rename(columns={
                col_map["data"]: "Data",
                col_map["descrição"]: "Descrição",
                col_map["valor"]: "Valor"
            })

            df = df[~df["Descrição"].astype(str).str.upper().str.startswith("SALDO")]

            df["Data"] = df["Data"].apply(parse_date)
            df["Valor"] = df["Valor"].apply(parse_money)

            contas = [row[0] for row in cursor.execute("SELECT nome FROM contas ORDER BY nome")]
            if not contas:
                st.error("Nenhuma conta cadastrada. Vá em Configurações → Contas.")
                st.stop()
            conta_sel = st.selectbox("Selecione a conta para os lançamentos", contas)

            cursor.execute("""
                SELECT s.id, s.nome, c.nome
                FROM subcategorias s
                JOIN categorias c ON s.categoria_id = c.id
                ORDER BY c.nome, s.nome
            """)
            subcat_map = {"Nenhuma": None}
            for sid, s_nome, c_nome in cursor.fetchall():
                subcat_map[f"{c_nome} → {s_nome}"] = sid

            df["Subcategoria"] = "Nenhuma"

            gb = GridOptionsBuilder.from_dataframe(df)
            gb.configure_default_column(editable=False)
            gb.configure_column("Subcategoria", editable=True, cellEditor="agSelectCellEditor",
                                cellEditorParams={"values": list(subcat_map.keys())})
            grid_options = gb.build()

            grid = AgGrid(
                df,
                gridOptions=grid_options,
                update_mode=GridUpdateMode.VALUE_CHANGED,
                fit_columns_on_grid_load=True,
                height=420,
                theme="balham"
            )

            df_editado = pd.DataFrame(grid["data"])

            if st.button("Importar lançamentos"):
                inserted = 0
                for _, row in df_editado.iterrows():
                    dt = row["Data"]
                    valor = row["Valor"]
                    desc = str(row["Descrição"])
                    if pd.isna(dt) or valor is None:
                        continue
                    cursor.execute("""
                        INSERT INTO transactions (date, description, value, account, subcategoria_id)
                        VALUES (?, ?, ?, ?, ?)
                    """, (
                        dt.strftime("%Y-%m-%d"),
                        desc,
                        float(valor),
                        conta_sel,
                        subcat_map.get(row["Subcategoria"], None)
                    ))
                    inserted += 1
                conn.commit()
                st.success(f"{inserted} lançamentos importados com sucesso!")
                st.rerun()
        except Exception as e:
            st.error(f"Erro ao importar: {e}")

# =====================
# (abas de lançamentos e configurações permanecem iguais à versão anterior)
# =====================
