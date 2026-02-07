# -*- coding: utf-8 -*-
"""
Blueprint para gerenciamento de horários de aula
Sistema: De Olho na Escola
Autor: Sávio
Data: 2026
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, send_from_directory
from werkzeug.utils import secure_filename
import os
from datetime import datetime

# Criar blueprint
bp_horario = Blueprint('horario', __name__, url_prefix='/horario')

# Configurações de upload
UPLOAD_FOLDER = 'static/horarios_aula'
ALLOWED_EXTENSIONS = {'png'}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB

# Variável global para armazenar a função conectar_bd
conectar_bd = None


# ==================== FUNÇÕES AUXILIARES ====================

def arquivo_permitido(filename):
    """Verifica se a extensão do arquivo é permitida"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def criar_diretorio_upload():
    """Cria o diretório de upload se não existir"""
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)
        print(f"✓ Diretório criado: {UPLOAD_FOLDER}")


def salvar_arquivo(arquivo, turma_id):
    """
    Salva o arquivo enviado e retorna o nome do arquivo
    """
    print(f"\n=== SALVANDO ARQUIVO ===")
    print(f"Nome original: {arquivo.filename}")
    print(f"Turma ID: {turma_id}")

    if not arquivo or arquivo.filename == '':
        print("❌ Arquivo vazio ou sem nome")
        return None

    if not arquivo_permitido(arquivo.filename):
        print(f"❌ Extensão não permitida: {arquivo.filename}")
        return None

    # Verificar tamanho do arquivo
    arquivo.seek(0, os.SEEK_END)
    tamanho = arquivo.tell()
    arquivo.seek(0)

    print(f"Tamanho do arquivo: {tamanho} bytes ({tamanho / 1024 / 1024:.2f}MB)")

    if tamanho > MAX_FILE_SIZE:
        print(f"❌ Arquivo muito grande: {tamanho} > {MAX_FILE_SIZE}")
        return None

    # Gerar nome único para o arquivo
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    nome_seguro = secure_filename(arquivo.filename)
    extensao = nome_seguro.rsplit('.', 1)[1].lower()
    nome_arquivo = f"horario_turma_{turma_id}_{timestamp}.{extensao}"

    print(f"Nome seguro gerado: {nome_arquivo}")

    # Criar diretório se não existir
    criar_diretorio_upload()

    # Salvar arquivo
    caminho_completo = os.path.join(UPLOAD_FOLDER, nome_arquivo)
    print(f"Caminho completo: {caminho_completo}")

    try:
        arquivo.save(caminho_completo)
        print(f"✅ Arquivo salvo com sucesso!")

        # Verificar se o arquivo foi realmente salvo
        if os.path.exists(caminho_completo):
            tamanho_salvo = os.path.getsize(caminho_completo)
            print(f"✅ Arquivo confirmado: {tamanho_salvo} bytes")
        else:
            print(f"❌ ERRO: Arquivo não foi salvo em {caminho_completo}")
            return None

    except Exception as e:
        print(f"❌ ERRO ao salvar arquivo: {e}")
        return None

    return nome_arquivo


# ==================== INICIALIZAÇÃO DO BANCO ====================

def ensure_horario_tables():
    """
    Cria a tabela de horários se não existir
    IMPORTANTE: Esta função deve ser chamada após conectar_bd ser injetado
    """
    if conectar_bd is None:
        print("⚠ AVISO: conectar_bd não foi injetado ainda")
        return

    try:
        conn = conectar_bd()
        cursor = conn.cursor()

        # Criar tabela de horários
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS horarios_turma (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                turma_id INTEGER NOT NULL,
                arquivo TEXT NOT NULL,
                cadastrado_por TEXT NOT NULL,
                cadastrado_em TEXT DEFAULT (datetime('now','localtime')),
                atualizado_em TEXT,
                ativo INTEGER DEFAULT 1,
                FOREIGN KEY (turma_id) REFERENCES turmas(id) ON DELETE CASCADE
            )
        ''')

        # Criar índice para melhor performance
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_horarios_turma 
            ON horarios_turma(turma_id, ativo)
        ''')

        conn.commit()
        conn.close()
        print("✓ Tabela horarios_turma verificada/criada com sucesso")

    except Exception as e:
        print(f"✗ Erro ao criar tabela horarios_turma: {e}")


# ==================== ROTAS PARA MODERADORES ====================

