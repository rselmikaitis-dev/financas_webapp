import streamlit as st
import pandas as pd
import numpy as np
import sqlite3
from datetime import date
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode

st.set_page_config(page_title="Controle Financeiro Familiar", layout="wide")

DB_PATH = "data.db"

# ---------- Persistence Helpers ----------
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

# ---------- Transform Helpers ----------
def to_lancamentos(df, data_col, desc_col, valor_col, origem, conta_nome, cat_col=None):
    df2 = df.copy()

    # Ignorar linhas cuja descrição começa com "SALDO"
    if desc_col in df2.columns:
        df2 = df2[~df2[desc_col].astype(str).str.strip().str.upper().str.startswith("SALDO")]

    # Data
    df2["__data"] = pd.to_datetime(df2[data_col], errors="coerce", dayfirst=True)

    # Descrição
    df2["__descricao"] = df2[desc_col].astype(str)

    # Valor (positivo = crédito, negativo = débito)
    # Trata valores como "1.234,56", "-1.234,56", "R$ 1.234,56"
    vals = (
        df2[valor_col].astype(str)
        .str.replace("R$", "", regex=False)
        .str.replace(" ", "", regex=False)
    )
    # Remove separador de milhares brasileiro e americano
    # Primeiro troca milhar brasileiro "." por nada, depois vírgula decimal por ponto
    vals = vals.str.replace(".", "", regex=False).str.replace(",", ".", regex=False)

    # Caso venha no padrão americano "1,234.56": remover vírgulas restantes
    vals = vals.str.replace(",", "", regex=False)

    vals = pd.to_numeric(vals, errors="coerce")

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

# ---------- UI ----------
st.title("💸 Controle Financeiro Familiar")

conn = get_conn()

tab1, tab2, tab3, tab4 = st.tabs(["📥 Importar", "📊 Painel Mensal", "📅 Provisões", "📤 Exportar"])

# --- Importar
with tab1:
    st.subheader("Importar Arquivos")
    conta_nome = st.text_input("Nome da conta/cartão", value="Conta Principal")
    uploaded = st.file_uploader("Selecione um arquivo (CSV, XLS, XLSX)", type=["csv", "xls", "xlsx"])
    origem = st.selectbox("Origem do arquivo", ["conta_corrente", "cartao"])

    # Estado de modo de seleção: 'manual' | 'all' | 'none'
    if "sel_mode" not in st.session_state:
        st.session_state["sel_mode"] = "manual"

    if uploaded is not None:
        try:
            if uploaded.name.lower().endswith(".csv"):
                df = pd.read_csv(uploaded, sep=None, engine="python")
            else:
                df = pd.read_excel(uploaded)
        except Exception as e:
            st.error(f"Erro ao ler arquivo: {e}")
            df = None

        if df is not None and not df.empty:
            st.caption("Obs.: Linhas cuja descrição começar com **SALDO** serão **ignoradas** ao importar.")
            st.write("Prévia dos dados (selecione as linhas para importar ou use os botões abaixo):")

            gb = GridOptionsBuilder.from_dataframe(df.head(500))
            gb.configure_selection(selection_mode="multiple", use_checkbox=True)
            gb.configure_grid_options(rowSelection="multiple")
            grid_options = gb.build()

            grid_response = AgGrid(
                df,
                gridOptions=grid_options,
                update_mode=GridUpdateMode.SELECTION_CHANGED,
                fit_columns_on_grid_load=True,
                enable_enterprise_modules=False,
                theme="balham",
                height=420,
            )

            selected_manual = pd.DataFrame(grid_response.get("selected_rows", []))

            c1, c2, c3 = st.columns(3)
            with c1:
                if st.button("Selecionar tudo", key="btn_all"):
                    st.session_state["sel_mode"] = "all"
            with c2:
                if st.button("Limpar seleção", key="btn_none"):
                    st.session_state["sel_mode"] = "none"
            with c3:
                if st.button("Usar seleção manual do grid", key="btn_manual"):
                    st.session_state["sel_mode"] = "manual"

            sel_mode = st.session_state["sel_mode"]

            # Decide o conjunto efetivo de linhas a importar
            if sel_mode == "all":
                base_sel = df.copy()
            elif sel_mode == "none":
                base_sel = df.iloc[0:0].copy()
            else:
                base_sel = selected_manual.copy()

            st.markdown(f"**Modo de seleção:** `{sel_mode}` — **{len(base_sel)}** linha(s) atualmente selecionada(s).")

            # Mapear colunas
            data_col = st.selectbox("Coluna de Data", options=df.columns.tolist(), key="col_data")
            desc_col = st.selectbox("Coluna de Descrição", options=df.columns.tolist(), key="col_desc")
            valor_col = st.selectbox("Coluna de Valor (+/–)", options=df.columns.tolist(), key="col_valor")
            cat_col = st.selectbox("Coluna de Categoria (opcional)", options=["<nenhuma>"] + df.columns.tolist(), key="col_cat")

            # Mostrar quantas linhas restam após regras (saldo e datas/valores válidos)
            if not base_sel.empty:
                try:
                    preview_norm = to_lancamentos(
                        base_sel,
                        data_col,
                        desc_col,
                        valor_col,
                        origem=origem,
                        conta_nome=conta_nome,
                        cat_col=None if cat_col == "<nenhuma>" else cat_col
                    )
                    st.caption(f"Prévia da normalização: {len(preview_norm)} linha(s) seriam importadas após filtros.")
                    st.dataframe(preview_norm.head(10), use_container_width=True)
                except Exception as e:
                    st.warning(f"Não foi possível pré-visualizar a normalização: {e}")

            if st.button("Importar linhas selecionadas", key="btn_import"):
                try:
                    if base_sel.empty:
                        st.warning("Nenhuma linha selecionada!")
                    else:
                        df_norm = to_lancamentos(
                            base_sel,
                            data_col,
                            desc_col,
                            valor_col,
                            origem=origem,
                            conta_nome=conta_nome,
                            cat_col=None if cat_col == "<nenhuma>" else cat_col
                        )
                        rows = df_norm.to_dict(orient="records")
                        if not rows:
                            st.warning("Nada para importar após aplicar filtros de data/valor e ignorar SALDO.")
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
