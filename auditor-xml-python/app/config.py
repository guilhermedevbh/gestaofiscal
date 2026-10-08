"""Configuração do serviço (variáveis de ambiente com padrões seguros)."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("XML_AUDITOR_DATA", str(BASE_DIR / "data")))
XML_DIR = DATA_DIR / "xml"          # arquivos armazenados FORA de qualquer pasta pública, renomeados pelo hash
DB_PATH = DATA_DIR / "auditoria_xml.db"

# Na internet (Render, Railway, Azure…) a plataforma informa a porta em PORT e o serviço escuta em todas as interfaces
PORT = int(os.environ.get("PORT") or os.environ.get("XML_AUDITOR_PORT", "8765"))
HOST = os.environ.get("XML_AUDITOR_HOST", "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1")
PUBLICO = HOST not in ("127.0.0.1", "localhost", "::1")

# Site entregue pelo próprio serviço (um único endereço https://… para a equipe e pessoas de fora)
SITE_HTML = Path(os.environ.get("XML_AUDITOR_SITE", str(BASE_DIR.parent / "Gestao_Fiscal_2026_CRPD_v10.html")))

# Atrás do proxy HTTPS da hospedagem, o IP real do usuário vem em X-Forwarded-For (usado no rate limit e no histórico)
CONFIAR_PROXY = os.environ.get("XML_AUDITOR_CONFIAR_PROXY", "1" if os.environ.get("PORT") else "0") == "1"

# Primeiro administrador definido pela hospedagem (somente o HASH SHA-256 do token; o token nunca fica no servidor)
ADMIN_TOKEN_HASH = os.environ.get("XML_AUDITOR_ADMIN_TOKEN_HASH", "").strip().lower()
ADMIN_NOME = os.environ.get("XML_AUDITOR_ADMIN_NOME", "Administrador").strip() or "Administrador"

# Tokens fixos compartilhados (ex.: equipe e consulta), definidos na hospedagem — somente o HASH SHA-256 de cada token.
# Formato: "Nome|perfil|hash;Nome 2|perfil|hash"   (perfil: admin | analista | consulta)
USUARIOS_FIXOS = [
    tuple(p.strip() for p in item.split("|"))
    for item in os.environ.get("XML_AUDITOR_USUARIOS_FIXOS", "").split(";")
    if item.count("|") == 2
]

MAX_XML_BYTES = int(os.environ.get("XML_AUDITOR_MAX_BYTES", str(5 * 1024 * 1024)))   # 5 MB por XML
MAX_JSON_BYTES = 64 * 1024
PLANILHA_CORRECOES = os.environ.get("XML_AUDITOR_PLANILHA", "")  # caminho local da planilha do SharePoint (sincronizada pelo OneDrive)
MAX_DADOS_BYTES = int(os.environ.get("XML_AUDITOR_MAX_DADOS", str(20 * 1024 * 1024)))  # 20 MB por módulo do site

# Origens autorizadas a chamar a API pelo navegador ("null" = site aberto como arquivo local)
ALLOWED_ORIGINS = [
    item.strip()
    for item in os.environ.get(
        "XML_AUDITOR_ORIGINS", "null,http://127.0.0.1:3333,http://localhost:3333"
    ).split(",")
    if item.strip()
]

# Tolerâncias padrão da conferência matemática (o administrador altera pela API/interface)
DEFAULT_TOLERANCIA_ABSOLUTA = 0.05     # R$
DEFAULT_TOLERANCIA_PERCENTUAL = 0.50   # % sobre o valor esperado

PERFIS = {
    "admin": "Administrador — tudo, inclusive aprovar, configurar tolerância e gerenciar usuários",
    "analista": "Analista fiscal — envia XML, analisa e resolve alertas",
    "consulta": "Consulta — somente leitura",
}


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    XML_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(DATA_DIR, 0o700)
        os.chmod(XML_DIR, 0o700)
    except OSError:
        pass
