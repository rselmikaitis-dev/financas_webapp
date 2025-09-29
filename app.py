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

import os
# =====================
# BANCO DE DADOS
# =====================

def garantir_schema(conn):
    cursor = conn.cursor()
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
            nome TEXT UNIQUE,
            tipo TEXT DEFAULT 'Despesa Variável'
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
        CREATE TABLE IF NOT EXISTS planejado (
            id INTEGER PRIMARY KEY,
            ano INTEGER NOT NULL,
            mes INTEGER NOT NULL,
            subcategoria_id INTEGER NOT NULL,
            valor REAL DEFAULT 0,
            UNIQUE(ano, mes, subcategoria_id),
            FOREIGN KEY (subcategoria_id) REFERENCES subcategorias(id) ON DELETE CASCADE
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
            parcela_atual INTEGER DEFAULT 1,
            parcelas_totais INTEGER DEFAULT 1,
            desc_norm TEXT,
            FOREIGN KEY (subcategoria_id) REFERENCES subcategorias(id)
        )
    """)
    conn.commit()
    
import unicodedata as _ud
import re as _re

def _normalize_desc(s: str) -> str:
    s = str(s or "").lower().strip()
    s = _ud.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = _re.sub(r"\d+/\d+", " ", s)   # remove parcelas 09/10
    s = _re.sub(r"\d+", " ", s)       # remove números soltos
    s = _re.sub(r"[^\w\s]", " ", s)   # remove pontuação
    s = _re.sub(r"\b(compra|pagamento|parcela|autorizado|debito|credito|loja|transacao)\b", " ", s)
    s = _re.sub(r"\s+", " ", s)
    return s.strip()
    
def atualizar_desc_norm(conn):
    """Preenche a coluna desc_norm para lançamentos antigos"""
    cursor = conn.cursor()
    rows = cursor.execute(
        "SELECT id, description, desc_norm FROM transactions WHERE description IS NOT NULL"
    ).fetchall()
    for rid, desc, desc_norm in rows:
        try:
            rid_int = int(rid)
            desc_str = str(desc)
            if not desc_str.strip():
                continue
            desc_n = _normalize_desc(desc_str)
            if desc_norm == desc_n:
                continue
            cursor.execute("UPDATE transactions SET desc_norm=? WHERE id=?", (desc_n, rid_int))
        except (ValueError, TypeError, sqlite3.InterfaceError) as exc:
            print(f"[atualizar_desc_norm] Falha ao normalizar registro {rid}: {exc}")
            continue
    conn.commit()

# 🔹 Cria conexão única
if "conn" not in st.session_state or st.session_state.conn is None:
    conn = sqlite3.connect("data.db", check_same_thread=False)
    st.session_state.conn = conn
else:
    conn = st.session_state.conn

# 🔹 Garante que tabelas e colunas existam
garantir_schema(conn)

# 🔹 Atualiza desc_norm retroativamente (executa sempre, mas só muda se estiver vazio/diferente)
atualizar_desc_norm(conn)

# 🔹 Cursor pronto
cursor = conn.cursor()

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
               c.nome as categoria, s.nome as subcategoria, c.tipo
        FROM transactions t
        LEFT JOIN subcategorias s ON t.subcategoria_id = s.id
        LEFT JOIN categorias   c ON s.categoria_id   = c.id
    """, conn)

def is_cartao_credito(nome_conta: str) -> bool:
    import unicodedata
    s = unicodedata.normalize("NFKD", str(nome_conta)).encode("ASCII", "ignore").decode().lower().strip()
    return s.startswith("cartao de credito")

# === Auto-classificação por similaridade (opcional) ===
# Requer: rapidfuzz (adicione em requirements.txt)
try:
    from rapidfuzz import process, fuzz
except Exception:
    process = fuzz = None  # roda sem quebrar caso não esteja instalado

def _build_hist_similaridade(conn, conta=None):
    """
    Retorna histórico de descrições já classificadas.
    Se 'conta' for informada, filtra só por ela.
    """
    if process is None:
        return None

    q = """
        SELECT t.description, s.id AS sub_id, (c.nome || ' → ' || s.nome) AS label, t.account
        FROM transactions t
        JOIN subcategorias s ON t.subcategoria_id = s.id
        JOIN categorias    c ON s.categoria_id   = c.id
        WHERE t.subcategoria_id IS NOT NULL AND t.description IS NOT NULL
    """
    dfh = pd.read_sql_query(q, conn)
    if dfh.empty:
        return None

    if conta:
        dfh = dfh[dfh["account"] == conta]

    if dfh.empty:
        return None

    dfh["desc_norm"] = dfh["description"].map(_normalize_desc)
    dfh = dfh.drop_duplicates(subset=["desc_norm", "sub_id"])

    return {
        "choices": dfh["desc_norm"].tolist(),
        "payloads": dfh[["sub_id", "label"]].to_dict(orient="records")
    }

