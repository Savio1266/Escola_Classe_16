# termo.py
import sqlite3
from flask import Blueprint, render_template_string, request, session, redirect, url_for, flash

bp_termo = Blueprint("termo", __name__, template_folder="templates")

# Termos padrão (você pode editar o texto quando quiser)
TERMO_PADRAO = {
    "professor": """TERMO DE USO E CIÊNCIA (PROFESSOR)
Ao criar conta e utilizar o sistema “De Olho na Escola”, declaro ciência de que:
1) Meus acessos podem ser registrados (logs) para segurança e auditoria.
2) Devo manter sigilo de informações sensíveis de estudantes e famílias.
3) É proibido compartilhar usuário/senha e expor dados fora do ambiente escolar.
4) O uso é institucional e pode ser revogado em caso de uso indevido.
5) Declaro que as informações fornecidas são verdadeiras.

Ao marcar “Li e aceito”, concordo integralmente com este termo.""",

    "responsavel": """TERMO DE USO E CIÊNCIA (RESPONSÁVEL)
Ao criar conta e utilizar o sistema “De Olho na Escola”, declaro ciência de que:
1) O acesso é pessoal e intransferível; não devo compartilhar usuário/senha.
2) As informações exibidas são confidenciais e destinadas ao acompanhamento escolar.
3) A escola pode registrar acessos (logs) para segurança.
4) Posso ter acesso apenas aos dados vinculados ao(s) estudante(s) sob minha responsabilidade.
5) Informações falsas podem levar ao bloqueio do acesso.
6) O site não é local de resolução de situações delicadas e/ou sigilosas, para isso devo procurar a escola pessoalmente.
7) O site não subistitui as informações oficiais da secretaria de educação, é apenas um suporte complementar.

Ao marcar “Li e aceito”, concordo integralmente com este termo."""
}


