# CAPETRO LIMS

Sistema de gestão laboratorial da Capetro. Controla amostras, ensaios e laudos dos produtos asfálticos.

## Como rodar

Precisa de **Python 3.10+** e **PostgreSQL** instalados.

```bash
# Instale as dependências
pip install -r requirements.txt

# Crie o banco de dados
python database.py

# Rode o servidor
python app.py
```

Acesse `http://localhost:5000` no navegador.

**Login padrão:** `admin@capetro.com` / `admin123`

> O WeasyPrint (geração de PDF) pode pedir dependências extras no Linux/Mac. Se der problema, ignore, o laudo HTML funciona normalmente sem ele.

## Estrutura

```
capetro-lims/
├── app.py              ← Rotas e lógica principal
├── database.py         ← Banco de dados e dados iniciais
├── tests.py            ← Testes automatizados
├── requirements.txt    ← Dependências
├── .gitignore
├── static/css/         ← Estilos
└── templates/
    ├── base.html       ← Layout base (sidebar + topbar)
    ├── dashboard.html  ← Métricas e gráficos
    ├── auth/           ← Login, registro, logout
    ├── amostras/       ← Listagem, criação e detalhes
    ├── ensaios/        ← Registro de ensaios
    └── laudos/         ← Laudo técnico (tela + PDF)
```

## O que o sistema faz

- Dashboard com métricas, gráficos e filtro por período
- Cadastro, filtro e acompanhamento de amostras (CAP 50/70, RR-1C, RR-2C, Imprimer)
- Registro de ensaios com validação automática conforme normas DNIT
- Fluxo de revisão de laudos (Coordenador aprova antes de oficializar)
- Geração de laudos em HTML e PDF
- Histórico completo de alterações (rastreabilidade)
- Backup automático do banco (a cada 24h) + backup manual pelo painel
- Gestão de usuários com 4 perfis de acesso (Técnico, Coordenador, Gerente, Administrador)

## Segurança

- Senhas criptografadas
- Proteção CSRF em todos os formulários
- Rate limiting no login (bloqueia após 5 tentativas)
- Timeout por inatividade (30 min, client-side)
- "Lembrar de mim" com sessão de 30 dias

## Tecnologias

Flask, PostgreSQL, Bootstrap 5, Chart.js, WeasyPrint

---

*Projeto de estágio — Capetro Asfaltos / CPTI*
