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

cursor.execute("CREATE TABLE IF NOT EXISTS contas (id INTEGER PRIMARY KEY, nome TEXT UNIQUE, dia_vencimento INTEGER)")
cursor.execute("CREATE TABLE IF NOT EXISTS categorias (id INTEGER PRIMARY KEY, nome TEXT UNIQUE)")
cursor.execute("CREATE TABLE IF NOT EXISTS subcategorias (id INTEGER PRIMARY KEY, categoria_id INTEGER, nome TEXT, UNIQUE(categoria_id, nome), FOREIGN KEY (categoria_id) REFERENCES categorias(id) ON DELETE CASCADE)")
cursor.execute("CREATE TABLE IF NOT EXISTS transactions (id INTEGER PRIMARY KEY, date TEXT, description TEXT, value REAL, account TEXT, subcategoria_id INTEGER, FOREIGN KEY (subcategoria_id) REFERENCES subcategorias(id))")
conn.commit()

# =====================
# HELPERS
# =====================
def parse_money(val) -> float | None:
    if pd.isna(val):
        return None
    s = str(val).strip()
    s = re.sub(r"[^\d,.-]", "", s)
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

def ultimo_dia_do_mes(ano: int, mes: int) -> int:
    if mes == 12:
        return 31
    return (date(ano, mes + 1, 1) - timedelta(days=1)).day

def seletor_mes_ano(label="Período", data_default=None):
    if data_default is None:
        data_default = date.today()
    anos = list(range(2020, datetime.today().year + 2))
    meses = {1:"Janeiro",2:"Fevereiro",3:"Março",4:"Abril",5:"Maio",6:"Junho",7:"Julho",8:"Agosto",9:"Setembro",10:"Outubro",11:"Novembro",12:"Dezembro"}
    col1, col2 = st.columns(2)
    with col1:
        ano_sel = st.selectbox(f"{label} - Ano", anos, index=anos.index(data_default.year))
    with col2:
        mes_sel = st.selectbox(f"{label} - Mês", list(meses.keys()), format_func=lambda x: meses[x], index=data_default.month-1)
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
        df_mes = df_lanc[(df_lanc["date"].dt.month==mes_sel)&(df_lanc["date"].dt.year==ano_sel)]
        if df_mes.empty:
            st.warning("Nenhum lançamento neste período.")
        else:
            entradas = df_mes[df_mes["value"]>0]["value"].sum()
            saidas = df_mes[df_mes["value"]<0]["value"].sum()
            saldo = entradas+saidas
            c1,c2,c3 = st.columns(3)
            c1.metric("Entradas", f"R$ {entradas:,.2f}")
            c2.metric("Saídas", f"R$ {saidas:,.2f}")
            c3.metric("Saldo", f"R$ {saldo:,.2f}")

# =====================
# LANÇAMENTOS
# =====================
elif menu=="Lançamentos":
    st.header("Lançamentos")
    mes_ref, ano_ref = seletor_mes_ano("Lançamentos", date.today())
    contas = ["Todas"]+[row[0] for row in cursor.execute("SELECT nome FROM contas ORDER BY nome")]
    conta_sel = st.selectbox("Conta", contas)
    df_lanc = read_table_transactions(conn)
    df_lanc["date"]=pd.to_datetime(df_lanc["date"],errors="coerce")
    df_filtrado=df_lanc[(df_lanc["date"].dt.month==mes_ref)&(df_lanc["date"].dt.year==ano_ref)]
    if conta_sel!="Todas":
        df_filtrado=df_filtrado[df_filtrado["account"]==conta_sel]
    st.dataframe(df_filtrado,use_container_width=True)

