import re
import sqlite3
import bcrypt
import pandas as pd
import streamlit as st
from datetime import date, datetime
from streamlit_option_menu import option_menu
from st_aggrid import GridOptionsBuilder, AgGrid, GridUpdateMode

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
    st.title("Login – Controle Financeiro Familiar")
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

# Contas
cursor.execute("""
    CREATE TABLE IF NOT EXISTS contas (
        id INTEGER PRIMARY KEY,
        nome TEXT UNIQUE,
        dia_vencimento INTEGER
    )
""")

# Categorias
cursor.execute("""
    CREATE TABLE IF NOT EXISTS categorias (
        id INTEGER PRIMARY KEY,
        nome TEXT UNIQUE
    )
""")

# Subcategorias
cursor.execute("""
    CREATE TABLE IF NOT EXISTS subcategorias (
        id INTEGER PRIMARY KEY,
        categoria_id INTEGER,
        nome TEXT,
        UNIQUE(categoria_id, nome),
        FOREIGN KEY (categoria_id) REFERENCES categorias(id) ON DELETE CASCADE
    )
""")

# Lançamentos
cursor.execute("""
    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY,
        date TEXT,
        description TEXT,
        value REAL,
        account TEXT,
        subcategoria_id INTEGER,
        FOREIGN KEY (subcategoria_id) REFERENCES subcategorias(id)
    )
""")
conn.commit()

# =====================
# HELPERS
# =====================
def parse_money(val) -> float | None:
    if pd.isna(val):
        return None
    s = str(val).strip()
    s = re.sub(r"[^\d,,-.]", "", s)  # mantém dígitos, vírgula, ponto e hífen
    # normaliza formato pt-BR -> ponto decimal
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    if s.endswith("-"):
        s = "-" + s[:-1]
    try:
        return float(s)
    except ValueError:
        return None

def parse_date(val):
    s = str(val).strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            continue
    return pd.NaT

def seletor_mes_ano(label="Período", data_default=None):
    if data_default is None:
        data_default = date.today()
    anos = list(range(2020, datetime.today().year + 2))
    meses = {
        1: "Janeiro", 2: "Fevereiro", 3: "Março",
        4: "Abril", 5: "Maio", 6: "Junho",
        7: "Julho", 8: "Agosto", 9: "Setembro",
        10: "Outubro", 11: "Novembro", 12: "Dezembro"
    }
    col1, col2 = st.columns(2)
    with col1:
        ano_sel = st.selectbox(f"{label} - Ano", anos, index=anos.index(data_default.year))
    with col2:
        mes_sel = st.selectbox(f"{label} - Mês", list(meses.keys()),
                               format_func=lambda x: meses[x],
                               index=data_default.month-1)
    return mes_sel, ano_sel

def read_table_transactions(conn):
    return pd.read_sql_query("""
        SELECT t.id, t.date, t.description, t.value, t.account,
               c.nome as categoria, s.nome as subcategoria
        FROM transactions t
        LEFT JOIN subcategorias s ON t.subcategoria_id = s.id
        LEFT JOIN categorias   c ON s.categoria_id   = c.id
    """, conn)

# =====================
# MENU LATERAL
# =====================
with st.sidebar:
    menu = option_menu(
        "Menu",
        ["Dashboard", "Lançamentos", "Importação", "Configurações"],
        menu_icon=None,
        icons=["", "", "", ""],
        default_index=0,
        orientation="vertical"
    )

# =====================
# DASHBOARD
# =====================
if menu == "Dashboard":
    st.header("Dashboard Financeiro")

    df_lanc = read_table_transactions(conn)

    if df_lanc.empty:
        st.info("Nenhum lançamento encontrado.")
    else:
        st.subheader("Selecione o mês e ano")
        mes_sel, ano_sel = seletor_mes_ano("Dashboard", date.today())

        df_lanc["date"] = pd.to_datetime(df_lanc["date"], errors="coerce")
        df_lanc = df_lanc.dropna(subset=["date"])
        df_mes = df_lanc[(df_lanc["date"].dt.month == mes_sel) & (df_lanc["date"].dt.year == ano_sel)]

        if df_mes.empty:
            st.warning(f"Nenhum lançamento encontrado para {mes_sel:02d}/{ano_sel}.")
        else:
            entradas = df_mes[df_mes["value"] > 0]["value"].sum()
            saidas   = df_mes[df_mes["value"] < 0]["value"].sum()
            saldo    = entradas + saidas

            st.subheader(f"Resumo {mes_sel:02d}/{ano_sel}")
            col1, col2, col3 = st.columns(3)
            col1.metric("Entradas", f"R$ {entradas:,.2f}")
            col2.metric("Saídas",   f"R$ {saidas:,.2f}")
            col3.metric("Saldo",    f"R$ {saldo:,.2f}")