def sugerir_subcategoria(descricao: str, hist: dict, limiar: int = 80):
    desc_norm = _normalize_desc(descricao)

    if "last_classif" not in st.session_state:
        st.session_state["last_classif"] = {}

    # 🔹 só reaplica se a descrição normalizada for idêntica
    if desc_norm in st.session_state["last_classif"]:
        return st.session_state["last_classif"][desc_norm]

    if not hist or process is None:
        return None, None, 0

    match = process.extractOne(desc_norm, hist["choices"], scorer=fuzz.token_set_ratio)
    if not match:
        return None, None, 0

    _, score, idx = match
    payload = hist["payloads"][idx]
    sub_id = payload["sub_id"] if score >= limiar else None

    resultado = (sub_id, payload["label"], int(score))
    if sub_id:
        st.session_state["last_classif"][desc_norm] = resultado
    return resultado
# Atualiza/insere marcador de parcela na descrição
def _apply_parcela_in_desc(desc: str, p: int, total: int) -> str:
    s = str(desc or "")

    # 1) tenta substituir padrões "3/10"
    def _repl_bar(m):
        return f"{m.group(1)}{p}/{total}{m.group(4)}"
    s2, n = re.subn(r"(\b)(\d+)\s*/\s*(\d+)(\b)", _repl_bar, s)

    # 2) senão, tenta "Parcela 3 de 10"
    if n == 0:
        s2, n = re.subn(r"(?i)\bparcela\s*\d+\s*de\s*\d+\b", f"Parcela {p} de {total}", s2)

    # 3) se nada foi encontrado, anexa " (3/10)" ao final
    if n == 0:
        s2 = f"{s2} ({p}/{total})"

    return s2

# =====================
# MENU
# =====================
with st.sidebar:
    menu = option_menu(
        "Menu",
        ["Dashboard Principal", "Lançamentos", "Importação", "Planejamento", "Configurações"],
        menu_icon=None,
        icons=["", "", "", "", ""],
        default_index=0
    )

