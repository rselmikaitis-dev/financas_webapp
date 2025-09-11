import streamlit as st
import pandas as pd
import numpy as np
import sqlite3
from datetime import date
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode
import bcrypt

st.set_page_config(page_title="Controle Financeiro Familiar", layout="wide")

DB_PATH = "data.db"

# =========================
# ====== AUTENTICAÇÃO =====
# =========================

# Pegue credenciais prioritariamente de st.secrets (ideal no Streamlit Cloud),
# com fallback para valores do código.
AUTH_USERNAME = st.secrets.get("AUTH_USERNAME", "rafael")
AUTH_PASSWORD_BCRYPT = st.secrets.get(
    "AUTH_PASSWORD_BCRYPT",
    # Substitua por um hash bcrypt seu (ex.: $2b$12$...):
    "$2b$12$abcdefghijklmnopqrstuv1234567890abcdefghijklmnopqrstuv12"
)

def check_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False

def login_view():
    st.title("🔐 Login – Controle Financeiro Familiar")
    with st.form("login_form", clear_on_submit=False):
        u = st.text_input("Usuário")
        p = st.text_input("Senha", type="password")
        submitted = st.form_submit_button("Entrar")
        if submitted:
            if u == AUTH_USERNAME and check_password(p, AUTH_PASSWORD_BCRYPT):
                st.session_state["auth_ok"] = True
                st.rerun()
            else:
                st.error("Usuário ou senha inválidos.")

    with st.expander("Gerar hash bcrypt (opcional)"):
        st.caption("Use isto para gerar um hash a partir de uma senha nova e colar em `st.secrets`.")
        new_pass = st.text_input("Digite a senha para gerar hash", type="password")
        if st.button("Gerar hash bcrypt"):
            if not new_pass:
                st.warning("Informe uma senha.")
            else:
                hashed = bcrypt.hashpw(new_pass.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
                st.code(hashed, language="text")
                st.info("Copie esse hash e configure em `AUTH_PASSWORD_BCRYPT` nos secrets.")

# Gate de autenticação
if "auth_ok" not in st.session_state or not st.session_state["auth_ok"]:
    login_view()
    st.stop()

# Botão de logout no topo
logout_col = st.columns(8)[-1]
with logout_col:
    if st.button("Sair", type="secondary"):
        st.session_state.clear()
        st.rerun()

# =========================
# ====== PERSISTÊNCIA =====
# =========================
def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS lancamentos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        data DATE NOT NULL,
        descricao TEXT,
        categoria TEXT,
        conta TEXT,
        origem TEXT, -- 'cartao' ou 'conta_corrente'
        valor REAL NOT NULL, -- negativo = saída, positivo = entrada
        competencia TEXT -- AAAA-MM
    )
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS provisoes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        competencia TEXT,
        descricao TEXT,
        categoria TEXT,
        valor REAL,
        recorrencia TEXT
    )
    """)
    return conn

def save_rows(conn, table, rows):
    if not rows:
        return 0
    cols = rows[0].keys()
    placeholders = ",".join(["?"]*len(cols))
    q = f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders})"
    cur = conn.cursor()
    cur.executemany(q, [tuple(r[c] for c in cols) for r in rows])
    conn.commit()
    return cur.rowcount

def read_df(conn, query, params=()):
    return pd.read_sql_query(query, conn, params=params)

# =========================
# ===== NORMALIZAÇÃO =====
# =========================
def normalize_numeric_series(series: pd.Series) -> pd.Series:
    # Trata "R$ 1.234,56", "-1.234,56", "1,234.56", etc.
    vals = series.astype(str).str.replace("R$", "", regex=False).str.replace(" ", "", regex=False)
    # Remoção do separador de milhar BR e troca vírgula decimal por ponto
    vals = vals.str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
    # Remoção de vírgulas remanescentes (caso formato en-US)
    vals = vals.str.replace(",", "", regex=False)
    return pd.to_numeric(vals, errors="coerce")

def to_lancamentos(df, data_col, desc_col, valor_col, origem, conta_nome, cat_col=None):
    df2 = df.copy()

    # Ignorar linhas que começam com "SALDO" (não apenas visual – também no import)
    if desc_col in df2.columns:
        df2 = df2[~df2[desc_col].astype(str).str.strip().str.upper().str.startswith("SALDO")]

    # Datas
    df2["__data"] = pd.to_datetime(df2[data_col], errors="coerce", dayfirst=True)

    # Descrição
    df2["__descricao"] = df2[desc_col].astype(str)

    # Valor (positivo = crédito, negativo = débito)
    vals = normalize_numeric_series(df2[valor_col])

    # Categoria (opcional)
    categoria = df2[cat_col].astype(str) if (cat_col and cat_col in df2.columns) else ""

    out = pd.DataFrame({
        "data": df2["__data"],
        "descricao": df2["__descricao"],
        "categoria": categoria,
        "conta": conta_nome,
        "origem": origem,
        "valor": vals
    }).dropna(subset=["data", "valor"])

    out["competencia"] = out["data"].dt.strftime("%Y-%m")
    return out

# =========================
# ========= UI ============
# =========================
st.title("💸 Controle Financeiro Familiar")

conn = get_conn()

tab1, tab2, tab3, tab4 = st.tabs(["📥 Importar", "📊 Painel Mensal", "📅 Provisões", "📤 Exportar"])

# --- Importar
with tab1:
    st.subheader("Importar Arquivos")
    conta_nome = st.text_input("Nome da conta/cartão", value="Conta Principal")
    uploaded = st.file_uploader("Selecione um arquivo (CSV, XLS, XLSX)", type=["csv", "xls", "xlsx"])
    origem = st.selectbox("Origem do arquivo", ["conta_corrente", "cartao"])

    if uploaded is not None:
        # Carregar arquivo
        try:
            if uploaded.name.lower().endswith(".csv"):
                raw_df = pd.read_csv(uploaded, sep=None, engine="python")
            else:
                raw_df = pd.read_excel(uploaded)
        except Exception as e:
            st.error(f"Erro ao ler arquivo: {e}")
            raw_df = None

        if raw_df is not None and not raw_df.empty:
            st.caption("Obs.: Linhas com descrição iniciando em **SALDO** serão ocultadas e não importadas.")

            # Mapeamento de colunas ANTES do grid,
            # para filtrarmos SALDO no DataFrame exibido.
            cols = raw_df.columns.tolist()
            # Tentativa de “chute” de colunas
            cols_lower = {c.lower(): c for c in cols}
            guess_data = next((cols_lower[k] for k in cols_lower if k in ["data", "date", "lançamento", "lan\u00e7amento", "dt"]), cols[0])
            guess_desc = next((cols_lower[k] for k in cols_lower if k in ["descricao", "descrição", "description", "history", "detalhe", "lançamento", "lan\u00e7amento"]), cols[min(1, len(cols)-1)])
            guess_val = next((cols_lower[k] for k in cols_lower if k in ["valor", "valor (r$)", "amount", "valor do lançamento", "vlr"]), cols[min(2, len(cols)-1)])

            data_col = st.selectbox("Coluna de Data", options=cols, index=cols.index(guess_data) if guess_data in cols else 0)
            desc_col = st.selectbox("Coluna de Descrição", options=cols, index=cols.index(guess_desc) if guess_desc in cols else 0)
            valor_col = st.selectbox("Coluna de Valor (+/–)", options=cols, index=cols.index(guess_val) if guess_val in cols else 0)
            cat_col = st.selectbox("Coluna de Categoria (opcional)", options=["<nenhuma>"] + cols)

            # Filtrar SALDO no DataFrame mostrado
            df_show = raw_df.copy()
            df_show = df_show[~df_show[desc_col].astype(str).str.strip().str.upper().str.startswith("SALDO")]

            st.write("Prévia dos dados (linhas SALDO removidas):")
            gb = GridOptionsBuilder.from_dataframe(df_show.head(1000))
            gb.configure_grid_options(rowSelection="single")  # apenas navegação; sem seleção múltipla
            grid_options = gb.build()

            AgGrid(
                df_show,
                gridOptions=grid_options,
                update_mode=GridUpdateMode.NO_UPDATE,
                fit_columns_on_grid_load=True,
                enable_enterprise_modules=False,
                theme="balham",
                height=420,
            )

            # Prévia da normalização (subset)
            try:
                preview_norm = to_lancamentos(
                    df_show.head(200),  # só para preview
                    data_col,
                    desc_col,
                    valor_col,
                    origem=origem,
                    conta_nome=conta_nome,
                    cat_col=None if cat_col == "<nenhuma>" else cat_col
                )
                st.caption(f"Prévia da normalização (primeiras {min(200, len(df_show))} linhas visíveis): {len(preview_norm)} linha(s).")
                st.dataframe(preview_norm.head(10), use_container_width=True)
            except Exception as e:
                st.warning(f"Não foi possível pré-visualizar a normalização: {e}")

            # Importar tudo (já com SALDO removido)
            if st.button("Importar tudo (sem SALDO)"):
                try:
                    df_norm = to_lancamentos(
                        df_show,  # SALDO já removido
                        data_col,
                        desc_col,
                        valor_col,
                        origem=origem,
                        conta_nome=conta_nome,
                        cat_col=None if cat_col == "<nenhuma>" else cat_col
                    )
                    rows = df_norm.to_dict(orient="records")
                    if not rows:
                        st.warning("Nada para importar após aplicar filtros de data/valor e remover SALDO.")
                    else:
                        n = save_rows(conn, "lancamentos", rows)
                        st.success(f"{n} lançamentos importados com sucesso.")
                except Exception as e:
                    st.error(f"Falha na importação: {e}")

# --- Painel
with tab2:
    st.subheader("Painel por Competência")
    lanc = read_df(conn, "SELECT * FROM lancamentos")
    if lanc.empty:
        st.info("Nenhum lançamento importado ainda.")
    else:
        lanc["data"] = pd.to_datetime(lanc["data"])
        lanc["competencia"] = lanc["data"].dt.strftime("%Y-%m")
        comp = st.selectbox("Competência", sorted(lanc["competencia"].unique()))
        filt = lanc[lanc["competencia"] == comp]

        colA, colB, colC = st.columns(3)
        total_entradas = filt.loc[filt["valor"] > 0, "valor"].sum()
        total_saidas = filt.loc[filt["valor"] < 0, "valor"].sum()
        saldo = filt["valor"].sum()
        with colA: st.metric("Entradas", f"R$ {total_entradas:,.2f}")
        with colB: st.metric("Saídas", f"R$ {total_saidas:,.2f}")
        with colC: st.metric("Saldo", f"R$ {saldo:,.2f}")

        by_cat = filt.groupby("categoria")["valor"].sum().sort_values()
        st.bar_chart(by_cat)

        st.markdown("#### Detalhes")
        st.dataframe(filt.sort_values("data"), use_container_width=True)

# --- Provisões
with tab3:
    st.subheader("Provisões")
    with st.form("prov_form"):
        comp = st.text_input("Competência (AAAA-MM)", value=pd.Timestamp.today().strftime("%Y-%m"))
        desc = st.text_input("Descrição", value="")
        cat = st.text_input("Categoria", value="Provisão")
        val = st.number_input("Valor (negativo para custo)", value=0.0, step=50.0, format="%.2f")
        rec = st.selectbox("Recorrência", ["mensal", "unico", "anual", "custom"])
        submitted = st.form_submit_button("Salvar Provisão")
        if submitted:
            rows = [{
                "competencia": comp,
                "descricao": desc,
                "categoria": cat,
                "valor": val,
                "recorrencia": rec
            }]
            n = save_rows(conn, "provisoes", rows)
            st.success("Provisão salva.")

    prov = read_df(conn, "SELECT * FROM provisoes")
    if not prov.empty:
        st.dataframe(prov, use_container_width=True)

# --- Exportar
with tab4:
    st.subheader("Exportar")
    lanc = read_df(conn, "SELECT * FROM lancamentos")
    prov = read_df(conn, "SELECT * FROM provisoes")

    if not lanc.empty:
        csv = lanc.to_csv(index=False).encode("utf-8")
        st.download_button("Baixar lançamentos (CSV)", data=csv, file_name="lancamentos.csv")

    if not prov.empty:
        csv2 = prov.to_csv(index=False).encode("utf-8")
        st.download_button("Baixar provisões (CSV)", data=csv2, file_name="provisoes.csv")
