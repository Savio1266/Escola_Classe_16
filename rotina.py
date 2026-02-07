"""
Sistema de Gestão de Eventos Escolares - VERSÃO SIMPLIFICADA
Gerencia eventos, prazos e calendário compartilhado
APENAS EVENTOS - SEM RECADOS
"""

from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
import sqlite3
from datetime import datetime, timedelta
from functools import wraps

bp_rotina = Blueprint('rotina', __name__)

# Função auxiliar para pegar a função conectar_bd do app
def get_conectar_bd():
    """Obtém a função conectar_bd injetada pelo app.py"""
    if hasattr(bp_rotina, 'conectar_bd') and bp_rotina.conectar_bd is not None:
        return bp_rotina.conectar_bd
    else:
        raise RuntimeError("Função conectar_bd não foi injetada no blueprint. Verifique app.py")

def conectar_bd():
    """Wrapper para chamar a função conectar_bd injetada"""
    return get_conectar_bd()()

def login_required(tipo_permitido=None):
    """
    Decorator para verificar autenticação e tipo de usuário
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'usuario' not in session:
                flash('Faça login para acessar esta página.', 'warning')
                return redirect(url_for('login'))
            
            tipo_usuario = session.get('tipo', 'professor')
            
            # Se requer moderador especificamente
            if tipo_permitido == 'moderador' and tipo_usuario != 'moderador':
                flash('Acesso negado. Apenas gestores podem acessar esta área.', 'danger')
                return redirect(url_for('dashboard_professor'))
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def ensure_rotina_tables():
    """Cria as tabelas necessárias para o sistema de eventos"""
    conn = conectar_bd()
    cursor = conn.cursor()
    
    # Tabela de eventos/rotinas
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS eventos_rotina (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo TEXT NOT NULL,
            descricao TEXT,
            tipo TEXT NOT NULL,
            data_evento DATE NOT NULL,
            data_limite DATE,
            prioridade TEXT DEFAULT 'normal',
            status TEXT DEFAULT 'pendente',
            dias_atraso INTEGER DEFAULT 0,
            cor TEXT DEFAULT '#6366f1',
            criado_por TEXT NOT NULL,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            visivel_para TEXT DEFAULT 'todos',
            notificado INTEGER DEFAULT 0
        )
    ''')
    
    # Tabela de visualizações
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS eventos_visualizacoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            evento_id INTEGER NOT NULL,
            usuario TEXT NOT NULL,
            visualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(evento_id, usuario),
            FOREIGN KEY (evento_id) REFERENCES eventos_rotina(id) ON DELETE CASCADE
        )
    ''')
    
    conn.commit()
    conn.close()


# ==================== ROTAS PARA MODERADORES ====================

@bp_rotina.route('/rotina/gestao')
@login_required('moderador')
def gestao_rotina():
    """Painel de gestão de eventos para moderadores"""
    conn = conectar_bd()
    cursor = conn.cursor()

    # Estatísticas
    cursor.execute('''
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN status = 'pendente' THEN 1 ELSE 0 END) as pendentes,
            SUM(CASE WHEN status = 'atrasado' THEN 1 ELSE 0 END) as atrasados,
            SUM(CASE WHEN status = 'concluido' THEN 1 ELSE 0 END) as concluidos
        FROM eventos_rotina
    ''')
    stats = cursor.fetchone()

    # Próximos eventos
    cursor.execute('''
        SELECT * FROM eventos_rotina
        WHERE data_evento >= date('now')
        ORDER BY data_evento ASC
        LIMIT 10
    ''')
    eventos_proximos = cursor.fetchall()

    # TODOS os eventos
    cursor.execute('''
        SELECT * FROM eventos_rotina
        ORDER BY data_evento DESC
    ''')
    eventos_todos = cursor.fetchall()

    conn.close()

    return render_template(
        'rotina/gestao_rotina.html',
        stats=stats,
        eventos_proximos=eventos_proximos,
        eventos_todos=eventos_todos
    )


@bp_rotina.route('/rotina/evento/novo', methods=['GET', 'POST'])
@login_required('moderador')
def novo_evento():
    """Criar novo evento"""
    if request.method == 'POST':
        conn = conectar_bd()
        cursor = conn.cursor()
        
        titulo = request.form.get('titulo')
        descricao = request.form.get('descricao')
        tipo = request.form.get('tipo')
        data_evento = request.form.get('data_evento')
        data_limite = request.form.get('data_limite')
        prioridade = request.form.get('prioridade', 'normal')
        cor = request.form.get('cor', '#6366f1')
        visivel_para = request.form.get('visivel_para', 'todos')
        
        cursor.execute('''
            INSERT INTO eventos_rotina 
            (titulo, descricao, tipo, data_evento, data_limite, prioridade, cor, criado_por, visivel_para)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (titulo, descricao, tipo, data_evento, data_limite, prioridade, cor, 
              session['usuario'], visivel_para))
        
        conn.commit()
        conn.close()
        
        flash('Evento cadastrado com sucesso!', 'success')
        return redirect(url_for('rotina.gestao_rotina'))
    
    return render_template('rotina/novo_evento.html')


@bp_rotina.route('/rotina/evento/<int:evento_id>/editar', methods=['GET', 'POST'])
@login_required('moderador')
def editar_evento(evento_id):
    """Editar evento existente"""
    conn = conectar_bd()
    cursor = conn.cursor()

    if request.method == 'POST':
        titulo = request.form.get('titulo')
        descricao = request.form.get('descricao')
        tipo = request.form.get('tipo')
        data_evento = request.form.get('data_evento')
        data_limite = request.form.get('data_limite')
        prioridade = request.form.get('prioridade')
        status = request.form.get('status')
        dias_atraso = request.form.get('dias_atraso', 0)
        cor = request.form.get('cor')
        visivel_para = request.form.get('visivel_para')

        cursor.execute('''
            UPDATE eventos_rotina SET
                titulo = ?, descricao = ?, tipo = ?, data_evento = ?,
                data_limite = ?, prioridade = ?, status = ?, dias_atraso = ?,
                cor = ?, visivel_para = ?, atualizado_em = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (titulo, descricao, tipo, data_evento, data_limite, prioridade,
              status, dias_atraso, cor, visivel_para, evento_id))

        conn.commit()
        conn.close()

        flash('Evento atualizado com sucesso!', 'success')
        return redirect(url_for('rotina.gestao_rotina'))

    cursor.execute('SELECT * FROM eventos_rotina WHERE id = ?', (evento_id,))
    evento = cursor.fetchone()
    conn.close()

    if not evento:
        flash('Evento não encontrado.', 'danger')
        return redirect(url_for('rotina.gestao_rotina'))

    return render_template('rotina/editar_evento.html', evento=evento)


@bp_rotina.route('/rotina/evento/<int:evento_id>/deletar', methods=['POST'])
@login_required('moderador')
def deletar_evento(evento_id):
    """Deletar evento"""
    conn = conectar_bd()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM eventos_rotina WHERE id = ?', (evento_id,))
    conn.commit()
    conn.close()
    
    flash('Evento removido com sucesso!', 'success')
    return redirect(url_for('rotina.gestao_rotina'))


# ==================== ROTAS PARA PROFESSORES ====================

@bp_rotina.route('/rotina/visualizar')
@login_required('professor')
def visualizar_rotina():
    """Visualização de eventos para professores e moderadores"""
    conn = conectar_bd()
    cursor = conn.cursor()
    
    tipo_usuario = session.get('tipo', 'professor')
    usuario = session['usuario']
    
    # Buscar eventos visíveis
    if tipo_usuario == 'moderador':
        # Moderador vê tudo
        cursor.execute('''
            SELECT * FROM eventos_rotina
            WHERE data_evento >= date('now', '-30 days')
            ORDER BY data_evento ASC, prioridade DESC
        ''')
    else:
        # Professor vê apenas o que é visível para ele
        cursor.execute('''
            SELECT * FROM eventos_rotina
            WHERE (visivel_para = 'todos' OR visivel_para = 'professores')
            AND data_evento >= date('now', '-30 days')
            ORDER BY data_evento ASC, prioridade DESC
        ''')
    eventos = cursor.fetchall()
    
    # Marcar eventos como visualizados
    for evento in eventos:
        cursor.execute('''
            INSERT OR IGNORE INTO eventos_visualizacoes (evento_id, usuario)
            VALUES (?, ?)
        ''', (evento['id'], usuario))
    
    conn.commit()
    conn.close()
    
    return render_template('rotina/visualizar_rotina.html', eventos=eventos)


# ==================== API PARA CALENDÁRIO ====================

@bp_rotina.route('/api/calendario/eventos')
def api_eventos_calendario():
    """API para buscar eventos do calendário (formato FullCalendar)"""
    if 'usuario' not in session:
        return jsonify({'error': 'Não autenticado'}), 401
    
    conn = conectar_bd()
    cursor = conn.cursor()
    
    tipo_usuario = session.get('tipo', 'professor')
    
    # Filtrar eventos baseado no tipo de usuário
    if tipo_usuario == 'moderador':
        cursor.execute('''
            SELECT id, titulo, descricao, tipo, data_evento as start, 
                   data_limite as end, cor as color, status, prioridade, dias_atraso,
                   criado_por, criado_em
            FROM eventos_rotina
            WHERE data_evento >= date('now', '-90 days')
            ORDER BY data_evento
        ''')
    else:  # professor
        cursor.execute('''
            SELECT id, titulo, descricao, tipo, data_evento as start,
                   data_limite as end, cor as color, status, prioridade, dias_atraso,
                   criado_por, criado_em
            FROM eventos_rotina
            WHERE (visivel_para = 'todos' OR visivel_para = 'professores')
            AND data_evento >= date('now', '-90 days')
            ORDER BY data_evento
        ''')
    
    eventos = cursor.fetchall()
    conn.close()
    
    # Formatar eventos para o FullCalendar
    eventos_formatados = []
    
    for evento in eventos:
        # Definir cor baseada no status
        cor = evento['color']
        if evento['status'] == 'atrasado':
            cor = '#ef4444'  # vermelho
        elif evento['status'] == 'concluido':
            cor = '#10b981'  # verde
        elif evento['status'] == 'pendente' and evento['prioridade'] == 'urgente':
            cor = '#f59e0b'  # laranja

        # Ícone baseado no tipo
        icone = {
            'evento': '📅',
            'prazo': '⏰',
            'aviso': '⚠️',
            'reuniao': '👥',
            'feriado': '🎉',
            'atividade': '📝'
        }.get(evento['tipo'], '📌')

        evento_formatado = {
            'id': f"evento_{evento['id']}",
            'title': f"{icone} {evento['titulo']}",
            'start': evento['start'],
            'color': cor,
            'allDay': True,
            'extendedProps': {
                'descricao': evento['descricao'] or 'Sem descrição',
                'tipo': evento['tipo'],
                'status': evento['status'],
                'prioridade': evento['prioridade'],
                'criado_por': evento['criado_por'],
                'criado_em': evento['criado_em'],
                'data_limite': evento['end']
            }
        }

        if evento['end']:
            evento_formatado['end'] = evento['end']

        eventos_formatados.append(evento_formatado)
    
    return jsonify(eventos_formatados)


# ==================== ATUALIZAÇÃO AUTOMÁTICA DE STATUS ====================

def atualizar_status_eventos():
    """
    Função para ser chamada periodicamente
    Atualiza o status dos eventos baseado na data atual
    """
    conn = conectar_bd()
    cursor = conn.cursor()
    
    # Atualizar eventos atrasados
    cursor.execute('''
        UPDATE eventos_rotina
        SET status = 'atrasado',
            dias_atraso = CAST(julianday('now') - julianday(data_limite) AS INTEGER),
            atualizado_em = CURRENT_TIMESTAMP
        WHERE data_limite < date('now')
        AND status NOT IN ('concluido', 'cancelado')
    ''')
    
    # Atualizar eventos em dia
    cursor.execute('''
        UPDATE eventos_rotina
        SET status = 'em_dia',
            dias_atraso = 0,
            atualizado_em = CURRENT_TIMESTAMP
        WHERE data_limite >= date('now')
        AND status = 'pendente'
    ''')
    
    conn.commit()
    conn.close()
