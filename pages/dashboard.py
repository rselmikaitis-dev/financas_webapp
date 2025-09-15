import streamlit as st
import pandas as pd
from helpers import seletor_mes_ano

def show(conn):
    st.header("Dashboard Financeiro")
    df_lanc = pd.read_sql_query("""
        SELECT t.id, t.date, t.description, t.value, t.account,
               c.nome as categoria, s.nome as subcategoria
        FROM transactions t
        LEFT JOIN subcategorias s ON t.subcategoria_id = s.id
        LEFT JOIN categorias   c ON s.categoria_id   = c.id
    """, conn)

    if df_lanc.empty:
        st.info("Nenhum lançamento encontrado.")
        return

    mes_sel, ano_sel = seletor_mes_ano(st, "Dashboard", pd.to_datetime("today"))
    df_lanc["date"] = pd.to_datetime(df_lanc["date"], errors="coerce")
    df_lanc["Ano"] = df_lanc["date"].dt.year
    df_lanc["Mês"] = df_lanc["date"].dt.month

    st.subheader("📊 Dashboard Principal")

    def gerar_tabela(df_base, titulo):
        df_base["Mês Nome"] = df_base["Mês"].map({
            1:"Jan",2:"Fev",3:"Mar",4:"Abr",5:"Mai",6:"Jun",
            7:"Jul",8:"Ago",9:"Set",10:"Out",11:"Nov",12:"Dez"
        })
        pivot = df_base.pivot_table(
            index="subcategoria",
            columns="Mês Nome",
            values="value",
            aggfunc="sum",
            fill_value=0
        ).reset_index()
        total = pivot.drop(columns=["subcategoria"]).sum().to_frame().T
        total.insert(0, "subcategoria", f"{titulo} (Total)")
        pivot = pd.concat([total, pivot], ignore_index=True)
        for col in pivot.columns[1:]:
            pivot[col] = pivot[col].apply(lambda x: f"R$ {x:,.2f}")
        return pivot

    # Receitas
    st.markdown("### Receitas")
    df_receitas = df_lanc[
        (df_lanc["Ano"] == ano_sel) & 
        (df_lanc["value"] > 0) & 
        (df_lanc["categoria"] == "Receita")
    ].copy()
    if not df_receitas.empty:
        st.dataframe(gerar_tabela(df_receitas, "Receitas"), use_container_width=True)
    else:
        st.info("Não há receitas neste ano.")

    st.markdown("---")

    # Investimentos
    st.markdown("### Investimentos")
    df_inv = df_lanc[
        (df_lanc["Ano"] == ano_sel) & 
        (df_lanc["categoria"] == "Investimento")
    ].copy()
    if not df_inv.empty:
        st.dataframe(gerar_tabela(df_inv, "Investimentos"), use_container_width=True)
    else:
        st.info("Não há investimentos neste ano.")
