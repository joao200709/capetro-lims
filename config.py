import os
import secrets
import warnings

from dotenv import load_dotenv


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, '.env'))


APP_ENV = os.environ.get('APP_ENV', 'development').lower()
IS_PRODUCTION = APP_ENV in ('prod', 'production')

DATABASE_URL = os.environ.get('DATABASE_URL')
TEST_DATABASE_URL = os.environ.get('TEST_DATABASE_URL')
BACKUP_DIR = os.environ.get('BACKUP_DIR')

FLASK_DEBUG = os.environ.get('FLASK_DEBUG', '').lower() in ('1', 'true', 'yes', 'on')

SECRET_KEY = os.environ.get('SECRET_KEY')
if not SECRET_KEY:
    if IS_PRODUCTION:
        raise RuntimeError('SECRET_KEY deve ser definida no ambiente de producao.')

    SECRET_KEY = secrets.token_hex(32)
    warnings.warn(
        'SECRET_KEY nao definida. Usando chave temporaria de desenvolvimento; '
        'sessoes serao invalidadas ao reiniciar o servidor.',
        RuntimeWarning,
        stacklevel=2,
    )


def require_database_url():
    if not DATABASE_URL:
        raise RuntimeError(
            'DATABASE_URL nao definida. Copie .env.example para .env e configure '
            'a conexao PostgreSQL antes de iniciar o sistema.'
        )
    return DATABASE_URL
