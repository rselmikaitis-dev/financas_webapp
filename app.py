import streamlit as st
import pandas as pd
import sqlite3

# Configuração inicial do aplicativo (pode ajustar título/ícone se necessário)
st.set_page_config(page_title="Controle Financeiro", page_icon="💰", layout="wide")

# Inicialização da conexão com o banco de dados SQLite (reutilizando durante a sessão)
if 'conn' not in st.session_state:
    st.session_state.conn = sqlite3.connect('data.db', check_same_thread=False)
conn = st.session_state.conn
cursor = conn.cursor()

# Garantir que as tabelas necessárias existam (contas e transações)
cursor.execute("""
    CREATE TABLE IF NOT EXISTS contas (
        id INTEGER PRIMARY KEY,
        nome TEXT UNIQUE
    )
""")
cursor.execute("""
    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY,
        date TEXT,
        description TEXT,
        value REAL,
        account TEXT
    )
""")
conn.commit()

# Verificação de autenticação (substitua de acordo com a lógica de autenticação do app)
if 'authentication_status' in st.session_state:
    if not st.session_state['authentication_status']:
        st.error("Você precisa fazer login para continuar.")
        st.stop()
else:
    # Se não houver informação de autenticação, não prosseguir
    st.warning("Por favor, faça login para acessar o aplicativo.")
    st.stop()

# Definição das abas principais do aplicativo
aba_importacao, aba_dashboard, aba_contas = st.tabs(["Importação", "Dashboard", "⚙️ Contas"])

# --- Aba de Importação de Lançamentos ---
with aba_importacao:
    st.header("Importação de Lançamentos")
    # Seleção da conta/cartão vinculada aos lançamentos importados
    cursor.execute("SELECT nome FROM contas")
    contas_cadastradas = [row[0] for row in cursor.fetchall()]
    if len(contas_cadastradas) == 0:
        st.info("Nenhuma conta cadastrada. Cadastre uma conta na aba ⚙️ Contas antes de importar lançamentos.")
    else:
        conta_escolhida = st.selectbox("Nome da conta/cartão", options=contas_cadastradas)
        # Upload do arquivo de extrato/fatura
        arquivo = st.file_uploader("Selecione o arquivo do extrato ou fatura", type=["xls", "xlsx", "csv"])
        btn_importar = st.button("Importar", disabled=(arquivo is None))
        if btn_importar:
            if arquivo is None:
                st.error("Por favor, selecione um arquivo para importar.")
            else:
                try:
                    # Leitura do arquivo em um DataFrame pandas
                    if arquivo.name.lower().endswith('.csv'):
                        df = pd.read_csv(arquivo, sep=";", engine='python')  # exemplo: CSV separado por ponto-e-vírgula
                    else:
                        df = pd.read_excel(arquivo)
                except Exception as e:
                    st.error(f"Erro ao ler o arquivo: {e}")
                    st.stop()
                # Determinar formato (extrato bancário ou fatura de cartão) com base nas colunas
                total_importados = 0
                if 'Débito' in df.columns or 'Debito' in df.columns:
                    # Trata como Extrato de conta corrente
                    col_debito = 'Débito' if 'Débito' in df.columns else 'Debito'
                    col_credito = 'Crédito' if 'Crédito' in df.columns else 'Credito'
                    col_desc = 'Identificação' if 'Identificação' in df.columns else 'Descricao'
                    # Remover linhas de saldo (ex.: "SALDO ANTERIOR", "SALDO DO DIA")
                    df_filtrado = df[~df[col_desc].astype(str).str.contains('SALDO', case=False, na=False)]
                    # Inserir cada lançamento filtrado no banco
                    for _, row in df_filtrado.iterrows():
                        # Converter data para string no formato YYYY-MM-DD
                        data_str = row['Data']
                        if not isinstance(data_str, str):
                            try:
                                data_str = data_str.strftime("%Y-%m-%d")
                            except Exception:
                                data_str = str(data_str)
                        descricao = str(row[col_desc])
                        # Calcular valor: crédito positivo, débito negativo
                        valor = 0.0
                        if col_credito in row and pd.notna(row[col_credito]):
                            valor += float(row[col_credito])
                        if col_debito in row and pd.notna(row[col_debito]):
                            valor -= float(row[col_debito])
                        valor = round(valor, 2)
                        # Inserir no SQLite
                        cursor.execute(
                            "INSERT INTO transactions (date, description, value, account) VALUES (?, ?, ?, ?)",
                            (data_str, descricao, valor, conta_escolhida)
                        )
                        total_importados += 1
                    conn.commit()
                else:
                    # Trata como Fatura de cartão de crédito
                    col_desc = 'Descrição' if 'Descrição' in df.columns else 'Descricao'
                    col_valor = 'Valor' if 'Valor' in df.columns else 'Valor (R$)'
                    df_filtrado = df[~df[col_desc].astype(str).str.contains('SALDO', case=False, na=False)]
                    for _, row in df_filtrado.iterrows():
                        data_str = row['Data']
                        if not isinstance(data_str, str):
                            try:
                                data_str = data_str.strftime("%Y-%m-%d")
                            except Exception:
                                data_str = str(data_str)
                        descricao = str(row[col_desc])
                        valor = float(row[col_valor]) if pd.notna(row[col_valor]) else 0.0
                        # Negativar valores de pagamentos/créditos (reduzem saldo do cartão)
                        desc_maiusc = descricao.upper()
                        if "PAGAMENTO" in desc_maiusc or "PAGTO" in desc_maiusc:
                            valor = -valor
                        valor = round(valor, 2)
                        cursor.execute(
                            "INSERT INTO transactions (date, description, value, account) VALUES (?, ?, ?, ?)",
                            (data_str, descricao, valor, conta_escolhida)
                        )
                        total_importados += 1
                    conn.commit()
                # Exibir mensagem de sucesso com quantidade importada
                if total_importados > 0:
                    st.success(f"{total_importados} lançamentos importados com sucesso para a conta **{conta_escolhida}**!")
                else:
                    st.warning("Nenhum lançamento foi importado (verifique se o arquivo continha lançamentos válidos).")

