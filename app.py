with tab1:
    st.subheader("Gerenciar Contas")
    cursor.execute("SELECT id, nome, dia_vencimento FROM contas ORDER BY nome")
    df_contas = pd.DataFrame(cursor.fetchall(), columns=["ID", "Conta", "Dia Vencimento"])

    if not df_contas.empty:
        st.dataframe(df_contas)

        conta_sel = st.selectbox("Selecione uma conta para editar/excluir", df_contas["Conta"])

        # Editar
        new_name = st.text_input("Novo nome da conta", value=conta_sel)
        new_venc = st.number_input("Novo dia de vencimento (se for cartão)", min_value=1, max_value=31, value=1)
        if st.button("Salvar alteração de conta"):
            cursor.execute("UPDATE contas SET nome=?, dia_vencimento=? WHERE nome=?", (new_name.strip(), new_venc, conta_sel))
            conn.commit()
            st.success("Conta atualizada!")
            st.rerun()

        # Excluir
        if st.button("Excluir conta selecionada"):
            cursor.execute("DELETE FROM contas WHERE nome=?", (conta_sel,))
            conn.commit()
            st.warning("Conta excluída. Lançamentos permanecem, mas sem vínculo com essa conta.")
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
