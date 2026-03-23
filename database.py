"""
Módulo de banco de dados - Schema e dados iniciais
Usa SQLite (arquivo capetro_lims.db na raiz do projeto)

Os dados dos parâmetros de ensaio são baseados nas fichas técnicas reais
dos produtos da Capetro, conforme normas DNIT.
"""

import sqlite3
import os

DATABASE = 'capetro_lims.db'


def get_db():
    """Retorna uma conexão com o banco de dados."""
    db = sqlite3.connect(DATABASE)
    db.row_factory = sqlite3.Row  # Permite acessar colunas por nome
    db.execute("PRAGMA foreign_keys = ON")
    return db


def init_db():
    """Cria todas as tabelas do banco de dados."""
    db = get_db()

    db.executescript('''
        -- Produtos fabricados pela Capetro
        CREATE TABLE IF NOT EXISTS produtos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            descricao TEXT,
            tipo TEXT NOT NULL  -- 'CAP' ou 'Emulsão'
        );

        -- Parâmetros de ensaio com limites por produto (a inteligência do sistema)
        CREATE TABLE IF NOT EXISTS parametros_ensaio (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            produto_id INTEGER NOT NULL,
            nome_parametro TEXT NOT NULL,
            unidade TEXT,
            valor_minimo REAL,
            valor_maximo REAL,
            metodo_ensaio TEXT,  -- Norma DNIT/ABNT de referência
            FOREIGN KEY (produto_id) REFERENCES produtos(id)
        );

        -- Amostras coletadas para análise
        CREATE TABLE IF NOT EXISTS amostras (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            produto_id INTEGER NOT NULL,
            numero_lote TEXT NOT NULL,
            data_coleta TEXT NOT NULL,
            responsavel TEXT NOT NULL,
            status TEXT DEFAULT 'Pendente',  -- Pendente, Aprovada, Reprovada
            observacoes TEXT,
            FOREIGN KEY (produto_id) REFERENCES produtos(id)
        );

        -- Resultados individuais de cada ensaio
        CREATE TABLE IF NOT EXISTS resultados (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            amostra_id INTEGER NOT NULL,
            parametro_id INTEGER NOT NULL,
            valor_obtido REAL,
            conforme INTEGER,  -- 1 = conforme, 0 = não conforme, NULL = pendente
            data_ensaio TEXT,
            tecnico TEXT,
            FOREIGN KEY (amostra_id) REFERENCES amostras(id),
            FOREIGN KEY (parametro_id) REFERENCES parametros_ensaio(id)
        );
    ''')

    db.commit()
    db.close()
    print("✓ Banco de dados criado com sucesso.")


