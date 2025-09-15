import sys, os
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

import pandas as pd
import streamlit as st
from helpers import seletor_mes_ano
from db import init_db

st.header("📊 Dashboard")

conn, cursor = init_db()
df = pd.read_sql_query("SELECT * FROM transactions", conn)

if df.empty:
    st.info("Nenhum lançamento encontrado.")
else:
    mes_sel, ano_sel = seletor_mes_ano("Período", None)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")

    df_mes = df[(df["date"].dt.month == mes_sel) & (df["date"].dt.year == ano_sel)]
    if df_mes.empty:
        st.warning("Nenhum lançamento neste período.")
    else:
        entradas = df_mes[df_mes["value"] > 0]["value"].sum()
        saidas = df_mes[df_mes["value"] < 0]["value"].sum()
        saldo = entradas + saidas

        c1, c2, c3 = st.columns(3)
        c1.metric("Entradas", f"R$ {entradas:,.2f}")
        c2.metric("Saídas", f"R$ {saidas:,.2f}")
        c3.metric("Saldo", f"R$ {saldo:,.2f}")

        st.dataframe(df_mes, use_container_width=True)
