import sys, os
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

import pandas as pd
import streamlit as st
from datetime import date
from db import init_db
from helpers import parse_money, parse_date, seletor_mes_ano, is_cartao_credito

st.header("⬆️ Importação de Lançamentos")

conn, cursor = init_db()

contas_db = [row[0] for row in cursor.execute("SELECT nome FROM contas ORDER BY nome")]
if not contas_db:
    st.error("Nenhuma conta cadastrada. Vá em Configurações → Contas.")
    st.stop()

conta_sel = st.selectbox("Conta destino", contas_db)

arquivo = st.file_uploader("Selecione o arquivo (CSV, XLSX ou XLS)", type=["csv", "xlsx", "xls"])

if conta_sel and is_cartao_credito(conta_sel):
    cursor.execute("SELECT dia_vencimento FROM contas WHERE nome=?", (conta_sel,))
    row = cursor.fetchone()
    dia_venc_cc = row[0] if row and row[0] else 1
    st.info(f"Conta de cartão detectada. Dia de vencimento cadastrado: **{dia_venc_cc}**.")
    mes_ref_cc, ano_ref_cc = seletor_mes_ano("Referente à fatura", date.today())
else:
    mes_ref_cc = ano_ref_cc = dia_venc_cc = None

if arquivo is not None:
    try:
        if arquivo.name.lower().endswith(".csv"):
            df = pd.read_csv(arquivo, sep=None, engine="python", dtype=str)
        else:
            df = pd.read_excel(arquivo, dtype=str)

        df.columns = [c.strip().lower().replace("\ufeff", "") for c in df.columns]

        mapa_colunas = {
            "data": ["data","data lançamento","data lancamento","dt"],
            "descrição": ["descrição","descricao","historico","histórico"],
            "valor": ["valor","valor (r$)","vlr","amount"]
        }

        col_map = {}
        for alvo, poss in mapa_colunas.items():
            for p in poss:
                if p in df.columns:
                    col_map[alvo] = p
                    break

        if "data" not in col_map or "valor" not in col_map:
            st.error("Arquivo inválido: colunas não encontradas.")
            st.stop()

        if "descrição" not in col_map:
            df["descrição"] = ""
            col_map["descrição"] = "descrição"

        df = df.rename(columns={
            col_map["data"]: "Data",
            col_map["descrição"]: "Descrição",
            col_map["valor"]: "Valor"
        })

        df = df[~df["Descrição"].astype(str).str.upper().str.startswith("SALDO")]

        df["Data"] = df["Data"].apply(parse_date)
        df["Valor"] = df["Valor"].apply(parse_money)

        st.subheader("Pré-visualização")
        st.dataframe(df, use_container_width=True)

        if st.button("Importar lançamentos"):
            inserted = 0
            for _, r in df.iterrows():
                desc = str(r["Descrição"])
                val = r["Valor"]
                if val is None:
                    continue
                if is_cartao_credito(conta_sel) and mes_ref_cc and ano_ref_cc:
                    from calendar import monthrange
                    dia_final = min(dia_venc_cc, monthrange(ano_ref_cc, mes_ref_cc)[1])
                    dt_obj = date(ano_ref_cc, mes_ref_cc, dia_final)
                    val = -abs(val)
                else:
                    dt_obj = r["Data"]
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
