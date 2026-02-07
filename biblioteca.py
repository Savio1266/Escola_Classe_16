import sqlite3
from datetime import datetime, date, timedelta

from flask import (
    Blueprint, render_template, request, redirect,
    url_for, session, flash
)
from werkzeug.security import generate_password_hash, check_password_hash

# Blueprint da Biblioteca
bp_biblioteca = Blueprint('biblioteca', __name__)

DB_PATH = 'rfa.db'


# ----------------- FUNÇÕES DE APOIO ----------------- #

def conectar_bd_biblioteca():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


# ----------------- FUNÇÕES DE APOIO ----------------- #

# ----------------- FUNÇÕES DE APOIO ----------------- #

def usuario_logado_biblioteca():
    """
    Considera logado na BIBLIOTECA apenas se o flag
    'biblioteca_logado' estiver True na sessão.
    """
    return session.get('biblioteca_logado') is True


def require_bibliotecario():
    """
    Uso nas rotas da Biblioteca para garantir que o usuário
    tenha feito login específico da biblioteca.
    """
    if not usuario_logado_biblioteca():
        flash("Acesso restrito à Biblioteca. Faça login na Biblioteca.")
        return False
    return True




# ----------------- PORTA DE ENTRADA ----------------- #

@bp_biblioteca.route('/')
def biblioteca_home():
    """
    - Se já estiver logado como moderador ou bibliotecário → vai para o dashboard.
    - Se não estiver logado → vai para a tela de login da Biblioteca.
    """
    if usuario_logado_biblioteca():
        return redirect(url_for('biblioteca.dashboard_biblioteca'))
    return redirect(url_for('biblioteca.login_biblioteca'))


# ----------------- LOGIN / CADASTRO ----------------- #

# ----------------- LOGIN / CADASTRO ----------------- #

# ----------------- LOGIN / CADASTRO ----------------- #

@bp_biblioteca.route('/login', methods=['GET', 'POST'])
def login_biblioteca():
    """
    Tela de login da BIBLIOTECA.

    Aceita:
    - Bibliotecário cadastrado na tabela 'bibliotecarios' (status = 'aprovado')
    - Moderador da tabela 'moderadores' (ex.: SAVIO, senha Ws396525$)
    """
    if request.method == 'POST':
        login = request.form.get('login', '').strip()
        senha = request.form.get('senha', '')

        conn = conectar_bd_biblioteca()
        cursor = conn.cursor()

        # 1) TENTA PRIMEIRO COMO BIBLIOTECÁRIO
        cursor.execute("""
            SELECT * FROM bibliotecarios WHERE login = ?
        """, (login,))
        bib = cursor.fetchone()

        if bib and check_password_hash(bib['senha'], senha):
            if bib['status'] != 'aprovado':
                cursor.close()
                conn.close()
                flash("Cadastro pendente de aprovação pelo moderador.")
                return redirect(url_for('biblioteca.login_biblioteca'))

            # Login OK como bibliotecário
            session['usuario'] = login
            session['tipo'] = 'bibliotecario'
            session['biblioteca_logado'] = True

            # Registra log de acesso (na tabela logs_acessos)
            try:
                c_log = conn.cursor()
                c_log.execute(
                    "INSERT INTO logs_acessos (tipo, login) VALUES (?, ?)",
                    ('biblioteca', login)
                )
                conn.commit()
                c_log.close()
            except Exception:
                pass

            cursor.close()
            conn.close()
            return redirect(url_for('biblioteca.dashboard_biblioteca'))

        # 2) SE NÃO FOR BIBLIOTECÁRIO VÁLIDO, TENTA COMO MODERADOR (ex.: SAVIO)
        cursor.execute("""
            SELECT senha, tipo FROM moderadores WHERE login = ?
        """, (login,))
        moderador = cursor.fetchone()

        if moderador and check_password_hash(moderador['senha'], senha):
            # Login OK como moderador
            session['usuario'] = login
            session['tipo'] = 'moderador'
            session['biblioteca_logado'] = True

            # Registra log de acesso da biblioteca também
            try:
                c_log = conn.cursor()
                c_log.execute(
                    "INSERT INTO logs_acessos (tipo, login) VALUES (?, ?)",
                    ('biblioteca', login)
                )
                conn.commit()
                c_log.close()
            except Exception:
                pass

            cursor.close()
            conn.close()
            return redirect(url_for('biblioteca.dashboard_biblioteca'))

        # 3) SE NENHUM DOS DOIS DEU CERTO → LOGIN INVÁLIDO
        cursor.close()
        conn.close()
        flash("Login ou senha inválidos.")
        return redirect(url_for('biblioteca.login_biblioteca'))

    # GET → só mostra a tela de login
    return render_template('biblioteca_login.html')


