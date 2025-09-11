import streamlit as st
import pandas as pd
import sqlite3
import bcrypt

st.set_page_config(page_title="Controle Financeiro", page_icon="💰", layout="wide")

# =====================
# AUTENTICAÇÃO
# =====================

AUTH_USERNAME = st.secrets.get("AUTH_USERNAME", "rafael")
AUTH_PASSWORD_BCRYPT = st.secrets.get(
    "AUTH_PASSWORD_BCRYPT",
    "$2b$12$abcdefghijklmnopqrstuv1234567890abcdefghijklmnopqrstuv12"  # hash de exemplo
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
                st.error("Usuário ou senha inválidos.")

    with st.expander("Gerar hash bcrypt (para configurar Secrets)"):
        new_pass = st.text_input("Digite a senha para gerar hash", type="password")
        if st.button("Gerar hash bcrypt"):
            if new_pass:
                hashed = bcrypt.hashpw(new_pass.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
                st.code(hashed, language="text")
            else:
                st.warning("Digite uma senha.")

if "auth_ok" not in st.session_state or not st.session_state["auth_ok"]:
    login_view()
    st.stop()

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
# ABAS
# =====================
aba_importacao, aba_dashboard, aba_contas = st.tabs(["📥 Importação", "📊 Dashboard", "⚙️ Contas"])

# --- Aba Importação
with aba_importacao:
    st.header("Importação de Lançamentos")
    cursor.execute("SELECT nome FROM contas")
    contas_cadastradas = [row[0] for row in cursor.fetchall()]

    if not contas_cadastradas:
        st.info("Nenhuma conta cadastrada. Cadastre uma conta na aba ⚙️ Contas antes de importar lançamentos.")
    else:
        conta_escolhida = st.selectbox("Conta/cartão", options=contas_cadastradas)
        arquivo = st.file_uploader("Selecione o arquivo do extrato ou fatura", type=["xls", "xlsx", "csv"])

        if st.button("Importar") and arquivo:
            try:
                if arquivo.name.lower().endswith(".csv"):
                    df = pd.read_csv(arquivo, sep=None, engine="python")
                else:
                    df = pd.read_excel(arquivo)
            except Exception as e:
                st.error(f"Erro ao ler o arquivo: {e}")
                st.stop()

            colunas = df.columns.tolist()
            data_col = st.selectbox("Coluna de Data", options=colunas)
            desc_col = st.selectbox("Coluna de Descrição", options=colunas)

            valor_col = None
            deb_col = None
            cred_col = None

            if "Débito" in colunas or "Debito" in colunas:
                deb_col = st.selectbox("Coluna de Débito", options=colunas)
                cred_col = st.selectbox("Coluna de Crédito", options=colunas)
            else:
                valor_col = st.selectbox("Coluna de Valor (+/–)", options=colunas)

            if st.button("Confirmar Importação"):
                try:
                    df_filtrado = df[~df[desc_col].astype(str).str.upper().str.startswith("SALDO")]
                    total_importados = 0

                    for _, row in df_filtrado.iterrows():
                        data_str = str(row[data_col]) if not isinstance(row[data_col], str) else row[data_col]
                        descricao = str(row[desc_col])

                        if valor_col:
                            valor = float(row[valor_col]) if pd.notna(row[valor_col]) else 0.0
                        else:
                            valor = 0.0
                            if pd.notna(row[cred_col]):
                                valor += float(row[cred_col])
                            if pd.notna(row[deb_col]):
                                valor -= float(row[deb_col])

                        cursor.execute(
                            "INSERT INTO transactions (date, description, value, account) VALUES (?, ?, ?, ?)",
                            (data_str, descricao, valor, conta_escolhida)
                        )
                        total_importados += 1

                    conn.commit()
                    st.success(f"{total_importados} lançamentos importados para a conta **{conta_escolhida}**!")
                except Exception as e:
                    st.error(f"Falha na importação: {e}")

# --- Aba Dashboard
with aba_dashboard:
    st.header("Dashboard")
    df_lanc = pd.read_sql_query("SELECT date, description, value, account FROM transactions", conn)
    if df_lanc.empty:
        st.info("Nenhum lançamento encontrado.")
    else:
        contas_disp = sorted(df_lanc["account"].unique().tolist())
        contas_sel = st.multiselect("Filtrar por conta:", options=contas_disp, default=contas_disp)
        df_filt = df_lanc[df_lanc["account"].isin(contas_sel)]
        incluir_saldo = st.checkbox("Incluir linhas de saldo", value=False)
        if not incluir_saldo:
            df_filt = df_filt[~df_filt["description"].str.upper().str.startswith("SALDO")]
        resumo = df_filt.groupby("account")["value"].sum().reset_index()
        st.subheader("Saldo por Conta")
        st.dataframe(resumo)
        st.subheader("Lançamentos")
        st.dataframe(df_filt.sort_values("date", ascending=False))

# --- Aba Contas
with aba_contas:
    st.header("⚙️ Contas")
    cursor.execute("SELECT nome FROM contas ORDER BY nome")
    contas = [r[0] for r in cursor.fetchall()]
    if contas:
        st.write("Contas cadastradas:")
        for c in contas:
            st.write("-", c)
    else:
        st.write("Nenhuma conta cadastrada.")

    nova = st.text_input("Adicionar nova conta:")
    if st.button("Adicionar"):
        if nova.strip():
            try:
                cursor.execute("INSERT INTO contas (nome) VALUES (?)", (nova.strip(),))
                conn.commit()
                st.success(f"Conta '{nova.strip()}' adicionada.")
            except sqlite3.IntegrityError:
                st.error("Essa conta já existe.")
        else:
            st.error("Digite um nome válido.")
