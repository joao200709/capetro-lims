# CAPETRO LIMS

Sistema de gestão laboratorial da Capetro. Controla amostras, ensaios e laudos dos produtos asfálticos.

## Como rodar

Precisa de **Python 3.10+** instalado.

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

- Dashboard com métricas e gráficos
- Cadastro e filtro de amostras
- Registro de ensaios com verificação automática de conformidade
- Geração de laudos em HTML e PDF
- Login com senhas criptografadas
- Parâmetros baseados em normas DNIT
- Produtos reais da Capetro (CAP 50/70, RR-1C, RR-2C, Imprimer)

## Tecnologias

Flask, SQLite, Bootstrap 5, Chart.js, WeasyPrint

---

*Projeto de estágio — Capetro Asfaltos / CPTI*
