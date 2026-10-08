"""API HTTP (somente biblioteca padrão do Python).

Segurança: autenticação por token (Bearer) com perfil, autorização por rota, rate limit, CORS restrito,
cabeçalhos de segurança, limites de tamanho, erros sem stack trace e auditoria de cada ação.
"""
import csv
import io
import json
import re
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import __version__, config, database, planilha
from .engine.alertas import ROTULO_STATUS
from .security import gerar_token, hash_token, rate_limiter
from .service import processar_upload

PERM = {"ler": {"admin", "analista", "consulta"}, "enviar": {"admin", "analista"}, "analisar": {"admin", "analista"}, "admin": {"admin"}}
STATUS_ALERTA = {"ABERTO", "EM_ANALISE", "RESOLVIDO", "IGNORADO"}
CHAVE_DADOS = re.compile(r"[A-Za-z0-9_.:-]{1,80}")
_cache_planilha = {"chave": None, "dados": None}


def _ler_planilha_cache(caminho: str) -> dict:
    """Relê a planilha só quando o arquivo muda (data/tamanho)."""
    st = Path(caminho).stat() if Path(caminho).is_file() else None
    chave = (caminho, st.st_mtime_ns, st.st_size) if st else None
    if chave and _cache_planilha["chave"] == chave:
        return _cache_planilha["dados"]
    dados = planilha.ler_xlsx(caminho)
    _cache_planilha.update(chave=chave, dados=dados)
    return dados


class ErroHTTP(Exception):
    def __init__(self, status: int, mensagem: str):
        super().__init__(mensagem)
        self.status = status
        self.mensagem = mensagem