@bp_horario.route('/moderador/horarios')
def moderador_gerenciar_horarios():
    """Lista todas as turmas com status do horário cadastrado"""

    print("\n=== ACESSANDO LISTA DE HORÁRIOS ===")

    # Verificar autenticação
    if 'tipo' not in session or session['tipo'] not in ['moderador', 'Diretor', 'Coordenador', 'diretor',
                                                        'coordenador']:
        flash('Acesso negado. Apenas gestores podem acessar esta área.', 'error')
        return redirect(url_for('login'))

    # Verificar se conectar_bd foi injetado
    if conectar_bd is None:
        print("❌ ERRO: conectar_bd é None!")
        flash('Erro de configuração do sistema. Contate o administrador.', 'error')
        return redirect(url_for('dashboard_moderador'))

    try:
        conn = conectar_bd()
        cursor = conn.cursor()

        # Buscar todas as turmas com informação se tem horário cadastrado
        cursor.execute('''
            SELECT 
                t.id,
                t.nome,
                t.turno,
                CASE WHEN h.id IS NOT NULL THEN 1 ELSE 0 END as tem_horario,
                h.cadastrado_em,
                h.cadastrado_por
            FROM turmas t
            LEFT JOIN horarios_turma h ON t.id = h.turma_id AND h.ativo = 1
            ORDER BY t.nome
        ''')

        turmas = []
        for row in cursor.fetchall():
            turmas.append({
                'id': row[0],
                'nome': row[1],
                'turno': row[2],
                'tem_horario': row[3],
                'cadastrado_em': row[4],
                'cadastrado_por': row[5]
            })

        conn.close()

        print(f"✅ {len(turmas)} turmas carregadas")

        return render_template('horarios_moderador.html', turmas=turmas)

    except Exception as e:
        print(f"❌ ERRO ao carregar turmas: {e}")
        flash(f'Erro ao carregar turmas: {str(e)}', 'error')
        return redirect(url_for('dashboard_moderador'))


