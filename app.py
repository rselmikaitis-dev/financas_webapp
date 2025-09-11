import streamlit as st
import pandas as pd
import numpy as np
import sqlite3
from datetime import date
from io import BytesIO

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
def to_lancamentos(df, data_col, desc_col, deb_col, cred_col, origem, conta_nome, cat_col=None):
    df2 = df.copy()

    # parse date
    df2["__data"] = pd.to_datetime(df2[data_col], errors="coerce", dayfirst=True)

    # description
    df2["__descricao"] = df2[desc_col].astype(str)

    # value = credit - debit
    deb_v = pd.to_numeric(df2[deb_col].astype(str)
                          .str.replace(",", ".", regex=False)
                          .str.replace("R$", "", regex=False)
                          .str.replace(".", "", regex=False),
                          errors="coerce").fillna(0)

    cred_v = pd.to_numeric(df2[cred_col].astype(str)
                           .str.replace(",", ".", regex=False)
                           .str.replace("R$", "", regex=False)
                           .str.replace(".", "", regex=False),
                           errors="coerce").fillna(0)

    vals = cred_v - deb_v

    categoria = df2[cat_col].astype(str) if cat_col and cat_col in df2.columns else ""

    out = pd.DataFrame({
        "data": df2["__data"],
        "descricao": df2["__descricao"],
        "categoria": categoria,
        "conta": conta_nome,
        "origem": origem,
        "valor": vals
    }).dropna(subset=["data"])

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
            st.write("Prévia dos dados:")
            st.dataframe(df.head(20), use_container_width=True)

            data_col = st.selectbox("Coluna de Data", options=df.columns.tolist())
            desc_col = st.selectbox("Coluna de Descrição", options=df.columns.tolist())
            deb_col = st.selectbox("Coluna Débito", options=df.columns.tolist())
            cred_col = st.selectbox("Coluna Crédito", options=df.columns.tolist())
            cat_col = st.selectbox("Coluna de Categoria (opcional)", options=["<nenhuma>"] + df.columns.tolist())

            if st.button("Importar"):
                try:
                    df_norm = to_lancamentos(df, data_col, desc_col, deb_col, cred_col,
                                             origem=origem, conta_nome=conta_nome,
                                             cat_col=None if cat_col == "<nenhuma>" else cat_col)
                    rows = df_norm.to_dict(orient="records")
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
