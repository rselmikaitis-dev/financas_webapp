import streamlit as st
import pandas as pd
from datetime import date
from helpers import parse_date, parse_money, seletor_mes_ano

def is_cartao_credito(nome_conta: str) -> bool:
    import unicodedata
    s = unicodedata.normalize("NFKD", str(nome_conta)).encode("ASCII", "ignore").decode().lower().strip()
    return s.startswith("cartao de credito")

def show(conn):
    st.header("Importação de Lançamentos")
    cursor = conn.cursor()

    # Selecionar conta destino
    contas_db = [row[0] for row in cursor.execute("SELECT nome FROM contas ORDER BY nome")]
    if not contas_db:
        st.error("Nenhuma conta cadastrada. Vá em Configurações → Contas.")
        return

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
        mes_ref_cc, ano_ref_cc = seletor_mes_ano(st, "Referente à fatura", date.today())

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
                return
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
