# ⬡ CAPETRO LIMS

**Sistema de Gestão Laboratorial para o CPTI**
Protótipo de controle de ensaios, amostras e laudos técnicos para os produtos asfálticos da Capetro.

---

## Pré-requisitos

- **Python 3.10+** instalado ([python.org](https://python.org))
- **VS Code** como editor
- **DBeaver** para visualizar o banco SQLite (opcional, mas recomendado)

---

## Como rodar o projeto

### 1. Clone ou extraia o projeto
```bash
cd ~/projetos  # ou onde preferir
# se baixou o zip:
unzip capetro-lims.zip
cd capetro-lims
```

### 2. Crie um ambiente virtual (recomendado)
```bash
python -m venv venv

# Linux/Mac:
source venv/bin/activate

# Windows:
venv\Scripts\activate
```

### 3. Instale as dependências
```bash
pip install -r requirements.txt
```

> **Nota:** O WeasyPrint pode precisar de dependências do sistema.
> - **Windows:** geralmente funciona direto com pip
> - **Linux:** `sudo apt install libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf2.0-0`
> - **Mac:** `brew install pango`
>
> Se o WeasyPrint der problema, não se preocupe — o sistema funciona 100% sem ele.
> O laudo HTML com botão de imprimir funciona independente do WeasyPrint.

### 4. Inicialize o banco de dados
```bash
python database.py
```
Isso cria o arquivo `capetro_lims.db` com os produtos da Capetro e dados de demonstração.

### 5. Rode o servidor
```bash
python app.py
```

### 6. Acesse no navegador
```
http://localhost:5000
```

---

## Abrindo o banco no DBeaver

1. Abra o DBeaver
2. **Database > New Connection > SQLite**
3. Em "Path", selecione o arquivo `capetro_lims.db` na pasta do projeto
4. Clique em **Finish**
5. Pronto! Você pode explorar as tabelas, fazer queries SQL, etc.

---

## Estrutura do Projeto

```
capetro-lims/
├── app.py              ← Aplicação Flask (rotas e lógica)
├── database.py         ← Schema do banco + dados iniciais
├── requirements.txt    ← Dependências Python
├── capetro_lims.db     ← Banco SQLite (criado ao rodar database.py)
├── static/
│   └── css/
│       └── style.css   ← Estilos customizados
└── templates/
    ├── base.html       ← Layout base (sidebar + topbar)
    ├── dashboard.html  ← Página inicial com métricas
    ├── amostras/
    │   ├── lista.html  ← Listagem de amostras com filtros
    │   ├── nova.html   ← Formulário de nova amostra
    │   └── detalhe.html← Detalhes + resultados de uma amostra
    ├── ensaios/
    │   └── registrar.html ← Formulário de registro de ensaios
    └── laudos/
        └── laudo.html  ← Laudo técnico (tela + impressão/PDF)
```

---

## Funcionalidades

- **Dashboard** com métricas e gráficos (Chart.js)
- **CRUD de amostras** com filtros por produto e status
- **Registro de ensaios** com verificação automática de conformidade
- **Geração de laudos** em HTML (imprimível) e PDF (WeasyPrint)
- **Dados reais** dos produtos Capetro (CAP 50/70, RR-1C, RR-2C, Imprimer)
- **Parâmetros de ensaio** baseados em normas DNIT

---

## Próximos passos (ideias para evoluir)

- [ ] Sistema de login/autenticação
- [ ] Histórico de alterações (audit log)
- [ ] Exportação de dados para Excel
- [ ] Upload de fotos das amostras
- [ ] Notificações de amostras pendentes
- [ ] API REST para integração com outros sistemas
- [ ] Deploy em servidor (Render, Railway, etc.)

---

## Tecnologias

| Camada    | Tecnologia         |
|-----------|--------------------|
| Backend   | Flask (Python)     |
| Banco     | SQLite + SQL puro  |
| Frontend  | HTML/CSS/JS        |
| UI        | Bootstrap 5        |
| Gráficos  | Chart.js           |
| PDF       | WeasyPrint         |
| Fontes    | DM Sans (Google)   |

---

*Protótipo desenvolvido como projeto de estágio para a Capetro Asfaltos.*
