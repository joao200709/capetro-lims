import unittest
import tempfile
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import database
from app import app
from database import get_db, init_db, seed_data


class BaseTest(unittest.TestCase):
    """Usa um banco temporario pra cada teste, evitando conflito de arquivos."""

    def setUp(self):
        # Cria um banco temporario so pra esse teste
        self.db_fd, self.db_path = tempfile.mkstemp(suffix='.db')
        database.DATABASE = self.db_path

        self.app = app
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

        init_db()
        seed_data()

    def tearDown(self):
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def fazer_login(self, email='admin@capetro.com', senha='admin123'):
        return self.client.post('/login', data={
            'email': email,
            'senha': senha
        }, follow_redirects=True)

    def fazer_registro(self, nome='Teste', email='teste@capetro.com',
                       senha='teste123', confirmar='teste123', cargo='Tecnico'):
        return self.client.post('/registro', data={
            'nome': nome,
            'email': email,
            'senha': senha,
            'confirmar_senha': confirmar,
            'cargo': cargo
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
        r = self.client.post('/login', data={'email': '', 'senha': ''}, follow_redirects=True)
        self.assertIn(b'Preencha', r.data)

    def test_logout(self):
        self.fazer_login()
        r = self.client.get('/logout', follow_redirects=True)
        self.assertIn(b'saiu', r.data)

    def test_rota_protegida_sem_login(self):
        r = self.client.get('/', follow_redirects=True)
        self.assertIn(b'login', r.data.lower())

    def test_registro_sucesso(self):
        r = self.fazer_registro()
        self.assertIn(b'Conta criada', r.data)

    def test_registro_email_duplicado(self):
        r = self.fazer_registro(email='admin@capetro.com')
        self.assertIn('já está cadastrado'.encode('utf-8'), r.data)

    def test_registro_senhas_diferentes(self):
        r = self.fazer_registro(senha='abc123', confirmar='xyz789')
        self.assertIn('não coincidem'.encode('utf-8'), r.data)

    def test_registro_senha_curta(self):
        r = self.fazer_registro(senha='123', confirmar='123')
        self.assertIn(b'pelo menos 6', r.data)

    def test_registro_campos_vazios(self):
        r = self.fazer_registro(nome='', email='')
        self.assertIn(b'Preencha', r.data)

    def test_senha_criptografada_no_banco(self):
        self.fazer_registro()
        db = get_db()
        user = db.execute("SELECT senha_hash FROM usuarios WHERE email = 'teste@capetro.com'").fetchone()
        db.close()
        self.assertNotEqual(user['senha_hash'], 'teste123')
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
        r = self.client.post('/amostras/nova', data={
            'produto_id': '1',
            'numero_lote': 'TEST-001',
            'data_coleta': '2025-06-01',
            'responsavel': 'Testador'
        }, follow_redirects=True)
        self.assertIn(b'cadastrada com sucesso', r.data)

    def test_criar_amostra_campos_vazios(self):
        self.fazer_login()
        r = self.client.post('/amostras/nova', data={
            'produto_id': '',
            'numero_lote': '',
            'data_coleta': '',
            'responsavel': ''
        }, follow_redirects=True)
        self.assertIn(b'Preencha', r.data)

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

    def test_registrar_ensaios_campos_obrigatorios(self):
        self.fazer_login()
        r = self.client.post('/ensaios/registrar/5', data={
            'tecnico': '',
            'data_ensaio': ''
        }, follow_redirects=True)
        self.assertIn(b'Preencha', r.data)

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
