"""Camada de normalização: transforma XMLs de padrões diferentes em uma estrutura fiscal única."""
from .base import documento_vazio
from .nfe import normalizar_nfe
from .nfse import normalizar_nfse
from .cte import normalizar_cte


def normalizar(root, deteccao: dict) -> dict:
    tipo = deteccao["tipo"]
    if tipo == "NFE":
        return normalizar_nfe(root, deteccao)
    if tipo == "NFSE":
        return normalizar_nfse(root, deteccao)
    if tipo == "CTE":
        return normalizar_cte(root, deteccao)
    doc = documento_vazio("DESCONHECIDO", deteccao.get("padrao", ""))
    doc["erros_leitura"].append("Tipo de documento fiscal não identificado (esperado NF-e ou NFS-e).")
    return doc
