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
# Garantir coluna dia_vencimento
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
def to_datestr(x) -> str:
    if isinstance(x, (datetime, pd.Timestamp)):
        return x.strftime("%Y-%m-%d")
    if isinstance(x, date):
        return x.strftime("%Y-%m-%d")
    return str(x)

def parse_money(val) -> float | None:
    if pd.isna(val):
        return None
    s = str(val).strip()
    if s == "":
        return None
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg = True
        s = s[1:-1].strip()
    s = re.sub(r"[^0-9,.\-+]", "", s)
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    s = re.sub(r"(?<!^)[\+\-]", "", s)
    try:
        num = float(s)
    except ValueError:
        return None
    return -num if neg else num

# =====================
# MENU LATERAL
# =====================
with st.sidebar:
    menu = option_menu(
        "Menu",
        ["📊 Dashboard", "📥 Importação", "⚙️ Contas"],
        icons=["bar-chart", "cloud-upload", "gear"],
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
        # Seleção de mês e ano
        col1, col2 = st.columns(2)
        with col1:
            mes_sel = st.number_input("Mês", min_value=1, max_value=12, value=datetime.today().month)
        with col2:
            ano_sel = st.number_input("Ano", min_value=2000, max_value=2100, value=datetime.today().year)

        # Converter datas
        df_lanc["date"] = pd.to_datetime(df_lanc["date"], errors="coerce")
        df_lanc = df_lanc.dropna(subset=["date"])

        # Filtro por mês/ano
        df_mes = df_lanc[(df_lanc["date"].dt.month == mes_sel) & (df_lanc["date"].dt.year == ano_sel)]

        if df_mes.empty:
            st.warning(f"Nenhum lançamento encontrado para {mes_sel:02d}/{ano_sel}.")
        else:
            # Resumo entradas/saídas
            entradas = df_mes[df_mes["value"] > 0]["value"].sum()
            saidas = df_mes[df_mes["value"] < 0]["value"].sum()
            saldo = entradas + saidas

            st.subheader(f"Resumo {mes_sel:02d}/{ano_sel}")
            col1, col2, col3 = st.columns(3)
            col1.metric("Entradas", f"R$ {entradas:,.2f}")
            col2.metric("Saídas", f"R$ {saidas:,.2f}")
            col3.metric("Saldo", f"R$ {saldo:,.2f}")

            st.subheader("Lançamentos do período")
            st.dataframe(
                df_mes.sort_values("date", ascending=False),
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
                mes_ref = st.number_input("Mês da fatura", 1, 12, value=datetime.today().month)
                ano_ref = st.number_input("Ano da fatura", 2000, 2100, value=datetime.today().year)
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
                else:
                    df = pd.read_excel(arquivo)

                df = df.iloc[:, :3]
                df.columns = ["Data", "Descrição", "Valor"]
                df["Data"] = df["Data"].apply(to_datestr)
                df["ValorNum"] = df["Valor"].apply(parse_money)
            except Exception as e:
                st.toast(f"Erro ao ler/normalizar o arquivo: {e} ⚠️", icon="⚠️")
                st.stop()

            mask_not_saldo = ~df["Descrição"].astype(str).str.strip().str.upper().str.startswith("SALDO")
            mask_val_ok = df["ValorNum"].notna()
            df_filtrado = df.loc[mask_not_saldo & mask_val_ok, ["Data", "Descrição", "ValorNum"]].copy()
            df_filtrado.rename(columns={"ValorNum": "Valor"}, inplace=True)

            # Ajustes para cartão de crédito
            if conta_escolhida.lower().startswith("cartão de crédito"):
                if data_vencimento:
                    df_filtrado["Data"] = to_datestr(data_vencimento)
                df_filtrado["Valor"] = df_filtrado["Valor"] * -1

            st.markdown("### Pré-visualização")
            st.dataframe(df_filtrado.head(30), use_container_width=True)

            if st.button(f"Importar para {conta_escolhida}"):
                try:
                    for _, row in df_filtrado.iterrows():
                        cursor.execute(
                            "INSERT INTO transactions (date, description, value, account) VALUES (?, ?, ?, ?)",
                            (str(row["Data"]), str(row["Descrição"]), float(row["Valor"]), conta_escolhida)
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

        # Editar
        st.subheader("Editar conta")
        if len(nomes_sel) == 1:
            old_name = nomes_sel[0]
            cursor.execute("SELECT dia_vencimento FROM contas WHERE nome=?", (old_name,))
            row = cursor.fetchone()
            venc_atual = row[0] if row else None

            new_name = st.text_input("Novo nome", value=old_name, key=f"edit_{old_name}")
            new_dia = None
            if old_name.lower().startswith("cartão de crédito") or new_name.lower().startswith("cartão de crédito"):
                new_dia = st.number_input(
                    "Dia do vencimento",
                    min_value=1, max_value=31,
                    value=int(venc_atual) if venc_atual else 1
                )

            if st.button("Salvar alteração"):
                new_name_clean = new_name.strip()
                try:
                    cursor.execute("UPDATE contas SET nome=?, dia_vencimento=? WHERE nome=?", (new_name_clean, new_dia, old_name))
                    cursor.execute("UPDATE transactions SET account=? WHERE account=?", (new_name_clean, old_name))
                    conn.commit()
                    st.toast(f"Conta atualizada: '{old_name}' → '{new_name_clean}' ✅", icon="✏️")
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.toast(f"Já existe uma conta chamada '{new_name_clean}' ⚠️", icon="⚠️")
        elif len(nomes_sel) > 1:
            st.caption("Selecione apenas **uma** conta para editar.")
        else:
            st.caption("Selecione uma conta no grid para editar.")

        # Excluir
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

    # Adicionar
    st.subheader("Adicionar nova conta")
    nova = st.text_input("Nome da nova conta:")
    dia_venc = None
    if nova.lower().startswith("cartão de crédito"):
        dia_venc = st.number_input("Dia do vencimento", min_value=1, max_value=31, value=1)

    if st.button("Adicionar conta"):
        if nova.strip():
            try:
                cursor.execute("INSERT INTO contas (nome, dia_vencimento) VALUES (?, ?)", (nova.strip(), dia_venc))
                conn.commit()
                st.toast(f"Conta '{nova.strip()}' adicionada ➕", icon="💳")
                st.rerun()
            except sqlite3.IntegrityError:
                st.toast("Essa conta já existe ⚠️", icon="⚠️")
        else:
            st.toast("Digite um nome válido ⚠️", icon="⚠️")