# =====================
# LANÇAMENTOS
# =====================
elif menu == "Lançamentos":
    st.header("Lançamentos por período")

    mes_ref, ano_ref = seletor_mes_ano("Lançamentos", date.today())

    # Contas
    contas = ["Todas"] + [row[0] for row in cursor.execute("SELECT nome FROM contas ORDER BY nome")]
    conta_sel = st.selectbox("Filtrar por conta", contas)

    # Categorias/Subcategorias para filtros e edição
    cursor.execute("SELECT id, nome FROM categorias ORDER BY nome")
    categorias = cursor.fetchall()
    cat_map = {c[1]: c[0] for c in categorias}
    cat_list = ["Todas"] + list(cat_map.keys())
    categoria_sel = st.selectbox("Filtrar por categoria", cat_list)

    subcat_map = {"Nenhuma": None}
    if categoria_sel != "Todas":
        cursor.execute("SELECT id, nome FROM subcategorias WHERE categoria_id=? ORDER BY nome", (cat_map[categoria_sel],))
        for sid, s_nome in cursor.fetchall():
            subcat_map[f"{categoria_sel} → {s_nome}"] = sid
    else:
        cursor.execute("""
            SELECT s.id, s.nome, c.nome
            FROM subcategorias s
            JOIN categorias c ON s.categoria_id = c.id
            ORDER BY c.nome, s.nome
        """)
        for sid, s_nome, c_nome in cursor.fetchall():
            subcat_map[f"{c_nome} → {s_nome}"] = sid
    subcat_list = ["Todas"] + list(subcat_map.keys())
    subcategoria_sel = st.selectbox("Filtrar por subcategoria", subcat_list)

    # Dados
    df_lanc = read_table_transactions(conn)
    df_lanc["date"] = pd.to_datetime(df_lanc["date"], errors="coerce")
    df_lanc = df_lanc.dropna(subset=["date"])

    df_filtrado = df_lanc[(df_lanc["date"].dt.month == mes_ref) & (df_lanc["date"].dt.year == ano_ref)]
    if conta_sel != "Todas":
        df_filtrado = df_filtrado[df_filtrado["account"] == conta_sel]
    if categoria_sel != "Todas":
        df_filtrado = df_filtrado[df_filtrado["categoria"] == categoria_sel]
    if subcategoria_sel != "Todas":
        sub_nome = subcategoria_sel.split(" → ")[-1]
        df_filtrado = df_filtrado[df_filtrado["subcategoria"] == sub_nome]

    if df_filtrado.empty:
        st.warning(f"Nenhum lançamento encontrado para {mes_ref:02d}/{ano_ref}.")
    else:
        df_filtrado = df_filtrado.copy()
        # Valor inicial da coluna editável precisa bater com as opções do dropdown
        df_filtrado["Subcategoria"] = df_filtrado.apply(
            lambda r: "Nenhuma" if pd.isna(r["subcategoria"]) else f'{r["categoria"]} → {r["subcategoria"]}',
            axis=1
        )
        df_filtrado["Categoria"] = df_filtrado["categoria"].fillna("–")

        gb = GridOptionsBuilder.from_dataframe(
            df_filtrado[["id", "date", "description", "value", "account", "Categoria", "Subcategoria"]]
        )
        gb.configure_default_column(editable=False)
        gb.configure_column("Subcategoria", editable=True, cellEditor="agSelectCellEditor",
                            cellEditorParams={"values": list(subcat_map.keys())})
        gb.configure_column("Categoria", editable=False)
        gb.configure_column("id", hide=True)
        grid_options = gb.build()

        grid = AgGrid(
            df_filtrado,
            gridOptions=grid_options,
            update_mode=GridUpdateMode.VALUE_CHANGED,
            fit_columns_on_grid_load=True,
            height=420,
            theme="balham"
        )

        df_editado = pd.DataFrame(grid["data"])

        if st.button("Salvar alterações"):
            for _, row in df_editado.iterrows():
                sub_id = subcat_map.get(row["Subcategoria"], None)
                cursor.execute("UPDATE transactions SET subcategoria_id=? WHERE id=?", (sub_id, int(row["id"])))
            conn.commit()
            st.success("Alterações salvas com sucesso!")
            st.rerun()

