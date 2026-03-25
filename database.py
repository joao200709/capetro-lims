import sqlite3
import random
import os
from werkzeug.security import generate_password_hash

DATABASE = 'capetro_lims.db'


def get_db():
    db = sqlite3.connect(DATABASE)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def init_db():
    db = get_db()

    db.executescript('''
        CREATE TABLE IF NOT EXISTS produtos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            descricao TEXT,
            tipo TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS parametros_ensaio (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            produto_id INTEGER NOT NULL,
            nome_parametro TEXT NOT NULL,
            unidade TEXT,
            valor_minimo REAL,
            valor_maximo REAL,
            metodo_ensaio TEXT,
            FOREIGN KEY (produto_id) REFERENCES produtos(id)
        );

        CREATE TABLE IF NOT EXISTS amostras (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            produto_id INTEGER NOT NULL,
            numero_lote TEXT NOT NULL,
            data_coleta TEXT NOT NULL,
            responsavel TEXT NOT NULL,
            status TEXT DEFAULT 'Pendente',
            observacoes TEXT,
            FOREIGN KEY (produto_id) REFERENCES produtos(id)
        );

        CREATE TABLE IF NOT EXISTS resultados (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            amostra_id INTEGER NOT NULL,
            parametro_id INTEGER NOT NULL,
            valor_obtido REAL,
            conforme INTEGER,
            data_ensaio TEXT,
            tecnico TEXT,
            FOREIGN KEY (amostra_id) REFERENCES amostras(id),
            FOREIGN KEY (parametro_id) REFERENCES parametros_ensaio(id)
        );

        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            senha_hash TEXT NOT NULL,
            cargo TEXT DEFAULT 'Tecnico',
            perfil TEXT DEFAULT 'tecnico',
            ativo INTEGER DEFAULT 1,
            criado_em TEXT DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS historico (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER,
            usuario_nome TEXT NOT NULL,
            acao TEXT NOT NULL,
            entidade TEXT NOT NULL,
            entidade_id INTEGER,
            detalhes TEXT,
            data_hora TEXT DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
        );
    ''')

    db.commit()
    db.close()
    print("[OK] Banco de dados criado.")


