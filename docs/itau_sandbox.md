# Sandbox Itaú for Developers

Este guia reúne os passos para gerar credenciais e tokens do ambiente de *sandbox* do Itaú for Developers, além de opções para automatizar o processo durante os testes do web app.

## 1. Obter credenciais do sandbox

1. Acesse o [Portal Itaú for Developers](https://devportal.itau.com.br/).
2. Navegue até o catálogo e abra a API que deseja testar.
3. Clique em **Ver especificação técnica**.
4. No bloco **Credenciais**, clique em **Gerar credenciais** para criar o par `client_id` e `client_secret` (apenas uma vez por usuário).

> As credenciais de sandbox só funcionam no ambiente de testes. Para produção será necessário gerar um novo par seguindo a documentação específica de produção.

## 2. Gerar token manualmente

1. Ainda na página da API, clique em **Gerar token** logo abaixo das credenciais.
2. O token (`access_token`) aparece em seguida e tem validade de 5 minutos.
3. Utilize o console de testes da própria página para executar chamadas. Não é necessário informar o token manualmente: o portal o injeta automaticamente nas requisições.

## 3. Gerar token com cURL

Para automatizar a geração de tokens via linha de comando, use o endpoint `POST https://sandbox.devportal.itau.com.br/api/oauth/jwt`:

```bash
curl --location --request POST 'https://sandbox.devportal.itau.com.br/api/oauth/jwt' \
  --header 'Content-Type: application/x-www-form-urlencoded' \
  --data grant_type=client_credentials \
  --data client_id="$CLIENT_ID" \
  --data client_secret="$CLIENT_SECRET"
```

A resposta terá a forma:

```json
{
  "access_token": "eyJhbGciOi...",
  "token_type": "Bearer",
  "expires_in": 300,
  "active": true,
  "scope": "exemplo-scope"
}
```

O token é válido apenas para as URLs do sandbox (`https://sandbox.devportal.itau.com.br/`).

## 4. Testar chamadas de API

Depois de obter um token válido:

- Utilize a **base URL** da API (`sandbox-url`) exibida na especificação técnica.
- Monte as requisições seguindo os exemplos da documentação ou do console de testes.
- Ao usar cURL ou ferramentas como Postman, informe o token no cabeçalho `Authorization: Bearer <token>`.

### Exemplo de chamada com cURL

```bash
curl --location --request GET 'https://sandbox.devportal.itau.com.br/sandboxapi/endpoint_exemplo?param=valor' \
  --header 'Authorization: Bearer eyJhbGciOi...'
```

## 5. Automação com Postman

1. Importe a collection oficial **Itaú for Developers v.2** (`sandbox.postman_collection.json`).
2. Importe também o environment `SANDBOX_PRD_ENV`.
3. No environment, informe o `client_id` e `client_secret` nas colunas **CURRENT VALUE**.
4. Execute a requisição `POST /auth` para preencher automaticamente a variável `sandbox_token` (expira em 5 minutos).
5. Use as demais requisições da collection como base para seus testes.

## 6. Automação via script Python

Para facilitar a integração com este projeto, foi adicionado o utilitário `scripts/itau_sandbox_token.py`. Ele solicita o token e o imprime no console, podendo ser integrado a *pipelines* ou *shell scripts*.

### Instalação das dependências

```bash
pip install -r requirements.txt
```

### Uso básico

```bash
python scripts/itau_sandbox_token.py --client-id "seu_client_id" --client-secret "seu_client_secret"
```

Por padrão o script exibe apenas o `access_token`. Para visualizar toda a resposta, utilize `--raw`.

### Utilizando variáveis de ambiente

```bash
export ITAU_SANDBOX_CLIENT_ID="seu_client_id"
export ITAU_SANDBOX_CLIENT_SECRET="seu_client_secret"
python scripts/itau_sandbox_token.py
```

O token obtido pode ser injetado automaticamente em requisições subsequentes do seu fluxo de testes.

## 7. Próximos passos para produção

Quando a aplicação estiver pronta para produção, gere novas credenciais seguindo as instruções do portal em **Produção**. O fluxo exige certificado mTLS e endpoints distintos — consulte também o arquivo [`docs/itau_open_finance_consent.md`](itau_open_finance_consent.md) para entender o processo de consentimento no ambiente controlado.
