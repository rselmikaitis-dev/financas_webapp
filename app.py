import streamlit as st
from streamlit_option_menu import option_menu
from db import init_db

st.set_page_config(page_title="Controle Financeiro", page_icon="💰", layout="wide")

# Banco de dados
conn, cursor = init_db()

with st.sidebar:
    menu = option_menu(
        "Menu",
        ["Dashboard", "Lançamentos", "Importação", "Configurações"],
        menu_icon=None,
        icons=["","","",""],
        default_index=0
    )

if menu == "Dashboard":
    dashboard.show(conn)
elif menu == "Lançamentos":
    lancamentos.show(conn)
elif menu == "Importação":
    importacao.show(conn)
elif menu == "Configurações":
    configuracoes.show(conn)