@bp_biblioteca.route('/cadastro', methods=['GET', 'POST'])
def cadastro_biblioteca():
    """Cadastro de bibliotecário – fica como pendente até o moderador aprovar."""
    if request.method == 'POST':
        nome = request.form.get('nome', '').strip()
        login = request.form.get('login', '').strip()
        telefone = request.form.get('telefone', '').strip()
        senha = request.form.get('senha', '')
        senha2 = request.form.get('senha2', '')

        if not nome or not login or not senha:
            flash("Preencha todos os campos obrigatórios.")
            return redirect(url_for('biblioteca.cadastro_biblioteca'))

        if senha != senha2:
            flash("As senhas não conferem.")
            return redirect(url_for('biblioteca.cadastro_biblioteca'))

        senha_hash = generate_password_hash(senha)

        conn = conectar_bd_biblioteca()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO bibliotecarios (login, senha, nome, telefone, status)
                VALUES (?, ?, ?, ?, 'pendente')
            """, (login, senha_hash, nome, telefone))
            conn.commit()
            flash("Cadastro enviado! Aguarde aprovação do moderador.")
        except sqlite3.IntegrityError:
            flash("Já existe um bibliotecário com esse login.")
        finally:
            cursor.close()
            conn.close()

        return redirect(url_for('biblioteca.login_biblioteca'))

    return render_template('biblioteca_cadastro.html')


@bp_biblioteca.route('/logout')
def logout_biblioteca():
    """
    Sai da sessão da BIBLIOTECA.
    - Remove o flag 'biblioteca_logado'
    - Se for bibliotecário, também limpa usuario/tipo (ele só existe para a biblioteca)
    """
    # Sai da biblioteca
    session.pop('biblioteca_logado', None)

    # Se for um bibliotecário, zera o login geral
    if session.get('tipo') == 'bibliotecario':
        session.pop('usuario', None)
        session.pop('tipo', None)

    flash("Você saiu da Biblioteca.")
    # Volta para a tela de login da biblioteca
    return redirect(url_for('biblioteca.login_biblioteca'))



# ----------------- GESTÃO DE BIBLIOTECÁRIOS (MODERADOR) ----------------- #

@bp_biblioteca.route('/gestao_usuarios')
def gestao_bibliotecarios():
    """Lista bibliotecários para o moderador aprovar ou reprovar."""
    if session.get('tipo') != 'moderador':
        flash("Acesso reservado ao moderador.")
        return redirect(url_for('login'))

    conn = conectar_bd_biblioteca()
    c = conn.cursor()
    c.execute("SELECT * FROM bibliotecarios ORDER BY status, nome")
    bibliotecarios = c.fetchall()
    c.close()
    conn.close()

    return render_template('biblioteca_usuarios.html', bibliotecarios=bibliotecarios)


@bp_biblioteca.route('/gestao_usuarios/<int:bib_id>/<acao>', methods=['POST'])
def atualizar_status_bibliotecario(bib_id, acao):
    if session.get('tipo') != 'moderador':
        flash("Acesso reservado ao moderador.")
        return redirect(url_for('login'))

    conn = conectar_bd_biblioteca()
    c = conn.cursor()

    try:
        if acao == 'aprovar':
            c.execute(
                "UPDATE bibliotecarios SET status = ? WHERE id = ?",
                ('aprovado', bib_id)
            )
            msg = "Bibliotecário aprovado com sucesso."
        elif acao == 'reprovar':
            c.execute(
                "UPDATE bibliotecarios SET status = ? WHERE id = ?",
                ('reprovado', bib_id)
            )
            msg = "Bibliotecário reprovado."
        elif acao == 'excluir':
            # Opcional: impedir exclusão de algum login específico
            c.execute("DELETE FROM bibliotecarios WHERE id = ?", (bib_id,))
            msg = "Bibliotecário excluído com sucesso."
        else:
            msg = "Ação inválida."

        conn.commit()
        flash(msg)
    finally:
        c.close()
        conn.close()

    return redirect(url_for('biblioteca.gestao_bibliotecarios'))



# ----------------- PAINEL PRINCIPAL DA BIBLIOTECA ----------------- #

@bp_biblioteca.route('/dashboard')
def dashboard_biblioteca():
    if not require_bibliotecario():
        return redirect(url_for('biblioteca.login_biblioteca'))

    hoje = date.today()
    hoje_str = hoje.strftime('%Y-%m-%d')
    mes_str = hoje.strftime('%Y-%m')

    conn = conectar_bd_biblioteca()
    c = conn.cursor()

    # Empréstimos ativos hoje
    c.execute("""
        SELECT COUNT(*) AS total
        FROM emprestimos_biblioteca
        WHERE status = 'Emprestado'
          AND data_emprestimo = ?
    """, (hoje_str,))
    emprestimos_hoje = c.fetchone()['total']

    # Empréstimos no mês
    c.execute("""
        SELECT COUNT(*) AS total
        FROM emprestimos_biblioteca
        WHERE data_emprestimo LIKE ?
    """, (f"{mes_str}%",))
    emprestimos_mes = c.fetchone()['total']

    # Turma com mais empréstimos nos últimos 30 dias
    data_limite = (hoje - timedelta(days=30)).strftime('%Y-%m-%d')
    c.execute("""
        SELECT t.nome AS turma_nome, t.turno AS turno, COUNT(*) AS total
        FROM emprestimos_biblioteca e
        JOIN turmas t ON t.id = e.turma_id
        WHERE e.data_emprestimo >= ?
        GROUP BY e.turma_id
        ORDER BY total DESC
        LIMIT 1
    """, (data_limite,))
    turma_top = c.fetchone()

    # Livros atrasados (emprestado e fora do prazo)
    c.execute("""
        SELECT COUNT(*) AS total
        FROM emprestimos_biblioteca
        WHERE status = 'Emprestado'
          AND data_prevista_devolucao IS NOT NULL
          AND data_prevista_devolucao < ?
    """, (hoje_str,))
    atrasados = c.fetchone()['total']

    c.close()
    conn.close()

    return render_template(
        'biblioteca_dashboard.html',
        emprestimos_hoje=emprestimos_hoje,
        emprestimos_mes=emprestimos_mes,
        turma_top=turma_top,
        atrasados=atrasados
    )


# ----------------- REGISTRAR EMPRÉSTIMO ----------------- #

@bp_biblioteca.route('/emprestimos/novo', methods=['GET', 'POST'])
def registrar_emprestimo():
    if not require_bibliotecario():
        return redirect(url_for('biblioteca.login_biblioteca'))

    conn = conectar_bd_biblioteca()
    c = conn.cursor()

    # Carrega turmas e alunos para montar estrutura de seleção dinâmica
    c.execute("SELECT id, nome, turno FROM turmas ORDER BY turno, nome")
    turmas = c.fetchall()

    c.execute("""
        SELECT a.id, a.nome, a.turma_id
        FROM alunos a
        ORDER BY a.nome
    """)
    alunos = c.fetchall()

    # Monta dicionário {turma_id: [alunos]}
    alunos_por_turma = {}
    for al in alunos:
        tid = al['turma_id']
        alunos_por_turma.setdefault(tid, []).append({
            'id': al['id'],
            'nome': al['nome']
        })

    c.close()
    conn.close()

    if request.method == 'POST':
        turma_id = request.form.get('turma_id')
        aluno_id = request.form.get('aluno_id')
        titulo = request.form.get('titulo', '').strip()
        autor = request.form.get('autor', '').strip()
        codigo = request.form.get('codigo', '').strip()
        data_prevista = request.form.get('data_prevista')

        if not turma_id or not aluno_id or not titulo:
            flash("Selecione turma, aluno e informe o título do livro.")
            return redirect(url_for('biblioteca.registrar_emprestimo'))

        hoje_str = date.today().strftime('%Y-%m-%d')

        conn = conectar_bd_biblioteca()
        c = conn.cursor()
        c.execute("""
            INSERT INTO emprestimos_biblioteca
            (aluno_id, turma_id, titulo_livro, autor, codigo_interno,
             data_emprestimo, data_prevista_devolucao, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'Emprestado')
        """, (aluno_id, turma_id, titulo, autor or None, codigo or None,
              hoje_str, data_prevista or None))
        conn.commit()
        c.close()
        conn.close()

        flash("Empréstimo registrado com sucesso.")
        return redirect(url_for('biblioteca.registrar_emprestimo'))

    return render_template(
        'biblioteca_registrar_emprestimo.html',
        turmas=turmas,
        alunos_por_turma=alunos_por_turma
    )


# ----------------- REGISTRAR DEVOLUÇÃO ----------------- #

@bp_biblioteca.route('/emprestimos/devolucao', methods=['GET'])
def registrar_devolucao():
    if not require_bibliotecario():
        return redirect(url_for('biblioteca.login_biblioteca'))

    termo = (request.args.get('termo') or '').strip()

    conn = conectar_bd_biblioteca()
    c = conn.cursor()
    query = """
        SELECT e.*, a.nome AS aluno_nome, t.nome AS turma_nome, t.turno
        FROM emprestimos_biblioteca e
        JOIN alunos a ON a.id = e.aluno_id
        JOIN turmas t ON t.id = e.turma_id
        WHERE e.status = 'Emprestado'
    """
    params = []
    if termo:
        query += " AND (a.nome LIKE ? OR e.titulo_livro LIKE ?)"
        like = f"%{termo}%"
        params.extend([like, like])

    query += " ORDER BY e.data_emprestimo DESC"
    c.execute(query, params)
    emprestimos = c.fetchall()
    c.close()
    conn.close()

    return render_template(
        'biblioteca_registrar_devolucao.html',
        emprestimos=emprestimos,
        termo=termo
    )


@bp_biblioteca.route('/emprestimos/devolver/<int:emprestimo_id>', methods=['POST'])
def devolver_livro(emprestimo_id):
    if not require_bibliotecario():
        return redirect(url_for('biblioteca.login_biblioteca'))

    hoje = date.today()
    hoje_str = hoje.strftime('%Y-%m-%d')

    conn = conectar_bd_biblioteca()
    c = conn.cursor()
    c.execute("""
        SELECT data_prevista_devolucao
        FROM emprestimos_biblioteca
        WHERE id = ?
    """, (emprestimo_id,))
    row = c.fetchone()

    if not row:
        c.close()
        conn.close()
        flash("Empréstimo não encontrado.")
        return redirect(url_for('biblioteca.registrar_devolucao'))

    data_prevista = row['data_prevista_devolucao']
    devolucao_pontual = None
    if data_prevista:
        try:
            data_prev = datetime.strptime(data_prevista, '%Y-%m-%d').date()
            devolucao_pontual = 1 if hoje <= data_prev else 0
        except ValueError:
            devolucao_pontual = None

    c.execute("""
        UPDATE emprestimos_biblioteca
        SET data_devolucao = ?, status = 'Devolvido', devolucao_pontual = ?
        WHERE id = ?
    """, (hoje_str, devolucao_pontual, emprestimo_id))
    conn.commit()
    c.close()
    conn.close()

    flash("Devolução registrado(a).")
    return redirect(url_for('biblioteca.registrar_devolucao'))


# ----------------- HISTÓRICO POR ESTUDANTE ----------------- #

@bp_biblioteca.route('/historico/estudante', methods=['GET', 'POST'])
def historico_estudante():
    if not require_bibliotecario():
        return redirect(url_for('biblioteca.login_biblioteca'))

    conn = conectar_bd_biblioteca()
    c = conn.cursor()

    c.execute("SELECT id, nome, turno FROM turmas ORDER BY turno, nome")
    turmas = c.fetchall()

    c.execute("""
        SELECT a.id, a.nome, a.turma_id
        FROM alunos a
        ORDER BY a.nome
    """)
    alunos = c.fetchall()

    alunos_por_turma = {}
    for al in alunos:
        tid = al['turma_id']
        alunos_por_turma.setdefault(tid, []).append({
            'id': al['id'],
            'nome': al['nome']
        })

    historico = []
    total_lidos = 0
    atrasos = 0
    aluno_nome = None
    turma_info = None

    aluno_id = None

    if request.method == 'POST':
        aluno_id = request.form.get('aluno_id')
    else:
        aluno_id = request.args.get('aluno_id')

    if aluno_id:
        c.execute("""
            SELECT a.nome AS aluno_nome, t.nome AS turma_nome, t.turno
            FROM alunos a
            JOIN turmas t ON t.id = a.turma_id
            WHERE a.id = ?
        """, (aluno_id,))
        info = c.fetchone()
        if info:
            aluno_nome = info['aluno_nome']
            turma_info = f"{info['turma_nome']} - {info['turno']}"

        c.execute("""
            SELECT *
            FROM emprestimos_biblioteca
            WHERE aluno_id = ?
            ORDER BY data_emprestimo DESC
        """, (aluno_id,))
        historico = c.fetchall()
        total_lidos = len(historico)

        c.execute("""
            SELECT COUNT(*) AS total
            FROM emprestimos_biblioteca
            WHERE aluno_id = ?
              AND status = 'Devolvido'
              AND devolucao_pontual = 0
        """, (aluno_id,))
        atrasos = c.fetchone()['total']

    c.close()
    conn.close()

    return render_template(
        'biblioteca_historico_estudante.html',
        turmas=turmas,
        alunos_por_turma=alunos_por_turma,
        historico=historico,
        aluno_nome=aluno_nome,
        turma_info=turma_info,
        total_lidos=total_lidos,
        atrasos=atrasos,
        aluno_id_selecionado=aluno_id
    )


# ----------------- HISTÓRICO POR TURMA ----------------- #

@bp_biblioteca.route('/historico/turma', methods=['GET', 'POST'])
def historico_turma():
    if not require_bibliotecario():
        return redirect(url_for('biblioteca.login_biblioteca'))

    conn = conectar_bd_biblioteca()
    c = conn.cursor()

    c.execute("SELECT id, nome, turno FROM turmas ORDER BY turno, nome")
    turmas = c.fetchall()

    turma_id = None
    if request.method == 'POST':
        turma_id = request.form.get('turma_id')
    else:
        turma_id = request.args.get('turma_id')

    historico = []
    resumo_alunos = []
    turma_info = None
    total_emprestimos = 0

    if turma_id:
        c.execute("""
            SELECT nome, turno FROM turmas WHERE id = ?
        """, (turma_id,))
        tinfo = c.fetchone()
        if tinfo:
            turma_info = f"{tinfo['nome']} - {tinfo['turno']}"

        # Histórico detalhado da turma
        c.execute("""
            SELECT e.*, a.nome AS aluno_nome
            FROM emprestimos_biblioteca e
            JOIN alunos a ON a.id = e.aluno_id
            WHERE e.turma_id = ?
            ORDER BY e.data_emprestimo DESC
        """, (turma_id,))
        historico = c.fetchall()
        total_emprestimos = len(historico)

        # Ranking de alunos da turma
        c.execute("""
            SELECT a.nome AS aluno_nome, COUNT(*) AS total
            FROM emprestimos_biblioteca e
            JOIN alunos a ON a.id = e.aluno_id
            WHERE e.turma_id = ?
            GROUP BY e.aluno_id
            ORDER BY total DESC, aluno_nome
        """, (turma_id,))
        resumo_alunos = c.fetchall()

    c.close()
    conn.close()

    return render_template(
        'biblioteca_historico_turma.html',
        turmas=turmas,
        turma_id_selecionada=turma_id,
        turma_info=turma_info,
        historico=historico,
        resumo_alunos=resumo_alunos,
        total_emprestimos=total_emprestimos
    )


# ----------------- INDICADORES GERAIS DA BIBLIOTECA ----------------- #

@bp_biblioteca.route('/indicadores')
def indicadores_biblioteca():
    if not require_bibliotecario():
        return redirect(url_for('biblioteca.login_biblioteca'))

    conn = conectar_bd_biblioteca()
    c = conn.cursor()

    # Totais
    c.execute("SELECT COUNT(*) AS total FROM emprestimos_biblioteca")
    total_emprestimos = c.fetchone()['total']

    c.execute("""
        SELECT COUNT(*) AS total
        FROM emprestimos_biblioteca
        WHERE status = 'Devolvido'
    """)
    total_devolvidos = c.fetchone()['total']

    c.execute("""
        SELECT COUNT(*) AS total
        FROM emprestimos_biblioteca
        WHERE status = 'Devolvido'
          AND devolucao_pontual = 1
    """)
    devolvidos_prazo = c.fetchone()['total']

    c.execute("""
        SELECT COUNT(*) AS total
        FROM emprestimos_biblioteca
        WHERE status = 'Devolvido'
          AND devolucao_pontual = 0
    """)
    devolvidos_atraso = c.fetchone()['total']

    # Médias
    c.execute("SELECT COUNT(DISTINCT aluno_id) AS qtd FROM emprestimos_biblioteca")
    alunos_distintos = c.fetchone()['qtd'] or 0

    media_por_estudante = 0
    if alunos_distintos > 0:
        media_por_estudante = round(total_emprestimos / alunos_distintos, 2)

    c.execute("SELECT COUNT(DISTINCT turma_id) AS qtd FROM emprestimos_biblioteca")
    turmas_distintas = c.fetchone()['qtd'] or 0

    media_por_turma = 0
    if turmas_distintas > 0:
        media_por_turma = round(total_emprestimos / turmas_distintas, 2)

    # Rankings
    c.execute("""
        SELECT t.nome AS turma_nome, t.turno, COUNT(*) AS total
        FROM emprestimos_biblioteca e
        JOIN turmas t ON t.id = e.turma_id
        GROUP BY e.turma_id
        ORDER BY total DESC
        LIMIT 5
    """)
    ranking_turmas = c.fetchall()

    c.execute("""
        SELECT a.nome AS aluno_nome, t.nome AS turma_nome, COUNT(*) AS total
        FROM emprestimos_biblioteca e
        JOIN alunos a ON a.id = e.aluno_id
        JOIN turmas t ON t.id = e.turma_id
        GROUP BY e.aluno_id
        ORDER BY total DESC, aluno_nome
        LIMIT 5
    """)
    ranking_alunos = c.fetchall()

    # Empréstimos por mês (converter Row -> dict)
    c.execute("""
        SELECT substr(data_emprestimo, 1, 7) AS periodo, COUNT(*) AS total
        FROM emprestimos_biblioteca
        GROUP BY periodo
        ORDER BY periodo
    """)
    rows = c.fetchall()
    emprestimos_por_mes = [
        {"periodo": row["periodo"], "total": row["total"]}
        for row in rows
        if row["periodo"] is not None
    ]

    c.close()
    conn.close()

    return render_template(
        'biblioteca_indicadores.html',
        total_emprestimos=total_emprestimos,
        total_devolvidos=total_devolvidos,
        devolvidos_prazo=devolvidos_prazo,
        devolvidos_atraso=devolvidos_atraso,
        media_por_estudante=media_por_estudante,
        media_por_turma=media_por_turma,
        ranking_turmas=ranking_turmas,
        ranking_alunos=ranking_alunos,
        emprestimos_por_mes=emprestimos_por_mes
    )

