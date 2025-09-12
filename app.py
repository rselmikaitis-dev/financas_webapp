import re
import sqlite3
import bcrypt
import pandas as pd
import streamlit as st
from datetime import date, datetime, timedelta
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

cursor.execute("CREATE TABLE IF NOT EXISTS contas (id INTEGER PRIMARY KEY, nome TEXT UNIQUE, dia_vencimento INTEGER)")
cursor.execute("CREATE TABLE IF NOT EXISTS categorias (id INTEGER PRIMARY KEY, nome TEXT UNIQUE)")
cursor.execute("CREATE TABLE IF NOT EXISTS subcategorias (id INTEGER PRIMARY KEY, categoria_id INTEGER, nome TEXT, UNIQUE(categoria_id, nome), FOREIGN KEY (categoria_id) REFERENCES categorias(id) ON DELETE CASCADE)")
cursor.execute("CREATE TABLE IF NOT EXISTS transactions (id INTEGER PRIMARY KEY, date TEXT, description TEXT, value REAL, account TEXT, subcategoria_id INTEGER, FOREIGN KEY (subcategoria_id) REFERENCES subcategorias(id))")
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

def ultimo_dia_do_mes(ano: int, mes: int) -> int:
    if mes == 12:
        return 31
    return (date(ano, mes + 1, 1) - timedelta(days=1)).day

def seletor_mes_ano(label="Período", data_default=None):
    if data_default is None:
        data_default = date.today()
    anos = list(range(2020, datetime.today().year + 2))
    meses = {1:"Janeiro",2:"Fevereiro",3:"Março",4:"Abril",5:"Maio",6:"Junho",7:"Julho",8:"Agosto",9:"Setembro",10:"Outubro",11:"Novembro",12:"Dezembro"}
    col1, col2 = st.columns(2)
    with col1:
        ano_sel = st.selectbox(f"{label} - Ano", anos, index=anos.index(data_default.year))
    with col2:
        mes_sel = st.selectbox(f"{label} - Mês", list(meses.keys()), format_func=lambda x: meses[x], index=data_default.month-1)
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
    menu = option_menu("Menu", ["Dashboard", "Lançamentos", "Importação", "Configurações"],
                       menu_icon=None, icons=["","","",""], default_index=0)

# =====================
# DASHBOARD
# =====================
if menu == "Dashboard":
    st.header("Dashboard Financeiro")
    df_lanc = read_table_transactions(conn)
    if df_lanc.empty:
        st.info("Nenhum lançamento encontrado.")
    else:
        mes_sel, ano_sel = seletor_mes_ano("Dashboard", date.today())
        df_lanc["date"] = pd.to_datetime(df_lanc["date"], errors="coerce")
        df_mes = df_lanc[(df_lanc["date"].dt.month==mes_sel)&(df_lanc["date"].dt.year==ano_sel)]
        if df_mes.empty:
            st.warning("Nenhum lançamento neste período.")
        else:
            entradas = df_mes[df_mes["value"]>0]["value"].sum()
            saidas = df_mes[df_mes["value"]<0]["value"].sum()
            saldo = entradas+saidas
            c1,c2,c3 = st.columns(3)
            c1.metric("Entradas", f"R$ {entradas:,.2f}")
            c2.metric("Saídas", f"R$ {saidas:,.2f}")
            c3.metric("Saldo", f"R$ {saldo:,.2f}")

# =====================
# LANÇAMENTOS
# =====================
elif menu=="Lançamentos":
    st.header("Lançamentos")
    mes_ref, ano_ref = seletor_mes_ano("Lançamentos", date.today())
    contas = ["Todas"]+[row[0] for row in cursor.execute("SELECT nome FROM contas ORDER BY nome")]
    conta_sel = st.selectbox("Conta", contas)
    df_lanc = read_table_transactions(conn)
    df_lanc["date"]=pd.to_datetime(df_lanc["date"],errors="coerce")
    df_filtrado=df_lanc[(df_lanc["date"].dt.month==mes_ref)&(df_lanc["date"].dt.year==ano_ref)]
    if conta_sel!="Todas":
        df_filtrado=df_filtrado[df_filtrado["account"]==conta_sel]
    st.dataframe(df_filtrado,use_container_width=True)

# =====================
# IMPORTAÇÃO
# =====================
elif menu=="Importação":
    st.header("Importação de Lançamentos")
    arq=st.file_uploader("Arquivo",type=["csv","xlsx","xls"])
    if arq:
        try:
            if arq.name.lower().endswith(".csv"):
                df=pd.read_csv(arq,sep=None,engine="python",dtype=str)
            elif arq.name.lower().endswith(".xlsx"):
                df=pd.read_excel(arq,engine="openpyxl",dtype=str)
            else:
                df=pd.read_excel(arq,engine="xlrd",dtype=str)
            df.columns=[c.strip().lower().replace("\ufeff","") for c in df.columns]
            mapa={"data":["data","data lançamento","data lancamento","dt","lançamento","data mov","data movimento"],
                  "descrição":["descrição","descricao","descricão","histórico","historico","detalhe","hist","descricao/historico"],
                  "valor":["valor","valor (r$)","valor r$","vlr","amount","valorlancamento","valor lancamento"]}
            col_map={}
            for alvo,poss in mapa.items():
                for p in poss:
                    if p in df.columns: col_map[alvo]=p; break
            if "data" not in col_map or "valor" not in col_map:
                st.error(f"Arquivo inválido. Colunas lidas: {list(df.columns)}"); st.stop()
            if "descrição" not in col_map:
                df["descrição"]=""
                col_map["descrição"]="descrição"
            df=df.rename(columns={col_map["data"]:"Data",col_map["descrição"]:"Descrição",col_map["valor"]:"Valor"})
            df=df[~df["Descrição"].astype(str).str.upper().str.startswith("SALDO")]
            df["Data"]=df["Data"].apply(parse_date)
            df["Valor"]=df["Valor"].apply(parse_money)
            contas=[r[0] for r in cursor.execute("SELECT nome FROM contas ORDER BY nome")]
            conta_sel=st.selectbox("Conta destino",contas)
            df["Subcategoria"]="Nenhuma"
            gb=GridOptionsBuilder.from_dataframe(df)
            gb.configure_default_column(editable=False)
            gb.configure_column("Subcategoria",editable=True,cellEditor="agSelectCellEditor",cellEditorParams={"values":["Nenhuma"]})
            grid=AgGrid(df,gridOptions=gb.build(),update_mode=GridUpdateMode.VALUE_CHANGED,fit_columns_on_grid_load=True,height=420)
            df_edit=pd.DataFrame(grid["data"])
            if st.button("Importar"):
                for _,row in df_edit.iterrows():
                    if pd.isna(row["Data"]) or row["Valor"] is None: continue
                    cursor.execute("INSERT INTO transactions(date,description,value,account) VALUES(?,?,?,?)",
                                   (row["Data"].strftime("%Y-%m-%d"),str(row["Descrição"]),float(row["Valor"]),conta_sel))
                conn.commit()
                st.success("Importado com sucesso!")
                st.rerun()
        except Exception as e:
            st.error(f"Erro: {e}")

# =====================
# CONFIGURAÇÕES
# =====================
elif menu=="Configurações":
    st.header("Configurações")
    st.subheader("Reset do banco")
    if st.button("⚠️ Apagar tudo e começar do zero"):
        cursor.execute("DELETE FROM transactions")
        cursor.execute("DELETE FROM subcategorias")
        cursor.execute("DELETE FROM categorias")
        cursor.execute("DELETE FROM contas")
        conn.commit()
        st.success("Todos os dados foram apagados!")
