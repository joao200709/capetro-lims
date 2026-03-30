from flask import Flask, render_template, request, redirect, url_for, flash, send_file, session, abort
from werkzeug.security import generate_password_hash, check_password_hash
from database import get_db, init_db, seed_data, db_needs_init
from backup import fazer_backup, listar_backups, BACKUP_DIR
from functools import wraps
from datetime import datetime, timedelta
import unicodedata
import threading
import tempfile
import os
import time
import secrets

app = Flask(__name__)
# Em produção, defina SECRET_KEY como variável de ambiente para manter sessões entre reinícios
app.secret_key = os.environ.get('SECRET_KEY') or secrets.token_hex(32)
app.permanent_session_lifetime = timedelta(days=30)
TIMEOUT_INATIVIDADE = 30  # minutos

# Rate limiting: rastreia tentativas de login por IP
# Formato: {ip: {'tentativas': int, 'bloqueado_ate': timestamp}}
tentativas_login = {}
MAX_TENTATIVAS = 5
BLOQUEIO_MINUTOS = 15

# Perfis: tecnico < coordenador < gerente < admin
PERFIS = {
    'tecnico': 1,
    'coordenador': 2,
    'gerente': 3,
    'admin': 4
}

PERFIL_LABELS = {
    'tecnico': 'Técnico',
    'coordenador': 'Coordenador',
    'gerente': 'Gerente',
    'admin': 'Administrador'
}


# --- Queries reutilizadas em varias rotas ---

def buscar_produtos(db):
    return db.execute('SELECT id, nome FROM produtos ORDER BY nome').fetchall()


def buscar_amostra(db, amostra_id, com_descricao=False):
    campos = 'a.*, p.nome as produto_nome'
    if com_descricao:
        campos += ', p.descricao as produto_descricao'

    return db.execute(f'''
        SELECT {campos}
        FROM amostras a
        JOIN produtos p ON a.produto_id = p.id
        WHERE a.id = ?
    ''', [amostra_id]).fetchone()


def buscar_amostra_ou_redirecionar(db, amostra_id, com_descricao=False):
    """Busca amostra e retorna. Se nao existir, fecha db e retorna (None, redirect)."""
    amostra = buscar_amostra(db, amostra_id, com_descricao)
    if not amostra:
        db.close()
        flash('Amostra não encontrada.', 'error')
        return None, redirect(url_for('listar_amostras'))
    return amostra, None


def buscar_resultados(db, amostra_id):
    return db.execute('''
        SELECT r.*, pe.nome_parametro, pe.unidade, pe.valor_minimo, pe.valor_maximo, pe.metodo_ensaio
        FROM resultados r
        JOIN parametros_ensaio pe ON r.parametro_id = pe.id
        WHERE r.amostra_id = ?
        ORDER BY pe.nome_parametro
    ''', [amostra_id]).fetchall()