# =====================
# DASHBOARD PRINCIPAL (Heatmap + Detalhamento por Item/Mês)
# =====================
if menu == "Dashboard Principal":
    st.header("📊 Dashboard Principal (Visão Anual)")

    df_lanc = read_table_transactions(conn)

    if df_lanc.empty:
        st.info("Nenhum lançamento encontrado.")
    else:
        # 🔹 seletor de ano
        anos = sorted(df_lanc["date"].dropna().astype(str).str[:4].astype(int).unique())
        ano_sel = st.selectbox("Selecione o ano", anos, index=anos.index(date.today().year))

        # 🔹 prepara dados
        df_lanc["date"] = pd.to_datetime(df_lanc["date"], errors="coerce")
        df_lanc["Ano"] = df_lanc["date"].dt.year
        df_lanc["Mês"] = df_lanc["date"].dt.month

        df_ano = df_lanc[df_lanc["Ano"] == ano_sel].copy()
        if df_ano.empty:
            st.warning("Nenhum lançamento neste ano.")
        else:
            # ignora transferências
            df_ano = df_ano[df_ano["categoria"] != "Transferências"].copy()

            meses_nomes = {
                1:"Jan",2:"Fev",3:"Mar",4:"Abr",5:"Mai",6:"Jun",
                7:"Jul",8:"Ago",9:"Set",10:"Out",11:"Nov",12:"Dez"
            }

            # linhas do relatório
            linhas = {
                "Receitas": [], 
                "Investimentos": [], 
                "Despesas Fixas": [], 
                "Despesas Variáveis": []
            }

            for mes in range(1, 13):
                df_mes = df_ano[df_ano["Mês"] == mes].copy()
                if df_mes.empty:
                    rec = inv = fix = var = 0.0
                else:
                    rec = df_mes[df_mes["tipo"] == "Receita"]["value"].sum()
                    inv = abs(df_mes[df_mes["tipo"] == "Investimento"]["value"].sum())
                    fix = abs(df_mes[df_mes["tipo"] == "Despesa Fixa"]["value"].sum())
                    var = abs(df_mes[df_mes["tipo"] == "Despesa Variável"]["value"].sum())

                linhas["Receitas"].append(rec)
                linhas["Investimentos"].append(inv)
                linhas["Despesas Fixas"].append(fix)
                linhas["Despesas Variáveis"].append(var)

            # adiciona linha Lucro/Prejuízo
            lucro_prejuizo = [
                linhas["Receitas"][i] - (
                    linhas["Investimentos"][i] +
                    linhas["Despesas Fixas"][i] +
                    linhas["Despesas Variáveis"][i]
                )
                for i in range(12)
            ]
            linhas["Lucro/Prejuízo"] = lucro_prejuizo

            # força a ordem desejada
            ordem = ["Receitas", "Investimentos", "Despesas Fixas", "Despesas Variáveis", "Lucro/Prejuízo"]

            # monta dataframe base
            df_valores = pd.DataFrame({
                "Item": ordem,
                **{meses_nomes[m]: [linhas[k][m-1] for k in ordem] for m in range(1, 13)},
                "Total Anual": [sum(linhas[k]) for k in ordem]
            })

            # --- formata R$ ---
            def brl_fmt(v):
                try:
                    v = float(v)
                except:
                    return "-"
                s = f"{abs(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                return ("-R$ " if v < 0 else "R$ ") + s

            # --- prepara matriz ---
            cols = [c for c in df_valores.columns if c != "Item"]
            items = df_valores["Item"].tolist()

            Z = df_valores[cols].astype(float).values
            Text = df_valores[cols].applymap(brl_fmt).values

            # Percentual vs Receita
            rec_series = df_valores.set_index("Item").loc["Receitas", cols].astype(float)

            custom_pct = []
            for i, item in enumerate(items):
                linha = []
                for j, col in enumerate(cols):
                    rec = float(rec_series[col]) if col in rec_series else 0.0
                    val = float(Z[i, j])
                    if item in ("Receitas", "Lucro/Prejuízo") or rec == 0:
                        linha.append("")
                    else:
                        linha.append(f"{(val/rec*100):.1f}%")
                custom_pct.append(linha)

            import numpy as np
            import plotly.graph_objects as go

            # --- Heatmap base ---
            fig = go.Figure(go.Heatmap(
                z=np.zeros_like(Z),
                x=cols,
                y=items,
                text=Text,
                texttemplate="%{text}",
                textfont={"size":12},
                customdata=custom_pct,
                hovertemplate=(
                    "Item: %{y}<br>"
                    "Mês: %{x}<br>"
                    "% s/ Receita: %{customdata}<extra></extra>"
                ),
                colorscale=[[0, "#f9f9f9"], [1, "#dfe7ff"]],
                showscale=False,
                xgap=2, ygap=2
            ))

            # --- Camada Lucro/Prejuízo (verde/vermelho) ---
            lucro_idx = items.index("Lucro/Prejuízo")
            z_lucro = np.full_like(Z, np.nan, dtype=float)
            z_lucro[lucro_idx, :] = Z[lucro_idx, :]

            fig.add_trace(go.Heatmap(
                z=z_lucro,
                x=cols,
                y=items,
                text=Text,
                texttemplate="%{text}",
                textfont={"size":12},
                customdata=custom_pct,
                hovertemplate=(
                    "Item: %{y}<br>"
                    "Mês: %{x}<br>"
                    "% s/ Receita: %{customdata}<extra></extra>"
                ),
                colorscale=[[0, "#f8d4d4"], [0.5, "#f9f9f9"], [1, "#d4f8d4"]],
                showscale=False,
                xgap=2, ygap=2
            ))

            fig.update_layout(
                margin=dict(l=0, r=0, t=10, b=0),
                xaxis=dict(side="top"),
                yaxis=dict(autorange="reversed")
            )

            st.plotly_chart(fig, use_container_width=True)

            # ================= Detalhamento por Item/Mês =================
            st.markdown("### 🔎 Detalhar composição")
            col_det1, col_det2 = st.columns(2)

            itens_disponiveis = ["Receitas", "Investimentos", "Despesas Fixas", "Despesas Variáveis"]
            item_escolhido = col_det1.selectbox("Item", itens_disponiveis, key="det_item")

            meses_nomes_inv = {v: k for k, v in meses_nomes.items()}
            mes_escolhido = col_det2.selectbox("Mês", list(meses_nomes.values()), key="det_mes")
            mes_num = meses_nomes_inv[mes_escolhido]

            df_mes = df_ano[df_ano["Mês"] == mes_num].copy()

            tipo_map = {
                "Receitas": "Receita",
                "Investimentos": "Investimento",
                "Despesas Fixas": "Despesa Fixa",
                "Despesas Variáveis": "Despesa Variável",
            }
            tipo_sel = tipo_map[item_escolhido]

            df_filtrado = df_mes[df_mes["tipo"] == tipo_sel].copy()

            st.subheader(f"Composição de {item_escolhido} – {mes_escolhido}/{ano_sel}")

            if df_filtrado.empty:
                st.info("Nenhum lançamento encontrado para esse filtro.")
            else:
                if tipo_sel != "Receita":
                    df_filtrado["value"] = df_filtrado["value"].abs()

                resumo = (
                    df_filtrado
                    .assign(subcategoria=df_filtrado["subcategoria"].fillna("Nenhuma"))
                    .groupby("subcategoria", dropna=False, as_index=False)["value"]
                    .sum()
                    .sort_values("value", ascending=False)
                )
                total_item = float(resumo["value"].sum())
                resumo["% do total"] = resumo["value"] / total_item * 100 if total_item else 0

                resumo_fmt = resumo.copy()
                resumo_fmt.rename(columns={"subcategoria": "Subcategoria", "value": "Valor (R$)"}, inplace=True)
                resumo_fmt["Valor (R$)"] = resumo_fmt["Valor (R$)"].map(brl_fmt)
                resumo_fmt["% do total"] = resumo_fmt["% do total"].map(lambda x: f"{x:.1f}%" if x else "-")

                st.dataframe(resumo_fmt, use_container_width=True)

                with st.expander("📜 Ver lançamentos individuais"):
                    df_listagem = df_filtrado[["date", "description", "value", "account", "categoria", "subcategoria"]].copy()
                    df_listagem["Valor (R$)"] = df_listagem["value"].map(brl_fmt)
                    df_listagem["Data"] = pd.to_datetime(df_listagem["date"], errors="coerce").dt.strftime("%d/%m/%Y")
                    df_listagem.rename(columns={
                        "description": "Descrição",
                        "account": "Conta",
                        "categoria": "Categoria",
                        "subcategoria": "Subcategoria",
                    }, inplace=True)
                    st.dataframe(
                        df_listagem[["Data", "Descrição", "Valor (R$)", "Conta", "Categoria", "Subcategoria"]],
                        use_container_width=True
                    )

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
        # ----- GRID -----
    dfv_display = dfv.copy()
    dfv_display["Data"] = dfv_display["Data"].dt.strftime("%d/%m/%Y")
    cols_order = ["ID", "Data", "Descrição", "Valor", "Conta", "Categoria/Subcategoria"]
    dfv_display = dfv_display[cols_order]

    gb = GridOptionsBuilder.from_dataframe(dfv_display)
    gb.configure_default_column(editable=False)
    gb.configure_selection("multiple", use_checkbox=True, header_checkbox=True)  # ✅ permite selecionar tudo
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

    # ----- TOTAL E SOMA -----
    soma_valores = dfv["Valor"].sum() if not dfv.empty else 0
    st.markdown(
        f"**Total de lançamentos exibidos: {len(dfv_display)} | Soma dos valores: R$ {soma_valores:,.2f}**"
    )

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
            
