"""
CAPETRO LIMS - Sistema de Gestão Laboratorial
Protótipo para o CPTI (Centro de Pesquisas, Tecnologia e Inovação)
"""

from flask import Flask, render_template, request, redirect, url_for, flash, send_file
from database import get_db, init_db, seed_data
from datetime import datetime
import os

app = Flask(__name__)
app.secret_key = 'capetro-lims-dev-key'  # Em produção, usar variável de ambiente

# ==============================================================
# INICIALIZAÇÃO
# ==============================================================

@app.before_request
def before_request():
    """Garante que o banco existe antes de qualquer requisição."""
    if not os.path.exists('capetro_lims.db'):
        init_db()
        seed_data()


# ==============================================================
# DASHBOARD
# ==============================================================

@app.route('/')
def dashboard():
    db = get_db()

    # Total de amostras
    total_amostras = db.execute('SELECT COUNT(*) FROM amostras').fetchone()[0]

    # Amostras por status
    aprovadas = db.execute("SELECT COUNT(*) FROM amostras WHERE status = 'Aprovada'").fetchone()[0]
    reprovadas = db.execute("SELECT COUNT(*) FROM amostras WHERE status = 'Reprovada'").fetchone()[0]
    pendentes = db.execute("SELECT COUNT(*) FROM amostras WHERE status = 'Pendente'").fetchone()[0]

    # Taxa de conformidade (evita divisão por zero)
    total_finalizadas = aprovadas + reprovadas
    taxa_conformidade = round((aprovadas / total_finalizadas * 100), 1) if total_finalizadas > 0 else 0

    # Últimas 5 amostras
    ultimas_amostras = db.execute('''
        SELECT a.id, p.nome as produto, a.numero_lote, a.data_coleta, a.status
        FROM amostras a
        JOIN produtos p ON a.produto_id = p.id
        ORDER BY a.data_coleta DESC
        LIMIT 5
    ''').fetchall()

    # Dados para gráfico: amostras por produto
    amostras_por_produto = db.execute('''
        SELECT p.nome, COUNT(a.id) as total
        FROM produtos p
        LEFT JOIN amostras a ON p.id = a.produto_id
        GROUP BY p.id
        ORDER BY total DESC
    ''').fetchall()

    # Dados para gráfico: conformidade por produto
    conformidade_por_produto = db.execute('''
        SELECT p.nome,
            SUM(CASE WHEN a.status = 'Aprovada' THEN 1 ELSE 0 END) as aprovadas,
            SUM(CASE WHEN a.status = 'Reprovada' THEN 1 ELSE 0 END) as reprovadas
        FROM produtos p
        LEFT JOIN amostras a ON p.id = a.produto_id AND a.status IN ('Aprovada', 'Reprovada')
        GROUP BY p.id
    ''').fetchall()

    db.close()

    return render_template('dashboard.html',
        total_amostras=total_amostras,
        aprovadas=aprovadas,
        reprovadas=reprovadas,
        pendentes=pendentes,
        taxa_conformidade=taxa_conformidade,
        ultimas_amostras=ultimas_amostras,
        amostras_por_produto=amostras_por_produto,
        conformidade_por_produto=conformidade_por_produto
    )


# ==============================================================
# AMOSTRAS
# ==============================================================

@app.route('/amostras')
def listar_amostras():
    db = get_db()

    # Filtros opcionais
    produto_id = request.args.get('produto_id', '')
    status = request.args.get('status', '')

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

    query += ' ORDER BY a.data_coleta DESC'

    amostras = db.execute(query, params).fetchall()
    produtos = db.execute('SELECT id, nome FROM produtos ORDER BY nome').fetchall()
    db.close()

    return render_template('amostras/lista.html',
        amostras=amostras,
        produtos=produtos,
        filtro_produto=produto_id,
        filtro_status=status
    )


@app.route('/amostras/nova', methods=['GET', 'POST'])
def nova_amostra():
    db = get_db()

    if request.method == 'POST':
        produto_id = request.form['produto_id']
        numero_lote = request.form['numero_lote']
        data_coleta = request.form['data_coleta']
        responsavel = request.form['responsavel']

        # Insere a amostra
        cursor = db.execute('''
            INSERT INTO amostras (produto_id, numero_lote, data_coleta, responsavel, status)
            VALUES (?, ?, ?, ?, 'Pendente')
        ''', [produto_id, numero_lote, data_coleta, responsavel])

        amostra_id = cursor.lastrowid

        # Cria registros vazios de resultados para cada parâmetro do produto
        parametros = db.execute(
            'SELECT id FROM parametros_ensaio WHERE produto_id = ?', [produto_id]
        ).fetchall()

        for param in parametros:
            db.execute('''
                INSERT INTO resultados (amostra_id, parametro_id, valor_obtido, conforme, data_ensaio, tecnico)
                VALUES (?, ?, NULL, NULL, NULL, NULL)
            ''', [amostra_id, param['id']])

        db.commit()
        db.close()

        flash('Amostra cadastrada com sucesso!', 'success')
        return redirect(url_for('detalhe_amostra', amostra_id=amostra_id))

    produtos = db.execute('SELECT id, nome FROM produtos ORDER BY nome').fetchall()
    db.close()
    return render_template('amostras/nova.html', produtos=produtos)


