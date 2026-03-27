import os
import subprocess
import glob
from datetime import datetime
from urllib.parse import urlparse
from database import DATABASE_URL

# Diretório de backups (relativo ao app)
BACKUP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backups')
MAX_BACKUPS = 30  # Manter últimos 30 backups


def _parse_db_url():
    """Extrai host, port, user, password e dbname da DATABASE_URL."""
    parsed = urlparse(DATABASE_URL)
    return {
        'host': parsed.hostname or 'localhost',
        'port': str(parsed.port or 5432),
        'user': parsed.username or 'postgres',
        'password': parsed.password or '',
        'dbname': parsed.path.lstrip('/'),
    }


def fazer_backup():
    """Executa pg_dump e salva o backup. Retorna (sucesso, caminho_ou_erro)."""
    os.makedirs(BACKUP_DIR, exist_ok=True)

    db = _parse_db_url()
    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    filename = f'backup_{timestamp}.sql'
    filepath = os.path.join(BACKUP_DIR, filename)

    env = os.environ.copy()
    env['PGPASSWORD'] = db['password']

    try:
        result = subprocess.run(
            [
                'pg_dump',
                '-h', db['host'],
                '-p', db['port'],
                '-U', db['user'],
                '-d', db['dbname'],
                '-f', filepath,
                '--no-owner',
                '--no-privileges',
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode != 0:
            return False, result.stderr.strip()

        _limpar_backups_antigos()
        return True, filepath

    except FileNotFoundError:
        return False, 'pg_dump não encontrado. Verifique se o PostgreSQL está no PATH do sistema.'
    except subprocess.TimeoutExpired:
        return False, 'Timeout: o backup demorou mais de 2 minutos.'
    except Exception as e:
        return False, str(e)


def _limpar_backups_antigos():
    """Remove backups antigos, mantendo apenas os últimos MAX_BACKUPS."""
    backups = sorted(glob.glob(os.path.join(BACKUP_DIR, 'backup_*.sql')))
    while len(backups) > MAX_BACKUPS:
        os.remove(backups.pop(0))


def listar_backups():
    """Retorna lista de backups existentes, do mais recente ao mais antigo."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    arquivos = glob.glob(os.path.join(BACKUP_DIR, 'backup_*.sql'))
    backups = []
    for f in sorted(arquivos, reverse=True):
        nome = os.path.basename(f)
        tamanho = os.path.getsize(f)
        backups.append({
            'nome': nome,
            'caminho': f,
            'tamanho_kb': round(tamanho / 1024, 1),
            'data': datetime.fromtimestamp(os.path.getmtime(f)).strftime('%d/%m/%Y %H:%M'),
        })
    return backups