def seed_data():
    """
    Popula o banco com os produtos reais da Capetro e seus parâmetros de ensaio.
    Dados extraídos das fichas técnicas disponíveis no site capetro.com.br
    """
    db = get_db()

    # ==========================================
    # PRODUTOS
    # ==========================================
    produtos = [
        ('CAPETRO PLUS 50/70', 'Cimento Asfáltico de Petróleo com penetração 50-70', 'CAP'),
        ('CAPETRO Emulsão RR-1C', 'Emulsão Asfáltica Catiônica de Ruptura Rápida RR-1C', 'Emulsão'),
        ('CAPETRO Emulsão RR-2C', 'Emulsão Asfáltica Catiônica de Ruptura Rápida RR-2C', 'Emulsão'),
        ('CAPETRO Imprimer', 'Emulsão Asfáltica para Imprimação de bases granulares', 'Emulsão'),
    ]

    for nome, descricao, tipo in produtos:
        db.execute(
            'INSERT INTO produtos (nome, descricao, tipo) VALUES (?, ?, ?)',
            [nome, descricao, tipo]
        )

    db.commit()

    # ==========================================
    # PARÂMETROS DE ENSAIO - CAP 50/70
    # (Baseado na norma DNIT 095/2006 - EM)
    # ==========================================
    cap_params = [
        ('Penetração (25°C, 100g, 5s)',    '0,1 mm',   50.0,   70.0,   'DNIT-ME 155'),
        ('Ponto de Amolecimento',           '°C',       46.0,   None,   'DNIT-ME 131'),
        ('Viscosidade Saybolt-Furol 135°C', 's',        141.0,  235.0,  'DNIT-ME 004'),
        ('Viscosidade Saybolt-Furol 150°C', 's',        50.0,   91.0,   'DNIT-ME 004'),
        ('Viscosidade Saybolt-Furol 177°C', 's',        15.0,   30.0,   'DNIT-ME 004'),
        ('Índice de Susceptibilidade Térmica', '',       -1.5,   0.7,    'DNIT 095/2006'),
        ('Ponto de Fulgor',                 '°C',       235.0,  None,   'DNIT-ME 148'),
        ('Solubilidade em Tricloroetileno',  '%',       99.5,   None,   'DNIT-ME 165'),
        ('Ductilidade a 25°C',              'cm',       60.0,   None,   'DNIT-ME 163'),
    ]

    for nome, unidade, vmin, vmax, metodo in cap_params:
        db.execute('''
            INSERT INTO parametros_ensaio (produto_id, nome_parametro, unidade, valor_minimo, valor_maximo, metodo_ensaio)
            VALUES (1, ?, ?, ?, ?, ?)
        ''', [nome, unidade, vmin, vmax, metodo])

    # ==========================================
    # PARÂMETROS DE ENSAIO - Emulsão RR-1C
    # (Baseado na norma DNIT 165/2013 - EM)
    # ==========================================
    rr1c_params = [
        ('Viscosidade Saybolt-Furol 50°C',  's',        20.0,   200.0,  'DNIT-ME 004'),
        ('Sedimentação (7 dias)',            '%',        None,   5.0,    'DNIT-ME 006'),
        ('Peneiração (0,84 mm)',             '%',        None,   0.1,    'DNIT-ME 005'),
        ('Carga da Partícula',              '',         None,   None,   'DNIT-ME 002'),
        ('pH',                              '',         None,   6.5,    'DNIT-ME 001'),
        ('Resíduo por Evaporação',          '%',        62.0,   None,   'DNIT-ME 003'),
        ('Penetração do Resíduo (25°C)',    '0,1 mm',   50.0,   250.0,  'DNIT-ME 155'),
    ]

    for nome, unidade, vmin, vmax, metodo in rr1c_params:
        db.execute('''
            INSERT INTO parametros_ensaio (produto_id, nome_parametro, unidade, valor_minimo, valor_maximo, metodo_ensaio)
            VALUES (2, ?, ?, ?, ?, ?)
        ''', [nome, unidade, vmin, vmax, metodo])

    # ==========================================
    # PARÂMETROS DE ENSAIO - Emulsão RR-2C
    # ==========================================
    rr2c_params = [
        ('Viscosidade Saybolt-Furol 50°C',  's',        100.0,  400.0,  'DNIT-ME 004'),
        ('Sedimentação (7 dias)',            '%',        None,   5.0,    'DNIT-ME 006'),
        ('Peneiração (0,84 mm)',             '%',        None,   0.1,    'DNIT-ME 005'),
        ('Carga da Partícula',              '',         None,   None,   'DNIT-ME 002'),
        ('pH',                              '',         None,   6.5,    'DNIT-ME 001'),
        ('Resíduo por Evaporação',          '%',        67.0,   None,   'DNIT-ME 003'),
        ('Penetração do Resíduo (25°C)',    '0,1 mm',   50.0,   250.0,  'DNIT-ME 155'),
    ]

    for nome, unidade, vmin, vmax, metodo in rr2c_params:
        db.execute('''
            INSERT INTO parametros_ensaio (produto_id, nome_parametro, unidade, valor_minimo, valor_maximo, metodo_ensaio)
            VALUES (3, ?, ?, ?, ?, ?)
        ''', [nome, unidade, vmin, vmax, metodo])

    # ==========================================
    # PARÂMETROS DE ENSAIO - Imprimer
    # ==========================================
    imprimer_params = [
        ('Viscosidade Saybolt-Furol 25°C',  's',        10.0,   60.0,   'DNIT-ME 004'),
        ('Sedimentação (7 dias)',            '%',        None,   5.0,    'DNIT-ME 006'),
        ('Peneiração (0,84 mm)',             '%',        None,   0.1,    'DNIT-ME 005'),
        ('pH',                              '',         None,   6.5,    'DNIT-ME 001'),
        ('Resíduo por Destilação',          '%',        None,   None,   'DNIT-ME 003'),
    ]

    for nome, unidade, vmin, vmax, metodo in imprimer_params:
        db.execute('''
            INSERT INTO parametros_ensaio (produto_id, nome_parametro, unidade, valor_minimo, valor_maximo, metodo_ensaio)
            VALUES (4, ?, ?, ?, ?, ?)
        ''', [nome, unidade, vmin, vmax, metodo])

    # ==========================================
    # AMOSTRAS DE EXEMPLO (para demonstração)
    # ==========================================
    amostras_demo = [
        (1, 'CAP-2025-001', '2025-03-10', 'João Silva', 'Aprovada'),
        (1, 'CAP-2025-002', '2025-03-12', 'João Silva', 'Aprovada'),
        (2, 'RR1C-2025-001', '2025-03-11', 'Maria Santos', 'Reprovada'),
        (3, 'RR2C-2025-001', '2025-03-13', 'Maria Santos', 'Aprovada'),
        (1, 'CAP-2025-003', '2025-03-15', 'João Silva', 'Pendente'),
        (4, 'IMP-2025-001', '2025-03-16', 'Carlos Oliveira', 'Aprovada'),
        (2, 'RR1C-2025-002', '2025-03-18', 'Maria Santos', 'Pendente'),
    ]

    for prod_id, lote, data, resp, status in amostras_demo:
        cursor = db.execute('''
            INSERT INTO amostras (produto_id, numero_lote, data_coleta, responsavel, status)
            VALUES (?, ?, ?, ?, ?)
        ''', [prod_id, lote, data, resp, status])

        amostra_id = cursor.lastrowid

        # Cria resultados para cada parâmetro
        parametros = db.execute(
            'SELECT id, valor_minimo, valor_maximo FROM parametros_ensaio WHERE produto_id = ?',
            [prod_id]
        ).fetchall()

        for param in parametros:
            if status != 'Pendente':
                # Gera valores fictícios dentro ou fora da faixa
                import random
                vmin = param['valor_minimo'] or 0
                vmax = param['valor_maximo'] or (vmin * 2 if vmin else 100)

                if status == 'Aprovada':
                    valor = round(random.uniform(vmin, vmax), 2)
                else:
                    # Para reprovadas, coloca um valor fora da faixa
                    valor = round(vmin * 0.7, 2) if random.random() > 0.5 else round(vmax * 1.3, 2)

                conforme = 1 if (
                    (param['valor_minimo'] is None or valor >= param['valor_minimo']) and
                    (param['valor_maximo'] is None or valor <= param['valor_maximo'])
                ) else 0

                db.execute('''
                    INSERT INTO resultados (amostra_id, parametro_id, valor_obtido, conforme, data_ensaio, tecnico)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', [amostra_id, param['id'], valor, conforme, data, resp])
            else:
                db.execute('''
                    INSERT INTO resultados (amostra_id, parametro_id, valor_obtido, conforme, data_ensaio, tecnico)
                    VALUES (?, ?, NULL, NULL, NULL, NULL)
                ''', [amostra_id, param['id']])

    db.commit()
    db.close()
    print("✓ Dados iniciais inseridos com sucesso.")


if __name__ == '__main__':
    """Permite rodar este arquivo diretamente para recriar o banco."""
    if os.path.exists(DATABASE):
        os.remove(DATABASE)
        print("Banco antigo removido.")
    init_db()
    seed_data()
    print("Pronto! Banco de dados populado.")
