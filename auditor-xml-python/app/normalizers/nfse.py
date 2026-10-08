"""Normalizador de NFS-e — camada que converte padrões diferentes em uma estrutura fiscal única.

Padrões cobertos:
- NFS-e Padrão Nacional (ADN): NFSe/infNFSe + DPS/infDPS
- ABRASF 1.0 / 2.x (CompNfse/Nfse/InfNfse, Servico/Valores, PrestadorServico, TomadorServico) — maioria dos municípios
- São Paulo (NFe com RazaoSocialPrestador/ValorServicos/AliquotaServicos)
- Genérico: busca por sinônimos de tags quando o município usa variações

Cada campo é procurado por uma lista de sinônimos, em ordem de preferência.
"""
import re

from ..parser import busca, filho, numero, texto_busca
from .base import documento_vazio, so_digitos_ou_alfa

SIN = {
    "numero": ("nNFSe", "Numero", "NumeroNFe", "NumeroNfse", "NumeroNota"),
    "codigo_verificacao": ("CodigoVerificacao", "CodigoVerificacaoNFe", "cVerif"),
    "emissao": ("dhEmi", "DataEmissao", "DataEmissaoNFe", "DataEmissaoNfse", "dhProc"),
    "competencia": ("dCompet", "Competencia", "DataFatoGerador"),
    "valor_servicos": ("vServ", "ValorServicos", "ValorServico", "ValorTotalServicos"),
    "deducoes": ("vDR", "ValorDeducoes"),
    "desconto_incondicionado": ("vDescIncond", "DescontoIncondicionado"),
    "desconto_condicionado": ("vDescCond", "DescontoCondicionado"),
    "base": ("vBC", "BaseCalculo", "ValorBaseCalculo"),
    "aliquota": ("pAliqAplic", "pAliq", "Aliquota", "AliquotaServicos", "AliquotaISS"),
    "valor_iss": ("vISSQN", "ValorIss", "ValorISS"),
    "valor_iss_retido": ("vISSRet", "ValorIssRetido", "ValorISSRetido"),
    "iss_retido_flag": ("tpRetISSQN", "IssRetido", "ISSRetido"),
    "valor_liquido": ("vLiq", "ValorLiquidoNfse", "ValorLiquido", "ValorLiquidoNFe"),
    "item_lc116": ("ItemListaServico", "cListServ", "CodigoServico"),
    "codigo_nacional": ("cTribNac",),
    "codigo_municipal": ("cTribMun", "CodigoTributacaoMunicipio", "CodigoTributacao"),
    "cnae": ("CodigoCnae", "CNAE", "cCNAE", "CodigoAtividade"),
    "nbs": ("cNBS", "CodigoNbs"),
    "discriminacao": ("xDescServ", "Discriminacao", "DescricaoServico"),
    "municipio_incidencia": ("cLocIncid", "MunicipioIncidencia", "CodigoMunicipioIncidencia", "CodigoMunicipio"),
    "municipio_incidencia_nome": ("xLocIncid",),
    "municipio_prestacao": ("cLocPrestacao", "MunicipioPrestacaoServico", "CodigoMunicipioPrestacao", "cMunPrestacao"),
    "natureza": ("NaturezaOperacao", "ExigibilidadeISS", "tribISSQN", "TributacaoNFe", "TipoTributacao"),
    "optante_simples": ("OptanteSimplesNacional", "opSimpNac", "RegimeEspecialTributacao"),
    "status": ("cStat", "StatusNFe", "Status", "SituacaoNfse"),
}
RETENCOES = {
    "irrf": ("vRetIRRF", "ValorIr", "ValorIR", "ValorIRRF"),
    "inss": ("vRetCP", "ValorInss", "ValorINSS"),
    "csll": ("vRetCSLL", "ValorCsll", "ValorCSLL"),
    "pis": ("ValorPis", "ValorPIS", "vRetPIS"),
    "cofins": ("ValorCofins", "ValorCOFINS", "vRetCOFINS"),
}
CONTAINERS_PRESTADOR = ("emit", "PrestadorServico", "Prestador", "prest", "DadosPrestador", "IdentificacaoPrestador")
CONTAINERS_TOMADOR = ("toma", "TomadorServico", "Tomador", "DadosTomador", "IdentificacaoTomador")


