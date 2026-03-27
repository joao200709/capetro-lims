import os
import random
import psycopg2
import psycopg2.extras
from werkzeug.security import generate_password_hash

# Senha hardcodada temporariamente, em producao usar variavel de ambiente
DATABASE_URL = os.environ.get(
    'DATABASE_URL',
    'postgresql://postgres:unicompra@localhost:5432/capetro-lims'
)


class DictRow:
    """Permite acesso por nome (row['col']) e por indice (row[0])."""
    def __init__(self, data):
        self._dict = dict(data)
        self._values = list(data.values())

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return self._dict[key]

    def __contains__(self, key):
        return key in self._dict

    def keys(self):
        return self._dict.keys()

    def __bool__(self):
        return True


class CursorWrapper:
    """Compatibiliza o cursor do psycopg2 com a interface que o app espera."""
    def __init__(self, cursor, lastrowid=None):
        self._cursor = cursor
        self.lastrowid = lastrowid

    def fetchone(self):
        row = self._cursor.fetchone()
        if row is None:
            return None
        return DictRow(row)

    def fetchall(self):
        rows = self._cursor.fetchall()
        return [DictRow(r) for r in rows]


class DBWrapper:
    """Interface para o PostgreSQL compativel com o resto do app."""
    def __init__(self, conn):
        self.conn = conn

    def execute(self, query, params=None):
        params = params or []

        # Converte placeholder do SQLite pro PostgreSQL
        query = query.replace('?', '%s')

        # Adiciona RETURNING id em INSERTs pra capturar o id gerado
        is_insert = query.strip().upper().startswith('INSERT')
        if is_insert and 'RETURNING' not in query.upper():
            query = query.rstrip().rstrip(';') + ' RETURNING id'

        cursor = self.conn.cursor()
        cursor.execute(query, params)

        lastrowid = None
        if is_insert:
            try:
                result = cursor.fetchone()
                if result:
                    lastrowid = result.get('id') if isinstance(result, dict) else result[0]
            except (psycopg2.ProgrammingError, IndexError, AttributeError):
                pass

        return CursorWrapper(cursor, lastrowid)

    def commit(self):
        self.conn.commit()

    def close(self):
        self.conn.close()


def get_db():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    return DBWrapper(conn)


def db_needs_init():
    """Verifica se as tabelas ja existem no banco."""
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    cursor.execute("SELECT EXISTS(SELECT FROM information_schema.tables WHERE table_name = 'produtos')")
    exists = cursor.fetchone()[0]
    conn.close()
    return not exists


