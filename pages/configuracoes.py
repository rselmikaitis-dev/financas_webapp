import sys, os
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

import pandas as pd
import sqlite3
import streamlit as st
from db import init_db

st.header("⚙️ Configurações")

conn, cursor = init_db()

tab1, tab2, tab3, tab4 = st.tabs(["Dados", "Contas", "Categorias", "Subcategorias"])

with tab1:
    st.subheader("Backup & Restauração")
    if st.button("📥 Baixar Backup"):
        st.success("Aqui você poderia exportar os dados.")
    st.warning("Função de backup/restore em construção.")

with tab2:
    st.subheader("Contas")
    st.info("Gerenciamento de contas aqui.")

with tab3:
    st.subheader("Categorias")
    st.info("Gerenciamento de categorias aqui.")

with tab4:
    st.subheader("Subcategorias")
    st.info("Gerenciamento de subcategorias aqui.")
