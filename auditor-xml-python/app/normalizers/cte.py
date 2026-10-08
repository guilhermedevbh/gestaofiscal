"""CT-e: estrutura preparada para inclusão futura.

Hoje o documento é reconhecido e os dados básicos são lidos; as regras fiscais específicas
(ICMS do transporte, tomador do serviço, componentes da prestação) serão adicionadas depois.
"""
from ..parser import busca, texto, texto_busca, numero
from .base import documento_vazio, so_digitos_ou_alfa


def normalizar_cte(root, deteccao: dict) -> dict:
    doc = documento_vazio("CTE", deteccao.get("padrao", "CT-e"))
    inf = busca(root, "infCte")
    ide = busca(inf, "ide")
    emit = busca(inf, "emit")
    doc["modelo"] = texto(ide, "mod") or "57"
    doc["numero"] = texto(ide, "nCT")
    doc["serie"] = texto(ide, "serie")
    doc["data_emissao"] = texto(ide, "dhEmi")[:19]
    doc["natureza_operacao"] = texto(ide, "natOp")
    doc["chave"] = so_digitos_ou_alfa((inf.get("Id") if inf is not None else "") or "").replace("CTE", "")
    doc["emitente"]["documento"] = texto_busca(emit, "CNPJ", "CPF")
    doc["emitente"]["nome"] = texto_busca(emit, "xNome")
    doc["emitente"]["uf"] = texto_busca(emit, "UF")
    doc["valor_total"] = numero(texto_busca(inf, "vTPrest")) or 0.0
    doc["avisos_leitura"].append("CT-e reconhecido. As regras de auditoria específicas do CT-e ainda não estão ativas nesta versão.")
    return doc