def init_db():
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()

    tables = [
        '''CREATE TABLE IF NOT EXISTS produtos (
            id SERIAL PRIMARY KEY,
            nome TEXT NOT NULL,
            descricao TEXT,
            tipo TEXT NOT NULL
        )''',
        '''CREATE TABLE IF NOT EXISTS parametros_ensaio (
            id SERIAL PRIMARY KEY,
            produto_id INTEGER NOT NULL REFERENCES produtos(id),
            nome_parametro TEXT NOT NULL,
            unidade TEXT,
            valor_minimo REAL,
            valor_maximo REAL,
            metodo_ensaio TEXT
        )''',
        '''CREATE TABLE IF NOT EXISTS amostras (
            id SERIAL PRIMARY KEY,
            produto_id INTEGER NOT NULL REFERENCES produtos(id),
            numero_lote TEXT NOT NULL,
            data_coleta TEXT NOT NULL,
            responsavel TEXT NOT NULL,
            status TEXT DEFAULT 'Pendente',
            observacoes TEXT,
            revisado_por TEXT,
            data_revisao TEXT
        )''',
        '''CREATE TABLE IF NOT EXISTS resultados (
            id SERIAL PRIMARY KEY,
            amostra_id INTEGER NOT NULL REFERENCES amostras(id),
            parametro_id INTEGER NOT NULL REFERENCES parametros_ensaio(id),
            valor_obtido REAL,
            conforme INTEGER,
            data_ensaio TEXT,
            tecnico TEXT
        )''',
        '''CREATE TABLE IF NOT EXISTS usuarios (
            id SERIAL PRIMARY KEY,
            nome TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            senha_hash TEXT NOT NULL,
            cargo TEXT DEFAULT 'Tecnico',
            perfil TEXT DEFAULT 'tecnico',
            ativo INTEGER DEFAULT 1,
            criado_em TIMESTAMP DEFAULT NOW()
        )''',
        '''CREATE TABLE IF NOT EXISTS historico (
            id SERIAL PRIMARY KEY,
            usuario_id INTEGER REFERENCES usuarios(id),
            usuario_nome TEXT NOT NULL,
            acao TEXT NOT NULL,
            entidade TEXT NOT NULL,
            entidade_id INTEGER,
            detalhes TEXT,
            data_hora TIMESTAMP DEFAULT NOW()
        )''',
    ]

    for sql in tables:
        cursor.execute(sql)

    # Migração: adicionar colunas de revisão se não existirem
    migrations = [
        "ALTER TABLE amostras ADD COLUMN IF NOT EXISTS revisado_por TEXT",
        "ALTER TABLE amostras ADD COLUMN IF NOT EXISTS data_revisao TEXT",
    ]
    for sql in migrations:
        cursor.execute(sql)

    # Índices para consultas frequentes
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_amostras_status ON amostras(status)",
        "CREATE INDEX IF NOT EXISTS idx_amostras_produto_id ON amostras(produto_id)",
        "CREATE INDEX IF NOT EXISTS idx_amostras_data_coleta ON amostras(data_coleta)",
        "CREATE INDEX IF NOT EXISTS idx_resultados_amostra_id ON resultados(amostra_id)",
        "CREATE INDEX IF NOT EXISTS idx_resultados_parametro_id ON resultados(parametro_id)",
        "CREATE INDEX IF NOT EXISTS idx_parametros_produto_id ON parametros_ensaio(produto_id)",
        "CREATE INDEX IF NOT EXISTS idx_historico_usuario_id ON historico(usuario_id)",
    ]
    for sql in indexes:
        cursor.execute(sql)

    conn.commit()
    conn.close()
    print("[OK] Banco de dados criado no PostgreSQL.")


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

    produtos = [
        ('CAPETRO PLUS 50/70', 'Cimento Asfaltico de Petroleo com penetracao 50-70', 'CAP'),
        ('CAPETRO Emulsao RR-1C', 'Emulsao Asfaltica Cationica de Ruptura Rapida RR-1C', 'Emulsao'),
        ('CAPETRO Emulsao RR-2C', 'Emulsao Asfaltica Cationica de Ruptura Rapida RR-2C', 'Emulsao'),
        ('CAPETRO Imprimer', 'Emulsao Asfaltica para Imprimacao de bases granulares', 'Emulsao'),
    ]

    for nome, descricao, tipo in produtos:
        db.execute('INSERT INTO produtos (nome, descricao, tipo) VALUES (?, ?, ?)', [nome, descricao, tipo])
    db.commit()

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

    amostras_demo = [
        (1, 'CAP-2026-001', '2026-01-10', 'Joao Silva',      'Aprovada'),
        (1, 'CAP-2026-002', '2026-01-25', 'Joao Silva',      'Aprovada'),
        (2, 'RR1C-2026-001','2026-02-05', 'Maria Santos',    'Reprovada'),
        (3, 'RR2C-2026-001','2026-02-18', 'Maria Santos',    'Aprovada'),
        (1, 'CAP-2026-003', '2026-03-05', 'Joao Silva',      'Pendente'),
        (4, 'IMP-2026-001', '2026-03-10', 'Carlos Oliveira', 'Aprovada'),
        (2, 'RR1C-2026-002','2026-03-15', 'Maria Santos',    'Pendente'),
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

    db.execute(
        'INSERT INTO usuarios (nome, email, senha_hash, cargo, perfil) VALUES (?, ?, ?, ?, ?)',
        ['Administrador', 'admin@capetro.com', generate_password_hash('admin123'), 'Administrador', 'admin']
    )

    db.commit()
    db.close()
    print("[OK] Dados iniciais inseridos.")
    print("[OK] Usuario padrao: admin@capetro.com / admin123")


if __name__ == '__main__':
    # Limpa tabelas existentes e recria
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    cursor.execute('DROP TABLE IF EXISTS historico, resultados, amostras, parametros_ensaio, produtos, usuarios CASCADE')
    conn.commit()
    conn.close()
    print("Tabelas antigas removidas.")

    init_db()
    seed_data()
    print("Pronto!")