# =====================
# IMPORTAÇÃO
# =====================
elif menu == "Importação":
    st.header("Importação de Lançamentos")

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
    def _coerce_to_pydate(x):
    """Converte valores vindos do AgGrid (dict/str/Timestamp) para date ou None."""
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return None
    # Já é Timestamp/datetime/date
    if isinstance(x, pd.Timestamp):
        return x.date()
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    # Veio como dict (ex.: {'year': 2025, 'month': 8, 'day': 6})
    if isinstance(x, dict):
        y = x.get("year") or x.get("Year")
        m = x.get("month") or x.get("Month")
        d = x.get("day") or x.get("Day")
        if y and m and d:
            try:
                return date(int(y), int(m), int(d))
            except Exception:
                pass
        # Tentativa com campo 'value' (string)
        v = x.get("value") or x.get("Value")
        if v:
            dtry = parse_date(v)
            return dtry if isinstance(dtry, date) else None
        return None
    # Caso geral: string
    dtry = parse_date(str(x))
    return dtry if isinstance(dtry, date) else None

    if arquivo is not None:
        try:
            df = _read_uploaded(arquivo)

            # limpar cabeçalhos e normalizar
            df.columns = [c.strip().lower().replace("\ufeff", "") for c in df.columns]

            mapa_colunas = {
                "data": ["data", "data lançamento", "data lancamento", "dt", "lançamento", "data mov", "data movimento"],
                "descrição": ["descrição", "descricao", "descricão", "histórico", "historico", "detalhe", "hist", "descricao/historico", "lançamento", "lancamento"],
                "valor": ["valor", "valor (r$)", "valor r$", "vlr", "amount", "valorlancamento", "valor lancamento"]
            }

            col_map = {}
            for alvo, poss in mapa_colunas.items():
                for p in poss:
                    if p in df.columns:
                        col_map[alvo] = p
                        break

            if "data" not in col_map or "valor" not in col_map:
                st.error(f"Arquivo inválido. Colunas lidas: {list(df.columns)}")
                st.stop()

            if "descrição" not in col_map:
                df["descrição"] = ""
                col_map["descrição"] = "descrição"

            df = df.rename(columns={
                col_map["data"]: "Data",
                col_map["descrição"]: "Descrição",
                col_map["valor"]: "Valor"
            })

            # remover linhas de saldo
            df = df[~df["Descrição"].astype(str).str.upper().str.startswith("SALDO")]

            # conversões
            df["Data"] = df["Data"].apply(parse_date)
            df["Valor"] = df["Valor"].apply(parse_money)

            # selecionar conta
            contas = [row[0] for row in cursor.execute("SELECT nome FROM contas ORDER BY nome")]
            if not contas:
                st.error("Nenhuma conta cadastrada. Vá em Configurações → Contas.")
                st.stop()
            conta_sel = st.selectbox("Selecione a conta destino", contas)

            # se for cartão de crédito → perguntar mês/ano da fatura
            mes_ref_cc, ano_ref_cc, dia_venc_cc = None, None, None
            if conta_sel.lower().startswith("cartão de crédito"):
                cursor.execute("SELECT dia_vencimento FROM contas WHERE nome=?", (conta_sel,))
                row = cursor.fetchone()
                dia_venc_cc = row[0] if row and row[0] else 1
                st.info(f"Conta de cartão detectada. Dia de vencimento cadastrado: {dia_venc_cc}.")
                mes_ref_cc, ano_ref_cc = seletor_mes_ano("Referente à fatura", date.today())

            # carregar categorias e subcategorias
            cursor.execute("SELECT id, nome FROM categorias ORDER BY nome")
            categorias = cursor.fetchall()
            cat_map = {c[1]: c[0] for c in categorias}

            cursor.execute("""
                SELECT s.id, s.nome, c.nome
                FROM subcategorias s
                JOIN categorias c ON s.categoria_id = c.id
                ORDER BY c.nome, s.nome
            """)
            subcat_map = {"Nenhuma": None}
            for sid, s_nome, c_nome in cursor.fetchall():
                subcat_map[f"{c_nome} → {s_nome}"] = sid

            # garantir colunas Categoria e Subcategoria
            if "Categoria" not in df.columns:
                df["Categoria"] = "Nenhuma"
            if "Subcategoria" not in df.columns:
                df["Subcategoria"] = "Nenhuma"

            # ordenar colunas: Data > Descrição > Valor > Categoria > Subcategoria > resto
            ordem = ["Data", "Descrição", "Valor", "Categoria", "Subcategoria"]
            cols_existentes = [c for c in ordem if c in df.columns]
            cols_restantes = [c for c in df.columns if c not in ordem]
            df = df[cols_existentes + cols_restantes]

            # grade de pré-visualização
            gb = GridOptionsBuilder.from_dataframe(df)
            gb.configure_default_column(editable=False)
            gb.configure_column("Categoria", editable=True,
                                cellEditor="agSelectCellEditor",
                                cellEditorParams={"values": ["Nenhuma"] + list(cat_map.keys())})
            gb.configure_column("Subcategoria", editable=True,
                                cellEditor="agSelectCellEditor",
                                cellEditorParams={"values": list(subcat_map.keys())})
            grid = AgGrid(df, gridOptions=gb.build(),
                          update_mode=GridUpdateMode.VALUE_CHANGED,
                          fit_columns_on_grid_load=True, height=420, theme="balham")

            df_editado = pd.DataFrame(grid["data"])

            if st.button("Importar lançamentos"):
    inserted = 0
    for _, row in df_editado.iterrows():
        desc = str(row["Descrição"])
        val = row["Valor"]
        dt_raw = row["Data"]

        # validações básicas
        if val is None:
            continue
        # garante número mesmo se o grid devolveu string
        try:
            valf = float(val)
        except Exception:
            valf = parse_money(val)
            if valf is None:
                continue

        # data: se cartão usa vencimento de mês/ano; senão normaliza do grid
        if conta_sel.lower().startswith("cartão de crédito") and mes_ref_cc and ano_ref_cc:
            dia = min(dia_venc_cc, ultimo_dia_do_mes(ano_ref_cc, mes_ref_cc))
            dt_obj = date(ano_ref_cc, mes_ref_cc, dia)
            # cartão: inverter sinal (positivos viram débitos)
            valf = -valf
        else:
            dt_obj = _coerce_to_pydate(dt_raw)

        if not isinstance(dt_obj, date):
            continue  # pula linhas sem data válida

        cursor.execute("""
            INSERT INTO transactions (date, description, value, account, subcategoria_id)
            VALUES (?, ?, ?, ?, ?)
        """, (
            dt_obj.strftime("%Y-%m-%d"),
            desc,
            valf,
            conta_sel,
            subcat_map.get(row.get("Subcategoria", "Nenhuma"), None)
        ))
        inserted += 1
    conn.commit()
    st.success(f"{inserted} lançamentos importados com sucesso!")
    st.rerun()
