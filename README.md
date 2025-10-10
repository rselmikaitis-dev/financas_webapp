# Controle Financeiro

Web app em **Streamlit** com **login (bcrypt)** para importar extratos de **conta corrente** e **faturas de cartão** (CSV/XLS/XLSX), consolidar gastos por competência e registrar **provisões**.

## Autenticação (um usuário)

- Configure no **Streamlit Cloud** em `Secrets`:
  - `AUTH_USERNAME`: seu usuário (ex.: `rafael`)
  - `AUTH_PASSWORD_BCRYPT`: hash bcrypt da sua senha
  - Opcionalmente, você pode definir `AUTH_PASSWORD_PLAIN` com a senha em texto puro
    (útil para testes locais rápidos). Quando ambos estiverem configurados, o hash
    continua tendo prioridade.

Para gerar um hash, use o **expander de “Gerar hash”** na tela de login localmente, copie o hash e cole em `Secrets`.

## Como rodar no Mac

1. Python 3.10+
2. Ambiente e dependências:
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
