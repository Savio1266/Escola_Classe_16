# carometro.py
import os
import base64
import sqlite3
from datetime import datetime

from flask import Blueprint, render_template, request, session, redirect, url_for, flash, jsonify

bp_carometro = Blueprint("bp_carometro", __name__, template_folder="templates")

DB_PATH = "rfa.db"


# ----------------- BANCO (mesmo rfa.db do app.py) -----------------
def conectar_bd():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_carometro_db():
    """Cria a tabela do carômetro (sem quebrar bancos antigos)."""
    conn = conectar_bd()
    cur = conn.cursor()
    cur.execute("PRAGMA foreign_keys = ON")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS carometro_fotos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            turma_id INTEGER NOT NULL,
            aluno_id INTEGER NOT NULL,
            professor_id INTEGER NOT NULL,
            arquivo TEXT NOT NULL,
            atualizado_em TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE (aluno_id),
            FOREIGN KEY (turma_id) REFERENCES turmas(id),
            FOREIGN KEY (aluno_id) REFERENCES alunos(id),
            FOREIGN KEY (professor_id) REFERENCES professores(id)
        )
    """)

    conn.commit()
    cur.close()
    conn.close()


# ----------------- HELPERS -----------------
def _somente_professor():
    if "usuario" not in session or session.get("tipo") != "professor":
        flash("Acesso não autorizado.")
        return False
    return True


def obter_professor_id(login: str):
    conn = conectar_bd()
    cur = conn.cursor()
    cur.execute("SELECT id FROM professores WHERE login = ?", (login,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row["id"] if row else None


def obter_turmas_professor(professor_id: int):
    conn = conectar_bd()
    cur = conn.cursor()
    cur.execute("""
        SELECT t.id, t.nome, t.turno
        FROM turmas t
        JOIN professor_turmas pt ON pt.turma_id = t.id
        WHERE pt.professor_id = ?
        ORDER BY t.turno, t.nome
    """, (professor_id,))
    turmas = cur.fetchall()
    cur.close()
    conn.close()
    return turmas


def _professor_tem_vinculos(professor_id: int) -> bool:
    try:
        return len(obter_turmas_professor(professor_id)) > 0
    except Exception:
        return False


def _turma_e_do_professor(professor_id: int, turma_id) -> bool:
    turmas = obter_turmas_professor(professor_id)
    return any(str(t["id"]) == str(turma_id) for t in turmas)


def _aluno_e_da_turma(aluno_id, turma_id) -> bool:
    conn = conectar_bd()
    cur = conn.cursor()
    cur.execute("SELECT id FROM alunos WHERE id = ? AND turma_id = ?", (aluno_id, turma_id))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return bool(row)


def _garantir_pasta(path: str):
    os.makedirs(path, exist_ok=True)


def _remover_arquivo_se_existir(caminho: str):
    try:
        if caminho and os.path.exists(caminho):
            os.remove(caminho)
    except Exception:
        pass


def _foto_ja_existe(aluno_id) -> bool:
    conn = conectar_bd()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM carometro_fotos WHERE aluno_id = ? LIMIT 1", (aluno_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return bool(row)


# ----------------- ROTAS (PROFESSOR) -----------------
@bp_carometro.route("/professor/carometro", methods=["GET"])
def carometro_professor():
    if not _somente_professor():
        return redirect(url_for("login"))

    professor_id = obter_professor_id(session["usuario"])
    turmas = obter_turmas_professor(professor_id)

    # Mantém o padrão do seu sistema: se não tiver vínculo, mostra todas
    if not turmas:
        conn = conectar_bd()
        cur = conn.cursor()
        cur.execute("SELECT id, nome, turno FROM turmas ORDER BY turno, nome")
        turmas = cur.fetchall()
        cur.close()
        conn.close()

    return render_template("carometro_professor.html", turmas=turmas, usuario=session["usuario"])


@bp_carometro.route("/professor/carometro/ver", methods=["GET"])
def carometro_ver():
    # ✅ MODIFICAÇÃO: Aceita professor OU moderador
    if "usuario" not in session:
        flash("Acesso não autorizado.")
        return redirect(url_for("login"))

    tipo = session.get("tipo", "")
    if tipo not in ["professor", "moderador"]:
        flash("Acesso não autorizado.")
        return redirect(url_for("login"))

    # Se for professor, busca suas turmas
    if tipo == "professor":
        professor_id = obter_professor_id(session["usuario"])
        turmas = obter_turmas_professor(professor_id)

        if not turmas:
            conn = conectar_bd()
            cur = conn.cursor()
            cur.execute("SELECT id, nome, turno FROM turmas ORDER BY turno, nome")
            turmas = cur.fetchall()
            cur.close()
            conn.close()
    else:
        # ✅ Se for moderador, mostra TODAS as turmas
        conn = conectar_bd()
        cur = conn.cursor()
        cur.execute("SELECT id, nome, turno FROM turmas ORDER BY turno, nome")
        turmas = cur.fetchall()
        cur.close()
        conn.close()

    turma_id = (request.args.get("turma_id") or "").strip()

    alunos = []
    if turma_id:
        # ✅ Se for professor com vínculos, verifica acesso
        if tipo == "professor":
            professor_id = obter_professor_id(session["usuario"])
            if _professor_tem_vinculos(professor_id) and not _turma_e_do_professor(professor_id, turma_id):
                flash("Você não tem acesso a essa turma.")
                return redirect(url_for("bp_carometro.carometro_ver"))

        conn = conectar_bd()
        cur = conn.cursor()
        cur.execute("""
            SELECT a.id, a.nome,
                   cf.arquivo AS arquivo,
                   cf.atualizado_em AS atualizado_em
            FROM alunos a
            LEFT JOIN carometro_fotos cf ON cf.aluno_id = a.id
            WHERE a.turma_id = ?
            ORDER BY a.nome
        """, (turma_id,))
        alunos = cur.fetchall()
        cur.close()
        conn.close()

    return render_template("carometro_ver.html", turmas=turmas, turma_id=turma_id, alunos=alunos)


# ----------------- APIs (AJAX) -----------------
@bp_carometro.route("/professor/carometro/api/alunos", methods=["GET"])
def api_alunos_turma():
    """
    Retorna alunos da turma para o select do cadastro.

    REGRA: por padrão, NÃO retorna alunos que já possuem foto cadastrada.
    Para incluir também os fotografados: ?include_fotografados=1
    """
    if not _somente_professor():
        return jsonify({"ok": False, "error": "Acesso não autorizado"}), 403

    professor_id = obter_professor_id(session["usuario"])
    turma_id = (request.args.get("turma_id") or "").strip()
    include_fotografados = (request.args.get("include_fotografados") or "").strip() == "1"

    if not turma_id:
        return jsonify({"ok": False, "error": "turma_id ausente"}), 400

    if _professor_tem_vinculos(professor_id) and not _turma_e_do_professor(professor_id, turma_id):
        return jsonify({"ok": False, "error": "Sem acesso à turma"}), 403

    conn = conectar_bd()
    cur = conn.cursor()

    if include_fotografados:
        cur.execute("""
            SELECT a.id, a.nome
            FROM alunos a
            WHERE a.turma_id = ?
            ORDER BY a.nome
        """, (turma_id,))
    else:
        cur.execute("""
            SELECT a.id, a.nome
            FROM alunos a
            LEFT JOIN carometro_fotos cf ON cf.aluno_id = a.id
            WHERE a.turma_id = ? AND cf.id IS NULL
            ORDER BY a.nome
        """, (turma_id,))

    alunos = [{"id": r["id"], "nome": r["nome"]} for r in cur.fetchall()]
    cur.close()
    conn.close()

    return jsonify({"ok": True, "alunos": alunos})


@bp_carometro.route("/professor/carometro/api/salvar", methods=["POST"])
def api_salvar_foto():
    if not _somente_professor():
        return jsonify({"ok": False, "error": "Acesso não autorizado"}), 403

    professor_id = obter_professor_id(session["usuario"])

    data = request.get_json(silent=True) or {}
    turma_id = str(data.get("turma_id") or "").strip()
    aluno_id = str(data.get("aluno_id") or "").strip()
    imagem_dataurl = data.get("imagem") or ""

    if not turma_id or not aluno_id or not imagem_dataurl:
        return jsonify({"ok": False, "error": "Dados incompletos"}), 400

    # segurança de acesso
    if _professor_tem_vinculos(professor_id) and not _turma_e_do_professor(professor_id, turma_id):
        return jsonify({"ok": False, "error": "Sem acesso à turma"}), 403

    if not _aluno_e_da_turma(aluno_id, turma_id):
        return jsonify({"ok": False, "error": "Aluno não pertence à turma"}), 400

    # BLOQUEIO ANTI-DUPLICIDADE:
    # se já tem foto cadastrada, não deixa salvar de novo (evita sobrescrever sem querer).
    if _foto_ja_existe(aluno_id):
        return jsonify({"ok": False,
                        "error": "Este aluno já possui foto cadastrada. Exclua a foto antes de cadastrar novamente."}), 409

    # espera dataURL: data:image/jpeg;base64,....
    if "base64," not in imagem_dataurl:
        return jsonify({"ok": False, "error": "Formato de imagem inválido"}), 400

    try:
        b64 = imagem_dataurl.split("base64,", 1)[1]
        blob = base64.b64decode(b64)
    except Exception:
        return jsonify({"ok": False, "error": "Falha ao decodificar imagem"}), 400

    # pasta e nome (1 foto por aluno)
    pasta = os.path.join("static", "carometro", f"turma_{turma_id}")
    _garantir_pasta(pasta)

    nome_arquivo = f"aluno_{aluno_id}.jpg"
    caminho = os.path.join(pasta, nome_arquivo)

    # se por algum motivo já existe arquivo, substitui (mas aqui o BD bloqueia duplicidade)
    _remover_arquivo_se_existir(caminho)

    try:
        with open(caminho, "wb") as f:
            f.write(blob)
    except Exception as e:
        return jsonify({"ok": False, "error": f"Falha ao salvar arquivo: {str(e)}"}), 500

    caminho_rel = f"carometro/turma_{turma_id}/{nome_arquivo}"  # relativo a /static/

    conn = conectar_bd()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO carometro_fotos (turma_id, aluno_id, professor_id, arquivo, atualizado_em)
        VALUES (?, ?, ?, ?, ?)
    """, (turma_id, aluno_id, professor_id, caminho_rel, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

    conn.commit()
    cur.close()
    conn.close()

    return jsonify({"ok": True, "arquivo": f"/static/{caminho_rel}"})


@bp_carometro.route("/professor/carometro/api/excluir/aluno", methods=["POST"])
def api_excluir_foto_aluno():
    """Exclui a foto (registro + arquivo) de UM aluno."""
    if not _somente_professor():
        return jsonify({"ok": False, "error": "Acesso não autorizado"}), 403

    professor_id = obter_professor_id(session["usuario"])

    data = request.get_json(silent=True) or {}
    turma_id = str(data.get("turma_id") or "").strip()
    aluno_id = str(data.get("aluno_id") or "").strip()

    if not turma_id or not aluno_id:
        return jsonify({"ok": False, "error": "Dados incompletos"}), 400

    if _professor_tem_vinculos(professor_id) and not _turma_e_do_professor(professor_id, turma_id):
        return jsonify({"ok": False, "error": "Sem acesso à turma"}), 403

    if not _aluno_e_da_turma(aluno_id, turma_id):
        return jsonify({"ok": False, "error": "Aluno não pertence à turma"}), 400

    conn = conectar_bd()
    cur = conn.cursor()

    cur.execute("SELECT arquivo FROM carometro_fotos WHERE aluno_id = ? AND turma_id = ?", (aluno_id, turma_id))
    row = cur.fetchone()
    if not row:
        cur.close()
        conn.close()
        return jsonify({"ok": False, "error": "Não há foto cadastrada para este aluno."}), 404

    arquivo_rel = row["arquivo"]
    cur.execute("DELETE FROM carometro_fotos WHERE aluno_id = ? AND turma_id = ?", (aluno_id, turma_id))
    conn.commit()
    cur.close()
    conn.close()

    _remover_arquivo_se_existir(os.path.join("static", arquivo_rel))

    return jsonify({"ok": True})
