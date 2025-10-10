# Controle Financeiro

Web app em **Streamlit** com **login (bcrypt)** para importar extratos de **conta corrente** e **faturas de cartão** (CSV/XLS/XLSX), consolidar gastos por competência e registrar **provisões**.

## Autenticação (um usuário)

- Configure no **Streamlit Cloud** em `Secrets`:
  - `AUTH_USERNAME`: seu usuário (ex.: `rafael`)
  - `AUTH_PASSWORD_BCRYPT`: hash bcrypt da sua senha
  - Opcionalmente, você pode definir `AUTH_PASSWORD_PLAIN` com a senha em texto puro
    (útil para testes locais rápidos). Quando ambos estiverem configurados, o hash
    continua tendo prioridade.
  - `AUTH_EMAIL`: e-mail principal do usuário autenticado (usado para recuperação de senha).

- Para o usuário padrão `rafael`, o sistema já associa automaticamente o e-mail
  `rselmikaitis@gmail.com`, podendo ser sobrescrito pelo segredo `AUTH_EMAIL`.

### Recuperação de senha com código por e-mail

- Para habilitar o envio do código de redefinição de senha, informe também:
  - `EMAIL_SMTP_HOST`, `EMAIL_SMTP_PORT`
  - `EMAIL_SMTP_USERNAME`, `EMAIL_SMTP_PASSWORD`
  - `EMAIL_SMTP_USE_TLS` (opcional, `True` por padrão)
  - `EMAIL_FROM`: endereço que aparecerá como remetente do e-mail
- Opcionalmente, ajuste `RESET_CODE_TTL_MINUTES` para definir quantos minutos o
  código permanece válido (padrão: 15 minutos).
- Na tela inicial, utilize a aba **“Recuperar senha”** para solicitar o código e
  cadastrar uma nova senha após recebê-lo por e-mail.

Para gerar um hash, use o **expander de “Gerar hash”** na tela de login localmente, copie o hash e cole em `Secrets`.

## Como rodar no Mac

1. Python 3.10+
2. Ambiente e dependências:
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