# =====================
# IMPORTAÇÃO
# =====================
elif menu == "Importação":
    st.header("Importação de Lançamentos")

    arquivo = st.file_uploader("Selecione o arquivo (CSV, XLSX ou XLS)", type=["csv", "xlsx", "xls"])

    def _read_uploaded(file):
        name = file.name.lower()
        if name.endswith(".csv"):
            return pd.read_csv(file, sep=None, engine="python")
        if name.endswith(".xlsx"):
            return pd.read_excel(file, engine="openpyxl")
        if name.endswith(".xls"):
            try:
                return pd.read_excel(file, engine="xlrd")
            except Exception:
                raise RuntimeError("Para arquivos .xls, instale 'xlrd>=2.0' no ambiente ou converta para CSV/XLSX.")
        raise RuntimeError("Formato não suportado.")

    if arquivo is not None:
        try:
            df = _read_uploaded(arquivo)

            # Normaliza nomes e valida colunas
            df.columns = [c.strip().lower() for c in df.columns]
            esperadas = ["data", "descrição", "valor"]
            if not all(c in df.columns for c in esperadas):
                st.error("Arquivo inválido. Esperado: colunas 'data', 'descrição', 'valor'.")
            else:
                df = df.rename(columns={"data": "Data", "descrição": "Descrição", "valor": "Valor"})
                # Remove linhas SALDO
                df = df[~df["Descrição"].astype(str).str.upper().str.startswith("SALDO")]
                # Converte tipos
                df["Data"] = df["Data"].apply(parse_date)
                df["Valor"] = df["Valor"].apply(parse_money)

                # Seleciona conta
                contas = [row[0] for row in cursor.execute("SELECT nome FROM contas ORDER BY nome")]
                if not contas:
                    st.error("Nenhuma conta cadastrada. Vá em Configurações → Contas e adicione uma conta.")
                    st.stop()
                conta_sel = st.selectbox("Selecione a conta para os lançamentos", contas)

                # Subcategorias disponíveis
                cursor.execute("""
                    SELECT s.id, s.nome, c.nome
                    FROM subcategorias s
                    JOIN categorias c ON s.categoria_id = c.id
                    ORDER BY c.nome, s.nome
                """)
                subcat_map = {"Nenhuma": None}
                for sid, s_nome, c_nome in cursor.fetchall():
                    subcat_map[f"{c_nome} → {s_nome}"] = sid

                # Coluna editável
                df["Subcategoria"] = "Nenhuma"

                gb = GridOptionsBuilder.from_dataframe(df)
                gb.configure_default_column(editable=False)
                gb.configure_column("Subcategoria", editable=True, cellEditor="agSelectCellEditor",
                                    cellEditorParams={"values": list(subcat_map.keys())})
                grid_options = gb.build()

                grid = AgGrid(
                    df,
                    gridOptions=grid_options,
                    update_mode=GridUpdateMode.VALUE_CHANGED,
                    fit_columns_on_grid_load=True,
                    height=420,
                    theme="balham"
                )

                df_editado = pd.DataFrame(grid["data"])

                st.subheader("Prévia dos dados ajustados")
                st.dataframe(df_editado.head(20), use_container_width=True)

                if st.button("Importar lançamentos"):
                    inserted = 0
                    for _, row in df_editado.iterrows():
                        dt = row["Data"]
                        valor = row["Valor"]
                        desc = str(row["Descrição"])
                        if pd.isna(dt) or valor is None:
                            continue
                        cursor.execute("""
                            INSERT INTO transactions (date, description, value, account, subcategoria_id)
                            VALUES (?, ?, ?, ?, ?)
                        """, (
                            dt.strftime("%Y-%m-%d"),
                            desc,
                            float(valor),
                            conta_sel,
                            subcat_map.get(row["Subcategoria"], None)
                        ))
                        inserted += 1
                    conn.commit()
                    st.success(f"{inserted} lançamentos importados com sucesso!")
                    st.rerun()
        except Exception as e:
            st.error(f"Erro ao importar: {e}")

