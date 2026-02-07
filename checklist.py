# checklist.py
from __future__ import annotations

import sqlite3
from datetime import datetime, date

from flask import Blueprint, render_template, request, redirect, url_for, flash, session

bp_checklist = Blueprint("checklist", __name__, template_folder="templates")

# app.py vai injetar conectar_bd aqui
conectar_bd = None

DEFAULT_ITENS = [
    "Registrou os conteúdos bimestrais",
    "Registrou as avaliações bimestrais",
    "Enviou a avaliação bimestral",
    "Fez a ficha do conselho de classe",
    "Informou a data e os instrumentos da recuperação processual",
    "Fez o RFA da sala de recursos",
    "Fez o RFA da sala do SuperAção",
    "Fez as adequações curriculares",
]


def _conn():
    global conectar_bd
    if conectar_bd:
        return conectar_bd()
    conn = sqlite3.connect("rfa.db", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _hoje_iso():
    return date.today().isoformat()


def ensure_checklist_tables():
    """
    NOVO MODELO:
    - checklist_modelo: um checklist por bimestre/ano (montado pela gestão)
    - checklist_itens_modelo: itens do checklist (com data opcional)
    - checklist_status: status por professor e por item do modelo
    """
    conn = _conn()
    cur = conn.cursor()
    cur.execute("PRAGMA foreign_keys = ON")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS checklist_modelo (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bimestre INTEGER NOT NULL,
            ano INTEGER NOT NULL,
            criado_por TEXT,
            criado_em TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            UNIQUE(bimestre, ano)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS checklist_itens_modelo (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            modelo_id INTEGER NOT NULL,
            titulo TEXT NOT NULL,
            data_limite TEXT,
            ordem INTEGER NOT NULL DEFAULT 0,
            criado_em TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (modelo_id) REFERENCES checklist_modelo(id) ON DELETE CASCADE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS checklist_status (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_modelo_id INTEGER NOT NULL,
            professor_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pendente', -- pendente | finalizado | atraso
            atualizado_em TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            UNIQUE(item_modelo_id, professor_id),
            FOREIGN KEY (item_modelo_id) REFERENCES checklist_itens_modelo(id) ON DELETE CASCADE,
            FOREIGN KEY (professor_id) REFERENCES professores(id) ON DELETE CASCADE
        )
    """)

    conn.commit()
    cur.close()
    conn.close()


def _require_moderador():
    if "usuario" not in session or session.get("tipo") != "moderador":
        flash("Acesso não autorizado.")
        return False
    return True


def _require_professor():
    if "usuario" not in session or session.get("tipo") != "professor":
        flash("Acesso não autorizado.")
        return False
    return True


def _parse_int(v, default=None):
    try:
        return int(v)
    except Exception:
        return default


def _obter_professor_id_por_login(login: str):
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT id FROM professores WHERE login = ?", (login,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row["id"] if row else None


def _listar_professores_aprovados():
    conn = _conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, login
        FROM professores
        WHERE status <> 'pendente'
        ORDER BY login COLLATE NOCASE
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def _get_modelo(bimestre: int, ano: int):
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM checklist_modelo WHERE bimestre=? AND ano=?", (bimestre, ano))
    m = cur.fetchone()
    cur.close()
    conn.close()
    return m


def _get_itens_modelo(modelo_id: int):
    conn = _conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, titulo, data_limite, ordem
        FROM checklist_itens_modelo
        WHERE modelo_id=?
        ORDER BY ordem ASC, id ASC
    """, (modelo_id,))
    itens = cur.fetchall()
    cur.close()
    conn.close()
    return itens


def _get_status_por_professor(item_ids, professor_id: int):
    if not item_ids:
        return {}
    conn = _conn()
    cur = conn.cursor()
    placeholders = ",".join(["?"] * len(item_ids))
    params = list(item_ids) + [professor_id]
    cur.execute(f"""
        SELECT item_modelo_id, status
        FROM checklist_status
        WHERE item_modelo_id IN ({placeholders}) AND professor_id=?
    """, tuple(params))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return {r["item_modelo_id"]: r["status"] for r in rows}


@bp_checklist.route("/checklist", methods=["GET"])
def checklist_moderador_home():
    """
    HOME do Moderador:
    - mostra se o checklist do bimestre existe
    - dá acesso a: montar (modelo) e marcar (execução)
    """
    if not _require_moderador():
        return redirect(url_for("login"))

    ano = _parse_int(request.args.get("ano"), datetime.now().year)
    bimestre = _parse_int(request.args.get("bimestre"), 1)

    if bimestre not in (1, 2, 3, 4):
        bimestre = 1

    modelo = _get_modelo(bimestre, ano)

    return render_template(
        "checklist_moderador_home.html",
        modelo=modelo,
        default_itens=DEFAULT_ITENS,
        filtro_bimestre=bimestre,
        filtro_ano=ano,
        hoje=_hoje_iso(),
    )


@bp_checklist.route("/checklist/montar", methods=["GET", "POST"])
def checklist_montar_modelo():
    """
    Montagem do checklist (MODELO) por bimestre/ano
    """
    if not _require_moderador():
        return redirect(url_for("login"))

    ano_padrao = datetime.now().year

    if request.method == "POST":
        bimestre = _parse_int(request.form.get("bimestre"))
        ano = _parse_int(request.form.get("ano"), ano_padrao)

        if not bimestre or bimestre not in (1, 2, 3, 4):
            flash("Selecione o bimestre corretamente.")
            return redirect(url_for("checklist.checklist_montar_modelo"))

        # Se já existe, vamos direcionar para edição do modelo (sem destruir)
        existente = _get_modelo(bimestre, ano)
        if existente:
            flash("Checklist do bimestre já existe. Abrindo para editar.")
            return redirect(url_for("checklist.checklist_editar_modelo", modelo_id=existente["id"]))

        itens_selecionados = request.form.getlist("itens_fixos")
        datas_fixos = {}
        for titulo in itens_selecionados:
            datas_fixos[titulo] = (request.form.get(f"data_fix_{titulo}") or "").strip() or None

        custom_titulos = request.form.getlist("custom_titulo[]")
        custom_datas = request.form.getlist("custom_data[]")

        personalizados = []
        for i, t in enumerate(custom_titulos):
            t = (t or "").strip()
            if not t:
                continue
            d = (custom_datas[i] or "").strip() or None if i < len(custom_datas) else None
            personalizados.append((t, d))

        if not itens_selecionados and not personalizados:
            flash("Selecione ao menos 1 item (fixo ou personalizado) para montar o checklist.")
            return redirect(url_for("checklist.checklist_montar_modelo"))

        conn = _conn()
        cur = conn.cursor()
        cur.execute("PRAGMA foreign_keys = ON")

        cur.execute("""
            INSERT INTO checklist_modelo (bimestre, ano, criado_por)
            VALUES (?, ?, ?)
        """, (bimestre, ano, session.get("usuario")))
        modelo_id = cur.lastrowid

        ordem = 1

        for titulo in itens_selecionados:
            cur.execute("""
                INSERT INTO checklist_itens_modelo (modelo_id, titulo, data_limite, ordem)
                VALUES (?, ?, ?, ?)
            """, (modelo_id, titulo, datas_fixos.get(titulo), ordem))
            ordem += 1

        for (titulo, data_limite) in personalizados:
            cur.execute("""
                INSERT INTO checklist_itens_modelo (modelo_id, titulo, data_limite, ordem)
                VALUES (?, ?, ?, ?)
            """, (modelo_id, titulo, data_limite, ordem))
            ordem += 1

        conn.commit()
        cur.close()
        conn.close()

        flash("Checklist do bimestre montado com sucesso.")
        return redirect(url_for("checklist.checklist_editar_modelo", modelo_id=modelo_id))

    return render_template(
        "checklist_modelo_form.html",
        modo="novo",
        default_itens=DEFAULT_ITENS,
        ano_padrao=ano_padrao,
        hoje=_hoje_iso(),
    )


@bp_checklist.route("/checklist/modelo/<int:modelo_id>", methods=["GET", "POST"])
def checklist_editar_modelo(modelo_id: int):
    """
    Editar o MODELO (datas / adicionar itens / remover itens).
    Importante: isso afeta o checklist que todos os professores veem nesse bimestre/ano.
    """
    if not _require_moderador():
        return redirect(url_for("login"))

    conn = _conn()
    cur = conn.cursor()

    cur.execute("SELECT * FROM checklist_modelo WHERE id=?", (modelo_id,))
    modelo = cur.fetchone()
    if not modelo:
        cur.close()
        conn.close()
        flash("Modelo não encontrado.")
        return redirect(url_for("checklist.checklist_moderador_home"))

    if request.method == "POST":
        # Atualizar datas/ordem
        item_ids = request.form.getlist("item_id[]")
        for idx, item_id in enumerate(item_ids, start=1):
            item_id_int = _parse_int(item_id)
            if not item_id_int:
                continue
            data_limite = (request.form.get(f"data_{item_id_int}") or "").strip() or None
            cur.execute("""
                UPDATE checklist_itens_modelo
                SET data_limite=?, ordem=?
                WHERE id=? AND modelo_id=?
            """, (data_limite, idx, item_id_int, modelo_id))

        # Adicionar novos personalizados
        custom_titulos = request.form.getlist("custom_titulo[]")
        custom_datas = request.form.getlist("custom_data[]")

        # pega a ordem atual máxima
        cur.execute("SELECT COALESCE(MAX(ordem), 0) AS mx FROM checklist_itens_modelo WHERE modelo_id=?", (modelo_id,))
        mx = cur.fetchone()["mx"] or 0
        ordem = mx + 1

        for i, t in enumerate(custom_titulos):
            t = (t or "").strip()
            if not t:
                continue
            d = (custom_datas[i] or "").strip() or None if i < len(custom_datas) else None
            cur.execute("""
                INSERT INTO checklist_itens_modelo (modelo_id, titulo, data_limite, ordem)
                VALUES (?, ?, ?, ?)
            """, (modelo_id, t, d, ordem))
            ordem += 1

        conn.commit()
        flash("Modelo atualizado.")
        return redirect(url_for("checklist.checklist_editar_modelo", modelo_id=modelo_id))

    # carregar itens
    cur.execute("""
        SELECT id, titulo, data_limite, ordem
        FROM checklist_itens_modelo
        WHERE modelo_id=?
        ORDER BY ordem ASC, id ASC
    """, (modelo_id,))
    itens = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        "checklist_modelo_form.html",
        modo="editar",
        modelo=modelo,
        itens=itens,
        hoje=_hoje_iso(),
    )


@bp_checklist.route("/checklist/modelo/excluir_item/<int:item_id>", methods=["POST"])
def checklist_modelo_excluir_item(item_id: int):
    if not _require_moderador():
        return redirect(url_for("login"))

    modelo_id = _parse_int(request.form.get("modelo_id"))
    if not modelo_id:
        flash("Ação inválida.")
        return redirect(url_for("checklist.checklist_moderador_home"))

    conn = _conn()
    cur = conn.cursor()
    cur.execute("PRAGMA foreign_keys = ON")
    cur.execute("DELETE FROM checklist_itens_modelo WHERE id=? AND modelo_id=?", (item_id, modelo_id))
    conn.commit()
    cur.close()
    conn.close()

    flash("Item removido do modelo.")
    return redirect(url_for("checklist.checklist_editar_modelo", modelo_id=modelo_id))


@bp_checklist.route("/checklist/marcar", methods=["GET", "POST"])
def checklist_marcar_professor():
    """
    Execução: Moderador marca o status item a item para 1 professor,
    sempre baseado no MODELO do bimestre/ano.
    """
    if not _require_moderador():
        return redirect(url_for("login"))

    professores = _listar_professores_aprovados()

    ano = _parse_int(request.args.get("ano"), datetime.now().year)
    bimestre = _parse_int(request.args.get("bimestre"), 1)
    professor_id = _parse_int(request.args.get("professor_id"), None)

    if bimestre not in (1, 2, 3, 4):
        bimestre = 1

    modelo = _get_modelo(bimestre, ano)
    itens_modelo = []
    status_map = {}

    if modelo:
        itens_modelo = _get_itens_modelo(modelo["id"])
        item_ids = [it["id"] for it in itens_modelo]
        if professor_id:
            status_map = _get_status_por_professor(item_ids, professor_id)

    if request.method == "POST":
        # POST chega com professor_id/bimestre/ano no formulário
        professor_id_post = _parse_int(request.form.get("professor_id"))
        bimestre_post = _parse_int(request.form.get("bimestre"))
        ano_post = _parse_int(request.form.get("ano"), datetime.now().year)

        if not professor_id_post or bimestre_post not in (1, 2, 3, 4):
            flash("Selecione professor e bimestre corretamente.")
            return redirect(url_for("checklist.checklist_marcar_professor"))

        modelo_post = _get_modelo(bimestre_post, ano_post)
        if not modelo_post:
            flash("Ainda não existe checklist montado para esse bimestre/ano. Monte primeiro.")
            return redirect(url_for("checklist.checklist_moderador_home", bimestre=bimestre_post, ano=ano_post))

        itens_do_modelo = _get_itens_modelo(modelo_post["id"])
        if not itens_do_modelo:
            flash("O modelo desse bimestre está sem itens.")
            return redirect(url_for("checklist.checklist_editar_modelo", modelo_id=modelo_post["id"]))

        conn = _conn()
        cur = conn.cursor()
        cur.execute("PRAGMA foreign_keys = ON")

        for it in itens_do_modelo:
            item_id = it["id"]
            status = (request.form.get(f"status_{item_id}") or "pendente").strip()
            if status not in ("pendente", "finalizado", "atraso"):
                status = "pendente"

            # upsert
            cur.execute("""
                INSERT INTO checklist_status (item_modelo_id, professor_id, status)
                VALUES (?, ?, ?)
                ON CONFLICT(item_modelo_id, professor_id)
                DO UPDATE SET status=excluded.status, atualizado_em=datetime('now','localtime')
            """, (item_id, professor_id_post, status))

        conn.commit()
        cur.close()
        conn.close()

        flash("Marcações salvas com sucesso.")
        return redirect(url_for("checklist.checklist_marcar_professor",
                                professor_id=professor_id_post, bimestre=bimestre_post, ano=ano_post))

    return render_template(
        "checklist_marcar_professor.html",
        professores=professores,
        modelo=modelo,
        itens_modelo=itens_modelo,
        status_map=status_map,
        filtro_professor_id=professor_id,
        filtro_bimestre=bimestre,
        filtro_ano=ano,
        hoje=_hoje_iso(),
    )


@bp_checklist.route("/checklist/professor", methods=["GET"])
def checklist_professor():
    """
    Professor vê o checklist do bimestre/ano (MODELO) + status dele.
    """
    if not _require_professor():
        return redirect(url_for("login"))

    professor_login = session.get("usuario")
    professor_id = _obter_professor_id_por_login(professor_login)
    if not professor_id:
        flash("Professor não encontrado.")
        return redirect(url_for("dashboard_professor"))

    ano = _parse_int(request.args.get("ano"), datetime.now().year)
    bimestre = _parse_int(request.args.get("bimestre"), 1)
    if bimestre not in (1, 2, 3, 4):
        bimestre = 1

    modelo = _get_modelo(bimestre, ano)
    itens_modelo = []
    status_map = {}

    if modelo:
        itens_modelo = _get_itens_modelo(modelo["id"])
        item_ids = [it["id"] for it in itens_modelo]
        status_map = _get_status_por_professor(item_ids, professor_id)

    return render_template(
        "checklist_professor.html",
        modelo=modelo,
        itens_modelo=itens_modelo,
        status_map=status_map,
        filtro_bimestre=bimestre,
        filtro_ano=ano,
        hoje=_hoje_iso(),
    )