# =====================
# CONFIGURAÇÕES
# =====================
elif menu == "Configurações":
    st.header("Configurações")
    tab1, tab2, tab3, tab4 = st.tabs(
        ["Dados", "Contas", "Categorias", "Subcategorias"]
    )

    # ---- DADOS ----
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

        # Reset
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
            new_venc = st.number_input("Dia vencimento (se cartão)", 1, 31, int(df_contas.loc[df_contas["Conta"] == conta_sel, "Dia Vencimento"].iloc[0] or 1))
            if st.button("Salvar alterações de conta"):
                cursor.execute("UPDATE contas SET nome=?, dia_vencimento=? WHERE nome=?", (new_name.strip(), new_venc, conta_sel))
                cursor.execute("UPDATE transactions SET account=? WHERE account=?", (new_name.strip(), conta_sel))
                conn.commit()
                st.success("Conta atualizada!")
                st.rerun()
            if st.button("Excluir conta"):
                cursor.execute("DELETE FROM contas WHERE nome=?", (conta_sel,))
                conn.commit()
                st.warning("Conta excluída. Lançamentos ficam com o nome antigo.")
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
                    cursor.execute("INSERT INTO contas (nome, dia_vencimento) VALUES (?, ?)", (nova.strip(), dia_venc))
                    conn.commit()
                    st.success("Conta adicionada!")
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error("Conta já existe")

    # ---- CATEGORIAS ----
    with tab3:
        st.subheader("Gerenciar Categorias")
        cursor.execute("SELECT id, nome FROM categorias ORDER BY nome")
        df_cat = pd.DataFrame(cursor.fetchall(), columns=["ID", "Nome"])
        if not df_cat.empty:
            st.dataframe(df_cat, use_container_width=True)
            cat_sel = st.selectbox("Categoria existente", df_cat["Nome"])
            new_name = st.text_input("Novo nome categoria", value=cat_sel)
            if st.button("Salvar alteração categoria"):
                cursor.execute("UPDATE categorias SET nome=? WHERE nome=?", (new_name.strip(), cat_sel))
                conn.commit()
                st.success("Categoria atualizada!")
                st.rerun()
            if st.button("Excluir categoria"):
                cursor.execute("SELECT id FROM subcategorias WHERE categoria_id=(SELECT id FROM categorias WHERE nome=?)", (cat_sel,))
                sub_ids = [r[0] for r in cursor.fetchall()]
                if sub_ids:
                    cursor.executemany("UPDATE transactions SET subcategoria_id=NULL WHERE subcategoria_id=?", [(sid,) for sid in sub_ids])
                    cursor.executemany("DELETE FROM subcategorias WHERE id=?", [(sid,) for sid in sub_ids])
                cursor.execute("DELETE FROM categorias WHERE nome=?", (cat_sel,))
                conn.commit()
                st.warning("Categoria e subcategorias excluídas!")
                st.rerun()
        else:
            st.info("Nenhuma categoria cadastrada.")

        nova_cat = st.text_input("Nova categoria")
        if st.button("Adicionar categoria"):
            if nova_cat.strip():
                try:
                    cursor.execute("INSERT INTO categorias (nome) VALUES (?)", (nova_cat.strip(),))
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
                    cursor.execute("UPDATE subcategorias SET nome=? WHERE id=(SELECT id FROM subcategorias WHERE nome=? AND categoria_id=?)", (new_sub.strip(), sub_sel, cat_map[cat_sel]))
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