@bp_horario.route('/moderador/horarios/cadastrar/<int:turma_id>', methods=['GET', 'POST'])
def moderador_cadastrar_horario(turma_id):
    """Cadastra ou atualiza o horário de uma turma"""

    print(f"\n=== CADASTRAR/ATUALIZAR HORÁRIO - Turma ID: {turma_id} ===")
    print(f"Método: {request.method}")

    # Verificar autenticação
    if 'tipo' not in session or session['tipo'] not in ['moderador', 'Diretor', 'Coordenador', 'diretor',
                                                        'coordenador']:
        flash('Acesso negado. Apenas gestores podem acessar esta área.', 'error')
        return redirect(url_for('login'))

    # Verificar se conectar_bd foi injetado
    if conectar_bd is None:
        print("❌ ERRO: conectar_bd é None!")
        flash('Erro de configuração do sistema. Contate o administrador.', 'error')
        return redirect(url_for('dashboard_moderador'))

    try:
        conn = conectar_bd()
        cursor = conn.cursor()

        # Buscar informações da turma
        cursor.execute('SELECT id, nome, turno FROM turmas WHERE id = ?', (turma_id,))
        turma = cursor.fetchone()

        if not turma:
            flash('Turma não encontrada.', 'error')
            conn.close()
            return redirect(url_for('horario.moderador_gerenciar_horarios'))

        turma_info = {
            'id': turma[0],
            'nome': turma[1],
            'turno': turma[2]
        }

        print(f"Turma encontrada: {turma_info['nome']}")

        # Verificar se já existe horário cadastrado
        cursor.execute('''
            SELECT id, arquivo, cadastrado_em 
            FROM horarios_turma 
            WHERE turma_id = ? AND ativo = 1
        ''', (turma_id,))

        horario_atual = cursor.fetchone()

        if horario_atual:
            print(f"Horário atual: {horario_atual[1]}")
        else:
            print("Nenhum horário cadastrado ainda")

        if request.method == 'POST':
            print("\n=== PROCESSANDO UPLOAD ===")

            # Debug: Ver todos os dados do request
            print(f"Files no request: {list(request.files.keys())}")
            print(f"Form no request: {list(request.form.keys())}")

            # Processar upload do arquivo
            if 'arquivo' not in request.files:
                print("❌ Campo 'arquivo' não encontrado no request")
                flash('Nenhum arquivo foi selecionado.', 'error')
                conn.close()
                return redirect(request.url)

            arquivo = request.files['arquivo']
            print(f"Arquivo recebido: {arquivo.filename}")
            print(f"Content-Type: {arquivo.content_type}")

            if arquivo.filename == '':
                print("❌ Nome do arquivo está vazio")
                flash('Nenhum arquivo foi selecionado.', 'error')
                conn.close()
                return redirect(request.url)

            if not arquivo_permitido(arquivo.filename):
                print(f"❌ Extensão não permitida: {arquivo.filename}")
                flash('Apenas arquivos PNG são permitidos.', 'error')
                conn.close()
                return redirect(request.url)

            # Verificar tamanho
            arquivo.seek(0, os.SEEK_END)
            tamanho = arquivo.tell()
            arquivo.seek(0)

            print(f"Tamanho do arquivo: {tamanho} bytes")

            if tamanho > MAX_FILE_SIZE:
                print(f"❌ Arquivo muito grande: {tamanho} bytes")
                flash('Arquivo muito grande. Tamanho máximo: 5MB.', 'error')
                conn.close()
                return redirect(request.url)

            # Salvar arquivo
            print("Tentando salvar arquivo...")
            nome_arquivo = salvar_arquivo(arquivo, turma_id)

            if not nome_arquivo:
                print("❌ Falha ao salvar arquivo")
                flash('Erro ao salvar o arquivo.', 'error')
                conn.close()
                return redirect(request.url)

            print(f"✅ Arquivo salvo: {nome_arquivo}")

            try:
                # Se já existe horário, desativar o anterior
                if horario_atual:
                    print(f"Desativando horário anterior: {horario_atual[1]}")
                    cursor.execute('''
                        UPDATE horarios_turma 
                        SET ativo = 0 
                        WHERE turma_id = ? AND ativo = 1
                    ''', (turma_id,))

                # Inserir novo horário
                usuario = session.get('usuario', 'Sistema')
                print(f"Inserindo novo horário no banco...")
                print(f"  turma_id: {turma_id}")
                print(f"  arquivo: {nome_arquivo}")
                print(f"  usuario: {usuario}")

                cursor.execute('''
                    INSERT INTO horarios_turma 
                    (turma_id, arquivo, cadastrado_por, cadastrado_em, ativo)
                    VALUES (?, ?, ?, datetime('now','localtime'), 1)
                ''', (turma_id, nome_arquivo, usuario))

                conn.commit()

                print(f"✅ Horário salvo no banco de dados!")
                print(f"   ID inserido: {cursor.lastrowid}")

                acao = 'atualizado' if horario_atual else 'cadastrado'
                flash(f'Horário {acao} com sucesso!', 'success')

            except Exception as e:
                print(f"❌ ERRO ao salvar no banco: {e}")
                conn.rollback()
                flash(f'Erro ao salvar no banco de dados: {str(e)}', 'error')

            finally:
                conn.close()

            return redirect(url_for('horario.moderador_gerenciar_horarios'))

        # GET - Exibir formulário
        conn.close()
        return render_template('horario_cadastrar.html',
                               turma=turma_info,
                               horario_atual=horario_atual)

    except Exception as e:
        print(f"❌ ERRO GERAL: {e}")
        import traceback
        traceback.print_exc()
        flash(f'Erro ao processar requisição: {str(e)}', 'error')
        return redirect(url_for('horario.moderador_gerenciar_horarios'))


@bp_horario.route('/moderador/horarios/visualizar/<int:turma_id>')
def moderador_visualizar_horario(turma_id):
    """Visualiza o horário cadastrado de uma turma"""

    # Verificar autenticação
    if 'tipo' not in session or session['tipo'] not in ['moderador', 'Diretor', 'Coordenador', 'diretor',
                                                        'coordenador']:
        flash('Acesso negado. Apenas gestores podem acessar esta área.', 'error')
        return redirect(url_for('login'))

    # Verificar se conectar_bd foi injetado
    if conectar_bd is None:
        flash('Erro de configuração do sistema. Contate o administrador.', 'error')
        return redirect(url_for('dashboard_moderador'))

    try:
        conn = conectar_bd()
        cursor = conn.cursor()

        # Buscar informações da turma e horário
        cursor.execute('''
            SELECT 
                t.id, t.nome, t.turno,
                h.arquivo, h.cadastrado_em, h.cadastrado_por
            FROM turmas t
            LEFT JOIN horarios_turma h ON t.id = h.turma_id AND h.ativo = 1
            WHERE t.id = ?
        ''', (turma_id,))

        resultado = cursor.fetchone()
        conn.close()

        if not resultado:
            flash('Turma não encontrada.', 'error')
            return redirect(url_for('horario.moderador_gerenciar_horarios'))

        if not resultado[3]:  # Se não tem arquivo
            flash('Esta turma não possui horário cadastrado.', 'warning')
            return redirect(url_for('horario.moderador_gerenciar_horarios'))

        turma_info = {
            'id': resultado[0],
            'nome': resultado[1],
            'turno': resultado[2],
            'arquivo': resultado[3],
            'cadastrado_em': resultado[4],
            'cadastrado_por': resultado[5]
        }

        return render_template('horario_visualizar.html', turma=turma_info)

    except Exception as e:
        flash(f'Erro ao visualizar horário: {str(e)}', 'error')
        return redirect(url_for('horario.moderador_gerenciar_horarios'))