# --- Aba de Dashboard Financeiro ---
with aba_dashboard:
    st.header("Dashboard Financeiro")
    # Consultar todos os lançamentos do banco
    df_lanc = pd.read_sql_query("SELECT date, description, value, account FROM transactions", conn)
    if df_lanc.empty:
        st.info("Nenhum lançamento encontrado no banco de dados.")
    else:
        # Filtro por conta (multiselect)
        contas_disp = sorted(df_lanc['account'].unique().tolist())
        contas_selecionadas = st.multiselect("Filtrar por conta:", options=contas_disp, default=contas_disp)
        df_filtrado = df_lanc[df_lanc['account'].isin(contas_selecionadas)]
        # Filtro para incluir/excluir linhas de saldo
        incluir_saldo = st.checkbox("Incluir linhas de saldo (SALDO ANTERIOR/FINAL)", value=False)
        if not incluir_saldo:
            df_filtrado = df_filtrado[~df_filtrado['description'].str.contains('SALDO', case=False, na=False)]
        # Exibir resumo por conta
        resumo = df_filtrado.groupby('account')['value'].sum().reset_index()
        resumo.columns = ['Conta', 'Saldo (soma dos valores)']
        st.subheader("Saldo por Conta")
        st.dataframe(resumo, height=150)
        # Exibir tabela de lançamentos filtrados
        st.subheader("Lançamentos Detalhados")
        st.dataframe(df_filtrado.sort_values(by='date', ascending=False), height=300)

# --- Aba de Contas (Gerenciamento de contas/cartões) ---
with aba_contas:
    st.header("⚙️ Contas")
    # Lista de contas cadastradas
    cursor.execute("SELECT nome FROM contas ORDER BY nome")
    todas_contas = [row[0] for row in cursor.fetchall()]
    if len(todas_contas) > 0:
        st.write("**Contas cadastradas:**")
        for nome_conta in todas_contas:
            st.write(f"- {nome_conta}")
    else:
        st.write("Nenhuma conta cadastrada ainda.")
    # Formulário simples para adicionar nova conta
    st.subheader("Adicionar nova conta/cartão")
    nova_conta = st.text_input("Nome da nova conta:")
    if st.button("Adicionar conta"):
        if nova_conta.strip() == "":
            st.error("O nome da conta não pode ser vazio.")
        else:
            try:
                cursor.execute("INSERT INTO contas (nome) VALUES (?)", (nova_conta.strip(),))
                conn.commit()
                st.success(f"Conta **{nova_conta.strip()}** adicionada com sucesso!")
                # Atualizar a lista de contas em tempo real
                todas_contas.append(nova_conta.strip())
            except sqlite3.IntegrityError:
                st.error("Já existe uma conta cadastrada com esse nome. Escolha outro nome.")
