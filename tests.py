import os
import re
import sys
import unittest
from urllib.parse import urlparse

from dotenv import load_dotenv


sys.path.insert(0, os.path.dirname(__file__))
load_dotenv()

TEST_DB_URL = os.environ.get('TEST_DATABASE_URL')
DB_SKIP_REASON = 'Defina TEST_DATABASE_URL no .env para executar os testes de integracao.'


if not TEST_DB_URL:
    class TestDatabaseConfiguration(unittest.TestCase):
        def test_test_database_url_configurada(self):
            self.skipTest(DB_SKIP_REASON)

else:
    import psycopg2
    from psycopg2 import sql

    os.environ['DATABASE_URL'] = TEST_DB_URL

    import database
    database.DATABASE_URL = TEST_DB_URL

    from app import app
    from database import get_db, init_db, seed_data


    def _criar_banco_teste():
        parsed = urlparse(TEST_DB_URL)
        dbname = parsed.path.lstrip('/')
        maintenance_url = parsed._replace(path='/postgres').geturl()

        conn = psycopg2.connect(maintenance_url)
        conn.autocommit = True
        cursor = conn.cursor()
        cursor.execute('SELECT 1 FROM pg_database WHERE datname = %s', [dbname])
        if not cursor.fetchone():
            cursor.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(dbname)))
        conn.close()


    def _limpar_tabelas():
        conn = psycopg2.connect(TEST_DB_URL)
        cursor = conn.cursor()
        cursor.execute('DROP TABLE IF EXISTS historico, resultados, amostras, parametros_ensaio, produtos, usuarios CASCADE')
        conn.commit()
        conn.close()


    class BaseTest(unittest.TestCase):

        @classmethod
        def setUpClass(cls):
            _criar_banco_teste()

        def setUp(self):
            _limpar_tabelas()

            self.app = app
            self.app.config['TESTING'] = True
            self.app.config['WTF_CSRF_ENABLED'] = False
            self.client = self.app.test_client()

            import app as app_module
            app_module._db_initialized = False

            init_db()
            seed_data()

        def tearDown(self):
            _limpar_tabelas()

        def _get_csrf(self, url):
            """Pega o token CSRF de uma pagina."""
            r = self.client.get(url)
            match = re.search(r'name="_csrf_token" value="([^"]+)"', r.data.decode())
            return match.group(1) if match else ''

        def fazer_login(self, email='admin@capetro.com', senha='admin123'):
            token = self._get_csrf('/login')
            return self.client.post('/login', data={
                'email': email,
                'senha': senha,
                '_csrf_token': token
            }, follow_redirects=True)


    class TestAutenticacao(BaseTest):

        def test_login_pagina_carrega(self):
            r = self.client.get('/login')
            self.assertEqual(r.status_code, 200)

        def test_login_correto(self):
            r = self.fazer_login()
            self.assertIn(b'Bem-vindo', r.data)

        def test_login_senha_errada(self):
            r = self.fazer_login(senha='errada')
            self.assertIn(b'incorretos', r.data)

        def test_login_email_inexistente(self):
            r = self.fazer_login(email='naoexiste@x.com')
            self.assertIn(b'incorretos', r.data)

        def test_login_campos_vazios(self):
            token = self._get_csrf('/login')
            r = self.client.post('/login', data={
                'email': '', 'senha': '', '_csrf_token': token
            }, follow_redirects=True)
            self.assertIn(b'Preencha', r.data)

        def test_logout(self):
            self.fazer_login()
            r = self.client.get('/logout', follow_redirects=True)
            self.assertIn(b'saiu', r.data)

        def test_rota_protegida_sem_login(self):
            r = self.client.get('/', follow_redirects=True)
            self.assertIn(b'login', r.data.lower())

        def test_senha_criptografada_no_banco(self):
            db = get_db()
            user = db.execute("SELECT senha_hash FROM usuarios WHERE email = 'admin@capetro.com'").fetchone()
            db.close()
            self.assertNotEqual(user['senha_hash'], 'admin123')
            self.assertIn('scrypt', user['senha_hash'])


    class TestDashboard(BaseTest):

        def test_dashboard_carrega(self):
            self.fazer_login()
            r = self.client.get('/')
            self.assertEqual(r.status_code, 200)

        def test_dashboard_mostra_metricas(self):
            self.fazer_login()
            r = self.client.get('/')
            self.assertIn(b'Aprovada', r.data)


    class TestAmostras(BaseTest):

        def test_listar_amostras(self):
            self.fazer_login()
            r = self.client.get('/amostras')
            self.assertEqual(r.status_code, 200)

        def test_criar_amostra(self):
            self.fazer_login()
            token = self._get_csrf('/amostras/nova')
            r = self.client.post('/amostras/nova', data={
                'produto_id': '1',
                'numero_lote': 'TEST-001',
                'data_coleta': '2025-06-01',
                'responsavel': 'Testador',
                '_csrf_token': token
            }, follow_redirects=True)
            self.assertIn(b'cadastrada com sucesso', r.data)

        def test_detalhe_amostra_existente(self):
            self.fazer_login()
            r = self.client.get('/amostras/1')
            self.assertEqual(r.status_code, 200)

        def test_detalhe_amostra_inexistente(self):
            self.fazer_login()
            r = self.client.get('/amostras/9999', follow_redirects=True)
            self.assertIn('não encontrada'.encode('utf-8'), r.data)

        def test_filtrar_por_status(self):
            self.fazer_login()
            r = self.client.get('/amostras?status=Aprovada')
            self.assertEqual(r.status_code, 200)


    class TestEnsaios(BaseTest):

        def test_registrar_ensaios_pagina(self):
            self.fazer_login()
            r = self.client.get('/ensaios/registrar/5')
            self.assertEqual(r.status_code, 200)

        def test_registrar_ensaio_amostra_inexistente(self):
            self.fazer_login()
            r = self.client.get('/ensaios/registrar/9999', follow_redirects=True)
            self.assertIn('não encontrada'.encode('utf-8'), r.data)


    class TestLaudos(BaseTest):

        def test_laudo_amostra_aprovada(self):
            self.fazer_login()
            r = self.client.get('/laudos/1')
            self.assertEqual(r.status_code, 200)

        def test_laudo_amostra_inexistente(self):
            self.fazer_login()
            r = self.client.get('/laudos/9999', follow_redirects=True)
            self.assertIn('não encontrada'.encode('utf-8'), r.data)


    class TestErros(BaseTest):

        def test_pagina_404(self):
            self.fazer_login()
            r = self.client.get('/rota/que/nao/existe', follow_redirects=True)
            self.assertIn('não encontrada'.encode('utf-8'), r.data)


if __name__ == '__main__':
    unittest.main()