elif menu == "Importação":
    st.header("Importação de Lançamentos")

    # Selecionar conta destino
    contas_db = [row[0] for row in cursor.execute("SELECT nome FROM contas ORDER BY nome")]
    if not contas_db:
        st.error("Nenhuma conta cadastrada. Vá em Configurações → Contas.")
    else:
        conta_sel = st.selectbox("Conta destino", contas_db)

        # ----- MAPA CATEGORIA/SUB -----
        cursor.execute(
            """
                SELECT s.id, s.nome, c.nome
                FROM subcategorias s
                JOIN categorias c ON s.categoria_id = c.id
                ORDER BY c.nome, s.nome
            """
        )
        cat_sub_map = {"Nenhuma": None}
        for sid, s_nome, c_nome in cursor.fetchall():
            cat_sub_map[f"{c_nome} → {s_nome}"] = sid

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
        mes_ref_cc = ano_ref_cc = None
        dia_venc_cc = None
        if conta_sel:
            cursor.execute("SELECT dia_vencimento FROM contas WHERE nome=?", (conta_sel,))
            row = cursor.fetchone()
            dia_venc_cc = row[0] if row and row[0] else None

        eh_cartao = is_cartao_credito(conta_sel) if conta_sel else False
        if dia_venc_cc:
            eh_cartao = True
            st.info(
                f"Conta de cartão detectada. Dia de vencimento cadastrado: **{dia_venc_cc}**."
            )

        if conta_sel and eh_cartao:
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

                    # Conversões seguras
                    df["Data"] = df["Data"].apply(parse_date)
                    df["Valor"] = df["Valor"].apply(parse_money)
                    df = df.dropna(subset=["Data", "Valor"])  # 🔹 remove linhas sem data/valor

                    # ---------- PRÉ-VISUALIZAÇÃO ----------
                    st.subheader("Pré-visualização")
                    
                    # 🔹 histórico de classificações já feitas
                    hist = _build_hist_similaridade(conn, conta_sel)
                    
                    df_preview = df.copy()
                    df_preview["Conta destino"] = conta_sel
                    
                    # Se for cartão → ajusta data
                    if eh_cartao and mes_ref_cc and ano_ref_cc:
                        from calendar import monthrange
                        dia_final = min(dia_venc_cc or 1, monthrange(ano_ref_cc, mes_ref_cc)[1])
                        dt_eff = date(ano_ref_cc, mes_ref_cc, dia_final)
                        df_preview["Data efetiva"] = dt_eff.strftime("%d/%m/%Y")
                    else:
                        df_preview["Data efetiva"] = pd.to_datetime(df_preview["Data"], errors="coerce").dt.strftime("%d/%m/%Y")

                    # Detecta parcelas automáticas no texto
                    def detectar_parcela(desc: str):
                        padroes = [
                            r"(\d+)\s*/\s*(\d+)",            # ex: "3/10"
                            r"parcela\s*(\d+)\s*de\s*(\d+)"  # ex: "Parcela 5 de 12"
                        ]
                        for p in padroes:
                            m = re.search(p, desc, re.IGNORECASE)
                            if m:
                                return int(m.group(1)), int(m.group(2))
                        return None, None
                    
                    parcelas_atuais, parcelas_totais = [], []
                    for _, r in df_preview.iterrows():
                        p_atual, p_total = detectar_parcela(str(r["Descrição"]))
                        parcelas_atuais.append(p_atual if p_atual else 1)
                        parcelas_totais.append(p_total if p_total else 1)

                    if eh_cartao:
                        df_preview["Parcela atual"] = parcelas_atuais
                        df_preview["Parcelas totais"] = parcelas_totais
                        df_preview["Parcelado?"] = [p > 1 for p in parcelas_totais]
                    else:
                        df_preview["Parcela atual"] = 1
                        df_preview["Parcelas totais"] = 1
                        df_preview["Parcelado?"] = False
                    
                    # 🔹 tenta sugerir categoria/subcategoria
                    sugestoes, sub_ids = [], []
                    for _, r in df_preview.iterrows():
                        desc = str(r["Descrição"])
                        val = r["Valor"]
                        if val is None:
                            sugestoes.append("Nenhuma")
                            sub_ids.append(None)
                            continue
                        sub_id, label, score = sugerir_subcategoria(desc, hist) if hist else (None, None, 0)
                        sugestoes.append(label if sub_id else "Nenhuma")
                        sub_ids.append(sub_id)
                    
                    df_preview["Sugestão Categoria/Sub"] = sugestoes
                    df_preview["sub_id_sugerido"] = sub_ids
                    
                    # 🔹 checa duplicidade usando descrição normalizada
                    duplicados = []
                    for _, r in df_preview.iterrows():
                        desc = str(r["Descrição"]).strip()
                        val = r["Valor"]

                        if val is None:
                            duplicados.append(False)
                            continue

                        try:
                            val = round(float(val), 2)
                        except:
                            val = 0.0

                        desc_norm = _normalize_desc(desc)

                        if eh_cartao and mes_ref_cc and ano_ref_cc:
                            data_cmp = datetime.strptime(r["Data efetiva"], "%d/%m/%Y").date()
                        else:
                            data_cmp = r["Data"] if isinstance(r["Data"], date) else parse_date(r["Data"])

                        cursor.execute("""
                            SELECT 1 FROM transactions
                             WHERE date=? AND ROUND(value,2)=ROUND(?,2) AND account=? 
                               AND desc_norm=?
                        """, (
                            data_cmp.strftime("%Y-%m-%d") if isinstance(data_cmp, date) else None,
                            val,
                            conta_sel,
                            desc_norm
                        ))
                        duplicados.append(cursor.fetchone() is not None)

                    df_preview["Já existe?"] = duplicados
                    
                    # Exibe preview editável
                    gb = GridOptionsBuilder.from_dataframe(df_preview)
                    gb.configure_default_column(editable=True)
                    gb.configure_column(
                        "Parcelado?",
                        editable=True,
                        cellEditor="agSelectCellEditor",
                        cellEditorParams={"values": ["True", "False"]},
                    )
                    gb.configure_column(
                        "Sugestão Categoria/Sub",
                        editable=True,
                        cellEditor="agSelectCellEditor",
                        cellEditorParams={"values": list(cat_sub_map.keys())},
                    )
                    gb.configure_column("sub_id_sugerido", hide=True)
                    grid = AgGrid(
                        df_preview,
                        gridOptions=gb.build(),
                        update_mode=GridUpdateMode.VALUE_CHANGED,
                        data_return_mode="AS_INPUT",
                        fit_columns_on_grid_load=True,
                        theme="balham",
                        height=400
                    )
                    df_preview_editado = pd.DataFrame(grid["data"])
                    if not df_preview_editado.empty and "Sugestão Categoria/Sub" in df_preview_editado.columns:
                        df_preview_editado["sub_id_sugerido"] = df_preview_editado[
                            "Sugestão Categoria/Sub"
                        ].map(lambda val: cat_sub_map.get(val, None))

                    # ---------- IMPORTAR ----------
                    if st.button("Importar lançamentos"):
                        from calendar import monthrange
                        from dateutil.relativedelta import relativedelta
                    
                        inserted = 0
                        hist = _build_hist_similaridade(conn, conta_sel)
                    
                        # Loop de lançamentos
                        for _, r in df_preview_editado.iterrows():
                            if r.get("Já existe?"):
                                continue
                            
                            desc_original = str(r["Descrição"]).strip()
                            val = r["Valor"]
                            if val is None:
                                continue

                            if eh_cartao and mes_ref_cc and ano_ref_cc:
                                dia_final = min(dia_venc_cc or 1, monthrange(ano_ref_cc, mes_ref_cc)[1])
                                dt_base = date(ano_ref_cc, mes_ref_cc, dia_final)
                                if val > 0:
                                    val = -abs(val)
                                    sub_id, _, _ = sugerir_subcategoria(desc_original, hist) if hist else (None, None, 0)
                                else:
                                    val = abs(val)
                                    sub_id = None
                            else:
                                dt_base = r["Data"] if isinstance(r["Data"], date) else parse_date(r["Data"])
                                if not isinstance(dt_base, date):
                                    continue
                                sub_id = r.get("sub_id_sugerido", None)

                            p_atual = int(r.get("Parcela atual", 1) or 1)
                            p_total = int(r.get("Parcelas totais", 1) or 1)

                            # Inserção preservando descrição original
                            cursor.execute("""
                                INSERT INTO transactions 
                                    (date, description, desc_norm, value, account, subcategoria_id, status, parcela_atual, parcelas_totais)
                                VALUES (?, ?, ?, ?, ?, ?, 'final', ?, ?)
                            """, (
                                dt_base.strftime("%Y-%m-%d"),
                                desc_original,
                                _normalize_desc(desc_original),
                                val,
                                conta_sel,
                                sub_id,
                                p_atual,
                                p_total
                            ))
                            inserted += 1

                            # Gera parcelas futuras se aplicável
                            if p_total > p_atual:
                                for p in range(p_atual + 1, p_total + 1):
                                    dt_nova = dt_base + relativedelta(months=(p - p_atual))
                                    cursor.execute("""
                                        SELECT 1 FROM transactions
                                        WHERE date=? AND value=? AND account=? 
                                          AND parcela_atual=? AND parcelas_totais=? AND desc_norm=?
                                    """, (
                                        dt_nova.strftime("%Y-%m-%d"),
                                        val,
                                        conta_sel,
                                        p,
                                        p_total,
                                        _normalize_desc(desc_original)
                                    ))
                                    if cursor.fetchone():
                                        continue

                                    cursor.execute("""
                                        INSERT INTO transactions 
                                            (date, description, desc_norm, value, account, subcategoria_id, status, parcela_atual, parcelas_totais)
                                        VALUES (?, ?, ?, ?, ?, ?, 'final', ?, ?)
                                    """, (
                                        dt_nova.strftime("%Y-%m-%d"),
                                        desc_original,
                                        _normalize_desc(desc_original),
                                        val,
                                        conta_sel,
                                        sub_id,
                                        p,
                                        p_total
                                    ))
                                    inserted += 1
                    
                        conn.commit()
                        st.success(f"{inserted} lançamentos (incluindo parcelas futuras) inseridos com sucesso!")
                        st.rerun()
            except Exception as e:
                st.error(f"Erro ao processar arquivo: {e}")