def _t(el, chave):
    return texto_busca(el, *SIN[chave])


def _parte(container) -> dict:
    if container is None:
        return {"documento": "", "nome": "", "ie": "", "im": "", "municipio": "", "codigo_municipio": "", "uf": "", "crt": ""}
    return {
        "documento": so_digitos_ou_alfa(texto_busca(container, "CNPJ", "Cnpj", "CPF", "Cpf", "NIF")),
        "nome": texto_busca(container, "xNome", "RazaoSocial", "Nome", "NomeFantasia", "xFant"),
        "ie": texto_busca(container, "IE", "InscricaoEstadual"),
        "im": texto_busca(container, "IM", "InscricaoMunicipal"),
        "municipio": texto_busca(container, "xMun", "xLocEmi", "Cidade", "NomeMunicipio"),
        "codigo_municipio": texto_busca(container, "cMun", "CodigoMunicipio", "Municipio"),
        "uf": texto_busca(container, "UF", "Uf", "Estado"),
        "crt": "",
    }


def _parte_sp(root, sufixo: str) -> dict:
    cont = busca(root, "CPFCNPJ" + sufixo)
    end = busca(root, "Endereco" + sufixo)
    return {
        "documento": so_digitos_ou_alfa(texto_busca(cont, "CNPJ", "CPF")),
        "nome": texto_busca(root, "RazaoSocial" + sufixo),
        "ie": "", "im": texto_busca(root, "InscricaoMunicipal" + sufixo) or texto_busca(root, "InscricaoPrestador" if sufixo == "Prestador" else "InscricaoTomador"),
        "municipio": texto_busca(end, "Cidade"), "codigo_municipio": texto_busca(end, "Cidade"),
        "uf": texto_busca(end, "UF"), "crt": "",
    }


def _aliquota_percentual(valor):
    """ABRASF 1.0 grava 0.05 (fração); demais padrões gravam 5.00 (percentual)."""
    if valor is None:
        return None
    return round(valor * 100, 4) if 0 < valor < 1 else valor


def _flag_retido(flag: str, padrao: str):
    f = str(flag or "").strip().lower()
    if not f:
        return None
    if "nacional" in padrao.lower():
        return f in ("2", "3")          # tpRetISSQN: 1 não retido, 2 retido pelo tomador, 3 retido pelo intermediário
    return f in ("1", "true", "s", "sim")   # ABRASF: 1 = sim, 2 = não; SP: true/false


def _item_lc116(codigo_nacional: str, item: str) -> str:
    if item:
        dig = re.sub(r"\D", "", item)
        if len(dig) >= 3:
            dig = dig.zfill(4)
            return f"{dig[:2]}.{dig[2:4]}"
        return item
    dig = re.sub(r"\D", "", codigo_nacional or "")
    if len(dig) >= 4:              # cTribNac "010701" → item 01.07, subitem 01
        return f"{dig[:2]}.{dig[2:4]}"
    return ""


