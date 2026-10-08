"""Banco de dados SQLite (consultas sempre parametrizadas).

Tabelas: documentos_fiscais, itens_documento, impostos_documento, alertas_fiscais, historico, usuarios, configuracoes.
O histórico fiscal é somente-inclusão: não há rota de exclusão; triggers impedem UPDATE/DELETE em historico.
"""
import hashlib
import json
import sqlite3
import threading
import zlib
from contextlib import contextmanager
from datetime import datetime, timezone

from . import config

_lock = threading.RLock()

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS usuarios (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  nome TEXT NOT NULL UNIQUE,
  perfil TEXT NOT NULL CHECK (perfil IN ('admin','analista','consulta')),
  token_hash TEXT NOT NULL UNIQUE,
  ativo INTEGER NOT NULL DEFAULT 1,
  criado_em TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS configuracoes (chave TEXT PRIMARY KEY, valor TEXT NOT NULL, atualizado_em TEXT, atualizado_por TEXT);
CREATE TABLE IF NOT EXISTS documentos_fiscais (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tipo_documento TEXT NOT NULL, padrao TEXT, modelo TEXT, numero TEXT, serie TEXT, chave_acesso TEXT,
  data_emissao TEXT, cnpj_emitente TEXT, razao_emitente TEXT, cnpj_destinatario TEXT, razao_destinatario TEXT,
  municipio TEXT, uf TEXT, valor_total REAL, valor_impostos REAL, valor_retencoes REAL, valor_liquido REAL,
  status TEXT NOT NULL, status_documento TEXT, qtd_alertas INTEGER DEFAULT 0,
  arquivo_original TEXT, arquivo_xml TEXT NOT NULL, hash_xml TEXT NOT NULL UNIQUE,
  dados_json TEXT NOT NULL, data_processamento TEXT NOT NULL, usuario_processamento TEXT NOT NULL,
  usuario_analise TEXT, data_analise TEXT, usuario_aprovacao TEXT, data_aprovacao TEXT
);
CREATE INDEX IF NOT EXISTS ix_doc_chave ON documentos_fiscais(chave_acesso);
CREATE INDEX IF NOT EXISTS ix_doc_num ON documentos_fiscais(numero, serie, cnpj_emitente);
CREATE INDEX IF NOT EXISTS ix_doc_emissao ON documentos_fiscais(data_emissao);
CREATE TABLE IF NOT EXISTS itens_documento (
  id INTEGER PRIMARY KEY AUTOINCREMENT, documento_id INTEGER NOT NULL REFERENCES documentos_fiscais(id),
  numero_item TEXT, codigo TEXT, descricao TEXT, ncm TEXT, cest TEXT, cfop TEXT, unidade TEXT,
  quantidade REAL, valor_unitario REAL, valor_total REAL, cst_csosn TEXT, origem TEXT, gtin TEXT
);
CREATE TABLE IF NOT EXISTS impostos_documento (
  id INTEGER PRIMARY KEY AUTOINCREMENT, documento_id INTEGER NOT NULL REFERENCES documentos_fiscais(id),
  imposto TEXT NOT NULL, item TEXT, cst_csosn TEXT, base_calculo REAL, aliquota REAL, valor REAL,
  valor_calculado REAL, diferenca REAL, status TEXT
);
CREATE INDEX IF NOT EXISTS ix_imp_doc ON impostos_documento(documento_id);
CREATE TABLE IF NOT EXISTS alertas_fiscais (
  id INTEGER PRIMARY KEY AUTOINCREMENT, documento_id INTEGER NOT NULL REFERENCES documentos_fiscais(id),
  tipo_alerta TEXT, imposto TEXT, gravidade TEXT, campo TEXT, item TEXT, valor_xml TEXT, valor_calculado TEXT, diferenca REAL,
  mensagem TEXT, motivo TEXT, recomendacao TEXT, explicacao_json TEXT, dados_json TEXT,
  status TEXT NOT NULL DEFAULT 'ABERTO', usuario_responsavel TEXT, data_criacao TEXT NOT NULL, data_resolucao TEXT, observacao_resolucao TEXT
);
CREATE INDEX IF NOT EXISTS ix_alerta_doc ON alertas_fiscais(documento_id);
CREATE TABLE IF NOT EXISTS historico (
  id INTEGER PRIMARY KEY AUTOINCREMENT, documento_id INTEGER, data_hora TEXT NOT NULL, usuario TEXT NOT NULL,
  acao TEXT NOT NULL, arquivo TEXT, hash_xml TEXT, resultado TEXT, detalhes TEXT, ip TEXT
);
CREATE TRIGGER IF NOT EXISTS historico_sem_update BEFORE UPDATE ON historico BEGIN SELECT RAISE(ABORT, 'Histórico fiscal não pode ser alterado'); END;
CREATE TRIGGER IF NOT EXISTS historico_sem_delete BEFORE DELETE ON historico BEGIN SELECT RAISE(ABORT, 'Histórico fiscal não pode ser excluído'); END;
-- Dados do site (cada módulo: correções, kanban, calendário, SPED...) — valor atual + todas as versões anteriores
CREATE TABLE IF NOT EXISTS dados_site (
  chave TEXT PRIMARY KEY, valor TEXT NOT NULL, versao INTEGER NOT NULL, hash TEXT NOT NULL,
  atualizado_em TEXT NOT NULL, atualizado_por TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dados_site_versoes (
  id INTEGER PRIMARY KEY AUTOINCREMENT, chave TEXT NOT NULL, versao INTEGER NOT NULL, valor_zlib BLOB, hash TEXT,
  tamanho INTEGER, removido INTEGER NOT NULL DEFAULT 0, data_hora TEXT NOT NULL, usuario TEXT NOT NULL, ip TEXT
);
CREATE INDEX IF NOT EXISTS ix_dsv_chave ON dados_site_versoes(chave, versao);
CREATE TRIGGER IF NOT EXISTS dsv_sem_update BEFORE UPDATE ON dados_site_versoes BEGIN SELECT RAISE(ABORT, 'Versões não podem ser alteradas'); END;
CREATE TRIGGER IF NOT EXISTS dsv_sem_delete BEFORE DELETE ON dados_site_versoes BEGIN SELECT RAISE(ABORT, 'Versões não podem ser excluídas'); END;
-- Registro de validações/ações feitas no site (somente inclusão)
CREATE TABLE IF NOT EXISTS registro_validacoes (
  id INTEGER PRIMARY KEY AUTOINCREMENT, data_hora TEXT NOT NULL, data_hora_cliente TEXT, usuario TEXT NOT NULL, usuario_site TEXT,
  modulo TEXT NOT NULL, acao TEXT NOT NULL, referencia TEXT, resultado TEXT, resumo TEXT, detalhes TEXT, ip TEXT
);
CREATE INDEX IF NOT EXISTS ix_rv_data ON registro_validacoes(data_hora);
CREATE TRIGGER IF NOT EXISTS rv_sem_update BEFORE UPDATE ON registro_validacoes BEGIN SELECT RAISE(ABORT, 'Registro de validações não pode ser alterado'); END;
CREATE TRIGGER IF NOT EXISTS rv_sem_delete BEFORE DELETE ON registro_validacoes BEGIN SELECT RAISE(ABORT, 'Registro de validações não pode ser excluído'); END;
"""


def agora() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


@contextmanager
def conexao():
    with _lock:
        con = sqlite3.connect(str(config.DB_PATH), timeout=30)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()


def inicializar() -> None:
    config.ensure_dirs()
    with conexao() as con:
        con.executescript(SCHEMA)
        for chave, valor in (("tolerancia_absoluta", str(config.DEFAULT_TOLERANCIA_ABSOLUTA)),
                             ("tolerancia_percentual", str(config.DEFAULT_TOLERANCIA_PERCENTUAL))):
            con.execute("INSERT OR IGNORE INTO configuracoes(chave, valor, atualizado_em, atualizado_por) VALUES (?,?,?,?)",
                        (chave, valor, agora(), "sistema"))


# ── usuários ──
def usuario_por_token_hash(token_hash: str):
    with conexao() as con:
        row = con.execute("SELECT id, nome, perfil, ativo FROM usuarios WHERE token_hash=?", (token_hash,)).fetchone()
        return dict(row) if row and row["ativo"] else None


def criar_usuario(nome: str, perfil: str, token_hash: str) -> int:
    if perfil not in config.PERFIS:
        raise ValueError("Perfil inválido.")
    with conexao() as con:
        cur = con.execute("INSERT INTO usuarios(nome, perfil, token_hash, ativo, criado_em) VALUES (?,?,?,1,?)",
                          (nome.strip()[:60], perfil, token_hash, agora()))
        return cur.lastrowid


def listar_usuarios():
    with conexao() as con:
        return [dict(r) for r in con.execute("SELECT id, nome, perfil, ativo, criado_em FROM usuarios ORDER BY nome")]


def desativar_usuario(nome: str) -> bool:
    with conexao() as con:
        return con.execute("UPDATE usuarios SET ativo=0 WHERE nome=?", (nome,)).rowcount > 0


def total_usuarios() -> int:
    with conexao() as con:
        return con.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0]


# ── configurações ──
def obter_config() -> dict:
    with conexao() as con:
        cfg = {r["chave"]: r["valor"] for r in con.execute("SELECT chave, valor FROM configuracoes")}
    return {"tol_abs": float(cfg.get("tolerancia_absoluta", config.DEFAULT_TOLERANCIA_ABSOLUTA)),
            "tol_pct": float(cfg.get("tolerancia_percentual", config.DEFAULT_TOLERANCIA_PERCENTUAL))}


def salvar_config(tol_abs: float, tol_pct: float, usuario: str) -> None:
    with conexao() as con:
        for chave, valor in (("tolerancia_absoluta", tol_abs), ("tolerancia_percentual", tol_pct)):
            con.execute("INSERT INTO configuracoes(chave, valor, atualizado_em, atualizado_por) VALUES (?,?,?,?) "
                        "ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor, atualizado_em=excluded.atualizado_em, atualizado_por=excluded.atualizado_por",
                        (chave, str(valor), agora(), usuario))


def obter_valor(chave: str, padrao: str = "") -> str:
    with conexao() as con:
        r = con.execute("SELECT valor FROM configuracoes WHERE chave=?", (chave,)).fetchone()
        return r["valor"] if r else padrao


def salvar_valor(chave: str, valor: str, usuario: str) -> None:
    with conexao() as con:
        con.execute("INSERT INTO configuracoes(chave, valor, atualizado_em, atualizado_por) VALUES (?,?,?,?) "
                    "ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor, atualizado_em=excluded.atualizado_em, atualizado_por=excluded.atualizado_por",
                    (chave, valor, agora(), usuario))


# ── histórico (somente inclusão) ──
def registrar_historico(usuario: str, acao: str, *, documento_id=None, arquivo=None, hash_xml=None, resultado=None, detalhes=None, ip=None) -> None:
    with conexao() as con:
        con.execute("INSERT INTO historico(documento_id, data_hora, usuario, acao, arquivo, hash_xml, resultado, detalhes, ip) VALUES (?,?,?,?,?,?,?,?,?)",
                    (documento_id, agora(), usuario, acao, arquivo, hash_xml, resultado,
                     json.dumps(detalhes, ensure_ascii=False) if isinstance(detalhes, (dict, list)) else detalhes, ip))


def listar_historico(limite: int = 500, documento_id=None):
    with conexao() as con:
        if documento_id:
            rows = con.execute("SELECT * FROM historico WHERE documento_id=? ORDER BY id DESC LIMIT ?", (documento_id, limite))
        else:
            rows = con.execute("SELECT * FROM historico ORDER BY id DESC LIMIT ?", (limite,))
        return [dict(r) for r in rows]


# ── duplicidade ──
def buscar_duplicado(hash_xml: str, chave: str, numero: str, serie: str, cnpj: str, tipo: str):
    with conexao() as con:
        row = con.execute("SELECT id, data_processamento, usuario_processamento, status, numero, serie, chave_acesso FROM documentos_fiscais WHERE hash_xml=?",
                          (hash_xml,)).fetchone()
        motivo = "mesmo arquivo (hash SHA-256)"
        if not row and chave:
            row = con.execute("SELECT id, data_processamento, usuario_processamento, status, numero, serie, chave_acesso FROM documentos_fiscais WHERE chave_acesso=?",
                              (chave,)).fetchone()
            motivo = "mesma chave de acesso"
        if not row and numero and cnpj:
            row = con.execute("SELECT id, data_processamento, usuario_processamento, status, numero, serie, chave_acesso FROM documentos_fiscais "
                              "WHERE tipo_documento=? AND numero=? AND COALESCE(serie,'')=? AND cnpj_emitente=?",
                              (tipo, numero, serie or "", cnpj)).fetchone()
            motivo = "mesmo número, série e CNPJ do emitente"
        return (dict(row), motivo) if row else (None, None)


# ── gravação do resultado ──
def salvar_documento(doc: dict, resultado: dict, *, arquivo_original: str, arquivo_xml: str, hash_xml: str, usuario: str) -> int:
    r = resultado["resumo"]
    with conexao() as con:
        cur = con.execute(
            """INSERT INTO documentos_fiscais(tipo_documento, padrao, modelo, numero, serie, chave_acesso, data_emissao, cnpj_emitente, razao_emitente,
               cnpj_destinatario, razao_destinatario, municipio, uf, valor_total, valor_impostos, valor_retencoes, valor_liquido, status, status_documento,
               qtd_alertas, arquivo_original, arquivo_xml, hash_xml, dados_json, data_processamento, usuario_processamento)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (doc["tipo"], doc.get("padrao"), doc.get("modelo"), doc.get("numero"), doc.get("serie"), doc.get("chave"), doc.get("data_emissao"),
             doc["emitente"].get("documento"), doc["emitente"].get("nome"), doc["destinatario"].get("documento"), doc["destinatario"].get("nome"),
             doc.get("municipio"), doc.get("uf"), r["valor_total"], r["valor_impostos"], r["valor_retencoes"], r["valor_liquido"], resultado["status"],
             doc.get("status_documento"), r["qtd_alertas"], arquivo_original, arquivo_xml, hash_xml,
             json.dumps({"documento": doc, "totais_impostos": resultado["totais_impostos"], "resumo": r}, ensure_ascii=False, default=str),
             agora(), usuario))
        doc_id = cur.lastrowid
        con.executemany(
            "INSERT INTO itens_documento(documento_id, numero_item, codigo, descricao, ncm, cest, cfop, unidade, quantidade, valor_unitario, valor_total, cst_csosn, origem, gtin) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(doc_id, it.get("numero_item"), it.get("codigo"), it.get("descricao"), it.get("ncm"), it.get("cest"), it.get("cfop"), it.get("unidade"),
              it.get("quantidade"), it.get("valor_unitario"), it.get("valor_total"), it.get("cst_csosn"), it.get("origem"), it.get("gtin"))
             for it in doc.get("itens") or []])
        con.executemany(
            "INSERT INTO impostos_documento(documento_id, imposto, item, cst_csosn, base_calculo, aliquota, valor, valor_calculado, diferenca, status) VALUES (?,?,?,?,?,?,?,?,?,?)",
            [(doc_id, l["imposto"], l.get("item"), l.get("cst_csosn"), l.get("base_calculo"), l.get("aliquota"), l.get("valor"),
              l.get("valor_calculado"), l.get("diferenca"), l.get("status")) for l in resultado["impostos"]])
        criado = agora()
        con.executemany(
            """INSERT INTO alertas_fiscais(documento_id, tipo_alerta, imposto, gravidade, campo, item, valor_xml, valor_calculado, diferenca, mensagem, motivo,
               recomendacao, explicacao_json, dados_json, status, data_criacao) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [(doc_id, a["tipo_alerta"], a["imposto"], a["gravidade"], a.get("campo"), a.get("item"),
              None if a.get("valor_xml") is None else str(a.get("valor_xml")), None if a.get("valor_calculado") is None else str(a.get("valor_calculado")),
              a.get("diferenca"), a["mensagem"], a.get("motivo"), a.get("recomendacao"),
              json.dumps(a.get("explicacao") or {}, ensure_ascii=False, default=str), json.dumps(a.get("dados_origem") or {}, ensure_ascii=False, default=str),
              "INFORMATIVO" if a["gravidade"] == "OK" else "ABERTO", criado) for a in resultado["alertas"]])
        return doc_id


# ── consultas ──
FILTROS_DOC = {
    "de": ("substr(d.data_emissao,1,10) >= ?", str), "ate": ("substr(d.data_emissao,1,10) <= ?", str),
    "cnpj": ("(d.cnpj_emitente LIKE ? OR d.cnpj_destinatario LIKE ?)", lambda x: ["%" + x + "%"] * 2),
    "fornecedor": ("d.razao_emitente LIKE ?", lambda x: "%" + x + "%"),
    "numero": ("d.numero = ?", str), "tipo": ("d.tipo_documento = ?", str), "status": ("d.status = ?", str),
    "imposto": ("EXISTS (SELECT 1 FROM impostos_documento i WHERE i.documento_id=d.id AND i.imposto=? AND COALESCE(i.valor,0) > 0)", str),
}


def _where(filtros: dict):
    clausulas, params = [], []
    for chave, (sql, conv) in FILTROS_DOC.items():
        valor = str(filtros.get(chave) or "").strip()[:100]
        if not valor:
            continue
        clausulas.append(sql)
        p = conv(valor)
        params.extend(p if isinstance(p, list) else [p])
    alerta = filtros.get("alerta")
    if alerta == "com":
        clausulas.append("d.qtd_alertas > 0")
    elif alerta == "sem":
        clausulas.append("d.qtd_alertas = 0")
    return ("WHERE " + " AND ".join(clausulas)) if clausulas else "", params


def listar_documentos(filtros: dict, limite: int = 500):
    where, params = _where(filtros)
    with conexao() as con:
        rows = con.execute(f"""SELECT d.id, d.tipo_documento, d.modelo, d.padrao, d.numero, d.serie, d.chave_acesso, d.data_emissao, d.cnpj_emitente,
                                d.razao_emitente, d.cnpj_destinatario, d.razao_destinatario, d.valor_total, d.valor_impostos, d.valor_retencoes,
                                d.valor_liquido, d.status, d.status_documento, d.qtd_alertas, d.arquivo_original, d.data_processamento,
                                d.usuario_processamento, d.usuario_analise, d.data_analise, d.usuario_aprovacao, d.data_aprovacao
                               FROM documentos_fiscais d {where} ORDER BY d.id DESC LIMIT ?""", (*params, min(int(limite), 2000)))
        return [dict(r) for r in rows]


def obter_documento(doc_id: int):
    with conexao() as con:
        d = con.execute("SELECT * FROM documentos_fiscais WHERE id=?", (doc_id,)).fetchone()
        if not d:
            return None
        doc = dict(d)
        doc["dados"] = json.loads(doc.pop("dados_json"))
        doc["impostos"] = [dict(r) for r in con.execute("SELECT * FROM impostos_documento WHERE documento_id=? ORDER BY id", (doc_id,))]
        alertas = []
        for r in con.execute("SELECT * FROM alertas_fiscais WHERE documento_id=? ORDER BY id", (doc_id,)):
            a = dict(r)
            a["explicacao"] = json.loads(a.pop("explicacao_json") or "{}")
            a["dados_origem"] = json.loads(a.pop("dados_json") or "{}")
            alertas.append(a)
        doc["alertas"] = alertas
        return doc


def caminho_xml(doc_id: int):
    with conexao() as con:
        row = con.execute("SELECT arquivo_xml, arquivo_original, chave_acesso, numero FROM documentos_fiscais WHERE id=?", (doc_id,)).fetchone()
        return dict(row) if row else None


def resumo_impostos(filtros: dict):
    where, params = _where(filtros)
    with conexao() as con:
        por_imposto = {r["imposto"]: r["total"] for r in con.execute(
            f"SELECT i.imposto, ROUND(SUM(COALESCE(i.valor,0)),2) AS total FROM impostos_documento i JOIN documentos_fiscais d ON d.id=i.documento_id {where} "
            f"GROUP BY i.imposto", params)}
        tot = con.execute(f"SELECT COUNT(*) AS docs, ROUND(SUM(valor_total),2) AS valor, ROUND(SUM(valor_impostos),2) AS impostos, "
                          f"ROUND(SUM(valor_retencoes),2) AS retencoes, ROUND(SUM(valor_liquido),2) AS liquido FROM documentos_fiscais d {where}", params).fetchone()
        status = {r["status"]: r["n"] for r in con.execute(f"SELECT status, COUNT(*) AS n FROM documentos_fiscais d {where} GROUP BY status", params)}
    return {"por_imposto": por_imposto, "totais": dict(tot), "por_status": status}


def listar_alertas(filtros: dict, limite: int = 1000):
    where, params = _where(filtros)
    extra, extra_p = [], []
    if filtros.get("gravidade"):
        extra.append("a.gravidade = ?")
        extra_p.append(str(filtros["gravidade"])[:20])
    if filtros.get("status_alerta"):
        extra.append("a.status = ?")
        extra_p.append(str(filtros["status_alerta"])[:20])
    if not filtros.get("incluir_ok"):
        extra.append("a.gravidade <> 'OK'")
    cond = where + ((" AND " if where else "WHERE ") + " AND ".join(extra) if extra else "")
    with conexao() as con:
        rows = con.execute(f"""SELECT a.id, a.documento_id, a.tipo_alerta, a.imposto, a.gravidade, a.campo, a.item, a.valor_xml, a.valor_calculado, a.diferenca,
                               a.mensagem, a.recomendacao, a.status, a.usuario_responsavel, a.data_criacao, a.data_resolucao,
                               d.tipo_documento, d.numero, d.serie, d.razao_emitente, d.cnpj_emitente
                               FROM alertas_fiscais a JOIN documentos_fiscais d ON d.id=a.documento_id {cond}
                               ORDER BY CASE a.gravidade WHEN 'CRITICO' THEN 0 WHEN 'DIVERGENCIA' THEN 1 WHEN 'ATENCAO' THEN 2 ELSE 3 END, a.id DESC LIMIT ?""",
                           (*params, *extra_p, min(int(limite), 5000)))
        return [dict(r) for r in rows]


def resolver_alerta(alerta_id: int, usuario: str, status: str, observacao: str):
    with conexao() as con:
        row = con.execute("SELECT documento_id, status FROM alertas_fiscais WHERE id=?", (alerta_id,)).fetchone()
        if not row:
            return None
        con.execute("UPDATE alertas_fiscais SET status=?, usuario_responsavel=?, data_resolucao=?, observacao_resolucao=? WHERE id=?",
                    (status, usuario, agora() if status != "ABERTO" else None, observacao[:1000], alerta_id))
        return {"documento_id": row["documento_id"], "status_anterior": row["status"]}


# ── dados do site (sincronização com o navegador) ──
def _hash(valor: str) -> str:
    return hashlib.sha256(valor.encode("utf-8")).hexdigest()


def dados_listar(com_valor: bool = False):
    campos = "chave, versao, hash, atualizado_em, atualizado_por, length(valor) AS tamanho" + (", valor" if com_valor else "")
    with conexao() as con:
        return [dict(r) for r in con.execute(f"SELECT {campos} FROM dados_site ORDER BY chave")]


def _gravar_versao(con, chave, versao, valor, usuario, ip, removido=0):
    con.execute("INSERT INTO dados_site_versoes(chave, versao, valor_zlib, hash, tamanho, removido, data_hora, usuario, ip) VALUES (?,?,?,?,?,?,?,?,?)",
                (chave, versao, None if valor is None else zlib.compress(valor.encode("utf-8"), 6), None if valor is None else _hash(valor),
                 0 if valor is None else len(valor), removido, agora(), usuario, ip))


def dados_salvar(chave: str, valor: str, versao_base: int, usuario: str, ip: str):
    """Grava com controle de concorrência otimista. Retorna ('ok', registro) ou ('conflito', registro_atual)."""
    h = _hash(valor)
    with conexao() as con:
        atual = con.execute("SELECT chave, valor, versao, hash, atualizado_em, atualizado_por FROM dados_site WHERE chave=?", (chave,)).fetchone()
        if atual and atual["hash"] == h:
            return "ok", {"chave": chave, "versao": atual["versao"], "inalterado": True}
        versao_atual = atual["versao"] if atual else 0
        if versao_base != versao_atual:
            return "conflito", dict(atual) if atual else {"chave": chave, "versao": 0, "valor": None}
        nova = versao_atual + 1
        con.execute("INSERT INTO dados_site(chave, valor, versao, hash, atualizado_em, atualizado_por) VALUES (?,?,?,?,?,?) "
                    "ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor, versao=excluded.versao, hash=excluded.hash, "
                    "atualizado_em=excluded.atualizado_em, atualizado_por=excluded.atualizado_por",
                    (chave, valor, nova, h, agora(), usuario))
        _gravar_versao(con, chave, nova, valor, usuario, ip)
        return "ok", {"chave": chave, "versao": nova}


def dados_remover(chave: str, versao_base: int, usuario: str, ip: str):
    with conexao() as con:
        atual = con.execute("SELECT versao FROM dados_site WHERE chave=?", (chave,)).fetchone()
        if not atual:
            return "ok", {"chave": chave, "versao": 0}
        if versao_base != atual["versao"]:
            return "conflito", {"chave": chave, "versao": atual["versao"]}
        con.execute("DELETE FROM dados_site WHERE chave=?", (chave,))
        _gravar_versao(con, chave, atual["versao"] + 1, None, usuario, ip, removido=1)
        return "ok", {"chave": chave, "versao": 0}


def dados_versoes(chave: str, limite: int = 200):
    with conexao() as con:
        return [dict(r) for r in con.execute("SELECT id, chave, versao, hash, tamanho, removido, data_hora, usuario FROM dados_site_versoes "
                                             "WHERE chave=? ORDER BY id DESC LIMIT ?", (chave, min(int(limite), 1000)))]


def dados_versao(versao_id: int):
    with conexao() as con:
        r = con.execute("SELECT id, chave, versao, valor_zlib, removido, data_hora, usuario FROM dados_site_versoes WHERE id=?", (versao_id,)).fetchone()
        if not r:
            return None
        d = dict(r)
        blob = d.pop("valor_zlib")
        d["valor"] = zlib.decompress(blob).decode("utf-8") if blob else None
        return d


# ── registro de validações (somente inclusão) ──
def registrar_validacao(usuario: str, ip: str, item: dict) -> int:
    with conexao() as con:
        cur = con.execute("INSERT INTO registro_validacoes(data_hora, data_hora_cliente, usuario, usuario_site, modulo, acao, referencia, resultado, resumo, detalhes, ip) "
                          "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                          (agora(), item.get("quando"), usuario, item.get("usuario_site"), item["modulo"], item["acao"], item.get("referencia"),
                           item.get("resultado"), item.get("resumo"), item.get("detalhes"), ip))
        return cur.lastrowid


def listar_validacoes(filtros: dict, limite: int = 2000):
    cond, params = [], []
    for campo, sql in (("modulo", "modulo = ?"), ("usuario", "(usuario = ? OR usuario_site = ?)"), ("de", "substr(data_hora,1,10) >= ?"), ("ate", "substr(data_hora,1,10) <= ?")):
        v = str(filtros.get(campo) or "").strip()[:100]
        if v:
            cond.append(sql)
            params.extend([v, v] if campo == "usuario" else [v])
    q = str(filtros.get("q") or "").strip()[:100]
    if q:
        cond.append("(resumo LIKE ? OR referencia LIKE ? OR acao LIKE ?)")
        params.extend(["%" + q + "%"] * 3)
    where = ("WHERE " + " AND ".join(cond)) if cond else ""
    with conexao() as con:
        return [dict(r) for r in con.execute(f"SELECT * FROM registro_validacoes {where} ORDER BY id DESC LIMIT ?", (*params, min(int(limite), 5000)))]


def atualizar_analise(doc_id: int, usuario: str, acao: str):
    campo = {"analisar": ("usuario_analise", "data_analise"), "aprovar": ("usuario_aprovacao", "data_aprovacao")}[acao]
    with conexao() as con:
        n = con.execute(f"UPDATE documentos_fiscais SET {campo[0]}=?, {campo[1]}=? WHERE id=?", (usuario, agora(), doc_id)).rowcount
        return n > 0
