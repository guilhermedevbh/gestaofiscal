"""Motor fiscal: orquestra as regras por imposto e consolida impostos, alertas, totais e status."""
from . import regras_cfop_ncm, regras_icms, regras_ipi_pis_cofins, regras_iss_retencoes, regras_totais
from .alertas import OK, ATENCAO, alerta, calcular_status, ordenar
from .calculos import v


def _soma(linhas, nome):
    return round(sum(v(l.get("valor")) for l in linhas if l["imposto"] == nome), 2)


def executar(doc: dict, ctx: dict) -> dict:
    """Recebe o documento normalizado e devolve {impostos, alertas, resumo, status}."""
    alertas, linhas = [], []
    if doc["tipo"] == "NFE":
        for it in doc.get("itens", []):
            for regra in (regras_icms.avaliar_item, regras_ipi_pis_cofins.avaliar_ipi, regras_ipi_pis_cofins.avaliar_pis_cofins,
                          regras_iss_retencoes.avaliar_issqn_nfe):
                a, l = regra(doc, it, ctx)
                alertas += a
                linhas += l
            alertas += regras_cfop_ncm.avaliar_cfop(doc, it)
            alertas += regras_cfop_ncm.avaliar_ncm(doc, it)
        alertas += regras_totais.avaliar_totais(doc, ctx)
    elif doc["tipo"] == "NFSE":
        a, l = regras_iss_retencoes.avaliar_iss(doc, ctx)
        alertas += a
        linhas += l
        pc = doc.get("pis_cofins_proprio") or {}
        if pc.get("pis") or pc.get("cofins"):
            linhas.append({"imposto": "PIS", "item": None, "cst_csosn": pc.get("cst"), "base_calculo": pc.get("base"), "aliquota": pc.get("aliq_pis"),
                           "valor": pc.get("pis"), "valor_calculado": None, "diferenca": None, "status": "OK"})
            linhas.append({"imposto": "COFINS", "item": None, "cst_csosn": pc.get("cst"), "base_calculo": pc.get("base"), "aliquota": pc.get("aliq_cofins"),
                           "valor": pc.get("cofins"), "valor_calculado": None, "diferenca": None, "status": "OK"})
    a, l = regras_iss_retencoes.avaliar_retencoes(doc, ctx)
    alertas += a
    linhas += l

    st = str(doc.get("status_documento") or "").lower()
    if "cancel" in st or "deneg" in st:
        alertas.append(alerta("DOCUMENTO_CANCELADO", "Documento", "CRITICO", f"Documento com situação: {doc.get('status_documento')}.",
                              campo="Situação", valor_xml=doc.get("status_documento"), dados={"protocolo": doc.get("protocolo")},
                              motivo="Documento cancelado ou denegado não deve gerar entrada, crédito ou pagamento.",
                              recomendacao="Não lançar o documento; solicitar ao emitente o documento válido."))
    if doc.get("tipo") == "NFE" and doc.get("ambiente") == "2":
        alertas.append(alerta("AMBIENTE_HOMOLOGACAO", "Documento", "CRITICO", "NF-e emitida em ambiente de homologação (sem valor fiscal).",
                              campo="tpAmb", valor_xml="2", dados={}, motivo="tpAmb=2 indica nota de teste.", recomendacao="Não lançar este documento."))
    for aviso in doc.get("avisos_leitura") or []:
        if "protocolo" in aviso.lower():
            alertas.append(alerta("SEM_PROTOCOLO", "Documento", ATENCAO, aviso, campo="protNFe", dados={},
                                  motivo="Sem o protocolo não é possível confirmar a autorização pelo XML.",
                                  recomendacao="Consultar a chave de acesso no portal da SEFAZ antes de lançar."))

    if not [x for x in alertas if x["gravidade"] != OK]:
        alertas.append(alerta("SEM_DIVERGENCIAS", "Geral", OK, "Nenhuma divergência identificada pelas regras automáticas.",
                              dados={}, motivo="Todas as conferências executadas ficaram dentro da tolerância.",
                              recomendacao="Seguir o fluxo normal de classificação e entrada."))

    retencoes = round(sum(v(x) for x in (doc.get("retencoes") or {}).values()), 2)
    impostos_nomes = ("ICMS", "ICMS-ST", "FCP", "FCP-ST", "DIFAL", "IPI", "PIS", "COFINS", "ISS")
    totais_impostos = {nome: _soma(linhas, nome) for nome in impostos_nomes}
    if doc["tipo"] == "NFE" and doc.get("totais"):
        t = doc["totais"]
        totais_impostos.update({"ICMS": v(t.get("vICMS")), "ICMS-ST": v(t.get("vST")), "IPI": v(t.get("vIPI")),
                                "PIS": v(t.get("vPIS")), "COFINS": v(t.get("vCOFINS")), "FCP": v(t.get("vFCP")), "FCP-ST": v(t.get("vFCPST"))})
    valor_impostos = round(sum(totais_impostos.values()), 2)
    alertas = ordenar(alertas)
    status = calcular_status(alertas, doc.get("erros_leitura") or [])
    return {
        "impostos": linhas,
        "alertas": alertas,
        "totais_impostos": totais_impostos,
        "resumo": {
            "valor_total": round(v(doc.get("valor_total")), 2),
            "valor_impostos": valor_impostos,
            "valor_retencoes": retencoes,
            "valor_liquido": round(v(doc.get("valor_liquido")) if doc.get("valor_liquido") is not None else v(doc.get("valor_total")) - retencoes, 2),
            "qtd_alertas": len([x for x in alertas if x["gravidade"] != OK]),
            "qtd_itens": len(doc.get("itens") or []),
        },
        "status": status,
    }
