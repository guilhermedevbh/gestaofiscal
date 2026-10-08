"""Normalizador da NF-e (modelo 55) / NFC-e (65) — leiaute nacional SEFAZ 4.00."""
from ..parser import busca, filho, filhos, local, numero, texto
from .base import documento_vazio, so_digitos_ou_alfa

STATUS_PROTOCOLO = {
    "100": "Autorizada", "150": "Autorizada fora de prazo", "101": "Cancelada", "135": "Cancelada (evento)",
    "151": "Cancelada fora de prazo", "110": "Denegada", "301": "Denegada", "302": "Denegada", "303": "Denegada",
}


def _n(el, nome):
    return numero(texto(el, nome))


def _parte(el, endereco_tag: str) -> dict:
    ender = filho(el, endereco_tag)
    return {
        "documento": texto(el, "CNPJ") or texto(el, "CPF") or texto(el, "idEstrangeiro"),
        "nome": texto(el, "xNome"),
        "ie": texto(el, "IE"),
        "im": texto(el, "IM"),
        "municipio": texto(ender, "xMun"),
        "codigo_municipio": texto(ender, "cMun"),
        "uf": texto(ender, "UF"),
        "crt": texto(el, "CRT"),
        "ind_ie_dest": texto(el, "indIEDest"),
    }


def _grupo_unico(pai):
    """ICMS/IPI/PIS/COFINS têm um subgrupo variável (ICMS00, PISAliq...). Retorna (nome, elemento)."""
    if pai is None:
        return "", None
    for c in list(pai):
        nome = local(c.tag)
        if nome not in ("IPI", "cEnq", "CNPJProd", "cSelo", "qSelo"):
            return nome, c
    return "", None


def _icms(imposto) -> dict:
    nome, g = _grupo_unico(filho(imposto, "ICMS"))
    if g is None:
        return {}
    d = {"grupo": nome}
    for campo in ("orig", "CST", "CSOSN", "modBC", "pRedBC", "motDesICMS", "modBCST"):
        d[campo] = texto(g, campo)
    for campo in ("vBC", "pICMS", "vICMS", "vICMSDeson", "vBCST", "pICMSST", "vICMSST", "pMVAST", "pRedBCST",
                  "vBCFCP", "pFCP", "vFCP", "vBCFCPST", "pFCPST", "vFCPST", "pCredSN", "vCredICMSSN",
                  "vBCSTRet", "vICMSSTRet", "pST", "vICMSSubstituto", "vICMSOp", "pDif", "vICMSDif"):
        d[campo] = _n(g, campo)
    return d


def _ipi(imposto) -> dict:
    ipi = filho(imposto, "IPI")
    if ipi is None:
        return {}
    trib = filho(ipi, "IPITrib")
    nt = filho(ipi, "IPINT")
    g = trib if trib is not None else nt
    return {
        "grupo": "IPITrib" if trib is not None else ("IPINT" if nt is not None else ""),
        "CST": texto(g, "CST"), "cEnq": texto(ipi, "cEnq"),
        "vBC": _n(g, "vBC"), "pIPI": _n(g, "pIPI"), "qUnid": _n(g, "qUnid"), "vUnid": _n(g, "vUnid"), "vIPI": _n(g, "vIPI"),
    }


def _pis_cofins(imposto, nome: str) -> dict:
    pai = filho(imposto, nome)
    grupo, g = _grupo_unico(pai)
    if g is None:
        return {}
    sufixo = "PIS" if nome == "PIS" else "COFINS"
    return {
        "grupo": grupo, "CST": texto(g, "CST"),
        "vBC": _n(g, "vBC"), "p": _n(g, "p" + sufixo), "v": _n(g, "v" + sufixo),
        "qBCProd": _n(g, "qBCProd"), "vAliqProd": _n(g, "vAliqProd"),
    }


def _difal(imposto) -> dict:
    g = filho(imposto, "ICMSUFDest")
    if g is None:
        return {}
    return {c: _n(g, c) for c in ("vBCUFDest", "vBCFCPUFDest", "pFCPUFDest", "pICMSUFDest", "pICMSInter",
                                   "pICMSInterPart", "vFCPUFDest", "vICMSUFDest", "vICMSUFRemet")}


def _issqn(imposto) -> dict:
    g = filho(imposto, "ISSQN")
    if g is None:
        return {}
    return {"vBC": _n(g, "vBC"), "vAliq": _n(g, "vAliq"), "vISSQN": _n(g, "vISSQN"),
            "cListServ": texto(g, "cListServ"), "cMunFG": texto(g, "cMunFG"), "vISSRet": _n(g, "vISSRet")}