# =====================
# PLANEJAMENTO (visão mensal)
# =====================
elif menu == "Planejamento":
    st.header("📅 Planejamento Mensal")

    # Selecionar ano e mês
    anos = list(range(2020, datetime.today().year + 2))
    ano_sel = st.selectbox("Ano", anos, index=anos.index(date.today().year))
    meses_nomes = {
        1:"Janeiro", 2:"Fevereiro", 3:"Março", 4:"Abril", 5:"Maio", 6:"Junho",
        7:"Julho", 8:"Agosto", 9:"Setembro", 10:"Outubro", 11:"Novembro", 12:"Dezembro"
    }
    mes_sel = st.selectbox("Mês", list(meses_nomes.keys()), format_func=lambda x: meses_nomes[x], index=date.today().month-1)

    # 🔹 todas subcategorias (já trazendo o tipo da categoria)
    df_subs = pd.read_sql_query("""
        SELECT s.id as sub_id, s.nome as subcategoria, c.nome as categoria, c.tipo as tipo
        FROM subcategorias s
        JOIN categorias c ON s.categoria_id = c.id
        ORDER BY c.tipo, c.nome, s.nome
    """, conn)

    # 🔹 dados já salvos
    df_plan = pd.read_sql_query("""
        SELECT ano, mes, subcategoria_id, valor
        FROM planejado
        WHERE ano=? AND mes=?
    """, conn, params=(ano_sel, mes_sel))

    # 🔹 realizado no mês
    df_real = pd.read_sql_query("""
        SELECT s.id as sub_id, SUM(t.value) as realizado
        FROM transactions t
        LEFT JOIN subcategorias s ON t.subcategoria_id = s.id
        WHERE strftime('%Y', t.date)=? AND strftime('%m', t.date)=?
        GROUP BY s.id
    """, conn, params=(str(ano_sel), f"{mes_sel:02d}"))

    # 🔹 histórico últimos 6 meses
    seis_meses_atras = date(ano_sel, mes_sel, 1) - pd.DateOffset(months=6)
    df_hist = pd.read_sql_query("""
        SELECT s.id as sub_id, AVG(t.value) as media_6m
        FROM transactions t
        LEFT JOIN subcategorias s ON t.subcategoria_id = s.id
        WHERE date(t.date) >= ? AND date(t.date) < ?
        GROUP BY s.id
    """, conn, params=(seis_meses_atras.strftime("%Y-%m-%d"), date(ano_sel, mes_sel, 1).strftime("%Y-%m-%d")))

    # monta base
    linhas = []
    for _, row in df_subs.iterrows():
        sub_id = row["sub_id"]
        cat = row["categoria"]
        sub = row["subcategoria"]
        tipo = row["tipo"]

        val_plan = df_plan.loc[df_plan["subcategoria_id"]==sub_id, "valor"]
        planejado = float(val_plan.iloc[0]) if not val_plan.empty else 0.0

        val_real = df_real.loc[df_real["sub_id"]==sub_id, "realizado"]
        realizado = float(val_real.iloc[0]) if not val_real.empty else 0.0

        val_hist = df_hist.loc[df_hist["sub_id"]==sub_id, "media_6m"]
        media6 = float(val_hist.iloc[0]) if not val_hist.empty else 0.0

        linhas.append({
            "Sub_id": sub_id,
            "Tipo": tipo,
            "Categoria": cat,
            "Subcategoria": sub,
            "Média 6m": round(media6, 2),
            "Planejado": round(planejado, 2),
            "Realizado": round(realizado, 2),
            "Diferença": round(realizado - planejado, 2)
        })

    colunas_planejamento = [
        "Sub_id",
        "Tipo",
        "Categoria",
        "Subcategoria",
        "Média 6m",
        "Planejado",
        "Realizado",
        "Diferença",
    ]
    df_mes = pd.DataFrame(linhas, columns=colunas_planejamento)

    # 🔹 adiciona totais por grupo
    grupos = []
    for tipo in ["Receita", "Despesa Fixa", "Despesa Variável"]:
        df_g = df_mes[df_mes["Tipo"] == tipo]
        if not df_g.empty:
            total_row = {
                "Sub_id": None,
                "Tipo": tipo,
                "Categoria": f"TOTAL {tipo.upper()}",
                "Subcategoria": "",
                "Média 6m": 0.0,
                "Planejado": round(df_g["Planejado"].sum(), 2),
                "Realizado": round(df_g["Realizado"].sum(), 2),
                "Diferença": round(df_g["Diferença"].sum(), 2)
            }
            grupos.append(df_g)
            grupos.append(pd.DataFrame([total_row]))
    if grupos:
        df_mes = pd.concat(grupos, ignore_index=True)
    else:
        df_mes = df_mes.reset_index(drop=True)

    # 🔹 adiciona total geral
    total_geral = {
        "Sub_id": None,
        "Tipo": "TOTAL",
        "Categoria": "TOTAL GERAL",
        "Subcategoria": "",
        "Média 6m": 0.0,
        "Planejado": round(df_mes["Planejado"].sum(), 2),
        "Realizado": round(df_mes["Realizado"].sum(), 2),
        "Diferença": round(df_mes["Diferença"].sum(), 2)
    }
    df_mes = pd.concat([df_mes, pd.DataFrame([total_geral])], ignore_index=True)

    # 🔹 saneamento antes do grid
    for col in ["Média 6m", "Planejado", "Realizado", "Diferença"]:
        df_mes[col] = pd.to_numeric(df_mes[col], errors="coerce").fillna(0.0)

    df_display = df_mes.copy()
    df_display["Categoria"] = df_display["Categoria"].astype(str)
    df_display["Subcategoria"] = df_display["Subcategoria"].astype(str)

    # grid editável só no Planejado (exceto linhas de TOTAL)
    gb = GridOptionsBuilder.from_dataframe(df_display)
    gb.configure_default_column(editable=False, resizable=True)
    gb.configure_column("Planejado", editable=True)
    gb.configure_column("Sub_id", hide=True)
    grid = AgGrid(
        df_display,
        gridOptions=gb.build(),
        update_mode=GridUpdateMode.VALUE_CHANGED,
        data_return_mode="AS_INPUT",
        fit_columns_on_grid_load=True,
        theme="balham",
        height=600
    )
    df_editado = pd.DataFrame(grid["data"])

    # botão salvar (ignora linhas de TOTAL)
    if st.button("💾 Salvar planejamento"):
        cursor.execute("DELETE FROM planejado WHERE ano=? AND mes=?", (ano_sel, mes_sel))
        for _, row in df_editado.iterrows():
            if "TOTAL" in str(row["Categoria"]).upper():
                continue
            sub_id = row.get("Sub_id")
            if pd.isna(sub_id) or sub_id in (None, ""):
                continue
            try:
                sub_id = int(sub_id)
            except (TypeError, ValueError):
                continue
            try:
                val = float(row["Planejado"]) if row["Planejado"] not in (None,"","NaN") else 0.0
            except Exception:
                val = 0.0
            cursor.execute(
                "INSERT INTO planejado (ano, mes, subcategoria_id, valor) VALUES (?, ?, ?, ?)",
                (ano_sel, mes_sel, sub_id, val)
            )
        conn.commit()
        st.success("Planejamento salvo com sucesso!")

