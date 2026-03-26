from flask import Flask, render_template, request, redirect, url_for, flash, send_file, session, abort
from werkzeug.security import generate_password_hash, check_password_hash
from database import get_db, init_db, seed_data
from functools import wraps
from datetime import datetime, timedelta
import tempfile
import os
import time
import secrets

app = Flask(__name__)
# Chave hardcodada temporariamente, em producao definir SECRET_KEY como variavel de ambiente
app.secret_key = os.environ.get('SECRET_KEY', 'capetro-lims-dev-key')
app.permanent_session_lifetime = timedelta(days=30)

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


@app.before_request
def before_request():
    if not os.path.exists('capetro_lims.db'):
        init_db()
        seed_data()

    # Valida CSRF em toda requisicao POST
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
            session['usuario_perfil'] = usuario['perfil'] if 'perfil' in usuario.keys() else 'tecnico'
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


@app.route('/logout')
def logout():
    session.clear()
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
        filtro_data = " AND a.data_coleta >= date('now', '-7 days')"
    elif periodo == '30d':
        filtro_data = " AND a.data_coleta >= date('now', '-30 days')"
    elif periodo == '90d':
        filtro_data = " AND a.data_coleta >= date('now', '-90 days')"
    elif periodo == '6m':
        filtro_data = " AND a.data_coleta >= date('now', '-6 months')"
    elif periodo == '1a':
        filtro_data = " AND a.data_coleta >= date('now', '-1 year')"
    elif periodo == 'custom':
        data_inicio = request.args.get('data_inicio', '')
        data_fim = request.args.get('data_fim', '')
        if data_inicio and data_fim:
            filtro_data = " AND a.data_coleta >= ? AND a.data_coleta <= ?"
            params_data = [data_inicio, data_fim]

    total_amostras = db.execute(
        f'SELECT COUNT(*) FROM amostras a WHERE 1=1{filtro_data}', params_data
    ).fetchone()[0]
    aprovadas = db.execute(
        f"SELECT COUNT(*) FROM amostras a WHERE status = 'Aprovada'{filtro_data}", params_data
    ).fetchone()[0]
    reprovadas = db.execute(
        f"SELECT COUNT(*) FROM amostras a WHERE status = 'Reprovada'{filtro_data}", params_data
    ).fetchone()[0]
    pendentes = db.execute(
        f"SELECT COUNT(*) FROM amostras a WHERE status = 'Pendente'{filtro_data}", params_data
    ).fetchone()[0]

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
        GROUP BY p.id
        ORDER BY total DESC
    ''', params_data).fetchall()

    conformidade_por_produto = db.execute(f'''
        SELECT p.nome,
            SUM(CASE WHEN a.status = 'Aprovada' THEN 1 ELSE 0 END) as aprovadas,
            SUM(CASE WHEN a.status = 'Reprovada' THEN 1 ELSE 0 END) as reprovadas
        FROM produtos p
        LEFT JOIN amostras a ON p.id = a.produto_id AND a.status IN ('Aprovada', 'Reprovada'){filtro_data}
        GROUP BY p.id
    ''', params_data).fetchall()

    db.close()

    return render_template('dashboard.html',
        total_amostras=total_amostras,
        aprovadas=aprovadas,
        reprovadas=reprovadas,
        pendentes=pendentes,
        taxa_conformidade=taxa_conformidade,
        ultimas_amostras=ultimas_amostras,
        amostras_por_produto=amostras_por_produto,
        conformidade_por_produto=conformidade_por_produto,
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
    produtos = db.execute('SELECT id, nome FROM produtos ORDER BY nome').fetchall()
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

    if request.method == 'POST':
        produto_id = request.form.get('produto_id', '').strip()
        numero_lote = request.form.get('numero_lote', '').strip()
        data_coleta = request.form.get('data_coleta', '').strip()
        responsavel = request.form.get('responsavel', '').strip()

        if not all([produto_id, numero_lote, data_coleta, responsavel]):
            flash('Preencha todos os campos.', 'error')
            produtos = db.execute('SELECT id, nome FROM produtos ORDER BY nome').fetchall()
            db.close()
            return render_template('amostras/nova.html', produtos=produtos)

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

    produtos = db.execute('SELECT id, nome FROM produtos ORDER BY nome').fetchall()
    db.close()
    return render_template('amostras/nova.html', produtos=produtos)


@app.route('/amostras/<int:amostra_id>')
@login_required
def detalhe_amostra(amostra_id):
    db = get_db()
    amostra = buscar_amostra(db, amostra_id)

    if not amostra:
        db.close()
        flash('Amostra não encontrada.', 'error')
        return redirect(url_for('listar_amostras'))

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
    amostra = buscar_amostra(db, amostra_id)

    if not amostra:
        db.close()
        flash('Amostra não encontrada.', 'error')
        return redirect(url_for('listar_amostras'))

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
    amostra = buscar_amostra(db, amostra_id)

    if not amostra:
        db.close()
        flash('Amostra não encontrada.', 'error')
        return redirect(url_for('listar_amostras'))

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
    amostra = buscar_amostra(db, amostra_id)

    if not amostra:
        db.close()
        flash('Amostra não encontrada.', 'error')
        return redirect(url_for('listar_amostras'))

    if request.method == 'POST':
        tecnico = request.form.get('tecnico', '').strip()
        data_ensaio = request.form.get('data_ensaio', '').strip()

        if not tecnico or not data_ensaio:
            flash('Preencha o técnico e a data do ensaio.', 'error')
            resultados = buscar_resultados(db, amostra_id)
            db.close()
            return render_template('ensaios/registrar.html', amostra=amostra, resultados=resultados)

        todos_conformes = True

        resultados = db.execute('''
            SELECT r.id, pe.valor_minimo, pe.valor_maximo
            FROM resultados r
            JOIN parametros_ensaio pe ON r.parametro_id = pe.id
            WHERE r.amostra_id = ?
        ''', [amostra_id]).fetchall()

        for resultado in resultados:
            campo = f'valor_{resultado["id"]}'
            valor_str = request.form.get(campo, '').strip()

            if valor_str:
                try:
                    valor = float(valor_str)
                except ValueError:
                    flash('Valor inválido encontrado. Use apenas números.', 'error')
                    resultados = buscar_resultados(db, amostra_id)
                    db.close()
                    return render_template('ensaios/registrar.html', amostra=amostra, resultados=resultados)

                conforme = True
                if resultado['valor_minimo'] is not None and valor < resultado['valor_minimo']:
                    conforme = False
                if resultado['valor_maximo'] is not None and valor > resultado['valor_maximo']:
                    conforme = False

                if not conforme:
                    todos_conformes = False

                db.execute('''
                    UPDATE resultados
                    SET valor_obtido = ?, conforme = ?, data_ensaio = ?, tecnico = ?
                    WHERE id = ?
                ''', [valor, conforme, data_ensaio, tecnico, resultado['id']])

        novo_status = 'Aprovada' if todos_conformes else 'Reprovada'
        db.execute('UPDATE amostras SET status = ? WHERE id = ?', [novo_status, amostra_id])
        registrar_historico(db, 'Registrou ensaios', 'Amostra', amostra_id, f'Status: {novo_status}')

        db.commit()
        db.close()

        flash(f'Ensaios registrados! Amostra {novo_status.lower()}.', 'success')
        return redirect(url_for('detalhe_amostra', amostra_id=amostra_id))

    resultados = buscar_resultados(db, amostra_id)
    db.close()

    return render_template('ensaios/registrar.html',
        amostra=amostra,
        resultados=resultados
    )


# --- Laudos ---

@app.route('/laudos/<int:amostra_id>')
@login_required
def gerar_laudo(amostra_id):
    db = get_db()
    amostra = buscar_amostra(db, amostra_id, com_descricao=True)

    if not amostra:
        db.close()
        flash('Amostra não encontrada.', 'error')
        return redirect(url_for('listar_amostras'))

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
    amostra = buscar_amostra(db, amostra_id, com_descricao=True)
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

    total = db.execute('SELECT COUNT(*) FROM historico').fetchone()[0]
    total_paginas = max(1, (total + por_pagina - 1) // por_pagina)
    pagina = max(1, min(pagina, total_paginas))

    registros = db.execute('''
        SELECT * FROM historico
        ORDER BY data_hora DESC
        LIMIT ? OFFSET ?
    ''', [por_pagina, (pagina - 1) * por_pagina]).fetchall()
    db.close()

    return render_template('historico.html',
        registros=registros,
        pagina=pagina,
        total_paginas=total_paginas,
        total=total
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
    flash('Página não encontrada.', 'error')
    return redirect(url_for('dashboard'))


@app.errorhandler(500)
def erro_interno(e):
    flash('Ocorreu um erro interno. Tente novamente mais tarde.', 'error')
    return redirect(url_for('dashboard'))


if __name__ == '__main__':
    # Em producao, rodar com debug=False (ou usar gunicorn/waitress)
    debug = os.environ.get('FLASK_ENV') != 'production'
    app.run(debug=debug, port=5000)