def _item(det) -> dict:
    prod = filho(det, "prod")
    imposto = filho(det, "imposto")
    icms = _icms(imposto)
    return {
        "numero_item": det.get("nItem") or "",
        "codigo": texto(prod, "cProd"),
        "gtin": texto(prod, "cEAN") or texto(prod, "cEANTrib"),
        "descricao": texto(prod, "xProd"),
        "ncm": texto(prod, "NCM"),
        "cest": texto(prod, "CEST"),
        "cfop": texto(prod, "CFOP"),
        "unidade": texto(prod, "uCom"),
        "quantidade": _n(prod, "qCom"),
        "valor_unitario": _n(prod, "vUnCom"),
        "valor_total": _n(prod, "vProd"),
        "desconto": _n(prod, "vDesc"),
        "frete": _n(prod, "vFrete"),
        "seguro": _n(prod, "vSeg"),
        "outras_despesas": _n(prod, "vOutro"),
        "ind_tot": texto(prod, "indTot"),
        "origem": icms.get("orig", ""),
        "cst_csosn": icms.get("CST") or icms.get("CSOSN") or "",
        "icms": icms,
        "ipi": _ipi(imposto),
        "pis": _pis_cofins(imposto, "PIS"),
        "cofins": _pis_cofins(imposto, "COFINS"),
        "difal": _difal(imposto),
        "issqn": _issqn(imposto),
        "valor_tributos_aproximado": _n(imposto, "vTotTrib"),
        "informacoes": texto(det, "infAdProd"),
    }


def normalizar_nfe(root, deteccao: dict) -> dict:
    doc = documento_vazio("NFE", deteccao.get("padrao", ""))
    inf = busca(root, "infNFe")
    if inf is None:
        doc["erros_leitura"].append("Grupo infNFe não encontrado.")
        return doc
    ide, emit, dest = filho(inf, "ide"), filho(inf, "emit"), filho(inf, "dest")
    doc["modelo"] = texto(ide, "mod") or deteccao.get("modelo", "55")
    doc["numero"] = texto(ide, "nNF")
    doc["serie"] = texto(ide, "serie")
    doc["chave"] = so_digitos_ou_alfa(inf.get("Id", "")).replace("NFE", "")
    doc["data_emissao"] = (texto(ide, "dhEmi") or texto(ide, "dEmi"))[:19]
    doc["data_saida"] = (texto(ide, "dhSaiEnt") or texto(ide, "dSaiEnt"))[:19]
    doc["natureza_operacao"] = texto(ide, "natOp")
    doc["tipo_operacao"] = texto(ide, "tpNF")
    doc["finalidade"] = texto(ide, "finNFe")
    doc["destino_operacao"] = texto(ide, "idDest")
    doc["consumidor_final"] = texto(ide, "indFinal")
    doc["presenca"] = texto(ide, "indPres")
    doc["ambiente"] = texto(ide, "tpAmb")
    doc["emitente"] = _parte(emit, "enderEmit")
    doc["destinatario"] = _parte(dest, "enderDest") if dest is not None else doc["destinatario"]
    doc["municipio"] = doc["emitente"]["municipio"]
    doc["uf"] = doc["emitente"]["uf"]
    doc["itens"] = [_item(det) for det in filhos(inf, "det")]
    if not doc["itens"]:
        doc["erros_leitura"].append("A NF-e não possui itens (grupo det).")

    tot = filho(inf, "total", "ICMSTot")
    doc["totais"] = {c: numero(texto(tot, c)) for c in (
        "vBC", "vICMS", "vICMSDeson", "vFCPUFDest", "vICMSUFDest", "vICMSUFRemet", "vFCP", "vBCST", "vST",
        "vFCPST", "vFCPSTRet", "vProd", "vFrete", "vSeg", "vDesc", "vII", "vIPI", "vIPIDevol", "vPIS",
        "vCOFINS", "vOutro", "vNF", "vTotTrib")} if tot is not None else {}
    if tot is None:
        doc["erros_leitura"].append("Totais da NF-e (ICMSTot) não encontrados.")
    issqn_tot = filho(inf, "total", "ISSQNtot")
    if issqn_tot is not None:
        doc["totais_issqn"] = {c: numero(texto(issqn_tot, c)) for c in ("vServ", "vBC", "vISS", "vPIS", "vCOFINS", "vISSRet", "vDeducao", "vDescIncond")}
    ret = filho(inf, "total", "retTrib")
    if ret is not None:
        doc["retencoes"] = {
            "irrf": numero(texto(ret, "vIRRF")) or 0.0, "inss": numero(texto(ret, "vRetPrev")) or 0.0,
            "pis": numero(texto(ret, "vRetPIS")) or 0.0, "cofins": numero(texto(ret, "vRetCOFINS")) or 0.0,
            "csll": numero(texto(ret, "vRetCSLL")) or 0.0,
            "iss": (doc.get("totais_issqn") or {}).get("vISSRet") or 0.0,
        }
    doc["valor_total"] = doc["totais"].get("vNF") or 0.0
    total_ret = sum(v or 0.0 for v in doc["retencoes"].values())
    doc["valor_liquido"] = round(doc["valor_total"] - total_ret, 2)

    doc["informacoes_adicionais"] = " ".join(filter(None, [texto(inf, "infAdic", "infCpl"), texto(inf, "infAdic", "infAdFisco")]))
    pag = filho(inf, "pag")
    doc["pagamentos"] = [{"forma": texto(d, "tPag"), "valor": numero(texto(d, "vPag"))} for d in filhos(pag, "detPag")]

    prot = busca(root, "infProt")
    if prot is not None:
        cstat = texto(prot, "cStat")
        doc["status_documento"] = STATUS_PROTOCOLO.get(cstat, f"Código {cstat} — {texto(prot, 'xMotivo')}")
        doc["protocolo"] = texto(prot, "nProt")
    else:
        doc["status_documento"] = "Sem protocolo de autorização no XML"
        doc["avisos_leitura"].append("O XML não contém o protocolo de autorização (nfeProc/protNFe). Confirme a situação na SEFAZ.")
    return doc