def normalizar_nfse(root, deteccao: dict) -> dict:
    padrao = deteccao.get("padrao", "")
    doc = documento_vazio("NFSE", padrao)
    doc["modelo"] = "NFS-e"
    nacional = "Nacional" in padrao
    sp = "São Paulo" in padrao

    inf = busca(root, "infNFSe") if nacional else busca(root, "InfNfse", "tcInfNfse")
    if inf is None:  # (comparação explícita: o "valor-verdade" de um Element depende dos filhos)
        inf = root
    dps = busca(root, "infDPS") if nacional else None
    valores = busca(dps, "valores") if nacional else busca(inf, "Valores", "ValoresNfse")
    escopo_valores = valores if valores is not None else inf

    doc["numero"] = _t(inf, "numero")
    doc["serie"] = texto_busca(dps, "serie") if nacional else texto_busca(inf, "Serie", "SerieRPS")
    doc["codigo_verificacao"] = _t(inf, "codigo_verificacao")
    if nacional and inf is not None:
        doc["chave"] = so_digitos_ou_alfa(inf.get("Id", "")).replace("NFS", "")
    elif sp:
        doc["chave"] = so_digitos_ou_alfa(texto_busca(root, "ChaveNFe"))
    doc["data_emissao"] = (texto_busca(dps, "dhEmi") if nacional else "") or _t(inf, "emissao")
    doc["data_emissao"] = doc["data_emissao"][:19]
    doc["data_saida"] = (_t(dps if nacional else inf, "competencia") or "")[:10]

    if sp:
        doc["emitente"] = _parte_sp(root, "Prestador")
        doc["destinatario"] = _parte_sp(root, "Tomador")
    else:
        doc["emitente"] = _parte(busca(inf, *CONTAINERS_PRESTADOR) if not nacional else filho(inf, "emit"))
        doc["destinatario"] = _parte(busca(dps if nacional else inf, *CONTAINERS_TOMADOR))
    if nacional and not doc["emitente"]["municipio"]:
        doc["emitente"]["municipio"] = texto_busca(inf, "xLocEmi")
    doc["municipio"] = doc["emitente"]["municipio"] or doc["emitente"]["codigo_municipio"]
    doc["uf"] = doc["emitente"]["uf"]

    servico_el = busca(dps, "serv") if nacional else busca(inf, "Servico")
    escopo_serv = servico_el if servico_el is not None else inf
    v_serv = numero(_t(escopo_valores if not nacional else dps, "valor_servicos")) or numero(_t(inf, "valor_servicos"))
    # ABRASF 2.x: BaseCalculo/Aliquota ficam em ValoresNfse e não em Servico/Valores → busca com fallback no InfNfse
    base = numero(_t(inf if nacional else escopo_valores, "base"))
    if base is None:
        base = numero(_t(inf, "base"))
    aliquota = numero(_t(inf if nacional else escopo_valores, "aliquota"))
    if aliquota is None:
        aliquota = numero(_t(dps if nacional else inf, "aliquota"))
    aliquota = _aliquota_percentual(aliquota)
    v_iss = numero(_t(inf if nacional else escopo_valores, "valor_iss"))
    if v_iss is None:
        v_iss = numero(_t(inf, "valor_iss"))
    flag = _t(dps if nacional else escopo_valores, "iss_retido_flag") or _t(inf, "iss_retido_flag")
    retido = _flag_retido(flag, padrao)
    v_iss_ret = numero(_t(inf if nacional else escopo_valores, "valor_iss_retido"))
    if v_iss_ret is None:
        v_iss_ret = numero(_t(inf, "valor_iss_retido"))
    if retido and not v_iss_ret:
        v_iss_ret = v_iss
    codigo_nac = _t(escopo_serv, "codigo_nacional")
    item = _t(escopo_serv, "item_lc116") if not nacional else ""
    if sp:
        item = texto_busca(root, "CodigoServico")

    doc["servico"] = {
        "item_lc116": _item_lc116(codigo_nac, item),
        "codigo_servico": codigo_nac or item,
        "codigo_tributacao_municipal": _t(escopo_serv, "codigo_municipal"),
        "cnae": _t(escopo_serv, "cnae") or _t(inf, "cnae"),
        "nbs": _t(escopo_serv, "nbs"),
        "discriminacao": _t(escopo_serv, "discriminacao") or _t(inf, "discriminacao"),
        "natureza_operacao": _t(inf if not nacional else dps, "natureza"),
        "municipio_incidencia": (_t(inf, "municipio_incidencia") if nacional else (_t(escopo_serv, "municipio_incidencia") or _t(inf, "municipio_incidencia"))),
        "municipio_incidencia_nome": _t(inf, "municipio_incidencia_nome"),
        "municipio_prestacao": _t(escopo_serv, "municipio_prestacao") or _t(dps, "municipio_prestacao"),
        "valor_servicos": v_serv,
        "deducoes": numero(_t(escopo_valores if not nacional else dps, "deducoes")),
        "desconto_incondicionado": numero(_t(escopo_valores if not nacional else dps, "desconto_incondicionado")),
        "desconto_condicionado": numero(_t(escopo_valores if not nacional else dps, "desconto_condicionado")),
        "base_iss": base,
        "aliquota_iss": aliquota,
        "valor_iss": v_iss,
        "iss_retido": bool(retido),
        "iss_retido_informado": retido is not None,
        "valor_iss_retido": v_iss_ret if retido else 0.0,
        "optante_simples": _t(inf if not nacional else dps, "optante_simples"),
    }
    doc["natureza_operacao"] = doc["servico"]["natureza_operacao"]

    escopo_ret = (busca(dps, "tribFed") if nacional else escopo_valores)
    ret = {}
    for chave, nomes in RETENCOES.items():
        ret[chave] = numero(texto_busca(escopo_ret if escopo_ret is not None else inf, *nomes)) or 0.0
    if nacional:
        # No padrão nacional, PIS/COFINS só são retenção quando tpRetPisCofins indica retenção (1)
        piscofins = busca(dps, "piscofins")
        tp = texto_busca(piscofins, "tpRetPisCofins")
        if tp == "1":
            ret["pis"] = numero(texto_busca(piscofins, "vPis")) or 0.0
            ret["cofins"] = numero(texto_busca(piscofins, "vCofins")) or 0.0
        doc["pis_cofins_proprio"] = {"cst": texto_busca(piscofins, "CST"), "base": numero(texto_busca(piscofins, "vBCPisCofins")),
                                     "aliq_pis": numero(texto_busca(piscofins, "pAliqPis")), "pis": numero(texto_busca(piscofins, "vPis")),
                                     "aliq_cofins": numero(texto_busca(piscofins, "pAliqCofins")), "cofins": numero(texto_busca(piscofins, "vCofins")),
                                     "retido": tp == "1"}
    ret["iss"] = doc["servico"]["valor_iss_retido"] or 0.0
    doc["retencoes"] = ret

    doc["valor_total"] = v_serv or 0.0
    liquido = numero(_t(inf if nacional else escopo_valores, "valor_liquido")) or numero(_t(inf, "valor_liquido"))
    doc["valor_liquido_informado"] = liquido
    total_ret = sum(v or 0.0 for v in ret.values())
    descontos = (doc["servico"]["desconto_incondicionado"] or 0.0) + (doc["servico"]["desconto_condicionado"] or 0.0)
    doc["valor_liquido_calculado"] = round((v_serv or 0.0) - total_ret - descontos, 2)
    doc["valor_liquido"] = liquido if liquido is not None else doc["valor_liquido_calculado"]

    status = _t(inf, "status")
    if busca(root, "NfseCancelamento", "Cancelamento", "infPedCanc") is not None or str(status).lower() in ("2", "cancelada", "c"):
        doc["status_documento"] = "Cancelada"
    elif status in ("100", "1", "N", "Normal", "normal"):
        doc["status_documento"] = "Autorizada / Normal"
    else:
        doc["status_documento"] = f"Situação informada: {status}" if status else "Situação não informada no XML"

    if not doc["numero"]:
        doc["avisos_leitura"].append("Número da NFS-e não localizado — o XML pode ser um RPS/DPS ainda não convertido em nota.")
    if v_serv is None:
        doc["erros_leitura"].append("Valor dos serviços não localizado no XML da NFS-e.")
    doc["avisos_leitura"].append(f"Padrão identificado: {padrao}. Campos lidos pela camada de normalização de NFS-e.")
    return doc
