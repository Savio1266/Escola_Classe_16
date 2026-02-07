# soe.py
import os
import sqlite3
from io import BytesIO

from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify, send_file, current_app
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

bp_soe = Blueprint("soe", __name__, template_folder="templates")


# =========================
# Banco (mesmo rfa.db)
# =========================
def conectar_bd():
    conn = sqlite3.connect("rfa.db", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_soe_table():
    """
    Cria a tabela do SOE se não existir.
    Encaminhamentos ficam SALVOS, mas NÃO entram no PDF.
    """
    conn = conectar_bd()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS soe_atendimentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            protocolo TEXT UNIQUE,
            turno TEXT,

            turma_id INTEGER NOT NULL,
            aluno_id INTEGER NOT NULL,

            responsavel_nome TEXT NOT NULL,
            responsavel_parentesco TEXT,
            orientadora_nome TEXT NOT NULL,

            data_atendimento TEXT NOT NULL,
            hora_atendimento TEXT,

            assunto TEXT,

            relato TEXT NOT NULL,
            combinados TEXT,

            retorno_previsto INTEGER DEFAULT 0,
            retorno_em TEXT,

            reuniao_agendada INTEGER DEFAULT 0,
            reuniao_data TEXT,

            encaminhamentos TEXT, -- SIGILOSO: NÃO VAI PARA O PDF

            criado_por_login TEXT,
            criado_em TEXT NOT NULL DEFAULT (datetime('now','localtime')),

            FOREIGN KEY (turma_id) REFERENCES turmas(id),
            FOREIGN KEY (aluno_id) REFERENCES alunos(id)
        )
    """)

    conn.commit()

    # Migração: garante coluna responsavel_parentesco (bancos antigos)
    try:
        cur.execute("PRAGMA table_info(soe_atendimentos);")
        cols = [r[1] for r in cur.fetchall()]  # r[1] = nome da coluna
        if "responsavel_parentesco" not in cols:
            cur.execute("ALTER TABLE soe_atendimentos ADD COLUMN responsavel_parentesco TEXT;")
            conn.commit()
    except Exception:
        pass

    cur.close()
    conn.close()


# =========================
# Segurança
# =========================
def _require_soe_full():
    # precisa estar logado como moderador
    if "usuario" not in session or session.get("tipo") != "moderador":
        flash("Acesso não autorizado.")
        return False

    # SAVIO tem acesso total permanente
    if (session.get("usuario") or "").upper() == "SAVIO":
        return True

    # demais moderadores: só se estiver liberado no campo soe_liberado
    try:
        conn = conectar_bd()
        cur = conn.cursor()
        # se a coluna não existir ainda, isso pode falhar: tratamos no except
        cur.execute(
            "SELECT COALESCE(soe_liberado, 0) AS soe_liberado "
            "FROM moderadores WHERE UPPER(login)=UPPER(?) LIMIT 1",
            (session.get("usuario"),)
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row and int(row["soe_liberado"] or 0) == 1:
            return True
    except Exception:
        pass

    flash("Acesso ao SOE restrito. Solicite liberação do moderador SAVIO.")
    return False


# =========================
# Helpers PDF
# =========================
def _draw_header(pdf, titulo: str):
    """
    Cabeçalho com logos na pasta static:
      static/logo.jpg
      static/logo1.PNG
    """
    app = current_app
    logo_esq = os.path.join(app.root_path, "static", "logo.jpg")
    logo_dir = os.path.join(app.root_path, "static", "logo1.PNG")

    y_top = 770

    if os.path.exists(logo_esq):
        pdf.drawImage(logo_esq, 40, y_top - 45, width=55, height=55, preserveAspectRatio=True, mask="auto")

    if os.path.exists(logo_dir):
        pdf.drawImage(logo_dir, 520, y_top - 45, width=55, height=55, preserveAspectRatio=True, mask="auto")

    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawCentredString(306, y_top - 10, "ESCOLA CLASSE 16")

    pdf.setFont("Helvetica", 9)
    pdf.drawCentredString(306, y_top - 26, "De Olho na Escola – Registro de Atendimento")

    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawCentredString(306, y_top - 50, titulo)

    pdf.setLineWidth(0.6)
    pdf.line(40, y_top - 60, 570, y_top - 60)

    return y_top - 70


def _wrap_text(texto: str, max_chars=95):
    if not texto:
        return []
    palavras = texto.split()
    linhas = []
    linha = ""
    for p in palavras:
        if len(linha) + len(p) + 1 <= max_chars:
            linha = (linha + " " + p).strip()
        else:
            linhas.append(linha)
            linha = p
    if linha:
        linhas.append(linha)
    return linhas


# =========================
# APIs (para selects, iguais ao padrão do moderador)
# =========================
@bp_soe.route("/soe/api/turmas")
def api_turmas_soe():
    if not _require_soe_full():
        return jsonify([])
    turno = (request.args.get("turno") or "").strip()
    try:
        conn = conectar_bd()
        cur = conn.cursor()
        if turno:
            cur.execute("SELECT id, nome, turno FROM turmas WHERE turno = ? ORDER BY nome", (turno,))
        else:
            cur.execute("SELECT id, nome, turno FROM turmas ORDER BY turno, nome")
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify([{"id": r["id"], "nome": r["nome"], "turno": r["turno"]} for r in rows])
    except Exception:
        return jsonify([])


@bp_soe.route("/soe/api/alunos")
def api_alunos_soe():
    if not _require_soe_full():
        return jsonify([])
    turma_id = (request.args.get("turma_id") or "").strip()
    if not turma_id:
        return jsonify([])
    try:
        conn = conectar_bd()
        cur = conn.cursor()
        cur.execute("SELECT id, nome FROM alunos WHERE turma_id = ? ORDER BY nome", (turma_id,))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify([{"id": r["id"], "nome": r["nome"]} for r in rows])
    except Exception:
        return jsonify([])


@bp_soe.route("/soe/api/check_protocolo")
def api_check_protocolo_soe():
    if not _require_soe_full():
        return jsonify({"ok": False})
    protocolo = (request.args.get("protocolo") or "").strip()
    if not protocolo:
        return jsonify({"ok": False})
    try:
        conn = conectar_bd()
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM soe_atendimentos WHERE protocolo = ? LIMIT 1", (protocolo,))
        exists = cur.fetchone() is not None
        cur.close()
        conn.close()
        return jsonify({"ok": not exists})
    except Exception:
        return jsonify({"ok": False})


# =========================
# Rotas (SOE)
# =========================
@bp_soe.route("/soe/novo", methods=["GET", "POST"])
def soe_novo():
    if not _require_soe_full():
        # Se estiver logado como moderador, volta para o dashboard (com a mensagem no flash).
        if "usuario" in session and session.get("tipo") == "moderador":
            return redirect(url_for("dashboard_moderador"))
        return redirect(url_for("login"))

    # turnos para o select inicial
    conn = conectar_bd()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT turno FROM turmas ORDER BY turno")
    turnos = [r["turno"] for r in cur.fetchall() if r["turno"]]
    cur.close()
    conn.close()

    if request.method == "POST":
        protocolo = (request.form.get("protocolo") or "").strip() or None
        turma_id = (request.form.get("turma_id") or "").strip()
        aluno_id = (request.form.get("aluno_id") or "").strip()

        responsavel_nome = (request.form.get("responsavel_nome") or "").strip()
        responsavel_parentesco = (request.form.get("responsavel_parentesco") or "").strip()
        orientadora_nome = (request.form.get("orientadora_nome") or "").strip()

        data_atendimento = (request.form.get("data_atendimento") or "").strip()
        hora_atendimento = (request.form.get("hora_atendimento") or "").strip() or None
        assunto = (request.form.get("assunto") or "").strip() or None

        relato = (request.form.get("relato") or "").strip()
        combinados = (request.form.get("combinados") or "").strip() or None

        retorno_previsto = 1 if request.form.get("retorno_previsto") else 0
        retorno_em = (request.form.get("retorno_em") or "").strip() or None

        reuniao_agendada = 1 if request.form.get("reuniao_agendada") else 0
        reuniao_data = (request.form.get("reuniao_data") or "").strip() or None

        encaminhamentos = (request.form.get("encaminhamentos") or "").strip() or None

        # turno da turma
        turno_turma = None
        try:
            if turma_id:
                c2 = conectar_bd()
                k = c2.cursor()
                k.execute("SELECT turno FROM turmas WHERE id = ?", (turma_id,))
                row = k.fetchone()
                k.close()
                c2.close()
                turno_turma = row["turno"] if row else None
        except Exception:
            turno_turma = None

        # validações
        if not turma_id or not aluno_id or not data_atendimento or not relato:
            flash("Preencha os campos obrigatórios: Turma, Aluno(a), Data do atendimento e Relato.")
            return redirect(url_for("soe.soe_novo"))

        if not responsavel_nome:
            flash("Informe o nome do(a) responsável presente no atendimento.")
            return redirect(url_for("soe.soe_novo"))

        if not responsavel_parentesco:
            flash("Informe o parentesco do(a) responsável.")
            return redirect(url_for("soe.soe_novo"))

        if not orientadora_nome:
            flash("Informe o nome da Orientadora (quem registrou).")
            return redirect(url_for("soe.soe_novo"))

        if retorno_previsto and not retorno_em:
            flash("Informe a data/hora do retorno.")
            return redirect(url_for("soe.soe_novo"))

        if reuniao_agendada and not reuniao_data:
            flash("Informe a data/hora da reunião.")
            return redirect(url_for("soe.soe_novo"))

        # protocolo único (se preenchido)
        if protocolo:
            c3 = conectar_bd()
            k = c3.cursor()
            k.execute("SELECT 1 FROM soe_atendimentos WHERE protocolo = ? LIMIT 1", (protocolo,))
            exists = k.fetchone() is not None
            k.close()
            c3.close()
            if exists:
                flash("Já existe um atendimento do SOE com esse protocolo. Gere outro ou deixe em branco.")
                return redirect(url_for("soe.soe_novo"))

        try:
            conn = conectar_bd()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO soe_atendimentos (
                    protocolo, turma_id, turno, aluno_id,
                    responsavel_nome, responsavel_parentesco, orientadora_nome,
                    data_atendimento, hora_atendimento, assunto,
                    relato, combinados,
                    retorno_previsto, retorno_em,
                    reuniao_agendada, reuniao_data,
                    encaminhamentos,
                    criado_por_login
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                protocolo, turma_id, turno_turma, aluno_id,
                responsavel_nome, responsavel_parentesco, orientadora_nome,
                data_atendimento, hora_atendimento, assunto,
                relato, combinados,
                retorno_previsto, retorno_em,
                reuniao_agendada, reuniao_data,
                encaminhamentos,
                session.get("usuario")
            ))
            conn.commit()
            cur.close()
            conn.close()
            flash("Atendimento do SOE salvo com sucesso.")
            return redirect(url_for("soe.soe_historico"))
        except sqlite3.Error as e:
            flash(f"Erro ao salvar atendimento do SOE: {e}")
            return redirect(url_for("soe.soe_novo"))

    # form (opcional) para repopular, se quiser evoluir depois
    return render_template("soe_novo.html", turnos=turnos, form=None)


@bp_soe.route("/soe/historico", methods=["GET"])
def soe_historico():
    if not _require_soe_full():
        # Se estiver logado como moderador, volta para o dashboard (com a mensagem no flash).
        if "usuario" in session and session.get("tipo") == "moderador":
            return redirect(url_for("dashboard_moderador"))
        return redirect(url_for("login"))

    protocolo = (request.args.get("protocolo") or "").strip()
    turno = (request.args.get("turno") or "").strip()
    turma_id = (request.args.get("turma_id") or "").strip()
    aluno_id = (request.args.get("aluno_id") or "").strip()
    data_ini = (request.args.get("data_ini") or "").strip()
    data_fim = (request.args.get("data_fim") or "").strip()

    conn = conectar_bd()
    cur = conn.cursor()

    # combos
    cur.execute("SELECT DISTINCT turno FROM turmas ORDER BY turno")
    turnos = [r["turno"] for r in cur.fetchall() if r["turno"]]
    cur.execute("SELECT id, nome, turno FROM turmas ORDER BY turno, nome")
    turmas = cur.fetchall()

    alunos = []
    if turma_id:
        cur.execute("SELECT id, nome FROM alunos WHERE turma_id = ? ORDER BY nome", (turma_id,))
        alunos = cur.fetchall()

    where = []
    params = []

    if protocolo:
        where.append("s.protocolo LIKE ?")
        params.append(f"%{protocolo}%")
    if turno:
        where.append("s.turno = ?")
        params.append(turno)
    if turma_id:
        where.append("s.turma_id = ?")
        params.append(turma_id)
    if aluno_id:
        where.append("s.aluno_id = ?")
        params.append(aluno_id)
    if data_ini:
        where.append("date(s.data_atendimento) >= date(?)")
        params.append(data_ini)
    if data_fim:
        where.append("date(s.data_atendimento) <= date(?)")
        params.append(data_fim)

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    cur.execute(f"""
        SELECT
            s.id,
            s.protocolo,
            s.turno,
            s.data_atendimento,
            s.hora_atendimento,
            s.orientadora_nome,
            s.responsavel_nome,
            s.assunto,
            t.nome AS turma_nome,
            t.turno AS turma_turno,
            a.nome AS aluno_nome
        FROM soe_atendimentos s
        JOIN turmas t ON t.id = s.turma_id
        JOIN alunos a ON a.id = s.aluno_id
        {where_sql}
        ORDER BY date(s.data_atendimento) DESC, s.id DESC
    """, params)

    registros = cur.fetchall()
    cur.close()
    conn.close()

    return render_template(
        "soe_historico.html",
        registros=registros,
        turnos=turnos,
        turmas=turmas,
        alunos=alunos,
        filtro={
            "protocolo": protocolo,
            "turno": turno,
            "turma_id": turma_id,
            "aluno_id": aluno_id,
            "data_ini": data_ini,
            "data_fim": data_fim
        }
    )


@bp_soe.route("/soe/ver/<int:atendimento_id>")
def soe_ver(atendimento_id):
    if not _require_soe_full():
        # Se estiver logado como moderador, volta para o dashboard (com a mensagem no flash).
        if "usuario" in session and session.get("tipo") == "moderador":
            return redirect(url_for("dashboard_moderador"))
        return redirect(url_for("login"))

    conn = conectar_bd()
    cur = conn.cursor()
    cur.execute("""
        SELECT
            s.*,
            t.nome AS turma_nome,
            t.turno AS turma_turno,
            a.nome AS aluno_nome
        FROM soe_atendimentos s
        JOIN turmas t ON t.id = s.turma_id
        JOIN alunos a ON a.id = s.aluno_id
        WHERE s.id = ?
    """, (atendimento_id,))
    at = cur.fetchone()
    cur.close()
    conn.close()

    if not at:
        flash("Atendimento do SOE não encontrado.")
        return redirect(url_for("soe.soe_historico"))

    return render_template("soe_ver.html", at=at)


@bp_soe.route("/soe/editar/<int:atendimento_id>", methods=["GET", "POST"])
def soe_editar(atendimento_id):
    if not _require_soe_full():
        # Se estiver logado como moderador, volta para o dashboard (com a mensagem no flash).
        if "usuario" in session and session.get("tipo") == "moderador":
            return redirect(url_for("dashboard_moderador"))
        return redirect(url_for("login"))

    conn = conectar_bd()
    cur = conn.cursor()

    # combos
    cur.execute("SELECT id, nome, turno FROM turmas ORDER BY turno, nome")
    turmas = cur.fetchall()

    if request.method == "POST":
        turma_id = (request.form.get("turma_id") or "").strip()
        aluno_id = (request.form.get("aluno_id") or "").strip()

        responsavel_nome = (request.form.get("responsavel_nome") or "").strip()
        responsavel_parentesco = (request.form.get("responsavel_parentesco") or "").strip()
        orientadora_nome = (request.form.get("orientadora_nome") or "").strip()

        data_atendimento = (request.form.get("data_atendimento") or "").strip()
        hora_atendimento = (request.form.get("hora_atendimento") or "").strip() or None
        assunto = (request.form.get("assunto") or "").strip() or None

        relato = (request.form.get("relato") or "").strip()
        combinados = (request.form.get("combinados") or "").strip() or None

        retorno_previsto = 1 if request.form.get("retorno_previsto") else 0
        retorno_em = (request.form.get("retorno_em") or "").strip() or None

        reuniao_agendada = 1 if request.form.get("reuniao_agendada") else 0
        reuniao_data = (request.form.get("reuniao_data") or "").strip() or None

        encaminhamentos = (request.form.get("encaminhamentos") or "").strip() or None

        # turno da turma
        turno_turma = None
        try:
            if turma_id:
                c2 = conectar_bd()
                k = c2.cursor()
                k.execute("SELECT turno FROM turmas WHERE id = ?", (turma_id,))
                row = k.fetchone()
                k.close()
                c2.close()
                turno_turma = row["turno"] if row else None
        except Exception:
            turno_turma = None

        if not turma_id or not aluno_id or not data_atendimento or not relato or not responsavel_nome or not orientadora_nome:
            flash("Preencha os campos obrigatórios.")
            cur.close()
            conn.close()
            return redirect(url_for("soe.soe_editar", atendimento_id=atendimento_id))

        if retorno_previsto and not retorno_em:
            flash("Informe a data/hora do retorno.")
            cur.close()
            conn.close()
            return redirect(url_for("soe.soe_editar", atendimento_id=atendimento_id))

        if reuniao_agendada and not reuniao_data:
            flash("Informe a data/hora da reunião.")
            cur.close()
            conn.close()
            return redirect(url_for("soe.soe_editar", atendimento_id=atendimento_id))

        try:
            cur.execute("""
                UPDATE soe_atendimentos
                SET
                    turma_id = ?,
                    aluno_id = ?,
                    turno = ?,
                    responsavel_nome = ?,
                    responsavel_parentesco = ?,
                    orientadora_nome = ?,
                    data_atendimento = ?,
                    hora_atendimento = ?,
                    assunto = ?,
                    relato = ?,
                    combinados = ?,
                    retorno_previsto = ?,
                    retorno_em = ?,
                    reuniao_agendada = ?,
                    reuniao_data = ?,
                    encaminhamentos = ?
                WHERE id = ?
            """, (
                turma_id, aluno_id, turno_turma,
                responsavel_nome, responsavel_parentesco, orientadora_nome,
                data_atendimento, hora_atendimento, assunto,
                relato, combinados,
                retorno_previsto, retorno_em,
                reuniao_agendada, reuniao_data,
                encaminhamentos,
                atendimento_id
            ))
            conn.commit()
            flash("Atendimento do SOE atualizado com sucesso.")
            cur.close()
            conn.close()
            return redirect(url_for("soe.soe_ver", atendimento_id=atendimento_id))
        except sqlite3.Error as e:
            flash(f"Erro ao atualizar atendimento do SOE: {e}")
            cur.close()
            conn.close()
            return redirect(url_for("soe.soe_editar", atendimento_id=atendimento_id))

    # GET
    cur.execute("SELECT * FROM soe_atendimentos WHERE id = ?", (atendimento_id,))
    at = cur.fetchone()

    alunos = []
    if at and at["turma_id"]:
        cur.execute("SELECT id, nome FROM alunos WHERE turma_id = ? ORDER BY nome", (at["turma_id"],))
        alunos = cur.fetchall()

    cur.close()
    conn.close()

    if not at:
        flash("Atendimento do SOE não encontrado.")
        return redirect(url_for("soe.soe_historico"))

    return render_template("soe_editar.html", at=at, turmas=turmas, alunos=alunos)


@bp_soe.route("/soe/pdf/<int:atendimento_id>", methods=["GET"])
def soe_pdf(atendimento_id):
    if not _require_soe_full():
        # Se estiver logado como moderador, volta para o dashboard (com a mensagem no flash).
        if "usuario" in session and session.get("tipo") == "moderador":
            return redirect(url_for("dashboard_moderador"))
        return redirect(url_for("login"))

    conn = conectar_bd()
    cur = conn.cursor()
    cur.execute("""
        SELECT
            s.*,
            t.nome AS turma_nome,
            t.turno AS turma_turno,
            a.nome AS aluno_nome
        FROM soe_atendimentos s
        JOIN turmas t ON t.id = s.turma_id
        JOIN alunos a ON a.id = s.aluno_id
        WHERE s.id = ?
        LIMIT 1
    """, (atendimento_id,))
    at = cur.fetchone()
    cur.close()
    conn.close()

    if not at:
        flash("Atendimento do SOE não encontrado.")
        return redirect(url_for("soe.soe_historico"))

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)

    y = _draw_header(pdf, "ATENDIMENTO – SOE (Orientação Educacional)")

    # Identificação
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(40, y, "Identificação")
    y -= 14
    pdf.setFont("Helvetica", 9)
    pdf.drawString(40, y, f"Turma: {at['turma_nome']} ({at['turma_turno']})")
    pdf.drawString(300, y, f"Data(Ano/Mês/Dia): {at['data_atendimento']}  {at['hora_atendimento'] or ''}".strip())
    y -= 12
    pdf.drawString(40, y, f"Aluno(a): {at['aluno_nome']}")
    y -= 12
    pdf.drawString(40, y, f"Responsável: {at['responsavel_nome']}" + (f" ({at['responsavel_parentesco']})" if at['responsavel_parentesco'] else ""))
    y -= 12
    pdf.drawString(40, y, f"Orientadora: {at['orientadora_nome']}")
    y -= 14
    if at["protocolo"]:
        pdf.drawString(40, y, f"Protocolo: {at['protocolo']}")
        y -= 14

    # Assunto
    if at["assunto"]:
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(40, y, "Assunto")
        y -= 12
        pdf.setFont("Helvetica", 9)
        for linha in _wrap_text(at["assunto"], 95):
            pdf.drawString(40, y, linha)
            y -= 11
        y -= 6

    # Relato
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(40, y, "Relato")
    y -= 12
    pdf.setFont("Helvetica", 9)
    for linha in _wrap_text(at["relato"], 95):
        if y < 90:
            pdf.showPage()
            y = _draw_header(pdf, "ATENDIMENTO – SOE (Orientação Educacional)")
            pdf.setFont("Helvetica", 9)
        pdf.drawString(40, y, linha)
        y -= 11
    y -= 8

    # Combinados (vai para o PDF)
    if at["combinados"]:
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(40, y, "Combinados do Atendimento")
        y -= 12
        pdf.setFont("Helvetica", 9)
        for linha in _wrap_text(at["combinados"], 95):
            if y < 90:
                pdf.showPage()
                y = _draw_header(pdf, "ATENDIMENTO – SOE (Orientação Educacional)")
                pdf.setFont("Helvetica", 9)
            pdf.drawString(40, y, linha)
            y -= 11
        y -= 8

    # Retorno/Reunião
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(40, y, "Retorno / Reunião")
    y -= 12
    pdf.setFont("Helvetica", 9)
    pdf.drawString(40, y, f"Retorno previsto: {'SIM' if at['retorno_previsto'] else 'NÃO'}")
    if at["retorno_previsto"] and at["retorno_em"]:
        pdf.drawString(220, y, f"Quando: {at['retorno_em']}")
    y -= 12
    pdf.drawString(40, y, f"Reunião agendada: {'SIM' if at['reuniao_agendada'] else 'NÃO'}")
    if at["reuniao_agendada"] and at["reuniao_data"]:
        pdf.drawString(220, y, f"Quando: {at['reuniao_data']}")
    y -= 26

    # Assinaturas
    pdf.setLineWidth(0.7)
    pdf.line(60, y, 280, y)
    pdf.line(330, y, 550, y)
    y -= 12
    pdf.setFont("Helvetica", 9)
    pdf.drawCentredString(170, y, "Assinatura da Orientadora")
    pdf.drawCentredString(440, y, "Assinatura do(a) Responsável")

    # IMPORTANTE: encaminhamentos NÃO entram no PDF (sigilo)
    pdf.showPage()
    pdf.save()

    buffer.seek(0)
    nome = f"atendimento_soe_{atendimento_id}.pdf"
    return send_file(buffer, as_attachment=True, download_name=nome, mimetype="application/pdf")
