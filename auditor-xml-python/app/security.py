"""Segurança do upload e do parsing de XML.

- Somente .xml, com MIME de XML, tamanho limitado e conteúdo textual.
- Nome do arquivo sanitizado (sem path traversal); armazenamento interno pelo hash SHA-256.
- Parsing sem DTD/entidades: qualquer <!DOCTYPE> ou <!ENTITY> é recusado ANTES do parser
  (bloqueia XXE e "billion laughs"); se a biblioteca defusedxml estiver instalada ela também é usada.
- Rate limit em memória por chave (usuário/IP).
"""
import hashlib
import re
import secrets
import threading
import time
from collections import defaultdict, deque
from xml.etree import ElementTree as ET

from . import config

try:  # opcional: camada extra de proteção se instalada (pip install defusedxml)
    from defusedxml import ElementTree as DefusedET  # type: ignore
except Exception:  # pragma: no cover - ausência é suportada
    DefusedET = None


class UploadInvalido(ValueError):
    """Arquivo recusado antes do processamento (extensão, MIME, tamanho, conteúdo)."""


class XMLInseguro(UploadInvalido):
    """XML com DTD/entidades — recusado por segurança."""


class XMLInvalido(UploadInvalido):
    """XML malformado, corrompido ou incompleto."""


MIME_PERMITIDOS = {"application/xml", "text/xml"}
_DTD = re.compile(rb"<!\s*(?:DOCTYPE|ENTITY|ATTLIST|ELEMENT|NOTATION)", re.IGNORECASE)
_PI_PERIGOSAS = re.compile(rb"<\?xml-stylesheet", re.IGNORECASE)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def gerar_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def sanitizar_nome(nome: str) -> str:
    """Remove diretórios e caracteres perigosos do nome original (usado só para exibição/auditoria)."""
    base = re.split(r"[\\/]", str(nome or ""))[-1]
    base = re.sub(r"[^A-Za-z0-9._ -]", "_", base).strip(" .")
    base = re.sub(r"\.{2,}", ".", base)
    if not base:
        base = "documento.xml"
    return base[:120]


def validar_upload(nome: str, content_type: str, data: bytes) -> str:
    """Valida extensão, MIME, tamanho e conteúdo. Retorna o nome sanitizado."""
    nome_limpo = sanitizar_nome(nome)
    if not nome_limpo.lower().endswith(".xml") or nome_limpo.lower().count(".xml") != 1:
        raise UploadInvalido("Somente arquivos .xml são aceitos (extensão dupla não é permitida).")
    mime = str(content_type or "").split(";")[0].strip().lower()
    if mime not in MIME_PERMITIDOS:
        raise UploadInvalido("Tipo de conteúdo inválido. Envie o arquivo como application/xml ou text/xml.")
    if not data:
        raise UploadInvalido("Arquivo vazio.")
    if len(data) > config.MAX_XML_BYTES:
        raise UploadInvalido(f"Arquivo maior que o limite de {config.MAX_XML_BYTES // (1024 * 1024)} MB.")
    if data[:2] in (b"\xff\xfe", b"\xfe\xff") or b"\x00" in data[:4096]:
        raise UploadInvalido("Codificação não suportada (UTF-16/binário). Os XMLs fiscais devem estar em UTF-8.")
    if data[:4] == b"PK\x03\x04" or data[:5] == b"%PDF-":
        raise UploadInvalido("O conteúdo não é XML (arquivo compactado ou PDF).")
    if not data.lstrip(b"\xef\xbb\xbf \t\r\n").startswith(b"<"):
        raise UploadInvalido("O conteúdo não é um XML válido.")
    if _DTD.search(data):
        raise XMLInseguro("XML recusado por segurança: contém DTD/entidades (<!DOCTYPE/<!ENTITY>). Documentos fiscais não usam DTD.")
    if _PI_PERIGOSAS.search(data):
        raise XMLInseguro("XML recusado por segurança: contém instrução de folha de estilo.")
    return nome_limpo


def parse_xml_seguro(data: bytes) -> ET.Element:
    """Faz o parsing sem resolver entidades externas. Chame somente após validar_upload."""
    if _DTD.search(data):
        raise XMLInseguro("XML com DTD/entidades não é aceito.")
    try:
        if DefusedET is not None:
            return DefusedET.fromstring(data, forbid_dtd=True, forbid_entities=True, forbid_external=True)
        parser = ET.XMLParser()
        parser.feed(data)
        return parser.close()
    except XMLInseguro:
        raise
    except ET.ParseError as exc:
        linha, coluna = getattr(exc, "position", (None, None))
        onde = f" (linha {linha}, coluna {coluna})" if linha else ""
        raise XMLInvalido(f"XML inválido, corrompido ou incompleto{onde}.") from exc
    except Exception as exc:  # defusedxml lança exceções próprias
        raise XMLInseguro(f"XML recusado na análise de segurança: {type(exc).__name__}.") from exc


class RateLimiter:
    """Janela deslizante em memória, segura para threads."""

    def __init__(self) -> None:
        self._hits = defaultdict(deque)
        self._lock = threading.Lock()

    def permitir(self, chave: str, limite: int, janela_s: float) -> bool:
        agora = time.monotonic()
        with self._lock:
            fila = self._hits[chave]
            while fila and agora - fila[0] > janela_s:
                fila.popleft()
            if len(fila) >= limite:
                return False
            fila.append(agora)
            if len(self._hits) > 10000:  # limpeza preventiva
                for k in [k for k, v in self._hits.items() if not v]:
                    del self._hits[k]
            return True


rate_limiter = RateLimiter()
