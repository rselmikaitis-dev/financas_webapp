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

# 🔹 Cria conexão única
if "conn" not in st.session_state or st.session_state.conn is None:
    conn = sqlite3.connect("data.db", check_same_thread=False)
    st.session_state.conn = conn
else:
    conn = st.session_state.conn

# 🔹 Garante que tabelas existam sempre
garantir_schema(conn)

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

# =====================
# MENU
# =====================
with st.sidebar:
    menu = option_menu("Menu", ["Dashboard", "Dashboard Principal", "Lançamentos", "Importação", "Configurações"],
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
        df_lanc["Ano"] = df_lanc["date"].dt.year
        df_lanc["Mês"] = df_lanc["date"].dt.month

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
            economia_pct = (saldo / entradas * 100) if entradas > 0 else 0

            # --- MÉTRICAS GERAIS ---
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Entradas", f"R$ {entradas:,.2f}")
            c2.metric("Saídas", f"R$ {saidas:,.2f}")
            c3.metric("Saldo", f"R$ {saldo:,.2f}")
            c4.metric("% Economia", f"{economia_pct:.1f}%")

            import plotly.express as px

            # --- ABAS ---
            tab1, tab2, tab3, tab4, tab5 = st.tabs(
                ["📥 Entradas", "📤 Saídas", "📈 Evolução", "🏆 Top 10 Gastos", "📊 Dashboard Principal"]
            )

            # ===== Entradas por subcategoria =====
            with tab1:
                df_entradas = df_mes_valid[df_mes_valid["value"] > 0].copy()
                if not df_entradas.empty:
                    df_cat_e = df_entradas.groupby("subcategoria")["value"].sum().reset_index()
                    df_cat_e = df_cat_e.sort_values("value", ascending=True)

                    fig_e = px.bar(
                        df_cat_e,
                        x="value", y="subcategoria",
                        orientation="h",
                        title="Entradas por Subcategoria",
                        text="value"
                    )
                    fig_e.update_traces(
                        texttemplate="R$ %{x:,.2f}", textposition="outside", showlegend=False
                    )
                    st.plotly_chart(fig_e, use_container_width=True)
                else:
                    st.info("Não há entradas neste período.")

            # ===== Saídas por categoria =====
            with tab2:
                df_saidas = df_mes_valid[df_mes_valid["value"] < 0].copy()
                if not df_saidas.empty:
                    df_cat_s = df_saidas.groupby("categoria")["value"].sum().abs().reset_index()
                    df_cat_s = df_cat_s.sort_values("value", ascending=True)

                    fig_s = px.bar(
                        df_cat_s,
                        x="value", y="categoria",
                        orientation="h",
                        title="Saídas por Categoria",
                        text="value"
                    )
                    fig_s.update_traces(
                        texttemplate="R$ %{x:,.2f}", textposition="outside", showlegend=False
                    )
                    st.plotly_chart(fig_s, use_container_width=True)
                else:
                    st.info("Não há saídas neste período.")

            # ===== Evolução diária =====
            with tab3:
                df_diario = df_mes_valid.groupby("date")["value"].sum().cumsum().reset_index()
                df_diario.columns = ["Data", "Saldo acumulado"]

                fig_l = px.line(
                    df_diario,
                    x="Data", y="Saldo acumulado",
                    title="Evolução do Saldo no Mês",
                    markers=True
                )
                fig_l.update_traces(showlegend=False)
                st.plotly_chart(fig_l, use_container_width=True)

            # ===== Top 10 gastos =====
            with tab4:
                df_top = df_mes_valid[df_mes_valid["value"] < 0].copy()
                if not df_top.empty:
                    df_top["Data"] = df_top["date"].dt.strftime("%d/%m/%Y")
                    df_top = df_top[["Data", "description", "value", "categoria", "subcategoria", "account"]]
                    df_top = df_top.sort_values("value").head(10)
                    df_top["value"] = df_top["value"].apply(lambda x: f"R$ {x:,.2f}")
                    st.dataframe(df_top, use_container_width=True)
                else:
                    st.info("Não há gastos neste período.")

           # ===== Dashboard Principal =====
            with tab5:
                st.subheader("📊 Dashboard Principal")
                
                # ---------- helpers ----------
                def brl_fmt(v):
                    """Formata em R$ pt-BR. Zeros viram 'R$ -'."""
                    try:
                        v = float(v)
                    except Exception:
                        return "R$ -"
                    if abs(v) < 0.005:
                        return "R$ -"
                    s = f"{abs(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                    prefix = "-R$ " if v < 0 else "R$ "
                    return prefix + s
                
                def linhas_secao(titulo, tipo, total_receitas, df_mes_valid, conn, mostra_pct=False):
                    """
                    Monta linhas para uma seção:
                      - 1 linha de título
                      - todas as subcategorias (mesmo sem movimento)
                      - 1 linha de Total
                      - (opcional) 1 linha de % sobre Receitas
                    Retorna (linhas:list[dict], total_da_secao:float)
                    """
                    linhas = [{"Item": titulo, "Valor": ""}]
                
                    # todas as subcategorias cadastradas daquele tipo
                    sql_subs = """
                        SELECT c.nome AS categoria, s.nome AS subcategoria
                        FROM subcategorias s
                        JOIN categorias c ON s.categoria_id = c.id
                        WHERE c.tipo = ?
                        ORDER BY c.nome, s.nome
                    """
                    all_subs = pd.read_sql_query(sql_subs, conn, params=(tipo,))
                
                    # soma dos lançamentos do mês para aquele tipo (excluindo Transferências já feito em df_mes_valid)
                    df_tipo = df_mes_valid[df_mes_valid["tipo"] == tipo].copy()
                    if df_tipo.empty:
                        soma = pd.DataFrame(columns=["categoria", "subcategoria", "value"])
                    else:
                        soma = (df_tipo
                                .groupby(["categoria", "subcategoria"], dropna=False)["value"]
                                .sum()
                                .reset_index())
                
                    # garante todas as subcategorias
                    merged = all_subs.merge(soma, on=["categoria", "subcategoria"], how="left").fillna({"value": 0.0})
                
                    # para despesas/investimentos mostramos valor absoluto
                    is_receita = (tipo.lower() == "receita")
                
                    for _, r in merged.iterrows():
                        val = r["value"] if is_receita else abs(r["value"])
                        label = f"{r['categoria']} - {r['subcategoria']}"
                        linhas.append({"Item": label, "Valor": brl_fmt(val)})
                
                    total_sec = merged["value"].sum()
                    if not is_receita:
                        total_sec = abs(total_sec)
                
                    titulo_base = titulo.split(" (")[0]  # remove "(20%)" etc para o texto do total
                    linhas.append({"Item": f"Total de {titulo_base}", "Valor": brl_fmt(total_sec)})
                
                    if mostra_pct:
                        pct = (total_sec / total_receitas * 100) if total_receitas > 0 else 0.0
                        if "Investimentos" in titulo_base:
                            pct_label = "% de Investimentos Realizado"
                        else:
                            pct_label = f"% de {titulo_base}"
                        linhas.append({"Item": pct_label, "Valor": f"{pct:.0f}%"})
                
                    return linhas, float(total_sec)
                
                # ---------- dados base do mês ----------
                # df_mes_valid já exclui Transferências acima
                # calculamos total de Receitas (apenas tipo Receita)
                df_receitas_mes = df_mes_valid[df_mes_valid["tipo"] == "Receita"].copy()
                total_receitas = float(df_receitas_mes["value"].sum()) if not df_receitas_mes.empty else 0.0
                
                linhas_total = []
                
                # Seção: Receitas
                lin, tot_rec = linhas_secao("Receitas", "Receita", total_receitas, df_mes_valid, conn, mostra_pct=False)
                linhas_total += lin
                
                # Seção: Investimentos (20%)
                lin, tot_inv = linhas_secao("Investimentos (20%)", "Investimento", total_receitas, df_mes_valid, conn, mostra_pct=True)
                linhas_total += lin
                
                # Seção: Despesas Fixas (50%)
                lin, tot_fix = linhas_secao("Despesas Fixas (50%)", "Despesa Fixa", total_receitas, df_mes_valid, conn, mostra_pct=True)
                linhas_total += lin
                
                # Seção: Despesas Variáveis (30%)
                lin, tot_var = linhas_secao("Despesas Variáveis (30%)", "Despesa Variável", total_receitas, df_mes_valid, conn, mostra_pct=True)
                linhas_total += lin
                
                # Saldo do mês = receitas - (inv + fixas + variáveis)
                saldo_mes = total_receitas - (tot_inv + tot_fix + tot_var)
                linhas_total.append({"Item": "Saldo do Mês", "Valor": brl_fmt(saldo_mes)})
                
                # ---------- dataframe e estilo ----------
                relatorio_df = pd.DataFrame(linhas_total, columns=["Item", "Valor"])
                
                def estilo_linhas(row):
                    item = str(row["Item"])
                    titulos = {
                        "Receitas",
                        "Investimentos (20%)",
                        "Despesas Fixas (50%)",
                        "Despesas Variáveis (30%)",
                        "Saldo do Mês",
                    }
                    if item in titulos or item.startswith("Total de ") or item.startswith("% de "):
                        return ["font-weight: 700"] * 2
                    return [""] * 2
                
                st.dataframe(
                    relatorio_df.style.apply(estilo_linhas, axis=1),
                    use_container_width=True
                )

# =====================
# DASHBOARD PRINCIPAL
# =====================
elif menu == "Dashboard Principal":
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

            # linhas do relatório (sem saldo)
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
                xaxis=dict(side="top")
            )

            st.plotly_chart(fig, use_container_width=True)
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

                    # ---------- PRÉ-VISUALIZAÇÃO ----------
                    st.subheader("Pré-visualização")

                    # 🔹 histórico de classificações já feitas
                    hist = _build_hist_similaridade(conn, conta_sel)

                    df_preview = df.copy()
                    df_preview["Conta destino"] = conta_sel
                    if is_cartao_credito(conta_sel) and mes_ref_cc and ano_ref_cc:
                        from calendar import monthrange
                        dia_final = min(dia_venc_cc, monthrange(ano_ref_cc, mes_ref_cc)[1])
                        dt_eff = date(ano_ref_cc, mes_ref_cc, dia_final)
                        df_preview["Data efetiva"] = dt_eff.strftime("%d/%m/%Y")

                    # 🔹 tenta sugerir categoria/subcategoria
                    sugestoes = []
                    for _, r in df_preview.iterrows():
                        desc = str(r["Descrição"])
                        val = r["Valor"]
                        if val is None:
                            sugestoes.append("Nenhuma")
                            continue

                        if is_cartao_credito(conta_sel) and mes_ref_cc and ano_ref_cc:
                            if val > 0:
                                # Compra normal
                                sub_id, label, score = sugerir_subcategoria(desc, hist) if hist else (None, None, 0)
                                sugestoes.append(label if sub_id else "Nenhuma")
                            else:
                                # Estorno
                                sugestoes.append("Estorno → Cartão de Crédito")
                        else:
                            sub_id, label, score = sugerir_subcategoria(desc, hist) if hist else (None, None, 0)
                            sugestoes.append(label if sub_id else "Nenhuma")

                    df_preview["Sugestão Categoria/Sub"] = sugestoes

                    st.dataframe(df_preview, use_container_width=True)

                    # ---------- IMPORTAR ----------
                    if st.button("Importar lançamentos"):
                        from calendar import monthrange
                        inserted = 0

                        # Garante categoria "Estorno" e subcategoria "Cartão de Crédito"
                        cursor.execute("SELECT id FROM categorias WHERE nome=?", ("Estorno",))
                        row = cursor.fetchone()
                        if row:
                            estorno_cat_id = row[0]
                        else:
                            cursor.execute("INSERT INTO categorias (nome, tipo) VALUES (?, ?)", ("Estorno", "Neutra"))
                            estorno_cat_id = cursor.lastrowid

                        cursor.execute("SELECT id FROM subcategorias WHERE nome=? AND categoria_id=?", ("Cartão de Crédito", estorno_cat_id))
                        row = cursor.fetchone()
                        if row:
                            estorno_sub_id = row[0]
                        else:
                            cursor.execute(
                                "INSERT INTO subcategorias (categoria_id, nome) VALUES (?, ?)",
                                (estorno_cat_id, "Cartão de Crédito")
                            )
                            estorno_sub_id = cursor.lastrowid

                        conn.commit()

                        # 🔹 histórico de classificações já feitas
                        hist = _build_hist_similaridade(conn, conta_sel)

                        # Loop de lançamentos
                        for _, r in df.iterrows():
                            desc = str(r["Descrição"])
                            val = r["Valor"]
                            if val is None:
                                continue

                            if is_cartao_credito(conta_sel) and mes_ref_cc and ano_ref_cc:
                                dia_final = min(dia_venc_cc, monthrange(ano_ref_cc, mes_ref_cc)[1])
                                dt_obj = date(ano_ref_cc, mes_ref_cc, dia_final)

                                if val > 0:
                                    # Compra → grava como negativo
                                    val = -abs(val)
                                    sub_id, _, _ = sugerir_subcategoria(desc, hist) if hist else (None, None, 0)
                                else:
                                    # Estorno → grava como positivo
                                    val = abs(val)
                                    sub_id = estorno_sub_id
                            else:
                                dt_obj = r["Data"] if isinstance(r["Data"], date) else parse_date(r["Data"])
                                if not isinstance(dt_obj, date):
                                    continue
                                sub_id, _, _ = sugerir_subcategoria(desc, hist) if hist else (None, None, 0)

                            # Insere
                            cursor.execute("""
                                INSERT INTO transactions (date, description, value, account, subcategoria_id, status)
                                VALUES (?, ?, ?, ?, ?, 'final')
                            """, (dt_obj.strftime("%Y-%m-%d"), desc, val, conta_sel, sub_id))
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
            with zipfile.ZipFile(buffer, "w") as zf:
                for nome_tabela in ["contas", "categorias", "subcategorias", "transactions"]:
                    df = pd.read_sql_query(f"SELECT * FROM {nome_tabela}", conn)
                    csv_bytes = df.to_csv(index=False).encode("utf-8")
                    zf.writestr(f"{nome_tabela}.csv", csv_bytes)
            buffer.seek(0)
            st.download_button("⬇️ Clique aqui para baixar backup.zip", buffer, file_name="backup_financas.zip")

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