def registrar_historico(db, acao, entidade, entidade_id=None, detalhes=None):
    """Salva uma entrada no historico de alteracoes."""
    db.execute('''
        INSERT INTO historico (usuario_id, usuario_nome, acao, entidade, entidade_id, detalhes)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', [
        session.get('usuario_id'),
        session.get('usuario_nome', 'Sistema'),
        acao, entidade, entidade_id, detalhes
    ])


def perfil_minimo(perfil_necessario):
    """Decorator que bloqueia acesso se o perfil do usuario for insuficiente."""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            perfil_usuario = session.get('usuario_perfil', 'tecnico')
            if PERFIS.get(perfil_usuario, 0) < PERFIS.get(perfil_necessario, 0):
                flash('Você não tem permissão para acessar esta página.', 'error')
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        return decorated
    return decorator


def gerar_csrf_token():
    """Gera um token CSRF unico por sessao pra proteger formularios contra requisicoes forjadas."""
    if '_csrf_token' not in session:
        session['_csrf_token'] = secrets.token_hex(32)
    return session['_csrf_token']


def validar_csrf():
    """Valida o token CSRF em requisicoes POST."""
    token = session.get('_csrf_token')
    token_form = request.form.get('_csrf_token')
    if not token or token != token_form:
        abort(403)


# Disponibiliza o token nos templates via {{ csrf_token() }}
app.jinja_env.globals['csrf_token'] = gerar_csrf_token


@app.after_request
def adicionar_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
    return response


@app.template_filter('data_br')
def filtro_data_br(valor):
    """Converte '2025-03-10' pra '10/03/2025' e timestamps pra 'dd/mm/aaaa HH:MM'."""
    if not valor:
        return '-'
    valor = str(valor)
    try:
        if len(valor) > 10:
            dt = datetime.strptime(valor[:19], '%Y-%m-%d %H:%M:%S')
            return dt.strftime('%d/%m/%Y %H:%M')
        dt = datetime.strptime(valor[:10], '%Y-%m-%d')
        return dt.strftime('%d/%m/%Y')
    except (ValueError, TypeError):
        return valor


@app.template_filter('status_class')
def filtro_status_class(valor):
    """Converte status para classe CSS (ex: 'Em Revisão' -> 'em-revisao')."""
    if not valor:
        return ''
    s = unicodedata.normalize('NFD', valor.lower())
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    return s.replace(' ', '-')


DIAS_PENDENTE_ALERTA = 7


@app.context_processor
def injetar_notificacoes():
    """Injeta notificacoes em todos os templates automaticamente."""
    if 'usuario_id' not in session or request.endpoint in ('static', 'login', 'logout'):
        return {'notificacoes': [], 'total_notificacoes': 0}

    try:
        db = get_db()
        notificacoes = []

        limite_pendente = (datetime.now() - timedelta(days=DIAS_PENDENTE_ALERTA)).strftime('%Y-%m-%d')
        inicio_mes = datetime.now().strftime('%Y-%m-%d')[:8] + '01'

        # Uma única query para todas as notificações
        rows = db.execute('''
            SELECT a.id, a.numero_lote, a.data_coleta, a.status, p.nome as produto
            FROM amostras a
            JOIN produtos p ON a.produto_id = p.id
            WHERE (a.status = 'Reprovada' AND a.data_coleta >= ?)
               OR (a.status = 'Pendente' AND a.data_coleta <= ?)
               OR (a.status = 'Em Revisão')
            ORDER BY a.data_coleta DESC
            LIMIT 30
        ''', [inicio_mes, limite_pendente]).fetchall()

        for r in rows:
            if r['status'] == 'Reprovada':
                notificacoes.append({
                    'tipo': 'reprovada',
                    'texto': f'{r["produto"]} — Lote {r["numero_lote"]} reprovada',
                    'data': r['data_coleta'],
                    'url': f'/amostras/{r["id"]}'
                })
            elif r['status'] == 'Pendente':
                dias = (datetime.now() - datetime.strptime(r['data_coleta'], '%Y-%m-%d')).days
                notificacoes.append({
                    'tipo': 'pendente',
                    'texto': f'{r["produto"]} — Lote {r["numero_lote"]} pendente há {dias} dias',
                    'data': r['data_coleta'],
                    'url': f'/amostras/{r["id"]}'
                })
            elif r['status'] == 'Em Revisão':
                notificacoes.append({
                    'tipo': 'revisao',
                    'texto': f'{r["produto"]} — Lote {r["numero_lote"]} aguardando revisão',
                    'data': r['data_coleta'],
                    'url': f'/amostras/{r["id"]}'
                })

        db.close()
        return {'notificacoes': notificacoes, 'total_notificacoes': len(notificacoes), 'TIMEOUT_INATIVIDADE': TIMEOUT_INATIVIDADE}
    except Exception:
        return {'notificacoes': [], 'total_notificacoes': 0, 'TIMEOUT_INATIVIDADE': TIMEOUT_INATIVIDADE}


_db_initialized = False

@app.before_request
def before_request():
    global _db_initialized
    if not _db_initialized:
        if db_needs_init():
            init_db()
            seed_data()
        _db_initialized = True

    # Timeout por inatividade (server-side apenas para sessões não-permanentes)
    # Sessões permanentes ("lembrar de mim") usam timeout via JavaScript no navegador
    if 'usuario_id' in session and request.endpoint not in ('login', 'logout', 'static'):
        if not session.permanent:
            ultima = session.get('ultima_atividade')
            agora = time.time()
            if ultima and (agora - ultima) > TIMEOUT_INATIVIDADE * 60:
                session.clear()
                flash('Sessão expirada por inatividade. Faça login novamente.', 'error')
                return redirect(url_for('login'))
            session['ultima_atividade'] = agora

    if request.method == 'POST':
        validar_csrf()


# --- Autenticacao ---

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'usuario_id' not in session:
            flash('Faça login para acessar o sistema.', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'usuario_id' in session:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        ip = request.remote_addr
        agora = time.time()

        # Verifica se o IP esta bloqueado
        if ip in tentativas_login:
            info = tentativas_login[ip]
            if info.get('bloqueado_ate') and agora < info['bloqueado_ate']:
                restante = int((info['bloqueado_ate'] - agora) / 60) + 1
                flash(f'Muitas tentativas. Tente novamente em {restante} minuto(s).', 'error')
                return render_template('auth/login.html')
            if info.get('bloqueado_ate') and agora >= info['bloqueado_ate']:
                tentativas_login.pop(ip)

        email = request.form.get('email', '').strip().lower()
        senha = request.form.get('senha', '')

        if not email or not senha:
            flash('Preencha todos os campos.', 'error')
            return render_template('auth/login.html')

        db = get_db()
        usuario = db.execute(
            'SELECT * FROM usuarios WHERE email = ? AND ativo = 1', [email]
        ).fetchone()
        db.close()

        if usuario and check_password_hash(usuario['senha_hash'], senha):
            # Login ok, limpa tentativas
            tentativas_login.pop(ip, None)
            if request.form.get('lembrar'):
                session.permanent = True
            else:
                session.permanent = False
            session['usuario_id'] = usuario['id']
            session['usuario_nome'] = usuario['nome']
            session['usuario_cargo'] = usuario['cargo']
            session['usuario_perfil'] = usuario['perfil'] if 'perfil' in usuario else 'tecnico'
            session['ultima_atividade'] = time.time()
            flash(f'Bem-vindo, {usuario["nome"]}!', 'success')
            return redirect(url_for('dashboard'))
        else:
            # Incrementa tentativas erradas
            if ip not in tentativas_login:
                tentativas_login[ip] = {'tentativas': 0}
            tentativas_login[ip]['tentativas'] += 1

            restantes = MAX_TENTATIVAS - tentativas_login[ip]['tentativas']
            if restantes <= 0:
                tentativas_login[ip]['bloqueado_ate'] = agora + (BLOQUEIO_MINUTOS * 60)
                flash(f'Conta bloqueada por {BLOQUEIO_MINUTOS} minutos após muitas tentativas.', 'error')
            elif restantes <= 2:
                flash(f'E-mail ou senha incorretos. {restantes} tentativa(s) restante(s).', 'error')
            else:
                flash('E-mail ou senha incorretos.', 'error')

    return render_template('auth/login.html')


def perfis_permitidos():
    """Retorna os perfis que o usuario logado pode criar/editar."""
    meu_perfil = session.get('usuario_perfil', 'tecnico')
    if meu_perfil == 'admin':
        return PERFIL_LABELS
    elif meu_perfil == 'gerente':
        return {k: v for k, v in PERFIL_LABELS.items() if k in ('tecnico', 'coordenador')}
    return {}


@app.route('/usuarios/novo', methods=['GET', 'POST'])
@login_required
@perfil_minimo('gerente')
def criar_usuario():
    perfis_disponiveis = perfis_permitidos()

    if request.method == 'POST':
        nome = request.form.get('nome', '').strip()
        email = request.form.get('email', '').strip().lower()
        senha = request.form.get('senha', '')
        confirmar = request.form.get('confirmar_senha', '')
        perfil = request.form.get('perfil', 'tecnico')
        form_data = {'nome': nome, 'email': email, 'perfil': perfil}

        if not nome or not email or not senha:
            flash('Preencha todos os campos.', 'error')
            return render_template('usuarios/novo.html', form=form_data, perfil_labels=perfis_disponiveis)

        if senha != confirmar:
            flash('As senhas não coincidem.', 'error')
            return render_template('usuarios/novo.html', form=form_data, perfil_labels=perfis_disponiveis)

        if len(senha) < 6:
            flash('A senha deve ter pelo menos 6 caracteres.', 'error')
            return render_template('usuarios/novo.html', form=form_data, perfil_labels=perfis_disponiveis)

        # Gerente nao pode criar gerente ou admin
        if perfil not in perfis_disponiveis:
            perfil = 'tecnico'

        cargo = PERFIL_LABELS.get(perfil, 'Técnico')

        db = get_db()
        existente = db.execute('SELECT id FROM usuarios WHERE email = ?', [email]).fetchone()

        if existente:
            db.close()
            flash('Este e-mail já está cadastrado.', 'error')
            return render_template('usuarios/novo.html', form=form_data, perfil_labels=perfis_disponiveis)

        db.execute(
            'INSERT INTO usuarios (nome, email, senha_hash, cargo, perfil) VALUES (?, ?, ?, ?, ?)',
            [nome, email, generate_password_hash(senha), cargo, perfil]
        )
        registrar_historico(db, 'Criou conta', 'Usuário', None, f'{nome} ({email})')
        db.commit()
        db.close()

        flash(f'Conta de {nome} criada com sucesso!', 'success')
        return redirect(url_for('listar_usuarios'))

    return render_template('usuarios/novo.html', perfil_labels=perfis_disponiveis)


@app.route('/logout', methods=['GET', 'POST'])
def logout():
    session.clear()
    motivo = request.args.get('motivo') or request.form.get('motivo')
    if motivo == 'inatividade':
        flash('Sessão expirada por inatividade. Faça login novamente.', 'error')
    else:
        flash('Você saiu do sistema.', 'success')
    return redirect(url_for('login'))


# --- Dashboard ---

@app.route('/')
@login_required
def dashboard():
    db = get_db()

    periodo = request.args.get('periodo', 'todos')
    filtro_data = ''
    params_data = []

    if periodo == '7d':
        filtro_data = " AND a.data_coleta >= (CURRENT_DATE - INTERVAL '7 days')::text"
    elif periodo == '30d':
        filtro_data = " AND a.data_coleta >= (CURRENT_DATE - INTERVAL '30 days')::text"
    elif periodo == '90d':
        filtro_data = " AND a.data_coleta >= (CURRENT_DATE - INTERVAL '90 days')::text"
    elif periodo == '6m':
        filtro_data = " AND a.data_coleta >= (CURRENT_DATE - INTERVAL '6 months')::text"
    elif periodo == '1a':
        filtro_data = " AND a.data_coleta >= (CURRENT_DATE - INTERVAL '1 year')::text"
    elif periodo == 'custom':
        data_inicio = request.args.get('data_inicio', '').strip()
        data_fim = request.args.get('data_fim', '').strip()
        if data_inicio and data_fim:
            try:
                datetime.strptime(data_inicio, '%Y-%m-%d')
                datetime.strptime(data_fim, '%Y-%m-%d')
                filtro_data = " AND a.data_coleta >= ? AND a.data_coleta <= ?"
                params_data = [data_inicio, data_fim]
            except ValueError:
                flash('Datas inválidas no período personalizado.', 'error')

    contagens = db.execute(f'''
        SELECT COUNT(*) as total,
            SUM(CASE WHEN a.status = 'Aprovada' THEN 1 ELSE 0 END) as aprovadas,
            SUM(CASE WHEN a.status = 'Reprovada' THEN 1 ELSE 0 END) as reprovadas,
            SUM(CASE WHEN a.status = 'Pendente' THEN 1 ELSE 0 END) as pendentes,
            SUM(CASE WHEN a.status = 'Em Revisão' THEN 1 ELSE 0 END) as em_revisao
        FROM amostras a WHERE 1=1{filtro_data}
    ''', params_data).fetchone()

    total_amostras = contagens['total'] or 0
    aprovadas = contagens['aprovadas'] or 0
    reprovadas = contagens['reprovadas'] or 0
    pendentes = contagens['pendentes'] or 0
    em_revisao = contagens['em_revisao'] or 0

    total_finalizadas = aprovadas + reprovadas
    taxa_conformidade = round((aprovadas / total_finalizadas * 100), 1) if total_finalizadas > 0 else 0

    ultimas_amostras = db.execute(f'''
        SELECT a.id, p.nome as produto, a.numero_lote, a.data_coleta, a.status
        FROM amostras a
        JOIN produtos p ON a.produto_id = p.id
        WHERE 1=1{filtro_data}
        ORDER BY a.data_coleta DESC
        LIMIT 5
    ''', params_data).fetchall()

    join_filtro = f" AND 1=1{filtro_data}" if filtro_data else ""
    amostras_por_produto = db.execute(f'''
        SELECT p.nome, COUNT(a.id) as total
        FROM produtos p
        LEFT JOIN amostras a ON p.id = a.produto_id{join_filtro}
        GROUP BY p.id, p.nome
        ORDER BY total DESC
    ''', params_data).fetchall()

    conformidade_por_produto = db.execute(f'''
        SELECT p.nome,
            SUM(CASE WHEN a.status = 'Aprovada' THEN 1 ELSE 0 END) as aprovadas,
            SUM(CASE WHEN a.status = 'Reprovada' THEN 1 ELSE 0 END) as reprovadas
        FROM produtos p
        LEFT JOIN amostras a ON p.id = a.produto_id AND a.status IN ('Aprovada', 'Reprovada'){filtro_data}
        GROUP BY p.id, p.nome
    ''', params_data).fetchall()

    # Tendencia mensal: amostras por mes nos ultimos 12 meses
    tendencia = db.execute(f'''
        SELECT TO_CHAR(a.data_coleta::date, 'YYYY-MM') as mes,
            COUNT(*) as total,
            SUM(CASE WHEN a.status = 'Aprovada' THEN 1 ELSE 0 END) as aprovadas,
            SUM(CASE WHEN a.status = 'Reprovada' THEN 1 ELSE 0 END) as reprovadas
        FROM amostras a
        WHERE a.data_coleta::date >= CURRENT_DATE - INTERVAL '12 months'
        GROUP BY TO_CHAR(a.data_coleta::date, 'YYYY-MM')
        ORDER BY mes
    ''').fetchall()

    db.close()

    return render_template('dashboard.html',
        total_amostras=total_amostras,
        aprovadas=aprovadas,
        reprovadas=reprovadas,
        pendentes=pendentes,
        em_revisao=em_revisao,
        taxa_conformidade=taxa_conformidade,
        ultimas_amostras=ultimas_amostras,
        amostras_por_produto=amostras_por_produto,
        conformidade_por_produto=conformidade_por_produto,
        tendencia=tendencia,
        periodo=periodo,
        data_inicio=request.args.get('data_inicio', ''),
        data_fim=request.args.get('data_fim', '')
    )


# --- Amostras ---

@app.route('/amostras')
@login_required
def listar_amostras():
    db = get_db()

    produto_id = request.args.get('produto_id', '')
    status = request.args.get('status', '')
    busca_lote = request.args.get('lote', '').strip()
    pagina = request.args.get('pagina', 1, type=int)
    por_pagina = 15

    query = '''
        SELECT a.id, p.nome as produto, a.numero_lote, a.data_coleta,
               a.responsavel, a.status
        FROM amostras a
        JOIN produtos p ON a.produto_id = p.id
        WHERE 1=1
    '''
    params = []

    if produto_id:
        query += ' AND a.produto_id = ?'
        params.append(produto_id)
    if status:
        query += ' AND a.status = ?'
        params.append(status)
    if busca_lote:
        query += ' AND a.numero_lote LIKE ?'
        params.append(f'%{busca_lote}%')

    count_query = query.replace(
        'SELECT a.id, p.nome as produto, a.numero_lote, a.data_coleta,\n               a.responsavel, a.status',
        'SELECT COUNT(*)'
    )
    total = db.execute(count_query, params).fetchone()[0]
    total_paginas = max(1, (total + por_pagina - 1) // por_pagina)
    pagina = max(1, min(pagina, total_paginas))

    query += ' ORDER BY a.data_coleta DESC LIMIT ? OFFSET ?'
    params.extend([por_pagina, (pagina - 1) * por_pagina])

    amostras = db.execute(query, params).fetchall()
    produtos = buscar_produtos(db)
    db.close()

    return render_template('amostras/lista.html',
        amostras=amostras,
        produtos=produtos,
        filtro_produto=produto_id,
        filtro_status=status,
        busca_lote=busca_lote,
        pagina=pagina,
        total_paginas=total_paginas,
        total=total
    )


@app.route('/amostras/nova', methods=['GET', 'POST'])
@login_required
def nova_amostra():
    db = get_db()
    produtos = buscar_produtos(db)

    if request.method == 'POST':
        produto_id = request.form.get('produto_id', '').strip()
        numero_lote = request.form.get('numero_lote', '').strip()
        data_coleta = request.form.get('data_coleta', '').strip()
        responsavel = request.form.get('responsavel', '').strip()

        form_data = {'produto_id': produto_id, 'numero_lote': numero_lote, 'data_coleta': data_coleta, 'responsavel': responsavel}

        if not all([produto_id, numero_lote, data_coleta, responsavel]):
            flash('Preencha todos os campos.', 'error')
            db.close()
            return render_template('amostras/nova.html', produtos=produtos, form=form_data)

        try:
            produto_id = int(produto_id)
        except ValueError:
            flash('Produto inválido.', 'error')
            db.close()
            return render_template('amostras/nova.html', produtos=produtos, form=form_data)

        if data_coleta > datetime.now().strftime('%Y-%m-%d'):
            flash('A data de coleta não pode ser depois de hoje.', 'error')
            db.close()
            return render_template('amostras/nova.html', produtos=produtos, form=form_data)

        cursor = db.execute('''
            INSERT INTO amostras (produto_id, numero_lote, data_coleta, responsavel, status)
            VALUES (?, ?, ?, ?, 'Pendente')
        ''', [produto_id, numero_lote, data_coleta, responsavel])

        amostra_id = cursor.lastrowid

        parametros = db.execute(
            'SELECT id FROM parametros_ensaio WHERE produto_id = ?', [produto_id]
        ).fetchall()

        for param in parametros:
            db.execute('''
                INSERT INTO resultados (amostra_id, parametro_id, valor_obtido, conforme, data_ensaio, tecnico)
                VALUES (?, ?, NULL, NULL, NULL, NULL)
            ''', [amostra_id, param['id']])

        registrar_historico(db, 'Criou', 'Amostra', amostra_id, f'Lote {numero_lote}')
        db.commit()
        db.close()

        flash('Amostra cadastrada com sucesso!', 'success')
        return redirect(url_for('detalhe_amostra', amostra_id=amostra_id))

    db.close()
    return render_template('amostras/nova.html', produtos=produtos)


@app.route('/amostras/<int:amostra_id>')
@login_required
def detalhe_amostra(amostra_id):
    db = get_db()
    amostra, redir = buscar_amostra_ou_redirecionar(db, amostra_id)
    if redir: return redir

    resultados = buscar_resultados(db, amostra_id)
    db.close()

    return render_template('amostras/detalhe.html',
        amostra=amostra,
        resultados=resultados
    )


@app.route('/amostras/<int:amostra_id>/editar', methods=['GET', 'POST'])
@login_required
def editar_amostra(amostra_id):
    db = get_db()
    amostra, redir = buscar_amostra_ou_redirecionar(db, amostra_id)
    if redir: return redir

    if request.method == 'POST':
        numero_lote = request.form.get('numero_lote', '').strip()
        data_coleta = request.form.get('data_coleta', '').strip()
        responsavel = request.form.get('responsavel', '').strip()

        if not all([numero_lote, data_coleta, responsavel]):
            flash('Preencha todos os campos.', 'error')
            db.close()
            return render_template('amostras/editar.html', amostra=amostra)

        db.execute('''
            UPDATE amostras SET numero_lote = ?, data_coleta = ?, responsavel = ?
            WHERE id = ?
        ''', [numero_lote, data_coleta, responsavel, amostra_id])
        registrar_historico(db, 'Editou', 'Amostra', amostra_id, f'Lote {numero_lote}')
        db.commit()
        db.close()

        flash('Amostra atualizada.', 'success')
        return redirect(url_for('detalhe_amostra', amostra_id=amostra_id))

    db.close()
    return render_template('amostras/editar.html', amostra=amostra)


@app.route('/amostras/<int:amostra_id>/excluir', methods=['POST'])
@login_required
@perfil_minimo('coordenador')
def excluir_amostra(amostra_id):
    db = get_db()
    amostra, redir = buscar_amostra_ou_redirecionar(db, amostra_id)
    if redir: return redir

    lote = amostra['numero_lote']
    db.execute('DELETE FROM resultados WHERE amostra_id = ?', [amostra_id])
    db.execute('DELETE FROM amostras WHERE id = ?', [amostra_id])
    registrar_historico(db, 'Excluiu', 'Amostra', amostra_id, f'Lote {lote}')
    db.commit()
    db.close()

    flash('Amostra excluída.', 'success')
    return redirect(url_for('listar_amostras'))


# --- Ensaios ---

@app.route('/ensaios/registrar/<int:amostra_id>', methods=['GET', 'POST'])
@login_required
def registrar_ensaios(amostra_id):
    db = get_db()
    amostra, redir = buscar_amostra_ou_redirecionar(db, amostra_id)
    if redir: return redir

    resultados_tpl = buscar_resultados(db, amostra_id)

    if request.method == 'POST':
        tecnico = request.form.get('tecnico', '').strip()
        data_ensaio = request.form.get('data_ensaio', '').strip()

        valores_ensaios = {}
        for key in request.form:
            if key.startswith('valor_'):
                valores_ensaios[key] = request.form[key]
        form_data = {'tecnico': tecnico, 'data_ensaio': data_ensaio, 'valores': valores_ensaios}

        if not tecnico or not data_ensaio:
            flash('Preencha o técnico e a data do ensaio.', 'error')
            db.close()
            return render_template('ensaios/registrar.html', amostra=amostra, resultados=resultados_tpl, form=form_data)

        if data_ensaio > datetime.now().strftime('%Y-%m-%d'):
            flash('A data do ensaio não pode ser depois de hoje.', 'error')
            db.close()
            return render_template('ensaios/registrar.html', amostra=amostra, resultados=resultados_tpl, form=form_data)

        if data_ensaio < amostra['data_coleta']:
            flash('A data do ensaio não pode ser antes da data de coleta da amostra.', 'error')
            db.close()
            return render_template('ensaios/registrar.html', amostra=amostra, resultados=resultados_tpl, form=form_data)

        resultados_db = db.execute('''
            SELECT r.id, pe.valor_minimo, pe.valor_maximo
            FROM resultados r
            JOIN parametros_ensaio pe ON r.parametro_id = pe.id
            WHERE r.amostra_id = ?
        ''', [amostra_id]).fetchall()

        # Validar todos os valores ANTES de fazer qualquer UPDATE
        valores_processados = []
        for resultado in resultados_db:
            campo = f'valor_{resultado["id"]}'
            valor_str = request.form.get(campo, '').strip()

            if not valor_str:
                flash('Todos os parâmetros devem ser preenchidos.', 'error')
                db.close()
                return render_template('ensaios/registrar.html', amostra=amostra, resultados=resultados_tpl)

            try:
                valor = float(valor_str)
            except ValueError:
                flash('Valor inválido encontrado. Use apenas números.', 'error')
                db.close()
                return render_template('ensaios/registrar.html', amostra=amostra, resultados=resultados_tpl)

            conforme = 1
            if resultado['valor_minimo'] is not None and valor < resultado['valor_minimo']:
                conforme = 0
            if resultado['valor_maximo'] is not None and valor > resultado['valor_maximo']:
                conforme = 0

            valores_processados.append((valor, conforme, resultado['id']))

        # Todos válidos — agora sim faz os UPDATEs
        for valor, conforme, resultado_id in valores_processados:
            db.execute('''
                UPDATE resultados
                SET valor_obtido = ?, conforme = ?, data_ensaio = ?, tecnico = ?
                WHERE id = ?
            ''', [valor, conforme, data_ensaio, tecnico, resultado_id])

        db.execute('UPDATE amostras SET status = ? WHERE id = ?', ['Em Revisão', amostra_id])
        registrar_historico(db, 'Registrou ensaios', 'Amostra', amostra_id, 'Aguardando revisão do coordenador')

        db.commit()
        db.close()

        flash('Ensaios registrados! Aguardando revisão do coordenador.', 'success')
        return redirect(url_for('detalhe_amostra', amostra_id=amostra_id))

    db.close()

    return render_template('ensaios/registrar.html',
        amostra=amostra,
        resultados=resultados_tpl
    )


# --- Revisão de Laudos ---

@app.route('/laudos/<int:amostra_id>/revisar', methods=['POST'])
@login_required
@perfil_minimo('coordenador')
def revisar_laudo(amostra_id):

    decisao = request.form.get('decisao')
    if decisao not in ['aprovar', 'reprovar']:
        flash('Decisão inválida.', 'error')
        return redirect(url_for('detalhe_amostra', amostra_id=amostra_id))

    db = get_db()
    amostra, redir = buscar_amostra_ou_redirecionar(db, amostra_id)
    if redir:
        db.close()
        return redir

    if amostra['status'] != 'Em Revisão':
        flash('Esta amostra não está em revisão.', 'error')
        db.close()
        return redirect(url_for('detalhe_amostra', amostra_id=amostra_id))

    novo_status = 'Aprovada' if decisao == 'aprovar' else 'Reprovada'
    revisor = session.get('usuario_nome')
    data_revisao = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    db.execute('''
        UPDATE amostras SET status = ?, revisado_por = ?, data_revisao = ?
        WHERE id = ?
    ''', [novo_status, revisor, data_revisao, amostra_id])

    registrar_historico(db, f'Revisou laudo ({novo_status})', 'Amostra', amostra_id,
                        f'Revisado por {revisor}')

    db.commit()
    db.close()

    flash(f'Laudo {novo_status.lower()} por {revisor}.', 'success')
    return redirect(url_for('detalhe_amostra', amostra_id=amostra_id))


# --- Laudos ---

@app.route('/laudos/<int:amostra_id>')
@login_required
def gerar_laudo(amostra_id):
    db = get_db()
    amostra, redir = buscar_amostra_ou_redirecionar(db, amostra_id, com_descricao=True)
    if redir: return redir

    resultados = buscar_resultados(db, amostra_id)
    db.close()

    return render_template('laudos/laudo.html',
        amostra=amostra,
        resultados=resultados,
        data_emissao=datetime.now().strftime('%d/%m/%Y')
    )


@app.route('/laudos/<int:amostra_id>/pdf')
@login_required
def gerar_laudo_pdf(amostra_id):
    try:
        from weasyprint import HTML
    except ImportError:
        flash('WeasyPrint não instalado. Use: pip install weasyprint', 'error')
        return redirect(url_for('detalhe_amostra', amostra_id=amostra_id))

    db = get_db()
    amostra, redir = buscar_amostra_ou_redirecionar(db, amostra_id, com_descricao=True)
    if redir: return redir
    resultados = buscar_resultados(db, amostra_id)
    db.close()

    html_string = render_template('laudos/laudo.html',
        amostra=amostra,
        resultados=resultados,
        data_emissao=datetime.now().strftime('%d/%m/%Y'),
        is_pdf=True
    )

    pdf = HTML(string=html_string, base_url=request.url_root).write_pdf()

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf')
    tmp.write(pdf)
    tmp.close()

    response = send_file(tmp.name, as_attachment=True,
                         download_name=f'Laudo_Capetro_{amostra["numero_lote"]}.pdf')

    @response.call_on_close
    def cleanup():
        os.unlink(tmp.name)

    return response


# --- Historico ---

@app.route('/historico')
@login_required
@perfil_minimo('coordenador')
def historico():
    db = get_db()
    pagina = request.args.get('pagina', 1, type=int)
    por_pagina = 20

    filtro_usuario = request.args.get('usuario', '').strip()
    filtro_acao = request.args.get('acao', '').strip()
    filtro_data_inicio = request.args.get('data_inicio', '').strip()
    filtro_data_fim = request.args.get('data_fim', '').strip()

    where = ' WHERE 1=1'
    params = []

    if filtro_usuario:
        where += ' AND h.usuario_nome LIKE ?'
        params.append(f'%{filtro_usuario}%')
    if filtro_acao:
        where += ' AND h.acao LIKE ?'
        params.append(f'%{filtro_acao}%')
    if filtro_data_inicio:
        where += ' AND h.data_hora::date >= ?::date'
        params.append(filtro_data_inicio)
    if filtro_data_fim:
        where += ' AND h.data_hora::date <= ?::date'
        params.append(filtro_data_fim)

    total = db.execute(f'SELECT COUNT(*) FROM historico h{where}', params).fetchone()[0]
    total_paginas = max(1, (total + por_pagina - 1) // por_pagina)
    pagina = max(1, min(pagina, total_paginas))

    registros = db.execute(f'''
        SELECT h.* FROM historico h{where}
        ORDER BY h.data_hora DESC
        LIMIT ? OFFSET ?
    ''', params + [por_pagina, (pagina - 1) * por_pagina]).fetchall()

    # Lista de usuarios e acoes unicas pra popular os filtros
    usuarios_historico = db.execute(
        'SELECT DISTINCT usuario_nome FROM historico ORDER BY usuario_nome'
    ).fetchall()
    acoes_historico = db.execute(
        'SELECT DISTINCT acao FROM historico ORDER BY acao'
    ).fetchall()

    db.close()

    return render_template('historico.html',
        registros=registros,
        pagina=pagina,
        total_paginas=total_paginas,
        total=total,
        filtro_usuario=filtro_usuario,
        filtro_acao=filtro_acao,
        filtro_data_inicio=filtro_data_inicio,
        filtro_data_fim=filtro_data_fim,
        usuarios_historico=usuarios_historico,
        acoes_historico=acoes_historico
    )


# --- Gestao de usuarios (admin) ---

@app.route('/usuarios')
@login_required
@perfil_minimo('gerente')
def listar_usuarios():
    db = get_db()
    meu_perfil = session.get('usuario_perfil', 'tecnico')

    # Gerente so ve tecnicos e coordenadores, admin ve todos
    if meu_perfil == 'gerente':
        usuarios = db.execute(
            "SELECT * FROM usuarios WHERE perfil IN ('tecnico', 'coordenador') ORDER BY nome"
        ).fetchall()
    else:
        usuarios = db.execute('SELECT * FROM usuarios ORDER BY nome').fetchall()

    db.close()
    return render_template('usuarios/lista.html', usuarios=usuarios, perfil_labels=PERFIL_LABELS)


@app.route('/usuarios/<int:usuario_id>/editar', methods=['GET', 'POST'])
@login_required
@perfil_minimo('gerente')
def editar_usuario(usuario_id):
    db = get_db()
    meu_perfil = session.get('usuario_perfil', 'tecnico')
    usuario = db.execute('SELECT * FROM usuarios WHERE id = ?', [usuario_id]).fetchone()

    if not usuario:
        db.close()
        flash('Usuário não encontrado.', 'error')
        return redirect(url_for('listar_usuarios'))

    # Gerente so pode editar tecnicos e coordenadores
    if meu_perfil == 'gerente' and usuario['perfil'] not in ('tecnico', 'coordenador'):
        db.close()
        flash('Você não tem permissão para editar este usuário.', 'error')
        return redirect(url_for('listar_usuarios'))

    perfis_disponiveis = perfis_permitidos()

    if request.method == 'POST':
        nome = request.form.get('nome', '').strip()
        email = request.form.get('email', '').strip().lower()
        perfil = request.form.get('perfil', 'tecnico')

        if not nome or not email:
            flash('Preencha nome e e-mail.', 'error')
            db.close()
            return render_template('usuarios/editar.html', usuario=usuario, perfil_labels=perfis_disponiveis)

        if perfil not in perfis_disponiveis:
            perfil = 'tecnico'

        cargo = PERFIL_LABELS.get(perfil, 'Técnico')

        existente = db.execute('SELECT id FROM usuarios WHERE email = ? AND id != ?', [email, usuario_id]).fetchone()
        if existente:
            db.close()
            flash('Este e-mail já está sendo usado por outro usuário.', 'error')
            return render_template('usuarios/editar.html', usuario=usuario, perfil_labels=perfis_disponiveis)

        db.execute('UPDATE usuarios SET nome = ?, email = ?, cargo = ?, perfil = ? WHERE id = ?',
                   [nome, email, cargo, perfil, usuario_id])

        mudancas = []
        if nome != usuario['nome']:
            mudancas.append(f'nome: {usuario["nome"]} → {nome}')
        if email != usuario['email']:
            mudancas.append(f'email: {usuario["email"]} → {email}')
        if perfil != usuario['perfil']:
            mudancas.append(f'perfil: {PERFIL_LABELS.get(perfil)}')

        registrar_historico(db, 'Editou conta', 'Usuário', usuario_id,
                            ', '.join(mudancas) if mudancas else 'Sem alterações')
        db.commit()
        db.close()

        if usuario_id == session.get('usuario_id'):
            session['usuario_nome'] = nome
            session['usuario_cargo'] = cargo
            session['usuario_perfil'] = perfil

        flash(f'Dados de {nome} atualizados.', 'success')
        return redirect(url_for('listar_usuarios'))

    db.close()
    return render_template('usuarios/editar.html', usuario=usuario, perfil_labels=perfis_disponiveis)


@app.route('/usuarios/<int:usuario_id>/ativar', methods=['POST'])
@login_required
@perfil_minimo('gerente')
def toggle_usuario(usuario_id):
    db = get_db()
    meu_perfil = session.get('usuario_perfil', 'tecnico')
    usuario = db.execute('SELECT * FROM usuarios WHERE id = ?', [usuario_id]).fetchone()

    if not usuario:
        db.close()
        flash('Usuário não encontrado.', 'error')
        return redirect(url_for('listar_usuarios'))

    if meu_perfil == 'gerente' and usuario['perfil'] not in ('tecnico', 'coordenador'):
        db.close()
        flash('Você não tem permissão para alterar este usuário.', 'error')
        return redirect(url_for('listar_usuarios'))

    novo_estado = 0 if usuario['ativo'] else 1
    acao = 'Ativou' if novo_estado else 'Desativou'
    db.execute('UPDATE usuarios SET ativo = ? WHERE id = ?', [novo_estado, usuario_id])
    registrar_historico(db, acao, 'Usuário', usuario_id, usuario['nome'])
    db.commit()
    db.close()

    flash(f'Usuário {usuario["nome"]} {"ativado" if novo_estado else "desativado"}.', 'success')
    return redirect(url_for('listar_usuarios'))


@app.route('/usuarios/<int:usuario_id>/excluir', methods=['POST'])
@login_required
@perfil_minimo('admin')
def excluir_usuario(usuario_id):
    if usuario_id == session.get('usuario_id'):
        flash('Você não pode excluir sua própria conta.', 'error')
        return redirect(url_for('listar_usuarios'))

    db = get_db()
    usuario = db.execute('SELECT * FROM usuarios WHERE id = ?', [usuario_id]).fetchone()
    if not usuario:
        db.close()
        flash('Usuário não encontrado.', 'error')
        return redirect(url_for('listar_usuarios'))

    nome = usuario['nome']
    db.execute('DELETE FROM usuarios WHERE id = ?', [usuario_id])
    registrar_historico(db, 'Excluiu conta', 'Usuário', usuario_id, nome)
    db.commit()
    db.close()

    flash(f'Conta de {nome} excluída permanentemente.', 'success')
    return redirect(url_for('listar_usuarios'))


# --- Minha conta ---

@app.route('/minha-conta', methods=['GET', 'POST'])
@login_required
def minha_conta():
    db = get_db()
    usuario = db.execute('SELECT * FROM usuarios WHERE id = ?', [session['usuario_id']]).fetchone()

    if request.method == 'POST':
        senha_atual = request.form.get('senha_atual', '')
        nova_senha = request.form.get('nova_senha', '')
        confirmar = request.form.get('confirmar_senha', '')

        if not check_password_hash(usuario['senha_hash'], senha_atual):
            db.close()
            flash('Senha atual incorreta.', 'error')
            return render_template('minha_conta.html', usuario=usuario, perfil_labels=PERFIL_LABELS)

        if nova_senha != confirmar:
            db.close()
            flash('As novas senhas não coincidem.', 'error')
            return render_template('minha_conta.html', usuario=usuario, perfil_labels=PERFIL_LABELS)

        if len(nova_senha) < 6:
            db.close()
            flash('A nova senha deve ter pelo menos 6 caracteres.', 'error')
            return render_template('minha_conta.html', usuario=usuario, perfil_labels=PERFIL_LABELS)

        db.execute('UPDATE usuarios SET senha_hash = ? WHERE id = ?',
                   [generate_password_hash(nova_senha), session['usuario_id']])
        registrar_historico(db, 'Alterou senha', 'Usuário', session['usuario_id'], usuario['nome'])
        db.commit()
        db.close()

        flash('Senha alterada com sucesso!', 'success')
        return redirect(url_for('minha_conta'))

    db.close()
    return render_template('minha_conta.html', usuario=usuario, perfil_labels=PERFIL_LABELS)


# --- Pagina de erro ---

@app.errorhandler(403)
def acesso_negado(e):
    flash('Requisição inválida ou expirada. Tente novamente.', 'error')
    return redirect(url_for('dashboard'))


@app.errorhandler(404)
def pagina_nao_encontrada(e):
    return render_template('404.html'), 404


@app.errorhandler(500)
def erro_interno(e):
    flash('Ocorreu um erro interno. Tente novamente mais tarde.', 'error')
    return redirect(url_for('dashboard'))


# --- Backups ---

@app.route('/backups')
@login_required
@perfil_minimo('admin')
def pagina_backups():
    backups = listar_backups()
    return render_template('backups.html', backups=backups)


@app.route('/backups/criar', methods=['POST'])
@login_required
@perfil_minimo('admin')
def criar_backup():
    sucesso, resultado = fazer_backup()
    if sucesso:
        db = get_db()
        registrar_historico(db, 'Criou backup', 'Sistema', detalhes=os.path.basename(resultado))
        db.commit()
        db.close()
        flash('Backup criado com sucesso!', 'success')
    else:
        flash(f'Falha ao criar backup: {resultado}', 'error')

    return redirect(url_for('pagina_backups'))


@app.route('/backups/download/<nome>')
@login_required
@perfil_minimo('admin')
def download_backup(nome):
    # Proteger contra path traversal
    if '/' in nome or '\\' in nome or '..' in nome:
        abort(404)

    caminho = os.path.join(BACKUP_DIR, nome)
    if not os.path.isfile(caminho):
        flash('Backup não encontrado.', 'error')
        return redirect(url_for('pagina_backups'))

    return send_file(caminho, as_attachment=True, download_name=nome)


# --- Backup automático diário ---

def _agendar_backup_diario():
    """Executa backup e reagenda para daqui 24h."""
    sucesso, resultado = fazer_backup()
    if sucesso:
        print(f'[BACKUP] Backup automático salvo: {os.path.basename(resultado)}')
    else:
        print(f'[BACKUP] Falha no backup automático: {resultado}')

    # Reagendar para daqui 24h
    timer = threading.Timer(86400, _agendar_backup_diario)
    timer.daemon = True
    timer.start()


def iniciar_backup_agendado():
    """Inicia o primeiro backup após 60s e depois repete a cada 24h."""
    timer = threading.Timer(60, _agendar_backup_diario)
    timer.daemon = True
    timer.start()
    print('[BACKUP] Backup automático agendado (a cada 24h)')


if __name__ == '__main__':
    # Debug desligado por padrão — para ligar: set FLASK_DEBUG=1
    debug = os.environ.get('FLASK_DEBUG', '').lower() in ('1', 'true')
    # Iniciar backup agendado apenas no processo principal (evitar duplicata no reloader)
    if not debug or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        iniciar_backup_agendado()
    app.run(debug=debug, port=5000)