def _inserir_parametros(db, produto_id, parametros):
    """Insere uma lista de parametros de ensaio pra um produto."""
    for nome, unidade, vmin, vmax, metodo in parametros:
        db.execute('''
            INSERT INTO parametros_ensaio (produto_id, nome_parametro, unidade, valor_minimo, valor_maximo, metodo_ensaio)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', [produto_id, nome, unidade, vmin, vmax, metodo])


def seed_data():
    """Popula o banco com produtos, parametros DNIT, amostras de exemplo e usuario admin."""
    db = get_db()

    # Produtos
    produtos = [
        ('CAPETRO PLUS 50/70', 'Cimento Asfaltico de Petroleo com penetracao 50-70', 'CAP'),
        ('CAPETRO Emulsao RR-1C', 'Emulsao Asfaltica Cationica de Ruptura Rapida RR-1C', 'Emulsao'),
        ('CAPETRO Emulsao RR-2C', 'Emulsao Asfaltica Cationica de Ruptura Rapida RR-2C', 'Emulsao'),
        ('CAPETRO Imprimer', 'Emulsao Asfaltica para Imprimacao de bases granulares', 'Emulsao'),
    ]

    for nome, descricao, tipo in produtos:
        db.execute('INSERT INTO produtos (nome, descricao, tipo) VALUES (?, ?, ?)', [nome, descricao, tipo])
    db.commit()

    # Parametros de ensaio por produto (normas DNIT)
    _inserir_parametros(db, 1, [
        ('Penetracao (25C, 100g, 5s)',     '0,1 mm', 50.0,  70.0,  'DNIT-ME 155'),
        ('Ponto de Amolecimento',           'C',      46.0,  None,  'DNIT-ME 131'),
        ('Viscosidade Saybolt-Furol 135C',  's',      141.0, 235.0, 'DNIT-ME 004'),
        ('Viscosidade Saybolt-Furol 150C',  's',      50.0,  91.0,  'DNIT-ME 004'),
        ('Viscosidade Saybolt-Furol 177C',  's',      15.0,  30.0,  'DNIT-ME 004'),
        ('Indice de Susceptibilidade Termica', '',     -1.5,  0.7,   'DNIT 095/2006'),
        ('Ponto de Fulgor',                 'C',      235.0, None,  'DNIT-ME 148'),
        ('Solubilidade em Tricloroetileno', '%',      99.5,  None,  'DNIT-ME 165'),
        ('Ductilidade a 25C',              'cm',     60.0,  None,  'DNIT-ME 163'),
    ])

    _inserir_parametros(db, 2, [
        ('Viscosidade Saybolt-Furol 50C',  's',      20.0,  200.0, 'DNIT-ME 004'),
        ('Sedimentacao (7 dias)',           '%',      None,  5.0,   'DNIT-ME 006'),
        ('Peneiracao (0,84 mm)',            '%',      None,  0.1,   'DNIT-ME 005'),
        ('Carga da Particula',             '',       None,  None,  'DNIT-ME 002'),
        ('pH',                             '',       None,  6.5,   'DNIT-ME 001'),
        ('Residuo por Evaporacao',         '%',      62.0,  None,  'DNIT-ME 003'),
        ('Penetracao do Residuo (25C)',    '0,1 mm', 50.0,  250.0, 'DNIT-ME 155'),
    ])

    _inserir_parametros(db, 3, [
        ('Viscosidade Saybolt-Furol 50C',  's',      100.0, 400.0, 'DNIT-ME 004'),
        ('Sedimentacao (7 dias)',           '%',      None,  5.0,   'DNIT-ME 006'),
        ('Peneiracao (0,84 mm)',            '%',      None,  0.1,   'DNIT-ME 005'),
        ('Carga da Particula',             '',       None,  None,  'DNIT-ME 002'),
        ('pH',                             '',       None,  6.5,   'DNIT-ME 001'),
        ('Residuo por Evaporacao',         '%',      67.0,  None,  'DNIT-ME 003'),
        ('Penetracao do Residuo (25C)',    '0,1 mm', 50.0,  250.0, 'DNIT-ME 155'),
    ])

    _inserir_parametros(db, 4, [
        ('Viscosidade Saybolt-Furol 25C',  's',  10.0, 60.0, 'DNIT-ME 004'),
        ('Sedimentacao (7 dias)',           '%',  None, 5.0,  'DNIT-ME 006'),
        ('Peneiracao (0,84 mm)',            '%',  None, 0.1,  'DNIT-ME 005'),
        ('pH',                             '',   None, 6.5,  'DNIT-ME 001'),
        ('Residuo por Destilacao',         '%',  None, None, 'DNIT-ME 003'),
    ])

    # Amostras de demonstracao com resultados ficticios
    amostras_demo = [
        (1, 'CAP-2025-001', '2025-03-10', 'Joao Silva',      'Aprovada'),
        (1, 'CAP-2025-002', '2025-03-12', 'Joao Silva',      'Aprovada'),
        (2, 'RR1C-2025-001','2025-03-11', 'Maria Santos',    'Reprovada'),
        (3, 'RR2C-2025-001','2025-03-13', 'Maria Santos',    'Aprovada'),
        (1, 'CAP-2025-003', '2025-03-15', 'Joao Silva',      'Pendente'),
        (4, 'IMP-2025-001', '2025-03-16', 'Carlos Oliveira', 'Aprovada'),
        (2, 'RR1C-2025-002','2025-03-18', 'Maria Santos',    'Pendente'),
    ]

    for prod_id, lote, data, resp, status in amostras_demo:
        cursor = db.execute('''
            INSERT INTO amostras (produto_id, numero_lote, data_coleta, responsavel, status)
            VALUES (?, ?, ?, ?, ?)
        ''', [prod_id, lote, data, resp, status])

        amostra_id = cursor.lastrowid
        parametros = db.execute(
            'SELECT id, valor_minimo, valor_maximo FROM parametros_ensaio WHERE produto_id = ?',
            [prod_id]
        ).fetchall()

        for param in parametros:
            if status == 'Pendente':
                db.execute('''
                    INSERT INTO resultados (amostra_id, parametro_id, valor_obtido, conforme, data_ensaio, tecnico)
                    VALUES (?, ?, NULL, NULL, NULL, NULL)
                ''', [amostra_id, param['id']])
                continue

            # Gera valores ficticios dentro ou fora da faixa dependendo do status
            vmin = param['valor_minimo'] or 0
            vmax = param['valor_maximo'] or (vmin * 2 if vmin else 100)

            if status == 'Aprovada':
                valor = round(random.uniform(vmin, vmax), 2)
            else:
                valor = round(vmin * 0.7, 2) if random.random() > 0.5 else round(vmax * 1.3, 2)

            conforme = 1 if (
                (param['valor_minimo'] is None or valor >= param['valor_minimo']) and
                (param['valor_maximo'] is None or valor <= param['valor_maximo'])
            ) else 0

            db.execute('''
                INSERT INTO resultados (amostra_id, parametro_id, valor_obtido, conforme, data_ensaio, tecnico)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', [amostra_id, param['id'], valor, conforme, data, resp])

    # Usuario admin padrao
    db.execute(
        'INSERT INTO usuarios (nome, email, senha_hash, cargo, perfil) VALUES (?, ?, ?, ?, ?)',
        ['Administrador', 'admin@capetro.com', generate_password_hash('admin123'), 'Administrador', 'admin']
    )

    db.commit()
    db.close()
    print("[OK] Dados iniciais inseridos.")
    print("[OK] Usuario padrao: admin@capetro.com / admin123")


if __name__ == '__main__':
    if os.path.exists(DATABASE):
        os.remove(DATABASE)
        print("Banco antigo removido.")
    init_db()
    seed_data()
    print("Pronto!")
