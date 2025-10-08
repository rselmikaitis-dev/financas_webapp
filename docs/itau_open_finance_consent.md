# Consentimento para contas no Itaú Open Finance

Este guia resume o fluxo necessário para que uma conta corrente fique autorizada a expor extratos via API e evitar o erro **403 Forbidden** ao consultar `/open-banking/accounts/v1/accounts/{accountId}/transactions`.

## 1. Criar um consentimento com escopos de conta

1. Envie um `POST https://api.itau.com.br/open-banking/consents/v1/consents` usando mTLS e o par `client_id`/`client_secret` da aplicação.
2. Informe os escopos exigidos pela API de extrato:

   ```json
   {
     "data": {
       "permissions": [
         "ACCOUNTS_READ",
         "ACCOUNTS_BALANCES_READ",
         "ACCOUNTS_TRANSACTIONS_READ",
         "ACCOUNTS_STATEMENTS_READ"
       ],
       "expirationDateTime": "2024-12-31T23:59:59Z",
       "transactionFromDateTime": "2024-01-01T00:00:00Z",
       "transactionToDateTime": "2024-12-31T23:59:59Z"
     }
   }
   ```
3. Armazene o `consentId` retornado e apresente o fluxo de autenticação ao titular.

> Dica: caso já possua um consentimento antigo, consulte `GET /open-banking/consents/v1/consents/{consentId}` e verifique se o `status` é `AUTHORISED` e se os `permissions` incluem todos os escopos acima. Caso contrário, gere um novo consentimento.

## 2. Coletar a autorização do titular

1. Redirecione o correntista para o endpoint OAuth do Itaú com `response_type=code`, `scope=openid accounts`, `consent_id=<consentId>` e o `code_challenge`/`state` exigidos.
2. Após o login e confirmação do titular, troque o `code` recebido por um `access_token` usando `POST https://sts.itau.com.br/api/oauth/token` com `grant_type=authorization_code`.
3. Guarde o `access_token` e o `refresh_token` para reutilização enquanto o consentimento estiver válido.

## 3. Chamar as APIs de contas e transações

1. Use sempre o `consentId` autorizado na requisição de token ou envie-o no cabeçalho `x-itau-consent-id` quando aplicável.
2. Preencha os cabeçalhos obrigatórios (`x-itau-apikey`, `x-itau-correlation-id`, `x-fapi-interaction-id`, `x-itau-nonce`) conforme a especificação.
3. Se o Itaú retornar **403 Forbidden**, confira:
   - o `status` do consentimento (deve ser `AUTHORISED`);
   - se a conta do `accountId` está entre as selecionadas pelo titular ao autorizar;
   - se o token usado foi emitido com o mesmo `consentId` e ainda está vigente;
   - se os cabeçalhos obrigatórios foram enviados corretamente.

Seguindo esses passos, a conta ficará apta a liberar o extrato via Open Finance e o aplicativo poderá importar as transações sem bloqueios.