@app.route('/amostras/<int:amostra_id>')
def detalhe_amostra(amostra_id):
    db = get_db()

    amostra = db.execute('''
        SELECT a.*, p.nome as produto_nome
        FROM amostras a
        JOIN produtos p ON a.produto_id = p.id
        WHERE a.id = ?
    ''', [amostra_id]).fetchone()

    if not amostra:
        flash('Amostra não encontrada.', 'error')
        return redirect(url_for('listar_amostras'))

    resultados = db.execute('''
        SELECT r.*, pe.nome_parametro, pe.unidade, pe.valor_minimo, pe.valor_maximo, pe.metodo_ensaio
        FROM resultados r
        JOIN parametros_ensaio pe ON r.parametro_id = pe.id
        WHERE r.amostra_id = ?
        ORDER BY pe.nome_parametro
    ''', [amostra_id]).fetchall()

    db.close()

    return render_template('amostras/detalhe.html',
        amostra=amostra,
        resultados=resultados
    )


# ==============================================================
# ENSAIOS (registro de resultados)
# ==============================================================

@app.route('/ensaios/registrar/<int:amostra_id>', methods=['GET', 'POST'])
def registrar_ensaios(amostra_id):
    db = get_db()

    amostra = db.execute('''
        SELECT a.*, p.nome as produto_nome
        FROM amostras a
        JOIN produtos p ON a.produto_id = p.id
        WHERE a.id = ?
    ''', [amostra_id]).fetchone()

    if not amostra:
        flash('Amostra não encontrada.', 'error')
        return redirect(url_for('listar_amostras'))

    if request.method == 'POST':
        tecnico = request.form['tecnico']
        data_ensaio = request.form['data_ensaio']
        todos_conformes = True

        # Busca os resultados pendentes desta amostra
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
                valor = float(valor_str)

                # Verifica conformidade
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

        # Atualiza status da amostra
        novo_status = 'Aprovada' if todos_conformes else 'Reprovada'
        db.execute('UPDATE amostras SET status = ? WHERE id = ?', [novo_status, amostra_id])

        db.commit()
        db.close()

        flash(f'Ensaios registrados! Amostra {novo_status.lower()}.', 'success')
        return redirect(url_for('detalhe_amostra', amostra_id=amostra_id))

    # GET: mostra formulário com parâmetros
    resultados = db.execute('''
        SELECT r.*, pe.nome_parametro, pe.unidade, pe.valor_minimo, pe.valor_maximo, pe.metodo_ensaio
        FROM resultados r
        JOIN parametros_ensaio pe ON r.parametro_id = pe.id
        WHERE r.amostra_id = ?
        ORDER BY pe.nome_parametro
    ''', [amostra_id]).fetchall()

    db.close()

    return render_template('ensaios/registrar.html',
        amostra=amostra,
        resultados=resultados
    )


# ==============================================================
# LAUDOS (geração de PDF)
# ==============================================================

@app.route('/laudos/<int:amostra_id>')
def gerar_laudo(amostra_id):
    """Gera o laudo como página HTML (para visualização e impressão)."""
    db = get_db()

    amostra = db.execute('''
        SELECT a.*, p.nome as produto_nome, p.descricao as produto_descricao
        FROM amostras a
        JOIN produtos p ON a.produto_id = p.id
        WHERE a.id = ?
    ''', [amostra_id]).fetchone()

    if not amostra:
        flash('Amostra não encontrada.', 'error')
        return redirect(url_for('listar_amostras'))

    resultados = db.execute('''
        SELECT r.*, pe.nome_parametro, pe.unidade, pe.valor_minimo, pe.valor_maximo, pe.metodo_ensaio
        FROM resultados r
        JOIN parametros_ensaio pe ON r.parametro_id = pe.id
        WHERE r.amostra_id = ?
        ORDER BY pe.nome_parametro
    ''', [amostra_id]).fetchall()

    db.close()

    data_emissao = datetime.now().strftime('%d/%m/%Y')

    return render_template('laudos/laudo.html',
        amostra=amostra,
        resultados=resultados,
        data_emissao=data_emissao
    )


@app.route('/laudos/<int:amostra_id>/pdf')
def gerar_laudo_pdf(amostra_id):
    """Gera o laudo em PDF usando WeasyPrint."""
    try:
        from weasyprint import HTML
    except ImportError:
        flash('WeasyPrint não instalado. Use: pip install weasyprint', 'error')
        return redirect(url_for('detalhe_amostra', amostra_id=amostra_id))

    db = get_db()

    amostra = db.execute('''
        SELECT a.*, p.nome as produto_nome, p.descricao as produto_descricao
        FROM amostras a
        JOIN produtos p ON a.produto_id = p.id
        WHERE a.id = ?
    ''', [amostra_id]).fetchone()

    resultados = db.execute('''
        SELECT r.*, pe.nome_parametro, pe.unidade, pe.valor_minimo, pe.valor_maximo, pe.metodo_ensaio
        FROM resultados r
        JOIN parametros_ensaio pe ON r.parametro_id = pe.id
        WHERE r.amostra_id = ?
        ORDER BY pe.nome_parametro
    ''', [amostra_id]).fetchall()

    db.close()

    data_emissao = datetime.now().strftime('%d/%m/%Y')

    html_string = render_template('laudos/laudo.html',
        amostra=amostra,
        resultados=resultados,
        data_emissao=data_emissao,
        is_pdf=True
    )

    pdf = HTML(string=html_string, base_url=request.url_root).write_pdf()

    # Salva temporariamente
    pdf_path = f'/tmp/laudo_{amostra_id}.pdf'
    with open(pdf_path, 'wb') as f:
        f.write(pdf)

    return send_file(pdf_path, as_attachment=True,
                     download_name=f'Laudo_Capetro_{amostra["numero_lote"]}.pdf')


# ==============================================================
# EXECUÇÃO
# ==============================================================

if __name__ == '__main__':
    app.run(debug=True, port=5000)
