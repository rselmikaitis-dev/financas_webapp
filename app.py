import streamlit as st
import pandas as pd
import sqlite3
import bcrypt
from streamlit_option_menu import option_menu
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode

st.set_page_config(page_title="Controle Financeiro", page_icon="💰", layout="wide")

# =====================
# AUTENTICAÇÃO
# =====================

AUTH_USERNAME = st.secrets.get("AUTH_USERNAME", "rafael")
AUTH_PASSWORD_BCRYPT = st.secrets.get(
    "AUTH_PASSWORD_BCRYPT",
    "$2b$12$abcdefghijklmnopqrstuv1234567890abcdefghijklmnopqrstuv12"  # substitua pelo seu hash
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

    with st.expander("Gerar hash bcrypt (para configurar Secrets)"):
        new_pass = st.text_input("Digite a senha para gerar hash", type="password")
        if st.button("Gerar hash bcrypt"):
            if new_pass:
                hashed = bcrypt.hashpw(new_pass.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
                st.code(hashed, language="text")
            else:
                st.toast("Digite uma senha ⚠️", icon="⚠️")

if "auth_ok" not in st.session_state or not st.session_state["auth_ok"]:
    login_view()
    st.stop()

# Botão de logout no topo
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
# MENU LATERAL MODERNO
# =====================
with st.sidebar:
    menu = option_menu(
        "Menu",
        ["📥 Importação", "📊 Dashboard", "⚙️ Contas"],
        icons=["cloud-upload", "bar-chart", "gear"],
        menu_icon="cast",
        default_index=0,
        orientation="vertical"
    )

# =====================
# IMPORTAÇÃO
# =====================
if menu == "📥 Importação":
    st.header("Importação de Lançamentos")

    cursor.execute("SELECT nome FROM contas ORDER BY nome")
    contas_cadastradas = [row[0] for row in cursor.fetchall()]

    if not contas_cadastradas:
        st.info("Nenhuma conta cadastrada. Cadastre uma conta na seção ⚙️ Contas antes de importar lançamentos.")
    else:
        conta_escolhida = st.selectbox("Conta/cartão", options=contas_cadastradas)
        arquivo = st.file_uploader("Selecione o arquivo do extrato ou fatura", type=["xls", "xlsx", "csv"])

        if arquivo is not None:
            try:
                if arquivo.name.lower().endswith(".csv"):
                    df = pd.read_csv(arquivo, sep=None, engine="python")
                else:
                    df = pd.read_excel(arquivo)
            except Exception as e:
                st.toast(f"Erro ao ler o arquivo: {e} ⚠️", icon="⚠️")
                st.stop()

            colunas = df.columns.tolist()
            st.markdown("### Mapeamento de colunas")
            data_col = st.selectbox("Coluna de Data", options=colunas, key="import_data_col")
            desc_col = st.selectbox("Coluna de Descrição", options=colunas, key="import_desc_col")

            if ("Débito" in colunas or "Debito" in colunas) and ("Crédito" in colunas or "Credito" in colunas):
                deb_col = st.selectbox("Coluna de Débito", options=colunas, key="import_deb_col")
                cred_col = st.selectbox("Coluna de Crédito", options=colunas, key="import_cred_col")
                valor_col = None
            else:
                valor_col = st.selectbox("Coluna de Valor (+/–)", options=colunas, key="import_val_col")
                deb_col, cred_col = None, None

            df_filtrado = df[~df[desc_col].astype(str).str.strip().str.upper().str.startswith("SALDO")]

            preview = []
            for _, row in df_filtrado.iterrows():
                data_str = str(row[data_col])
                descricao = str(row[desc_col])

                if valor_col is not None:
                    raw_val = row[valor_col]
                    valor = float(raw_val) if pd.notna(raw_val) else 0.0
                else:
                    valor = 0.0
                    if pd.notna(row[cred_col]):
                        valor += float(row[cred_col])
                    if pd.notna(row[deb_col]):
                        valor -= float(row[deb_col])

                preview.append({"Data": data_str, "Descrição": descricao, "Valor": valor, "Conta": conta_escolhida})

            df_preview = pd.DataFrame(preview)

            st.markdown("### Pré-visualização (linhas SALDO removidas)")
            st.dataframe(df_preview.head(30), use_container_width=True)

            if st.button(f"Importar para {conta_escolhida}"):
                try:
                    for _, row in df_preview.iterrows():
                        cursor.execute(
                            "INSERT INTO transactions (date, description, value, account) VALUES (?, ?, ?, ?)",
                            (row["Data"], row["Descrição"], float(row["Valor"]), row["Conta"])
                        )
                    conn.commit()
                    st.toast(f"{len(df_preview)} lançamentos importados para {conta_escolhida} 💰", icon="📥")
                except Exception as e:
                    st.toast(f"Falha na importação: {e} ⚠️", icon="⚠️")

# =====================
# DASHBOARD
# =====================
elif menu == "📊 Dashboard":
    st.header("Dashboard Financeiro")

    df_lanc = pd.read_sql_query("SELECT date, description, value, account FROM transactions", conn)
    if df_lanc.empty:
        st.info("Nenhum lançamento encontrado.")
    else:
        contas_disp = sorted(df_lanc["account"].unique().tolist())
        contas_sel = st.multiselect("Filtrar por conta:", options=contas_disp, default=contas_disp)
        df_filt = df_lanc[df_lanc["account"].isin(contas_sel)]

        incluir_saldo = st.checkbox("Incluir linhas de saldo", value=False)
        if not incluir_saldo:
            df_filt = df_filt[~df_filt["description"].astype(str).str.upper().str.startswith("SALDO")]

        resumo = df_filt.groupby("account", as_index=False)["value"].sum()
        resumo.columns = ["Conta", "Saldo (soma dos valores)"]

        st.subheader("Saldo por Conta")
        st.dataframe(resumo, use_container_width=True)

        st.subheader("Lançamentos")
        st.dataframe(df_filt.sort_values("date", ascending=False), use_container_width=True)

# =====================
# CONTAS
# =====================
elif menu == "⚙️ Contas":
    st.header("⚙️ Contas")

    cursor.execute("SELECT nome FROM contas ORDER BY nome")
    contas_rows = cursor.fetchall()
    df_contas = pd.DataFrame(contas_rows, columns=["Conta"])

    if df_contas.empty:
        st.info("Nenhuma conta cadastrada ainda.")
    else:
        gb = GridOptionsBuilder.from_dataframe(df_contas)
        gb.configure_default_column(editable=True)
        gb.configure_selection(selection_mode="multiple", use_checkbox=True)
        grid_options = gb.build()

        grid = AgGrid(
            df_contas,
            gridOptions=grid_options,
            update_mode=GridUpdateMode.MODEL_CHANGED,
            fit_columns_on_grid_load=True,
            height=280,
            theme="balham"
        )

        # Edição inline
        updated_df = pd.DataFrame(grid["data"])
        if not updated_df.equals(df_contas):
            for old, new in zip(df_contas["Conta"], updated_df["Conta"]):
                if old != new:
                    try:
                        cursor.execute("UPDATE contas SET nome=? WHERE nome=?", (new, old))
                        cursor.execute("UPDATE transactions SET account=? WHERE account=?", (new, old))
                        conn.commit()
                        st.toast(f"Conta renomeada: '{old}' → '{new}' ✅", icon="✏️")
                        st.rerun()
                    except sqlite3.IntegrityError:
                        st.toast(f"Já existe uma conta chamada '{new}' ⚠️", icon="⚠️")

        # Exclusão
        selected_rows = grid.get("selected_rows", [])
        if isinstance(selected_rows, pd.DataFrame):
            selected_rows = selected_rows.to_dict("records")

        nomes_sel = [r["Conta"] for r in selected_rows] if selected_rows else []

        if nomes_sel:
            st.warning(f"Selecionadas para exclusão: {', '.join(nomes_sel)}")
            confirm = st.checkbox("Confirmar exclusão")
            if confirm and st.button("Excluir selecionadas"):
                for nome in nomes_sel:
                    cursor.execute("DELETE FROM transactions WHERE account=?", (nome,))
                    cursor.execute("DELETE FROM contas WHERE nome=?", (nome,))
                conn.commit()
                st.toast("Contas excluídas com sucesso 🗑️", icon="🗑️")
                st.rerun()

    # Adicionar nova conta
    st.subheader("Adicionar nova conta")
    nova = st.text_input("Nome da nova conta:")
    if st.button("Adicionar conta"):
        if nova.strip():
            try:
                cursor.execute("INSERT INTO contas (nome) VALUES (?)", (nova.strip(),))
                conn.commit()
                st.toast(f"Conta '{nova.strip()}' adicionada ➕", icon="💳")
                st.rerun()
            except sqlite3.IntegrityError:
                st.toast("Essa conta já existe ⚠️", icon="⚠️")
        else:
            st.toast("Digite um nome válido ⚠️", icon="⚠️")