def ensure_termo_tables(conectar_bd):
    """
    Cria tabelas de termos e aceites, e garante termo ativo para professor/responsavel.
    """
    conn = conectar_bd()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS termos_uso (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo TEXT NOT NULL,                 -- professor, responsavel, etc
            versao INTEGER NOT NULL,
            conteudo TEXT NOT NULL,
            ativo INTEGER NOT NULL DEFAULT 1,
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS aceites_termo (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            termo_id INTEGER NOT NULL,
            termo_tipo TEXT NOT NULL,
            termo_versao INTEGER NOT NULL,
            tipo_cadastro TEXT NOT NULL,        -- professor, responsavel, coordenador, etc
            login TEXT NOT NULL,
            ip TEXT,
            user_agent TEXT,
            aceito_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (termo_id) REFERENCES termos_uso(id)
        )
    """)

    # Seed: cria 1 termo ativo por tipo se ainda não existir nenhum
    for tipo, conteudo in TERMO_PADRAO.items():
        cur.execute("SELECT COUNT(*) AS n FROM termos_uso WHERE tipo = ?", (tipo,))
        n = cur.fetchone()["n"]
        if n == 0:
            cur.execute(
                "INSERT INTO termos_uso (tipo, versao, conteudo, ativo) VALUES (?, ?, ?, 1)",
                (tipo, 1, conteudo)
            )

    conn.commit()
    cur.close()
    conn.close()


def get_termo_ativo(conectar_bd, tipo: str):
    conn = conectar_bd()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("""
        SELECT id, tipo, versao, conteudo
        FROM termos_uso
        WHERE tipo = ? AND ativo = 1
        ORDER BY versao DESC, id DESC
        LIMIT 1
    """, (tipo,))
    termo = cur.fetchone()
    cur.close()
    conn.close()
    return termo


def registrar_aceite(conectar_bd, termo, tipo_cadastro: str, login: str):
    conn = conectar_bd()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO aceites_termo
        (termo_id, termo_tipo, termo_versao, tipo_cadastro, login, ip, user_agent)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        termo["id"],
        termo["tipo"],
        termo["versao"],
        tipo_cadastro,
        login,
        request.remote_addr,
        (request.headers.get("User-Agent") or "")[:240]
    ))
    conn.commit()
    cur.close()
    conn.close()


@bp_termo.route("/termo/<tipo>")
def ver_termo(tipo):
    """
    Página pública para leitura do termo (útil para link "ler termo")
    """
    termo = get_termo_ativo(bp_termo.conectar_bd, tipo) if hasattr(bp_termo, "conectar_bd") else None
    if termo is None:
        return "Termo não encontrado.", 404

    html = """
    <html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Termo de Uso</title>
    <style>
      body{font-family:Arial,sans-serif; max-width:900px; margin:24px auto; padding:0 16px; line-height:1.5; color:#0f172a}
      .box{border:1px solid #e5e7eb; border-radius:14px; padding:16px; background:#fff}
      .meta{color:#64748b; font-size:13px; margin-bottom:10px}
      pre{white-space:pre-wrap; font-family:Arial,sans-serif; margin:0}
      a{color:#2563eb; text-decoration:none; font-weight:700}
      a:hover{text-decoration:underline}
    </style></head>
    <body>
      <h2>Termo de Uso</h2>
      <div class="meta">Tipo: {{tipo}} • Versão: {{versao}}</div>
      <div class="box"><pre>{{conteudo}}</pre></div>
    </body></html>
    """
    return render_template_string(
        html,
        tipo=termo["tipo"],
        versao=termo["versao"],
        conteudo=termo["conteudo"]
    )


@bp_termo.route("/moderador/aceites-termo")
def moderador_aceites_termo():
    # Só moderador
    if "usuario" not in session or session.get("tipo") != "moderador":
        flash("Acesso não autorizado.")
        return redirect(url_for("login"))

    perfil = (request.args.get("perfil") or "todos").strip().lower()

    conn = bp_termo.conectar_bd()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # ✅ Perfis existentes para o filtro
    cur.execute("""
        SELECT DISTINCT tipo_cadastro
        FROM aceites_termo
        ORDER BY tipo_cadastro
    """)
    perfis = [r["tipo_cadastro"] for r in cur.fetchall()]

    # ✅ Termos disponíveis (para o moderador "ler termo do perfil")
    cur.execute("""
        SELECT tipo, versao, ativo
        FROM termos_uso
        WHERE ativo = 1
        ORDER BY tipo
    """)
    termos_ativos = cur.fetchall()

    where = ""
    params = []
    if perfil and perfil != "todos":
        where = "WHERE a.tipo_cadastro = ?"
        params.append(perfil)

    cur.execute(f"""
        SELECT
            a.aceito_em,
            a.login,
            a.tipo_cadastro,
            a.termo_tipo,
            a.termo_versao
        FROM aceites_termo a
        {where}
        ORDER BY a.aceito_em DESC
        LIMIT 500
    """, params)

    rows = cur.fetchall()
    cur.close()
    conn.close()

    html = """
    <html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Aceites de Termo</title>
    <style>
      body{font-family:Arial,sans-serif; background:#f6f8fc; margin:0; padding:18px; color:#0f172a}
      .card{max-width:1100px; margin:0 auto; background:#fff; border:1px solid #e5e7eb; border-radius:16px; padding:14px 14px 18px}
      h2{margin:6px 0 10px}
      table{width:100%; border-collapse:collapse; font-size:13px}
      th,td{border-bottom:1px solid #eef2f7; padding:10px 8px; text-align:left; vertical-align:top}
      th{color:#475569; font-weight:700; background:#fafafa}
      .muted{color:#64748b}
      .top{display:flex; gap:10px; align-items:flex-start; justify-content:space-between; flex-wrap:wrap}
      a.btn{display:inline-flex; gap:8px; align-items:center; padding:8px 12px; border-radius:10px; border:1px solid #e5e7eb; text-decoration:none; color:#0f172a; background:#fff}
      a.btn:hover{background:#eef2ff}
      .row{display:flex; gap:12px; flex-wrap:wrap; align-items:center}
      .box{border:1px solid #e5e7eb; border-radius:12px; padding:10px; background:#fff}
      select{padding:8px 10px; border-radius:10px; border:1px solid #e5e7eb; background:#fff}
      .term-links a{margin-right:10px; font-weight:700; color:#2563eb; text-decoration:none}
      .term-links a:hover{text-decoration:underline}
    </style></head>
    <body>
      <div class="card">
        <div class="top">
          <div>
            <h2>Aceites de Termo</h2>
            <div class="muted">Filtre por perfil e consulte o termo ativo antes de analisar os registros.</div>
          </div>
          <a class="btn" href="{{ url_for('dashboard_moderador') }}">Voltar ao painel</a>
        </div>

        <div class="row" style="margin:10px 0 12px;">
          <form method="GET" class="box">
            <div class="muted" style="font-size:12px; margin-bottom:6px;">Filtro por perfil</div>
            <select name="perfil" onchange="this.form.submit()">
              <option value="todos" {{ 'selected' if perfil=='todos' else '' }}>Todos</option>
              {% for p in perfis %}
                <option value="{{ p }}" {{ 'selected' if perfil==p else '' }}>{{ p }}</option>
              {% endfor %}
            </select>
          </form>

          <div class="box term-links">
            <div class="muted" style="font-size:12px; margin-bottom:6px;">Ler termo ativo por perfil</div>
            {% if termos_ativos %}
              {% for t in termos_ativos %}
                <a href="{{ url_for('termo.ver_termo', tipo=t['tipo']) }}" target="_blank" rel="noopener">
                  {{ t['tipo'] }} (v{{ t['versao'] }})
                </a>
              {% endfor %}
            {% else %}
              <span class="muted">Nenhum termo ativo cadastrado.</span>
            {% endif %}
          </div>
        </div>

        <table>
          <thead>
            <tr>
              <th>Data/Hora</th>
              <th>Login</th>
              <th>Tipo de cadastro</th>
              <th>Termo</th>
              <th>Versão</th>
            </tr>
          </thead>
          <tbody>
            {% for r in rows %}
              <tr>
                <td>{{ r['aceito_em'] }}</td>
                <td>{{ r['login'] }}</td>
                <td>{{ r['tipo_cadastro'] }}</td>
                <td>{{ r['termo_tipo'] }}</td>
                <td>{{ r['termo_versao'] }}</td>
              </tr>
            {% endfor %}
            {% if not rows %}
              <tr><td colspan="5" class="muted">Nenhum aceite encontrado para este filtro.</td></tr>
            {% endif %}
          </tbody>
        </table>
      </div>
    </body></html>
    """
    return render_template_string(
        html,
        rows=rows,
        perfis=perfis,
        perfil=perfil,
        termos_ativos=termos_ativos
    )