# =====================
# CONFIGURAÇÕES
# =====================
elif menu == "Configurações":
    st.header("Configurações")
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["Dados", "Contas", "Categorias", "Subcategorias", "SQL Console"])

    # ---- DADOS ----
     
    with tab1:
        st.subheader("Gerenciar Dados")

        # =========================
        # EXPORTAR BACKUP
        # =========================
        st.markdown("### 📥 Baixar Backup")
        if st.button("Baixar todos os dados"):
            import io, zipfile
            buffer = io.BytesIO()
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            with zipfile.ZipFile(buffer, "w") as zf:
                for nome_tabela in ["contas", "categorias", "subcategorias", "transactions"]:
                    df = pd.read_sql_query(f"SELECT * FROM {nome_tabela}", conn)
                    csv_bytes = df.to_csv(index=False).encode("utf-8")
                    zf.writestr(f"{nome_tabela}.csv", csv_bytes)
            buffer.seek(0)
            file_name = f"backup_financas_{timestamp}.zip"
            st.download_button("⬇️ Clique aqui para baixar backup.zip", buffer, file_name=file_name)

        st.markdown("---")

        # =========================
        # RESTAURAR BACKUP
        # =========================
        st.markdown("### 📤 Restaurar Backup")
        uploaded_backup = st.file_uploader("Selecione o arquivo backup_financas.zip", type=["zip"])
        
        if uploaded_backup is not None and st.button("Restaurar backup do arquivo"):
            import io, zipfile, os
            try:
                # Fecha conexão atual e remove o arquivo antigo
                try:
                    conn.close()
                except:
                    pass
                if os.path.exists("data.db"):
                    os.remove("data.db")

                # Recria o banco
                conn = sqlite3.connect("data.db", check_same_thread=False)
                st.session_state.conn = conn
                cursor = conn.cursor()
                # Recria o banco
                conn = sqlite3.connect("data.db", check_same_thread=False)
                st.session_state.conn = conn
                cursor = conn.cursor()
                
                # 🔹 Garante a estrutura mínima do banco (função única)
                garantir_schema(conn)
                
                # 🔹 Restaura os dados do backup
                with zipfile.ZipFile(uploaded_backup, "r") as zf:
                    for tabela in ["contas", "categorias", "subcategorias", "transactions"]:
                        if f"{tabela}.csv" not in zf.namelist():
                            st.error(f"{tabela}.csv não encontrado no backup")
                            st.stop()
                        df = pd.read_csv(zf.open(f"{tabela}.csv"))
                
                        if "id" in df.columns:
                            cols = df.columns.tolist()
                            placeholders = ",".join(["?"] * len(cols))
                            colnames = ",".join(cols)
                            cursor.executemany(
                                f"INSERT INTO {tabela} ({colnames}) VALUES ({placeholders})",
                                df.itertuples(index=False, name=None)
                            )
                        else:
                            df.to_sql(tabela, conn, if_exists="append", index=False)
                
                    conn.commit()
                
                st.success("✅ Backup restaurado com sucesso! IDs preservados.")
                st.rerun()

                # 🔹 Restaura os dados do backup
                with zipfile.ZipFile(uploaded_backup, "r") as zf:
                    for tabela in ["contas", "categorias", "subcategorias", "transactions"]:
                        if f"{tabela}.csv" not in zf.namelist():
                            st.error(f"{tabela}.csv não encontrado no backup")
                            st.stop()
                        df = pd.read_csv(zf.open(f"{tabela}.csv"))

                        if "id" in df.columns:
                            cols = df.columns.tolist()
                            placeholders = ",".join(["?"] * len(cols))
                            colnames = ",".join(cols)
                            cursor.executemany(
                                f"INSERT INTO {tabela} ({colnames}) VALUES ({placeholders})",
                                df.itertuples(index=False, name=None)
                            )
                        else:
                            df.to_sql(tabela, conn, if_exists="append", index=False)

                    conn.commit()

                st.success("✅ Backup restaurado com sucesso! IDs preservados.")
                st.rerun()

            except Exception as e:
                st.error(f"Erro ao restaurar backup: {e}")

        st.markdown("---")

        # =========================
        # RESETAR BANCO (OPCIONAL)
        # =========================
        if st.button("⚠️ Resetar banco (apaga tudo)"):
            cursor.execute("DELETE FROM transactions")
            cursor.execute("DELETE FROM subcategorias")
            cursor.execute("DELETE FROM categorias")
            cursor.execute("DELETE FROM contas")
            conn.commit()
            st.warning("Banco resetado com sucesso! Todas as tabelas estão vazias.")

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
                if row_sel["Nome"] == "Estorno":
                    st.warning("⚠️ A categoria 'Estorno' é protegida e não pode ser excluída.")
                else:
                    cursor.execute("SELECT id FROM subcategorias WHERE categoria_id=?", (int(row_sel["ID"]),))
                    sub_ids = [r[0] for r in cursor.fetchall()]
                    if sub_ids:
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
                    if cat_sel == "Estorno" and sub_sel == "Cartão de Crédito":
                        st.warning("⚠️ A subcategoria 'Cartão de Crédito' da categoria 'Estorno' é protegida e não pode ser excluída.")
                    else:
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
        with tab5:
            st.subheader("🛠️ SQL Console (avançado)")
            
            query = st.text_area("Digite sua consulta SQL (somente SELECT):", height=120)
        
            if st.button("Executar consulta"):
                if not query.strip().lower().startswith("select"):
                    st.error("⚠️ Só é permitido SELECT por segurança.")
                else:
                    try:
                        df_query = pd.read_sql_query(query, conn)
                        if df_query.empty:
                            st.info("Consulta executada, mas não retornou dados.")
                        else:
                            st.dataframe(df_query, use_container_width=True)
                    except Exception as e:
                        st.error(f"Erro ao executar: {e}")
        
            st.markdown("---")
            st.subheader("📌 Parcelas Futuras")
            
            if st.button("Gerar parcelas futuras"):
                from dateutil.relativedelta import relativedelta
                c = conn.cursor()
            
                rows = c.execute("""
                    SELECT id, date, description, value, account, subcategoria_id, parcela_atual, parcelas_totais
                    FROM transactions
                    WHERE parcelas_totais > 1
                    ORDER BY account, description, parcela_atual
                """).fetchall()
            
                inseridos = 0
                for (id_, dt_str, desc, val, conta, sub_id, p_atual, p_total) in rows:
                    try:
                        dt_base = datetime.strptime(dt_str, "%Y-%m-%d").date()
                    except Exception:
                        continue
            
                    # gera SEM exigir que seja a 1ª parcela
                    for p in range(p_atual + 1, p_total + 1):
                        nova_data = dt_base + relativedelta(months=(p - p_atual))
                        desc_nova = _apply_parcela_in_desc(desc, p, p_total)
            
                        c.execute("""
                            SELECT 1 FROM transactions
                            WHERE date=? AND description=? AND value=? AND account=? 
                              AND parcela_atual=? AND parcelas_totais=?
                        """, (
                            nova_data.strftime("%Y-%m-%d"),
                            desc_nova,
                            val,
                            conta,
                            p,
                            p_total
                        ))
                        if c.fetchone():
                            continue
            
                        c.execute("""
                            INSERT INTO transactions 
                                (date, description, value, account, subcategoria_id, status, parcela_atual, parcelas_totais)
                            VALUES (?, ?, ?, ?, ?, 'final', ?, ?)
                        """, (
                            nova_data.strftime("%Y-%m-%d"),
                            desc_nova,
                            val,
                            conta,
                            sub_id,
                            p,
                            p_total
                        ))
                        inseridos += 1
            
                conn.commit()
                st.success(f"{inseridos} parcelas futuras geradas/atualizadas com sucesso!")
