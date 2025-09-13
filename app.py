import re
import sqlite3
import bcrypt
import pandas as pd
import streamlit as st
from datetime import date, datetime, timedelta
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
    st.title("Login – Controle Financeiro")
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

# Logout
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

# Criação das tabelas base
cursor.execute("""
    CREATE TABLE IF NOT EXISTS contas (
        id INTEGER PRIMARY KEY,
        nome TEXT UNIQUE,
        dia_vencimento INTEGER
    )
""")

cursor.execute("""
    CREATE TABLE IF NOT EXISTS categorias (
        id INTEGER PRIMARY KEY,
        nome TEXT UNIQUE
        -- coluna tipo será garantida abaixo (retrocompatibilidade)
    )
""")

cursor.execute("""
    CREATE TABLE IF NOT EXISTS subcategorias (
        id INTEGER PRIMARY KEY,
        categoria_id INTEGER,
        nome TEXT,
        UNIQUE(categoria_id, nome),
        FOREIGN KEY (categoria_id) REFERENCES categorias(id) ON DELETE CASCADE
    )
""")

cursor.execute("""
    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY,
        date TEXT,
        description TEXT,
        value REAL,
        account TEXT,
        subcategoria_id INTEGER,
        status TEXT DEFAULT 'final',
        FOREIGN KEY (subcategoria_id) REFERENCES subcategorias(id)
    )
""")
conn.commit()

# Garante coluna "tipo" em categorias (retrocompatível com bases antigas)
cursor.execute("PRAGMA table_info(categorias)")
cols = [c[1] for c in cursor.fetchall()]
if "tipo" not in cols:
    cursor.execute("ALTER TABLE categorias ADD COLUMN tipo TEXT DEFAULT 'Despesa Variável'")
    conn.commit()

# Garante categoria Transferências e subcategoria Entre contas
cursor.execute(
    "INSERT OR IGNORE INTO categorias (nome, tipo) VALUES (?, ?)",
    ("Transferências", "Neutra")
)
conn.commit()
cursor.execute("SELECT id FROM categorias WHERE nome='Transferências'")
cat_id = cursor.fetchone()[0]
cursor.execute(
    "INSERT OR IGNORE INTO subcategorias (categoria_id, nome) VALUES (?, ?)",
    (cat_id, "Entre contas")
)
conn.commit()

# =====================
# HELPERS
# =====================
def parse_money(val) -> float | None:
    if pd.isna(val):
        return None
    s = str(val).strip()
    # remove tudo que não é dígito, vírgula, ponto ou sinal
    s = re.sub(r"[^\d,.-]", "", s)
    # converte padrão brasileiro para float
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    # casos com traço ao final para negativo (ex: "123,45-")
    if s.endswith("-"):
        s = "-" + s[:-1]
    # strings vazias viram None
    if s in ("", "-", "+", "."):
        return None
    try:
        return float(s)
    except ValueError:
        return None

def parse_date(val):
    if pd.isna(val):
        return pd.NaT
    s = str(val).strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            continue
    # tenta pandas
    try:
        x = pd.to_datetime(s, dayfirst=True, errors="coerce")
        return x.date() if not pd.isna(x) else pd.NaT
    except Exception:
        return pd.NaT

def ultimo_dia_do_mes(ano: int, mes: int) -> int:
    if mes == 12:
        return 31
    return (date(ano, mes + 1, 1) - timedelta(days=1)).day