class Handler(BaseHTTPRequestHandler):
    server_version = "AuditorXML"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    # ── utilidades ──
    def log_message(self, fmt, *args):  # log enxuto, sem corpo da requisição nem tokens
        sys.stderr.write("[%s] %s %s\n" % (self.log_date_time_string(), self.client_address[0], fmt % args))

    def _ip(self):
        if config.CONFIAR_PROXY:
            xff = (self.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
            if re.fullmatch(r"[0-9a-fA-F:.]{3,45}", xff or ""):
                return xff
        return self.client_address[0]

    def _origem_permitida(self, origem: str) -> bool:
        if origem in config.ALLOWED_ORIGINS:
            return True
        # o próprio site entregue por este serviço (mesmo endereço)
        host = (self.headers.get("X-Forwarded-Host") or self.headers.get("Host") or "").strip().lower()
        return bool(host) and urlparse(origem).netloc.lower() == host

    def _cabecalhos_seguranca(self, pagina=False):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        if pagina:
            # o site usa scripts próprios embutidos e bibliotecas do cdnjs (com SRI); consulta APIs públicas de CNPJ/CEP
            self.send_header("Content-Security-Policy", "frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'")
            self.send_header("Cache-Control", "no-cache")
        else:
            self.send_header("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
            self.send_header("Cache-Control", "no-store")
        if (self.headers.get("X-Forwarded-Proto") or "").lower() == "https":
            self.send_header("Strict-Transport-Security", "max-age=31536000")
        origem = self.headers.get("Origin")
        if origem and self._origem_permitida(origem):
            self.send_header("Access-Control-Allow-Origin", origem)
            self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-File-Name")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Expose-Headers", "Content-Disposition")
            self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Vary", "Origin")

    def _responder(self, status: int, corpo, tipo="application/json; charset=utf-8", extras=None, pagina=False):
        dados = corpo if isinstance(corpo, (bytes, bytearray)) else json.dumps(corpo, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self._cabecalhos_seguranca(pagina)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(dados)))
        for k, v in (extras or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(dados)

    def _corpo(self, limite: int) -> bytes:
        if self.headers.get("Transfer-Encoding"):
            raise ErroHTTP(411, "Envie o corpo com Content-Length (transferência em partes não suportada).")
        try:
            tamanho = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ErroHTTP(400, "Content-Length inválido.")
        if tamanho > limite:
            raise ErroHTTP(413, f"Conteúdo maior que o limite de {limite // 1024} KB.")
        return self.rfile.read(tamanho) if tamanho > 0 else b""

    def _json(self, limite: int = 0) -> dict:
        tipo = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if tipo != "application/json":
            raise ErroHTTP(415, "Envie JSON (Content-Type: application/json).")
        try:
            valor = json.loads(self._corpo(limite or config.MAX_JSON_BYTES).decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            raise ErroHTTP(400, "JSON inválido.")
        if not isinstance(valor, dict):
            raise ErroHTTP(400, "JSON deve ser um objeto.")
        return valor

    def _usuario(self, permissao: str) -> dict:
        ip = self._ip()
        auth = self.headers.get("Authorization") or ""
        m = re.match(r"^Bearer\s+([A-Za-z0-9_\-]{20,200})$", auth)
        usuario = database.usuario_por_token_hash(hash_token(m.group(1))) if m else None
        if not usuario:
            if not rate_limiter.permitir(f"auth-falha|{ip}", 10, 900):
                database.registrar_historico("anônimo", "ACESSO_BLOQUEADO", resultado="BLOQUEADO", detalhes={"rota": self.path.split("?")[0]}, ip=ip)
                raise ErroHTTP(429, "Muitas tentativas com token inválido. Aguarde 15 minutos.")
            raise ErroHTTP(401, "Token de acesso inválido ou ausente.")
        if usuario["perfil"] not in PERM[permissao]:
            database.registrar_historico(usuario["nome"], "ACESSO_NEGADO", resultado="NEGADO", detalhes={"rota": self.path.split("?")[0], "permissao": permissao}, ip=ip)
            raise ErroHTTP(403, "Seu perfil não tem permissão para esta operação.")
        if not rate_limiter.permitir(f"usuario|{usuario['nome']}", 600, 60):
            raise ErroHTTP(429, "Muitas requisições. Aguarde um minuto.")
        return usuario

    def _filtros(self, query: dict) -> dict:
        permitidos = ("de", "ate", "cnpj", "fornecedor", "numero", "tipo", "status", "imposto", "alerta", "gravidade", "status_alerta", "incluir_ok", "documento_id")
        return {k: query[k][0][:100] for k in permitidos if k in query}

    # ── roteamento ──
    def do_OPTIONS(self):
        self.send_response(204)
        self._cabecalhos_seguranca()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        self._executar("GET")

    def do_POST(self):
        self._executar("POST")

    def do_PUT(self):
        self._responder(405, {"erro": "Método não permitido."})

    do_DELETE = do_PATCH = do_PUT

    def _executar(self, metodo: str):
        try:
            if not rate_limiter.permitir(f"ip|{self._ip()}", 1200, 60):
                raise ErroHTTP(429, "Muitas requisições. Aguarde um minuto.")
            url = urlparse(self.path)
            rota, query = url.path.rstrip("/") or "/", parse_qs(url.query, keep_blank_values=False)
            self._rotear(metodo, rota, query)
        except ErroHTTP as exc:
            self._responder(exc.status, {"erro": exc.mensagem})
        except Exception:  # nunca expor stack trace ao cliente
            traceback.print_exc(file=sys.stderr)
            self._responder(500, {"erro": "Falha interna ao processar a solicitação."})

    def _rotear(self, metodo, rota, query):
        if metodo == "GET" and rota == "/health":
            return self._responder(200, {"status": "ok", "servico": "auditoria-xml", "versao": __version__})
        if metodo == "GET" and rota in ("/", "/index.html"):
            # o próprio site (a página não contém dados: tudo vem da API, mediante token de cada usuário)
            if not config.SITE_HTML.is_file():
                raise ErroHTTP(404, "Página do site não encontrada no servidor.")
            return self._responder(200, config.SITE_HTML.read_bytes(), "text/html; charset=utf-8", pagina=True)
        if not rota.startswith("/api/"):
            raise ErroHTTP(404, "Rota não encontrada.")

        if metodo == "GET" and rota == "/api/me":
            u = self._usuario("ler")
            return self._responder(200, {"nome": u["nome"], "perfil": u["perfil"], "descricao": config.PERFIS[u["perfil"]], "tolerancia": database.obter_config()})

        if metodo == "POST" and rota == "/api/xml/upload":
            u = self._usuario("enviar")
            if not rate_limiter.permitir(f"upload|{u['nome']}", 300, 60):
                raise ErroHTTP(429, "Limite de envios por minuto atingido.")
            nome = unquote(self.headers.get("X-File-Name") or "")[:255]
            corpo = self._corpo(config.MAX_XML_BYTES)
            resultado = processar_upload(nome, self.headers.get("Content-Type") or "", corpo, u, self._ip())
            status = 201 if resultado.get("ok") else (409 if resultado.get("duplicado") else 422)
            return self._responder(status, resultado)

        m = re.match(r"^/api/documentos/(\d{1,10})(?:/(xml|analisar|aprovar))?$", rota)
        if m:
            doc_id, acao = int(m.group(1)), m.group(2)
            if metodo == "GET" and not acao:
                self._usuario("ler")
                doc = database.obter_documento(doc_id)
                if not doc:
                    raise ErroHTTP(404, "Documento não encontrado.")
                doc["status_rotulo"] = ROTULO_STATUS.get(doc["status"], doc["status"])
                doc["historico"] = database.listar_historico(200, doc_id)
                doc.pop("arquivo_xml", None)
                return self._responder(200, doc)
            if metodo == "GET" and acao == "xml":
                u = self._usuario("ler")
                info = database.caminho_xml(doc_id)
                if not info:
                    raise ErroHTTP(404, "Documento não encontrado.")
                if not re.fullmatch(r"[a-f0-9]{64}\.xml", info["arquivo_xml"]):
                    raise ErroHTTP(500, "Referência de arquivo inválida.")
                caminho = (config.XML_DIR / info["arquivo_xml"]).resolve()
                if caminho.parent != config.XML_DIR.resolve() or not caminho.exists():
                    raise ErroHTTP(404, "Arquivo XML não disponível.")
                database.registrar_historico(u["nome"], "DOWNLOAD_XML", documento_id=doc_id, ip=self._ip())
                nome = re.sub(r"[^A-Za-z0-9._-]", "_", (info["chave_acesso"] or info["numero"] or f"documento_{doc_id}"))[:80] + ".xml"
                return self._responder(200, caminho.read_bytes(), "application/xml; charset=utf-8",
                                       {"Content-Disposition": f'attachment; filename="{nome}"'})
            if metodo == "POST" and acao in ("analisar", "aprovar"):
                u = self._usuario("admin" if acao == "aprovar" else "analisar")
                corpo = self._json()
                obs = str(corpo.get("observacao") or "")[:1000]
                if not database.atualizar_analise(doc_id, u["nome"], acao):
                    raise ErroHTTP(404, "Documento não encontrado.")
                database.registrar_historico(u["nome"], "DOCUMENTO_ANALISADO" if acao == "analisar" else "DOCUMENTO_APROVADO",
                                             documento_id=doc_id, resultado="OK", detalhes={"observacao": obs}, ip=self._ip())
                return self._responder(200, {"ok": True})

        if metodo == "GET" and rota == "/api/documentos":
            self._usuario("ler")
            docs = database.listar_documentos(self._filtros(query))
            for d in docs:
                d["status_rotulo"] = ROTULO_STATUS.get(d["status"], d["status"])
            return self._responder(200, docs)

        if metodo == "GET" and rota == "/api/alertas":
            self._usuario("ler")
            return self._responder(200, database.listar_alertas(self._filtros(query)))

        m = re.match(r"^/api/alertas/(\d{1,10})/resolver$", rota)
        if metodo == "POST" and m:
            u = self._usuario("analisar")
            corpo = self._json()
            status = str(corpo.get("status") or "").upper()
            if status not in STATUS_ALERTA:
                raise ErroHTTP(400, "Status inválido. Use ABERTO, EM_ANALISE, RESOLVIDO ou IGNORADO.")
            obs = str(corpo.get("observacao") or "").strip()[:1000]
            if status in ("RESOLVIDO", "IGNORADO") and len(obs) < 5:
                raise ErroHTTP(400, "Informe uma justificativa (mínimo 5 caracteres) para resolver ou ignorar o alerta.")
            res = database.resolver_alerta(int(m.group(1)), u["nome"], status, obs)
            if not res:
                raise ErroHTTP(404, "Alerta não encontrado.")
            database.registrar_historico(u["nome"], "ALERTA_ATUALIZADO", documento_id=res["documento_id"], resultado=status,
                                         detalhes={"alerta_id": int(m.group(1)), "de": res["status_anterior"], "para": status, "observacao": obs}, ip=self._ip())
            return self._responder(200, {"ok": True})

        if metodo == "GET" and rota == "/api/impostos/resumo":
            self._usuario("ler")
            return self._responder(200, database.resumo_impostos(self._filtros(query)))

        if metodo == "GET" and rota == "/api/historico":
            self._usuario("ler")
            doc_id = query.get("documento_id", [""])[0]
            return self._responder(200, database.listar_historico(1000, int(doc_id) if doc_id.isdigit() else None))

        if rota == "/api/config":
            if metodo == "GET":
                self._usuario("ler")
                return self._responder(200, database.obter_config())
            u = self._usuario("admin")
            corpo = self._json()
            try:
                tol_abs, tol_pct = float(corpo.get("tol_abs")), float(corpo.get("tol_pct"))
            except (TypeError, ValueError):
                raise ErroHTTP(400, "Informe tol_abs (R$) e tol_pct (%) numéricos.")
            if not (0 <= tol_abs <= 1000 and 0 <= tol_pct <= 50):
                raise ErroHTTP(400, "Tolerância fora do intervalo permitido (R$ 0–1.000 e 0–50%).")
            anterior = database.obter_config()
            database.salvar_config(tol_abs, tol_pct, u["nome"])
            database.registrar_historico(u["nome"], "TOLERANCIA_ALTERADA", resultado="OK", detalhes={"de": anterior, "para": {"tol_abs": tol_abs, "tol_pct": tol_pct}}, ip=self._ip())
            return self._responder(200, database.obter_config())

        if rota == "/api/usuarios":
            u = self._usuario("admin")
            if metodo == "GET":
                return self._responder(200, database.listar_usuarios())
            corpo = self._json()
            nome, perfil = str(corpo.get("nome") or "").strip(), str(corpo.get("perfil") or "")
            if not re.fullmatch(r"[\wÀ-ÿ .'-]{2,60}", nome) or perfil not in config.PERFIS:
                raise ErroHTTP(400, "Nome (2–60 caracteres) e perfil (admin, analista ou consulta) são obrigatórios.")
            token = gerar_token()
            try:
                database.criar_usuario(nome, perfil, hash_token(token))
            except Exception:
                raise ErroHTTP(409, "Já existe um usuário com esse nome.")
            database.registrar_historico(u["nome"], "USUARIO_CRIADO", resultado="OK", detalhes={"usuario": nome, "perfil": perfil}, ip=self._ip())
            return self._responder(201, {"nome": nome, "perfil": perfil, "token": token, "aviso": "Guarde o token agora: ele não será exibido novamente."})

        # ── dados do site: tudo o que o site grava no navegador também fica no banco (com versões) ──
        if metodo == "GET" and rota == "/api/dados":
            self._usuario("ler")
            return self._responder(200, database.dados_listar(query.get("valores", ["0"])[0] == "1"))

        if metodo == "POST" and rota in ("/api/dados/salvar", "/api/dados/remover"):
            u = self._usuario("analisar")
            corpo = self._json(config.MAX_DADOS_BYTES)
            chave = str(corpo.get("chave") or "")
            if not CHAVE_DADOS.fullmatch(chave):
                raise ErroHTTP(400, "Chave inválida.")
            try:
                base = int(corpo.get("versao_base") or 0)
            except (TypeError, ValueError):
                raise ErroHTTP(400, "versao_base inválida.")
            if rota.endswith("salvar"):
                valor = corpo.get("valor")
                if not isinstance(valor, str):
                    raise ErroHTTP(400, "O valor deve ser texto.")
                res, reg = database.dados_salvar(chave, valor, base, u["nome"], self._ip())
            else:
                res, reg = database.dados_remover(chave, base, u["nome"], self._ip())
            return self._responder(409 if res == "conflito" else 200, {"resultado": res, "registro": reg})

        if metodo == "GET" and rota == "/api/dados/versoes":
            self._usuario("ler")
            chave = query.get("chave", [""])[0]
            if not CHAVE_DADOS.fullmatch(chave):
                raise ErroHTTP(400, "Chave inválida.")
            return self._responder(200, database.dados_versoes(chave))

        m = re.match(r"^/api/dados/versao/(\d{1,12})$", rota)
        if metodo == "GET" and m:
            self._usuario("ler")
            v = database.dados_versao(int(m.group(1)))
            if not v:
                raise ErroHTTP(404, "Versão não encontrada.")
            return self._responder(200, v)

        if rota == "/api/validacoes":
            if metodo == "GET":
                self._usuario("ler")
                f = {k: query[k][0] for k in ("modulo", "usuario", "de", "ate", "q") if k in query}
                return self._responder(200, database.listar_validacoes(f))
            u = self._usuario("analisar")
            corpo = self._json(config.MAX_JSON_BYTES * 8)
            itens = corpo.get("itens") if isinstance(corpo.get("itens"), list) else [corpo]
            if len(itens) > 500:
                raise ErroHTTP(413, "Envie no máximo 500 registros por vez.")
            ids = []
            for it in itens:
                if not isinstance(it, dict) or not str(it.get("modulo") or "").strip() or not str(it.get("acao") or "").strip():
                    continue
                limpo = {k: (None if it.get(k) is None else str(it.get(k))[:lim]) for k, lim in
                         (("modulo", 80), ("acao", 120), ("referencia", 200), ("resultado", 60), ("resumo", 2000), ("usuario_site", 80), ("quando", 40))}
                det = it.get("detalhes")
                limpo["detalhes"] = None if det is None else json.dumps(det, ensure_ascii=False, default=str)[:20000]
                ids.append(database.registrar_validacao(u["nome"], self._ip(), limpo))
            return self._responder(201, {"ok": True, "registrados": len(ids)})

        # ── planilha de correções do SharePoint (arquivo sincronizado pelo OneDrive) ──
        if rota == "/api/planilha/config":
            if metodo == "GET":
                self._usuario("ler")
                cam = database.obter_valor("planilha_correcoes", config.PLANILHA_CORRECOES)
                return self._responder(200, {"caminho": cam, "existe": bool(cam) and Path(cam).is_file()})
            u = self._usuario("admin")
            cam = str(self._json().get("caminho") or "").strip().strip('"')[:500]
            if cam and (not cam.lower().endswith((".xlsx", ".xlsm")) or not Path(cam).is_file()):
                raise ErroHTTP(400, "Informe o caminho completo de um arquivo .xlsx existente neste computador.")
            database.salvar_valor("planilha_correcoes", cam, u["nome"])
            database.registrar_historico(u["nome"], "PLANILHA_CONFIGURADA", resultado="OK", detalhes={"caminho": cam}, ip=self._ip())
            return self._responder(200, {"caminho": cam, "existe": bool(cam)})

        if metodo == "GET" and rota == "/api/planilha/localizar":
            self._usuario("admin")
            if config.PUBLICO:
                raise ErroHTTP(403, "Indisponível no servidor da internet: envie a planilha pelo botão Importar planilha.")
            return self._responder(200, {"arquivos": planilha.localizar()})

        if metodo == "GET" and rota == "/api/planilha/correcoes":
            self._usuario("ler")
            cam = database.obter_valor("planilha_correcoes", config.PLANILHA_CORRECOES)
            if not cam:
                return self._responder(200, {"configurada": False})
            try:
                dados = _ler_planilha_cache(cam)
            except planilha.PlanilhaErro as exc:
                return self._responder(200, {"configurada": True, "erro": str(exc)})
            if query.get("desde", [""])[0] == dados["hash"]:
                return self._responder(200, {"configurada": True, "inalterado": True, "hash": dados["hash"]})
            return self._responder(200, dict(dados, configurada=True))

        if metodo == "GET" and rota == "/api/export.csv":
            u = self._usuario("ler")
            docs = database.listar_documentos(self._filtros(query), 2000)
            buf = io.StringIO()
            w = csv.writer(buf, delimiter=";")
            cols = ["id", "tipo_documento", "numero", "serie", "chave_acesso", "data_emissao", "cnpj_emitente", "razao_emitente", "cnpj_destinatario",
                    "razao_destinatario", "valor_total", "valor_impostos", "valor_retencoes", "valor_liquido", "status", "qtd_alertas", "data_processamento", "usuario_processamento"]
            w.writerow(cols)
            for d in docs:
                # neutraliza fórmulas (CSV injection) em textos vindos do XML
                w.writerow([("'" + str(d.get(c))) if isinstance(d.get(c), str) and str(d.get(c))[:1] in "=+-@\t\r" else d.get(c) for c in cols])
            database.registrar_historico(u["nome"], "EXPORTACAO_CSV", resultado="OK", detalhes={"registros": len(docs)}, ip=self._ip())
            return self._responder(200, ("﻿" + buf.getvalue()).encode("utf-8"), "text/csv; charset=utf-8",
                                   {"Content-Disposition": 'attachment; filename="auditoria-xml.csv"'})

        raise ErroHTTP(404, "Rota não encontrada.")


def _provisionar_admin():
    """Ativa um token de administrador entregue como arquivo data/provisionar_admin.json (contém só o HASH do token).
    Usado quando não é possível rodar 'gerenciar.py criar-usuario'. O arquivo é apagado depois de usado."""
    arq = config.DATA_DIR / "provisionar_admin.json"
    if not arq.exists():
        return
    try:
        dados = json.loads(arq.read_text(encoding="utf-8"))
        h = str(dados.get("token_hash") or "").lower()
        if not re.fullmatch(r"[a-f0-9]{64}", h):
            raise ValueError("hash inválido")
        if database.usuario_por_token_hash(h):
            print("Token de administrador já estava ativo.")
        else:
            base = re.sub(r"[^\wÀ-ÿ .'-]", "", str(dados.get("nome") or "Administrador"))[:50] or "Administrador"
            nomes = {u["nome"] for u in database.listar_usuarios()}
            nome, n = base, 2
            while nome in nomes:
                nome, n = f"{base} {n}", n + 1
            database.criar_usuario(nome, "admin", h)
            database.registrar_historico("console", "USUARIO_CRIADO", resultado="OK", detalhes={"usuario": nome, "perfil": "admin", "origem": "provisionar_admin.json"})
            print(f"Novo token de administrador ativado para o usuário '{nome}'.")
    except Exception as exc:
        print(f"Não foi possível ativar data/provisionar_admin.json: {exc}", file=sys.stderr)
    finally:
        try:
            arq.unlink()
        except OSError:
            pass


def _usuario_da_hospedagem(nome_base: str, perfil: str, h: str, origem: str):
    """Cria (uma vez) um usuário cujo token é definido na hospedagem; o servidor só conhece o HASH SHA-256."""
    h = (h or "").strip().lower()
    if not h:
        return
    if perfil not in config.PERFIS or not re.fullmatch(r"[a-f0-9]{64}", h):
        print(f"{origem}: perfil ou hash inválido para '{nome_base}' (perfil: admin|analista|consulta; hash: SHA-256 hex).", file=sys.stderr)
        return
    if database.usuario_por_token_hash(h):
        return
    nomes = {u["nome"] for u in database.listar_usuarios()}
    base = re.sub(r"[^\wÀ-ÿ .'-]", "", nome_base)[:50] or "Usuário"
    nome, n = base, 2
    while nome in nomes:
        nome, n = f"{base} {n}", n + 1
    database.criar_usuario(nome, perfil, h)
    database.registrar_historico("sistema", "USUARIO_CRIADO", resultado="OK", detalhes={"usuario": nome, "perfil": perfil, "origem": origem})
    print(f"Usuário '{nome}' ({perfil}) criado a partir da configuração da hospedagem.")


def _admin_da_hospedagem():
    """Primeiro administrador (XML_AUDITOR_ADMIN_TOKEN_HASH) e tokens fixos da equipe (XML_AUDITOR_USUARIOS_FIXOS)."""
    _usuario_da_hospedagem(config.ADMIN_NOME, "admin", config.ADMIN_TOKEN_HASH, "XML_AUDITOR_ADMIN_TOKEN_HASH")
    for nome, perfil, h in config.USUARIOS_FIXOS:
        _usuario_da_hospedagem(nome, perfil, h, "XML_AUDITOR_USUARIOS_FIXOS")


def iniciar():
    database.inicializar()
    _provisionar_admin()
    _admin_da_hospedagem()
    if database.total_usuarios() == 0:
        if not config.PUBLICO:
            print("Nenhum usuário cadastrado. Execute primeiro:  python gerenciar.py inicializar", file=sys.stderr)
            sys.exit(1)
        # Na hospedagem não derruba o serviço (evita o ciclo de reinícios): o site e o /health continuam no ar,
        # a API recusa tudo (401) até o administrador ser configurado pela variável de ambiente.
        print("ATENÇÃO: nenhum administrador configurado. Defina a variável XML_AUDITOR_ADMIN_TOKEN_HASH "
              "(SHA-256 do token) na hospedagem e reinicie o serviço. Até lá, o banco recusa todos os acessos.", file=sys.stderr)
    if config.PUBLICO:
        print(f"Modo internet: escutando em {config.HOST}:{config.PORT}. Use somente atrás de HTTPS (a hospedagem fornece).", file=sys.stderr)
    servidor = ThreadingHTTPServer((config.HOST, config.PORT), Handler)
    servidor.daemon_threads = True
    print(f"Auditoria Fiscal de XML ativa em http://{config.HOST}:{config.PORT}  (Ctrl+C para encerrar)")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        servidor.server_close()


if __name__ == "__main__":
    iniciar()