@bp_horario.route('/moderador/horarios/excluir/<int:horario_id>', methods=['POST'])
def moderador_excluir_horario(horario_id):
    """Exclui (desativa) um horário cadastrado"""

    # Verificar autenticação
    if 'tipo' not in session or session['tipo'] not in ['moderador', 'Diretor', 'Coordenador', 'diretor',
                                                        'coordenador']:
        flash('Acesso negado. Apenas gestores podem acessar esta área.', 'error')
        return redirect(url_for('login'))

    # Verificar se conectar_bd foi injetado
    if conectar_bd is None:
        flash('Erro de configuração do sistema. Contate o administrador.', 'error')
        return redirect(url_for('dashboard_moderador'))

    try:
        conn = conectar_bd()
        cursor = conn.cursor()

        # Desativar o horário (soft delete)
        cursor.execute('''
            UPDATE horarios_turma 
            SET ativo = 0 
            WHERE id = ?
        ''', (horario_id,))

        conn.commit()
        conn.close()

        flash('Horário excluído com sucesso!', 'success')

    except Exception as e:
        flash(f'Erro ao excluir horário: {str(e)}', 'error')

    return redirect(url_for('horario.moderador_gerenciar_horarios'))


# ==================== ROTAS PARA RESPONSÁVEIS ====================

@bp_horario.route('/responsavel/horario')
def responsavel_ver_horario():
    """Visualiza o horário da turma do aluno vinculado ao responsável"""

    # Verificar autenticação
    if 'tipo' not in session or session['tipo'] != 'responsavel':
        flash('Acesso negado. Apenas responsáveis podem acessar esta área.', 'error')
        return redirect(url_for('login'))

    # Verificar se conectar_bd foi injetado
    if conectar_bd is None:
        flash('Erro de configuração do sistema. Contate o administrador.', 'error')
        return redirect(url_for('area_responsavel'))

    try:
        conn = conectar_bd()
        cursor = conn.cursor()

        # Buscar o aluno vinculado ao responsável
        login_responsavel = session.get('usuario')

        cursor.execute('''
            SELECT 
                a.id, a.nome, a.turma_id,
                t.nome as turma_nome, t.turno,
                h.arquivo, h.cadastrado_em
            FROM alunos a
            INNER JOIN turmas t ON a.turma_id = t.id
            LEFT JOIN horarios_turma h ON t.id = h.turma_id AND h.ativo = 1
            WHERE a.responsavel_login = ?
            LIMIT 1
        ''', (login_responsavel,))

        resultado = cursor.fetchone()
        conn.close()

        if not resultado:
            flash('Aluno não encontrado ou não vinculado a este responsável.', 'error')
            return redirect(url_for('area_responsavel'))

        aluno_info = {
            'id': resultado[0],
            'nome': resultado[1],
            'turma_id': resultado[2],
            'turma_nome': resultado[3],
            'turno': resultado[4],
            'arquivo': resultado[5],
            'cadastrado_em': resultado[6]
        }

        return render_template('horario_responsavel.html', aluno=aluno_info)

    except Exception as e:
        flash(f'Erro ao buscar horário: {str(e)}', 'error')
        return redirect(url_for('area_responsavel'))


# ==================== ROTA PARA SERVIR IMAGENS ====================

@bp_horario.route('/horarios/imagem/<filename>')
def servir_imagem(filename):
    """Serve os arquivos de horário (requer autenticação)"""

    # Verificar autenticação
    if 'usuario' not in session:
        flash('Você precisa estar autenticado para acessar este arquivo.', 'error')
        return redirect(url_for('login'))

    try:
        return send_from_directory(UPLOAD_FOLDER, filename)
    except Exception as e:
        flash(f'Erro ao carregar imagem: {str(e)}', 'error')
        return redirect(url_for('dashboard_moderador'))
