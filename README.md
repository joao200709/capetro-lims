# CAPETRO LIMS

Sistema de gestão laboratorial da Capetro. Controla amostras, ensaios, revisão e laudos de produtos asfálticos.

## Como rodar

Requisitos:

- Python 3.10+
- PostgreSQL
- `pg_dump` no PATH do sistema, caso queira usar backups pelo painel

```bash
# Instale as dependências
pip install -r requirements.txt

# Crie seu arquivo local de configuração
copy .env.example .env
```

Edite o `.env` com os dados da sua máquina. Para gerar uma `SECRET_KEY` real:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Exemplo de variáveis:

```env
APP_ENV=development
SECRET_KEY=cole-a-chave-gerada-aqui
DATABASE_URL=postgresql://usuario:senha@localhost:5432/capetro_lims
TEST_DATABASE_URL=postgresql://usuario:senha@localhost:5432/capetro_lims_test
FLASK_DEBUG=1
BACKUP_DIR=./backups
```

Depois:

```bash
# Crie as tabelas e dados iniciais no banco configurado
python database.py

# Rode o servidor
python app.py
```

Acesse `http://localhost:5000` no navegador.

**Login padrão após `python database.py`:** `admin@capetro.com` / `admin123`

> O WeasyPrint, usado para geração de PDF, pode pedir dependências extras no Linux/Mac. Se der problema, o laudo HTML continua funcionando normalmente.

## Testes

Os testes usam `TEST_DATABASE_URL`, separado do banco principal, porque recriam tabelas durante a execução.

```bash
python tests.py
```

Se `TEST_DATABASE_URL` não estiver configurado, os testes de integração com banco serão pulados com uma mensagem clara.

## Estrutura

```text
capetro-lims/
├── app.py              # Rotas e lógica principal
├── backup.py           # Backup manual e automático via pg_dump
├── config.py           # Configuração por variáveis de ambiente
├── database.py         # Banco de dados e dados iniciais
├── tests.py            # Testes automatizados
├── requirements.txt    # Dependências
├── .env.example        # Modelo seguro de configuração local
├── static/css/         # Estilos
└── templates/
    ├── base.html       # Layout base
    ├── dashboard.html  # Métricas e gráficos
    ├── auth/           # Login
    ├── amostras/       # Listagem, criação, edição e detalhes
    ├── ensaios/        # Registro de ensaios
    ├── laudos/         # Laudo técnico HTML/PDF
    └── usuarios/       # Gestão de usuários
```

## O que o sistema faz

- Dashboard com métricas, gráficos e filtro por período
- Cadastro, filtro e acompanhamento de amostras
- Registro de ensaios com validação automática conforme parâmetros DNIT
- Fluxo de revisão de laudos por coordenador/gestão
- Geração de laudos em HTML e PDF
- Histórico completo de alterações
- Backup automático a cada 24h e backup manual pelo painel
- Gestão de usuários com perfis de acesso: técnico, coordenador, gerente e administrador

## Segurança e configuração

- Senhas criptografadas com Werkzeug
- Proteção CSRF em formulários
- Rate limiting no login
- Timeout por inatividade
- `SECRET_KEY`, `DATABASE_URL` e `TEST_DATABASE_URL` ficam fora do código
- `.env` fica fora do Git; use `.env.example` como modelo

---

Projeto de estágio — Capetro Asfaltos / CPTI