# =====================
# CONFIGURAÇÕES
# =====================
elif menu == "Configurações":
    st.header("Configurações")
    tab1, tab2, tab3 = st.tabs(["Contas", "Categorias", "Subcategorias"])

    # ---- CONTAS ----
    with tab1:
        st.subheader("Gerenciar Contas")
        cursor.execute("SELECT id, nome, dia_vencimento FROM contas ORDER BY nome")
        df_contas = pd.DataFrame(cursor.fetchall(), columns=["ID", "Conta", "Dia Vencimento"])

        if not df_contas.empty:
            st.dataframe(df_contas, use_container_width=True)

            conta_sel = st.selectbox("Selecione uma conta para editar/excluir", df_contas["Conta"])

            # Editar
            new_name = st.text_input("Novo nome da conta", value=conta_sel)
            new_venc = st.number_input("Novo dia de vencimento (se cartão)", min_value=1, max_value=31, value=1)
            if st.button("Salvar alteração de conta"):
                try:
                    cursor.execute("UPDATE contas SET nome=?, dia_vencimento=? WHERE nome=?", (new_name.strip(), new_venc, conta_sel))
                    # reflete nos lançamentos já importados
                    cursor.execute("UPDATE transactions SET account=? WHERE account=?", (new_name.strip(), conta_sel))
                    conn.commit()
                    st.success("Conta atualizada e refletida nos lançamentos!")
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error("Já existe uma conta com esse nome.")

            # Excluir
            if st.button("Excluir conta selecionada"):
                cursor.execute("DELETE FROM contas WHERE nome=?", (conta_sel,))
                conn.commit()
                st.warning("Conta excluída. Lançamentos permanecem com o nome antigo da conta.")
                st.rerun()
        else:
            st.info("Nenhuma conta cadastrada ainda.")

        # Nova conta
        nova = st.text_input("Nome da nova conta:")
        dia_venc = None
        if nova.lower().startswith("cartão de crédito"):
            dia_venc = st.number_input("Dia do vencimento", min_value=1, max_value=31, value=1)

        if st.button("Adicionar conta"):
            if nova.strip():
                try:
                    cursor.execute("INSERT INTO contas (nome, dia_vencimento) VALUES (?, ?)", (nova.strip(), dia_venc))
                    conn.commit()
                    st.success("Conta adicionada!")
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error("Essa conta já existe.")
            else:
                st.error("Digite um nome válido.")

    # ---- CATEGORIAS ----
    with tab2:
        st.subheader("Gerenciar Categorias")
        cursor.execute("SELECT id, nome FROM categorias ORDER BY nome")
        df_cat = pd.DataFrame(cursor.fetchall(), columns=["ID", "Nome"])

        if not df_cat.empty:
            st.dataframe(df_cat, use_container_width=True)
            cat_sel = st.selectbox("Selecione uma categoria para editar/excluir", df_cat["Nome"])

            new_name = st.text_input("Novo nome da categoria", value=cat_sel)
            if st.button("Salvar alteração de categoria"):
                try:
                    cursor.execute("UPDATE categorias SET nome=? WHERE nome=?", (new_name.strip(), cat_sel))
                    conn.commit()
                    st.success("Categoria atualizada!")
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error("Já existe uma categoria com esse nome.")

            if st.button("Excluir categoria selecionada"):
                # Excluir categoria -> apaga subcategorias (pelo nosso fluxo, não dependemos do PRAGMA)
                # Primeiro, limpar referências de transações para subcategorias dessa categoria
                cursor.execute("""
                    SELECT s.id
                    FROM subcategorias s
                    JOIN categorias c ON s.categoria_id = c.id
                    WHERE c.nome=?
                """, (cat_sel,))
                sub_ids = [r[0] for r in cursor.fetchall()]
                if sub_ids:
                    cursor.executemany("UPDATE transactions SET subcategoria_id=NULL WHERE subcategoria_id=?", [(sid,) for sid in sub_ids])
                    cursor.execute("DELETE FROM subcategorias WHERE id IN (%s)" % ",".join("?"*len(sub_ids)), sub_ids)
                cursor.execute("DELETE FROM categorias WHERE nome=?", (cat_sel,))
                conn.commit()
                st.warning("Categoria excluída. Subcategorias removidas e lançamentos desvinculados.")
                st.rerun()
        else:
            st.info("Nenhuma categoria cadastrada ainda.")

        nova_cat = st.text_input("Nome da nova categoria:")
        if st.button("Adicionar categoria"):
            if nova_cat.strip():
                try:
                    cursor.execute("INSERT INTO categorias (nome) VALUES (?)", (nova_cat.strip(),))
                    conn.commit()
                    st.success("Categoria adicionada!")
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error("Essa categoria já existe.")
            else:
                st.error("Digite um nome válido.")

    # ---- SUBCATEGORIAS ----
    with tab3:
        st.subheader("Gerenciar Subcategorias")
        cursor.execute("SELECT id, nome FROM categorias ORDER BY nome")
        categorias_opts = cursor.fetchall()

        if not categorias_opts:
            st.info("Cadastre uma categoria primeiro.")
        else:
            cat_map2 = {c[1]: c[0] for c in categorias_opts}
            cat_sel2 = st.selectbox("Categoria", list(cat_map2.keys()))
            nova_sub = st.text_input("Nome da nova subcategoria:")

            if st.button("Adicionar subcategoria"):
                if nova_sub.strip():
                    try:
                        cursor.execute(
                            "INSERT INTO subcategorias (categoria_id, nome) VALUES (?, ?)",
                            (cat_map2[cat_sel2], nova_sub.strip())
                        )
                        conn.commit()
                        st.success("Subcategoria adicionada!")
                        st.rerun()
                    except sqlite3.IntegrityError:
                        st.error("Essa subcategoria já existe nessa categoria.")
                else:
                    st.error("Digite um nome válido.")

            # Listagem
            cursor.execute("""
                SELECT s.id, s.nome, c.nome
                FROM subcategorias s
                JOIN categorias c ON s.categoria_id = c.id
                ORDER BY c.nome, s.nome
            """)
            df_sub = pd.DataFrame(cursor.fetchall(), columns=["ID", "Subcategoria", "Categoria"])

            if not df_sub.empty:
                st.dataframe(df_sub, use_container_width=True)

                sub_sel = st.selectbox("Selecione uma subcategoria para editar/excluir", df_sub["Subcategoria"])

                new_sub = st.text_input("Novo nome da subcategoria", value=sub_sel)
                if st.button("Salvar alteração de subcategoria"):
                    try:
                        cursor.execute("UPDATE subcategorias SET nome=? WHERE nome=?", (new_sub.strip(), sub_sel))
                        conn.commit()
                        st.success("Subcategoria atualizada!")
                        st.rerun()
                    except sqlite3.IntegrityError:
                        st.error("Já existe essa subcategoria nessa categoria.")

                if st.button("Excluir subcategoria selecionada"):
                    cursor.execute("SELECT id FROM subcategorias WHERE nome=?", (sub_sel,))
                    row = cursor.fetchone()
                    if row:
                        sub_id = row[0]
                        cursor.execute("UPDATE transactions SET subcategoria_id=NULL WHERE subcategoria_id=?", (sub_id,))
                        cursor.execute("DELETE FROM subcategorias WHERE id=?", (sub_id,))
                        conn.commit()
                        st.warning("Subcategoria excluída. Lançamentos permaneceram, mas sem categoria atribuída.")
                        st.rerun()