def seletor_mes_ano(label="Período", data_default=None):
    if data_default is None:
        data_default = date.today()
    anos = list(range(2020, datetime.today().year + 2))
    meses = {
        1:"Janeiro",2:"Fevereiro",3:"Março",4:"Abril",5:"Maio",6:"Junho",
        7:"Julho",8:"Agosto",9:"Setembro",10:"Outubro",11:"Novembro",12:"Dezembro"
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

def is_cartao_credito(nome_conta: str) -> bool:
    import unicodedata
    s = unicodedata.normalize("NFKD", str(nome_conta)).encode("ASCII", "ignore").decode().lower().strip()
    return s.startswith("cartao de credito")

# =====================
# MENU
# =====================
with st.sidebar:
    menu = option_menu("Menu", ["Dashboard", "Lançamentos", "Importação", "Configurações"],
                       menu_icon=None, icons=["","","",""], default_index=0)

# =====================
# DASHBOARD
# =====================
if menu == "Dashboard":
    st.header("Dashboard Financeiro")
    df_lanc = read_table_transactions(conn)

    if df_lanc.empty:
        st.info("Nenhum lançamento encontrado.")
    else:
        mes_sel, ano_sel = seletor_mes_ano("Dashboard", date.today())
        df_lanc["date"] = pd.to_datetime(df_lanc["date"], errors="coerce")

        df_mes = df_lanc[
            (df_lanc["date"].dt.month == mes_sel) &
            (df_lanc["date"].dt.year == ano_sel)
        ]

        if df_mes.empty:
            st.warning("Nenhum lançamento neste período.")
        else:
            # Ignora transferências no cálculo consolidado
            df_mes_valid = df_mes[df_mes["categoria"] != "Transferências"]

            entradas = df_mes_valid[df_mes_valid["value"] > 0]["value"].sum()
            saidas = df_mes_valid[df_mes_valid["value"] < 0]["value"].sum()
            saldo = entradas + saidas

            c1, c2, c3 = st.columns(3)
            c1.metric("Entradas", f"R$ {entradas:,.2f}")
            c2.metric("Saídas", f"R$ {saidas:,.2f}")
            c3.metric("Saldo", f"R$ {saldo:,.2f}")

            import plotly.express as px

            # ===== Gráfico de pizza das entradas =====
            df_entradas = df_mes_valid[df_mes_valid["value"] > 0].copy()
            if not df_entradas.empty:
                df_pizza_e = df_entradas.groupby("categoria")["value"].sum().reset_index()
                df_pizza_e = df_pizza_e.sort_values("value", ascending=False)

                fig_e = px.pie(
                    df_pizza_e,
                    values="value",
                    names="categoria",
                    title="Distribuição das Entradas por Categoria"
                )
                st.plotly_chart(fig_e, use_container_width=True)
            else:
                st.info("Não há entradas neste período para exibir gráfico.")

            # ===== Gráfico de pizza das saídas =====
            df_saidas = df_mes_valid[df_mes_valid["value"] < 0].copy()
            if not df_saidas.empty:
                df_pizza_s = df_saidas.groupby("categoria")["value"].sum().reset_index()
                df_pizza_s["value"] = df_pizza_s["value"].abs()  # valores positivos para pizza

                fig_s = px.pie(
                    df_pizza_s,
                    values="value",
                    names="categoria",
                    title="Distribuição das Saídas por Categoria"
                )
                st.plotly_chart(fig_s, use_container_width=True)
            else:
                st.info("Não há saídas neste período para exibir gráfico.")
# =====================
# LANÇAMENTOS
# =====================
elif menu == "Lançamentos":
    st.header("Lançamentos")

    # garante contador para chave do grid
    if "grid_refresh" not in st.session_state:
        st.session_state["grid_refresh"] = 0

    # ----- MAPA CATEGORIA/SUB -----
    cursor.execute("""
        SELECT s.id, s.nome, c.nome
        FROM subcategorias s
        JOIN categorias c ON s.categoria_id = c.id
        ORDER BY c.nome, s.nome
    """)
    cat_sub_map = {"Nenhuma": None}
    for sid, s_nome, c_nome in cursor.fetchall():
        cat_sub_map[f"{c_nome} → {s_nome}"] = sid

    # ----- CARREGAMENTO DE LANÇAMENTOS -----
    if "df_lanc" not in st.session_state:
        st.session_state["df_lanc"] = pd.read_sql_query(
            """
            SELECT t.id, t.date, t.description, t.value, t.account, t.subcategoria_id,
                   c.nome AS categoria, s.nome AS subcategoria,
                   COALESCE(c.nome || ' → ' || s.nome, 'Nenhuma') AS cat_sub
            FROM transactions t
            LEFT JOIN subcategorias s ON t.subcategoria_id = s.id
            LEFT JOIN categorias c ON s.categoria_id = c.id
            ORDER BY t.date DESC
            """,
            conn
        )

    df_lanc = st.session_state["df_lanc"].copy()

    # Ajusta colunas
    df_lanc.rename(columns={
        "id": "ID",
        "date": "Data",
        "description": "Descrição",
        "value": "Valor",
        "account": "Conta",
        "cat_sub": "Categoria/Subcategoria"
    }, inplace=True)

    # Normaliza datas e categorias
    df_lanc["Data"] = pd.to_datetime(df_lanc["Data"], errors="coerce")
    df_lanc["Ano"] = df_lanc["Data"].dt.year
    df_lanc["Mês"] = df_lanc["Data"].dt.month
    df_lanc["Categoria"] = df_lanc["categoria"].fillna("Nenhuma")
    df_lanc["Subcategoria"] = df_lanc["subcategoria"].fillna("Nenhuma")

    meses_nomes = {
        1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril",
        5: "Maio", 6: "Junho", 7: "Julho", 8: "Agosto",
        9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro"
    }

    # ----- FILTROS -----
    col1, col2, col3, col4, col5 = st.columns(5)
    contas = ["Todas"] + sorted(df_lanc["Conta"].dropna().unique().tolist())
    conta_filtro = col1.selectbox("Conta", contas, key="flt_conta")

    cats = ["Todas", "Nenhuma"] + sorted(df_lanc["Categoria"].dropna().unique().tolist())
    cat_filtro = col2.selectbox("Categoria", cats, key="flt_categoria")

    subs = ["Todas", "Nenhuma"]
    if cat_filtro not in ["Todas", "Nenhuma"]:
        subs += sorted(df_lanc[df_lanc["Categoria"] == cat_filtro]["Subcategoria"].dropna().unique().tolist())
    elif cat_filtro == "Nenhuma":
        subs = ["Todas", "Nenhuma"]
    else:
        subs += sorted(df_lanc["Subcategoria"].dropna().unique().tolist())
    sub_filtro = col3.selectbox("Subcategoria", subs, key="flt_subcategoria")

    anos = ["Todos"] + sorted(df_lanc["Ano"].dropna().unique().astype(int).tolist())
    ano_filtro = col4.selectbox("Ano", anos, key="flt_ano")

    meses = ["Todos"] + [meses_nomes[m] for m in range(1, 13)]
    mes_filtro = col5.selectbox("Mês", meses, key="flt_mes")

    # ----- APLICA FILTROS -----
    dfv = df_lanc.copy()
    if conta_filtro != "Todas":
        dfv = dfv[dfv["Conta"] == conta_filtro]
    if cat_filtro != "Todas":
        dfv = dfv[dfv["Categoria"] == cat_filtro]
    if sub_filtro != "Todas":
        dfv = dfv[dfv["Subcategoria"] == sub_filtro]
    if ano_filtro != "Todos":
        dfv = dfv[dfv["Ano"] == int(ano_filtro)]
    if mes_filtro != "Todos":
        mes_num = [k for k, v in meses_nomes.items() if v == mes_filtro][0]
        dfv = dfv[dfv["Mês"] == mes_num]

    # ----- GRID -----
    dfv_display = dfv.copy()
    dfv_display["Data"] = dfv_display["Data"].dt.strftime("%d/%m/%Y")
    cols_order = ["ID", "Data", "Descrição", "Valor", "Conta", "Categoria/Subcategoria"]
    dfv_display = dfv_display[cols_order]

    gb = GridOptionsBuilder.from_dataframe(dfv_display)
    gb.configure_default_column(editable=False)
    gb.configure_selection("multiple", use_checkbox=True)
    gb.configure_column("Categoria/Subcategoria", editable=True,
                        cellEditor="agSelectCellEditor",
                        cellEditorParams={"values": list(cat_sub_map.keys())})
    grid = AgGrid(
        dfv_display,
        gridOptions=gb.build(),
        update_mode=GridUpdateMode.MODEL_CHANGED,
        data_return_mode="AS_INPUT",
        fit_columns_on_grid_load=True,
        height=420,
        theme="balham",
        key=f"grid_lancamentos_{st.session_state['grid_refresh']}"
    )

    # Data editada
    grid_data = grid.get("data", None)
    if isinstance(grid_data, list) and len(grid_data) > 0:
        df_editado = pd.DataFrame(grid_data)
    elif isinstance(grid_data, pd.DataFrame):
        df_editado = grid_data.copy()
    else:
        df_editado = pd.DataFrame(columns=dfv_display.columns)

    # Seleção
    selected_ids = []
    if "selected_rows" in grid:
        sel_obj = grid["selected_rows"]
        if isinstance(sel_obj, pd.DataFrame) and "ID" in sel_obj.columns:
            selected_ids = [int(x) for x in sel_obj["ID"].dropna().tolist()]
        elif isinstance(sel_obj, list):
            selected_ids = [int(r.get("ID")) for r in sel_obj if isinstance(r, dict) and r.get("ID") is not None]

    st.markdown(f"**Total de lançamentos exibidos: {len(dfv_display)}**")

    # ----- BOTÕES -----
    col1b, col2b = st.columns([1, 1])
    with col1b:
        if st.button("💾 Salvar alterações"):
            updated = 0
            for _, row in df_editado.iterrows():
                sub_id = cat_sub_map.get(row.get("Categoria/Subcategoria", "Nenhuma"), None)
                try:
                    cursor.execute(
                        "UPDATE transactions SET subcategoria_id=? WHERE id=?",
                        (sub_id, int(row["ID"]))
                    )
                    updated += 1
                except Exception:
                    pass
            conn.commit()
            st.success(f"{updated} lançamentos atualizados com sucesso!")

            # força recarregar os dados e aplicar filtros de novo
            if "df_lanc" in st.session_state:
                del st.session_state["df_lanc"]
            st.session_state["grid_refresh"] += 1
            st.rerun()

    with col2b:
        if st.button("🗑️ Excluir selecionados") and selected_ids:
            cursor.executemany("DELETE FROM transactions WHERE id=?", [(i,) for i in selected_ids])
            conn.commit()
            st.warning(f"{len(selected_ids)} lançamentos excluídos!")

            if "df_lanc" in st.session_state:
                del st.session_state["df_lanc"]
            st.session_state["grid_refresh"] += 1
            st.rerun()

# =====================
# IMPORTAÇÃO
# =====================
elif menu == "Importação":
    st.header("Importação de Lançamentos")

    # Selecionar conta destino
    contas_db = [row[0] for row in cursor.execute("SELECT nome FROM contas ORDER BY nome")]
    if not contas_db:
        st.error("Nenhuma conta cadastrada. Vá em Configurações → Contas.")
    else:
        conta_sel = st.selectbox("Conta destino", contas_db)

        # Upload de arquivo
        arquivo = st.file_uploader("Selecione o arquivo (CSV, XLSX ou XLS)", type=["csv", "xlsx", "xls"])

        def _read_uploaded(file):
            name = file.name.lower()
            if name.endswith(".csv"):
                return pd.read_csv(file, sep=None, engine="python", dtype=str)
            if name.endswith(".xlsx"):
                return pd.read_excel(file, engine="openpyxl", dtype=str)
            if name.endswith(".xls"):
                return pd.read_excel(file, engine="xlrd", dtype=str)
            raise RuntimeError("Formato não suportado.")

        # Se for cartão de crédito → pedir mês/ano
        mes_ref_cc = ano_ref_cc = dia_venc_cc = None
        if conta_sel and is_cartao_credito(conta_sel):
            cursor.execute("SELECT dia_vencimento FROM contas WHERE nome=?", (conta_sel,))
            row = cursor.fetchone()
            dia_venc_cc = row[0] if row and row[0] else 1
            st.info(f"Conta de cartão detectada. Dia de vencimento cadastrado: **{dia_venc_cc}**.")
            mes_ref_cc, ano_ref_cc = seletor_mes_ano("Referente à fatura", date.today())

        if arquivo is not None:
            try:
                df = _read_uploaded(arquivo)
                df.columns = [c.strip().lower().replace("\ufeff", "") for c in df.columns]

                mapa_colunas = {
                    "data": ["data","data lançamento","data lancamento","dt","lançamento","data mov","data movimento"],
                    "descrição": ["descrição","descricao","historico","histórico","detalhe","descricao/historico","lançamento"],
                    "valor": ["valor","valor (r$)","valor r$","vlr","amount","valorlancamento","valor lancamento"]
                }
                col_map = {}
                for alvo, poss in mapa_colunas.items():
                    for p in poss:
                        if p in df.columns:
                            col_map[alvo] = p
                            break

                if "data" not in col_map or "valor" not in col_map:
                    st.error(f"Arquivo inválido. Colunas lidas: {list(df.columns)}")
                else:
                    if "descrição" not in col_map:
                        df["descrição"] = ""
                        col_map["descrição"] = "descrição"

                    df = df.rename(columns={
                        col_map["data"]: "Data",
                        col_map["descrição"]: "Descrição",
                        col_map["valor"]: "Valor"
                    })

                    # Remove linhas de saldo
                    df = df[~df["Descrição"].astype(str).str.upper().str.startswith("SALDO")]

                    # Conversões
                    df["Data"] = df["Data"].apply(parse_date)
                    df["Valor"] = df["Valor"].apply(parse_money)

                    # Prévia
                    df_preview = df.copy()
                    df_preview["Conta destino"] = conta_sel
                    if is_cartao_credito(conta_sel) and mes_ref_cc and ano_ref_cc:
                        from calendar import monthrange
                        dia_final = min(dia_venc_cc, monthrange(ano_ref_cc, mes_ref_cc)[1])
                        dt_eff = date(ano_ref_cc, mes_ref_cc, dia_final)
                        df_preview["Data efetiva"] = dt_eff.strftime("%d/%m/%Y")

                    st.subheader("Pré-visualização")
                    st.dataframe(df_preview, use_container_width=True)

                    # Importar direto (sem rascunho, já final)
                    if st.button("Importar lançamentos"):
                        from calendar import monthrange
                        inserted = 0
                        for _, r in df.iterrows():
                            desc = str(r["Descrição"])
                            val = r["Valor"]
                            if val is None:
                                continue

                            # Regras de data/valor
                            if is_cartao_credito(conta_sel) and mes_ref_cc and ano_ref_cc:
                                dia_final = min(dia_venc_cc, monthrange(ano_ref_cc, mes_ref_cc)[1])
                                dt_obj = date(ano_ref_cc, mes_ref_cc, dia_final)
                                val = -abs(val)  # sempre débito no cartão
                            else:
                                dt_obj = r["Data"] if isinstance(r["Data"], date) else parse_date(r["Data"])
                            if not isinstance(dt_obj, date):
                                continue

                            cursor.execute("""
                                INSERT INTO transactions (date, description, value, account, subcategoria_id, status)
                                VALUES (?, ?, ?, ?, ?, 'final')
                            """, (dt_obj.strftime("%Y-%m-%d"), desc, val, conta_sel, None))
                            inserted += 1
                        conn.commit()

                        st.success(f"{inserted} lançamentos importados com sucesso!")
                        st.rerun()
            except Exception as e:
                st.error(f"Erro ao processar arquivo: {e}")
# =====================
# CONFIGURAÇÕES
# =====================
elif menu == "Configurações":
    st.header("Configurações")
    tab1, tab2, tab3, tab4 = st.tabs(["Dados", "Contas", "Categorias", "Subcategorias"])

    # ---- DADOS ----
    with tab1:
        st.subheader("Gerenciar Dados")

        # Exportar backup
        st.markdown("### 📥 Baixar Backup")
        if st.button("Baixar todos os dados"):
            import io, zipfile
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w") as zf:
                for nome_tabela in ["contas", "categorias", "subcategorias", "transactions"]:
                    df = pd.read_sql_query(f"SELECT * FROM {nome_tabela}", conn)
                    csv_bytes = df.to_csv(index=False).encode("utf-8")
                    zf.writestr(f"{nome_tabela}.csv", csv_bytes)
            buffer.seek(0)
            st.download_button("⬇️ Clique aqui para baixar backup.zip", buffer, file_name="backup_financas.zip")

        st.markdown("---")

        # Importar backup
        st.markdown("### 📤 Restaurar Backup")
        uploaded_backup = st.file_uploader("Selecione o arquivo backup_financas.zip", type=["zip"])
        if uploaded_backup is not None and st.button("Restaurar backup do arquivo"):
            import io, zipfile
            try:
                with zipfile.ZipFile(uploaded_backup, "r") as zf:
                    # Reset antes de restaurar
                    cursor.execute("DELETE FROM transactions")
                    cursor.execute("DELETE FROM subcategorias")
                    cursor.execute("DELETE FROM categorias")
                    cursor.execute("DELETE FROM contas")

                    # Restaurar na ordem correta
                    for tabela in ["contas", "categorias", "subcategorias", "transactions"]:
                        if f"{tabela}.csv" not in zf.namelist():
                            st.error(f"{tabela}.csv não encontrado no backup")
                            st.stop()
                        df = pd.read_csv(zf.open(f"{tabela}.csv"))
                        df.to_sql(tabela, conn, if_exists="append", index=False)
                    conn.commit()
                st.success("Backup restaurado com sucesso!")
                st.rerun()
            except Exception as e:
                st.error(f"Erro ao restaurar backup: {e}")

        st.markdown("---")

        # Reset total
        st.markdown("### ⚠️ Resetar Banco de Dados")
        confirm = st.checkbox("Confirmo que desejo apagar TODOS os dados")
        if st.button("Apagar tudo e começar do zero", type="primary", disabled=not confirm):
            cursor.execute("DELETE FROM transactions")
            cursor.execute("DELETE FROM subcategorias")
            cursor.execute("DELETE FROM categorias")
            cursor.execute("DELETE FROM contas")
            conn.commit()
            st.success("Todos os dados foram apagados!")

    # ---- CONTAS ----
    with tab2:
        st.subheader("Gerenciar Contas")
        cursor.execute("SELECT id, nome, dia_vencimento FROM contas ORDER BY nome")
        df_contas = pd.DataFrame(cursor.fetchall(), columns=["ID", "Conta", "Dia Vencimento"])

        if not df_contas.empty:
            st.dataframe(df_contas, use_container_width=True)
            conta_sel = st.selectbox("Conta existente", df_contas["Conta"])
            new_name = st.text_input("Novo nome", value=conta_sel)

            # dia vencimento default seguro
            venc_raw = df_contas.loc[df_contas["Conta"] == conta_sel, "Dia Vencimento"].iloc[0]
            try:
                venc_default = int(venc_raw) if pd.notna(venc_raw) else 1
            except Exception:
                venc_default = 1
            new_venc = st.number_input("Dia vencimento (se cartão)", 1, 31, venc_default)

            if st.button("Salvar alterações de conta"):
                cursor.execute(
                    "UPDATE contas SET nome=?, dia_vencimento=? WHERE nome=?",
                    (new_name.strip(), new_venc, conta_sel)
                )
                # reflete nos lançamentos
                cursor.execute(
                    "UPDATE transactions SET account=? WHERE account=?",
                    (new_name.strip(), conta_sel)
                )
                conn.commit()
                st.success("Conta atualizada!")
                st.rerun()

            if st.button("Excluir conta"):
                cursor.execute("DELETE FROM contas WHERE nome=?", (conta_sel,))
                conn.commit()
                st.warning("Conta excluída. Lançamentos existentes ficam com o nome antigo (texto).")
                st.rerun()
        else:
            st.info("Nenhuma conta cadastrada.")

        st.markdown("---")
        nova = st.text_input("Nova conta")
        dia_venc = None
        if nova.lower().startswith("cartão de crédito"):
            dia_venc = st.number_input("Dia vencimento cartão", 1, 31, 1)
        if st.button("Adicionar conta"):
            if nova.strip():
                try:
                    cursor.execute(
                        "INSERT INTO contas (nome, dia_vencimento) VALUES (?, ?)",
                        (nova.strip(), dia_venc)
                    )
                    conn.commit()
                    st.success("Conta adicionada!")
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error("Conta já existe")

    # ---- CATEGORIAS ----
    with tab3:
        st.subheader("Gerenciar Categorias")

        tipos_possiveis = ["Despesa Fixa", "Despesa Variável", "Investimento", "Receita", "Neutra"]

        cursor.execute("SELECT id, nome, tipo FROM categorias ORDER BY nome")
        df_cat = pd.DataFrame(cursor.fetchall(), columns=["ID", "Nome", "Tipo"])
        if not df_cat.empty:
            st.dataframe(df_cat, use_container_width=True)

            cat_sel = st.selectbox("Categoria existente", df_cat["Nome"])
            row_sel = df_cat[df_cat["Nome"] == cat_sel].iloc[0]

            new_name = st.text_input("Novo nome categoria", value=row_sel["Nome"])
            new_tipo = st.selectbox(
                "Tipo",
                tipos_possiveis,
                index=tipos_possiveis.index(row_sel["Tipo"]) if row_sel["Tipo"] in tipos_possiveis else 1,
            )

            if st.button("Salvar alteração categoria"):
                cursor.execute("UPDATE categorias SET nome=?, tipo=? WHERE id=?", (new_name.strip(), new_tipo, int(row_sel["ID"])))
                conn.commit()
                st.success("Categoria atualizada!")
                st.rerun()

            if st.button("Excluir categoria"):
                cursor.execute("SELECT id FROM subcategorias WHERE categoria_id=?", (int(row_sel["ID"]),))
                sub_ids = [r[0] for r in cursor.fetchall()]
                if sub_ids:
                    # desvincula lançamentos e remove subcategorias
                    cursor.executemany("UPDATE transactions SET subcategoria_id=NULL WHERE subcategoria_id=?", [(sid,) for sid in sub_ids])
                    cursor.executemany("DELETE FROM subcategorias WHERE id=?", [(sid,) for sid in sub_ids])
                cursor.execute("DELETE FROM categorias WHERE id=?", (int(row_sel["ID"]),))
                conn.commit()
                st.warning("Categoria e subcategorias excluídas!")
                st.rerun()
        else:
            st.info("Nenhuma categoria cadastrada.")

        st.markdown("---")
        nova_cat = st.text_input("Nova categoria")
        novo_tipo = st.selectbox("Tipo da nova categoria", tipos_possiveis, key="novo_tipo_cat")
        if st.button("Adicionar categoria"):
            if nova_cat.strip():
                try:
                    cursor.execute("INSERT INTO categorias (nome, tipo) VALUES (?, ?)", (nova_cat.strip(), novo_tipo))
                    conn.commit()
                    st.success("Categoria adicionada!")
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error("Categoria já existe")

    # ---- SUBCATEGORIAS ----
    with tab4:
        st.subheader("Gerenciar Subcategorias")
        cursor.execute("SELECT id, nome FROM categorias ORDER BY nome")
        categorias_opts = cursor.fetchall()
        if not categorias_opts:
            st.info("Cadastre uma categoria primeiro")
        else:
            cat_map = {c[1]: c[0] for c in categorias_opts}
            cat_sel = st.selectbox("Categoria", list(cat_map.keys()))
            cursor.execute("SELECT id, nome FROM subcategorias WHERE categoria_id=? ORDER BY nome", (cat_map[cat_sel],))
            df_sub = pd.DataFrame(cursor.fetchall(), columns=["ID", "Nome"])
            if not df_sub.empty:
                st.dataframe(df_sub, use_container_width=True)
                sub_sel = st.selectbox("Subcategoria existente", df_sub["Nome"])
                new_sub = st.text_input("Novo nome subcategoria", value=sub_sel)
                if st.button("Salvar alteração subcategoria"):
                    cursor.execute("""
                        UPDATE subcategorias
                           SET nome=?
                         WHERE id=(SELECT id FROM subcategorias WHERE nome=? AND categoria_id=?)
                    """, (new_sub.strip(), sub_sel, cat_map[cat_sel]))
                    conn.commit()
                    st.success("Subcategoria atualizada!")
                    st.rerun()
                if st.button("Excluir subcategoria"):
                    cursor.execute("SELECT id FROM subcategorias WHERE nome=? AND categoria_id=?", (sub_sel, cat_map[cat_sel]))
                    row = cursor.fetchone()
                    if row:
                        sid = row[0]
                        cursor.execute("UPDATE transactions SET subcategoria_id=NULL WHERE subcategoria_id=?", (sid,))
                        cursor.execute("DELETE FROM subcategorias WHERE id=?", (sid,))
                        conn.commit()
                        st.warning("Subcategoria excluída e desvinculada dos lançamentos.")
                        st.rerun()
            else:
                st.info("Nenhuma subcategoria nesta categoria.")

            nova_sub = st.text_input("Nova subcategoria")
            if st.button("Adicionar subcategoria"):
                if nova_sub.strip():
                    try:
                        cursor.execute("INSERT INTO subcategorias (categoria_id, nome) VALUES (?, ?)", (cat_map[cat_sel], nova_sub.strip()))
                        conn.commit()
                        st.success("Subcategoria adicionada!")
                        st.rerun()
                    except sqlite3.IntegrityError:
                        st.error("Já existe essa subcategoria")
