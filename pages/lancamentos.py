import sys, os
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

import pandas as pd
import streamlit as st
from st_aggrid import GridOptionsBuilder, AgGrid, GridUpdateMode
from db import init_db
from helpers import parse_money, parse_date

st.header("📑 Lançamentos")

conn, cursor = init_db()

df = pd.read_sql_query("""
    SELECT t.id, t.date, t.description, t.value, t.account,
           COALESCE(c.nome || ' → ' || s.nome, 'Nenhuma') AS cat_sub
    FROM transactions t
    LEFT JOIN subcategorias s ON t.subcategoria_id = s.id
    LEFT JOIN categorias c ON s.categoria_id = c.id
    ORDER BY t.date DESC
""", conn)

if df.empty:
    st.info("Nenhum lançamento encontrado.")
else:
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df.rename(columns={
        "id": "ID",
        "date": "Data",
        "description": "Descrição",
        "value": "Valor",
        "account": "Conta",
        "cat_sub": "Categoria/Subcategoria"
    }, inplace=True)

    gb = GridOptionsBuilder.from_dataframe(df)
    gb.configure_default_column(editable=False)
    gb.configure_column("Categoria/Subcategoria", editable=True)
    gb.configure_selection("multiple", use_checkbox=True)

    grid = AgGrid(
        df,
        gridOptions=gb.build(),
        update_mode=GridUpdateMode.MODEL_CHANGED,
        data_return_mode="AS_INPUT",
        fit_columns_on_grid_load=True,
        height=420,
        theme="balham"
    )

    st.markdown(f"**Total de lançamentos: {len(df)}**")
