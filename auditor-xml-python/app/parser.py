"""Parser: utilitários de leitura independentes de namespace e identificação do tipo de documento."""
from typing import Iterable, List, Optional
from xml.etree import ElementTree as ET


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def filhos(el: Optional[ET.Element], nome: str) -> List[ET.Element]:
    if el is None:
        return []
    return [c for c in list(el) if local(c.tag) == nome]


def filho(el: Optional[ET.Element], *caminho: str) -> Optional[ET.Element]:
    """Segue um caminho de filhos diretos (nomes locais)."""
    atual = el
    for nome in caminho:
        if atual is None:
            return None
        atual = next((c for c in list(atual) if local(c.tag) == nome), None)
    return atual


def busca(el: Optional[ET.Element], *nomes: str) -> Optional[ET.Element]:
    """Primeiro descendente (qualquer profundidade) cujo nome local esteja em 'nomes', na ordem de preferência."""
    if el is None:
        return None
    for nome in nomes:
        for item in el.iter():
            if local(item.tag) == nome:
                return item
    return None


def busca_todos(el: Optional[ET.Element], nome: str) -> List[ET.Element]:
    if el is None:
        return []
    return [item for item in el.iter() if local(item.tag) == nome]


def texto(el: Optional[ET.Element], *caminho: str, default: str = "") -> str:
    alvo = filho(el, *caminho) if caminho else el
    if alvo is None or alvo.text is None:
        return default
    return alvo.text.strip()


def texto_busca(el: Optional[ET.Element], *nomes: str, default: str = "") -> str:
    alvo = busca(el, *nomes)
    return alvo.text.strip() if alvo is not None and alvo.text else default


def numero(valor) -> Optional[float]:
    """Converte '1234.56' ou '1.234,56' em float; vazio → None."""
    if valor is None:
        return None
    s = str(valor).strip()
    if not s:
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def nomes_presentes(root: ET.Element, limite: int = 4000) -> set:
    nomes = set()
    for i, item in enumerate(root.iter()):
        nomes.add(local(item.tag))
        if i >= limite:
            break
    return nomes


TIPOS = ("NFE", "NFSE", "CTE", "DESCONHECIDO")


def detectar_tipo(root: ET.Element) -> dict:
    """Identifica o documento pelo conteúdo (não pelo nome do arquivo)."""
    nomes = nomes_presentes(root)
    if "infNFe" in nomes:
        modelo = texto_busca(root, "mod") or "55"
        return {"tipo": "NFE", "modelo": modelo, "padrao": "NF-e (leiaute nacional SEFAZ)"}
    if "infCte" in nomes:
        return {"tipo": "CTE", "modelo": texto_busca(root, "mod") or "57", "padrao": "CT-e"}
    if "infNFSe" in nomes or "DPS" in nomes:
        return {"tipo": "NFSE", "modelo": "NFS-e", "padrao": "NFS-e Padrão Nacional (ADN)"}
    if {"RazaoSocialPrestador", "ValorServicos"} & nomes and ("ChaveNFe" in nomes or "NumeroNFe" in nomes):
        return {"tipo": "NFSE", "modelo": "NFS-e", "padrao": "NFS-e São Paulo (Nota do Milhão)"}
    if {"InfNfse", "CompNfse", "tcInfNfse"} & nomes or ("Nfse" in nomes and "Servico" in nomes):
        return {"tipo": "NFSE", "modelo": "NFS-e", "padrao": "NFS-e ABRASF (municipal)"}
    if {"ItemListaServico", "ValorServicos", "Discriminacao"} & nomes:
        return {"tipo": "NFSE", "modelo": "NFS-e", "padrao": "NFS-e (padrão municipal genérico)"}
    return {"tipo": "DESCONHECIDO", "modelo": "", "padrao": "Não identificado"}


def primeiro(valores: Iterable) -> str:
    for v in valores:
        if v not in (None, ""):
            return v
    return ""
