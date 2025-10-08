# Controle Financeiro

Web app em **Streamlit** com **login (bcrypt)** para importar extratos de **conta corrente** e **faturas de cartão** (CSV/XLS/XLSX), consolidar gastos por competência e registrar **provisões**.

## Autenticação (um usuário)

- Configure no **Streamlit Cloud** em `Secrets`:
  - `AUTH_USERNAME`: seu usuário (ex.: `rafael`)
  - `AUTH_PASSWORD_BCRYPT`: hash bcrypt da sua senha

Para gerar um hash, use o **expander de “Gerar hash”** na tela de login localmente, copie o hash e cole em `Secrets`.

## Como rodar no Mac

1. Python 3.10+
2. Ambiente e dependências:
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Integração com Itaú Open Finance

1. Cadastre sua aplicação no portal de desenvolvedores do Itaú e habilite o escopo de **Open Finance** conforme a [documentação oficial](https://devportal.itau.com.br/nossas-apis/openfinance).
2. No arquivo `.streamlit/secrets.toml` (ou nas variáveis de ambiente do Streamlit Cloud) crie a seção `itau_openfinance` com as credenciais e caminhos para os certificados mTLS:

   ```toml
   [itau_openfinance]
   client_id = "..."
   client_secret = "..."
   consent_id = "..."            # opcional dependendo do fluxo
   base_url = "https://api.itau.com.br/open-banking"
   token_url = "https://sts.itau.com.br/api/oauth/token"
   certificate = "/app/certs/cert.pem"
   certificate_key = "/app/certs/key.pem"
   scope = "openid accounts transactions"
   static_access_token = "eyJ..."            # opcional: token estático já obtido
   static_token_expires_at = "2024-08-30T18:00:00Z"  # ISO 8601 ou timestamp Unix
   accounts_endpoint = "/open-banking/accounts/v1/accounts"  # opcional
   transactions_endpoint = "/open-banking/accounts/v1/accounts/{account_id}/transactions"
   # opcional: cabeçalhos adicionais (JSON)
   additional_headers = "{\"x-itau-nonce\": \"...\"}"
   ```

   > Os arquivos de certificado/ chave devem estar presentes no contêiner (ex.: pasta `certs/`).

3. Antes de importar, siga o [guia de consentimento](docs/itau_open_finance_consent.md) para criar/autorizar o `consentId` necessário e evitar respostas 403 da API.
4. Acesse o menu **Importação → Open Finance Itaú** no app para:
   - listar contas elegíveis (`Atualizar contas Itaú`);
   - selecionar a conta (`accountId`) e o período desejado;
   - importar as transações diretamente para a base local, utilizando o mesmo fluxo de classificação/edição do upload de arquivos.

5. Caso deseje testar manualmente, é possível informar `client_id`, `client_secret`, `consent_id`, token estático, endpoints, cabeçalhos e parâmetros extras diretamente na interface — os valores digitados ficam apenas na sessão atual.

6. Para cartões de crédito cadastrados na aba **Configurações → Contas** com dia de vencimento, continue selecionando o mês/ano de referência antes de importar para que as parcelas futuras sejam geradas corretamente.
