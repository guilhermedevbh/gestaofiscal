"""Regras de IPI, PIS e COFINS (NF-e)."""
from .alertas import ATENCAO, CRITICO, DIVERGENCIA, alerta
from .calculos import comparar, moeda, pct, severidade_diferenca, v

IPI_CST_SEM_VALOR = {"02", "03", "04", "05", "52", "53", "54", "55"}
PISCOFINS_CST_TRIBUTADO_ALIQ = {"01", "02"}
PISCOFINS_CST_SEM_VALOR = {"04", "05", "06", "07", "08", "09"}
ALIQ_PADRAO = {"PIS": (0.65, 1.65), "COFINS": (3.0, 7.6)}


def _row(item, nome, cst, base, aliq, valor, calc=None, dif=None, status="OK"):
    return {"imposto": nome, "item": item, "cst_csosn": cst, "base_calculo": base, "aliquota": aliq,
            "valor": valor, "valor_calculado": calc, "diferenca": dif, "status": status}


def avaliar_ipi(doc, it, ctx):
    alertas, linhas = [], []
    ipi = it.get("ipi") or {}
    if not ipi:
        return alertas, linhas
    n, cst = it.get("numero_item"), ipi.get("CST") or ""
    vbc, aliq, vipi = ipi.get("vBC"), ipi.get("pIPI"), ipi.get("vIPI")
    dados = {"item": n, "descricao": it.get("descricao"), "ncm": it.get("ncm"), "CST": cst, "vBC": vbc, "pIPI": aliq, "vIPI": vipi}
    if v(vipi) > 0 and not v(vbc) and not v(ipi.get("qUnid")):
        alertas.append(alerta("IPI_SEM_BASE", "IPI", CRITICO, f"Item {n}: IPI de {moeda(vipi)} sem base de cálculo.", campo="vBC", valor_xml=vbc, item=n, dados=dados,
                              motivo="IPI informado sem base ad valorem nem quantidade tributável.", recomendacao="Validar a base e a forma de cálculo do IPI."))
    if cst in IPI_CST_SEM_VALOR and v(vipi) > 0:
        alertas.append(alerta("IPI_CST_INCOMPATIVEL", "IPI", CRITICO, f"Item {n}: CST {cst} do IPI com valor de {moeda(vipi)}.", campo="CST", valor_xml=cst, item=n, dados=dados,
                              motivo="O CST indica operação isenta, imune, suspensa ou não tributada, mas há valor de IPI.",
                              recomendacao="Validar o CST do IPI, o enquadramento (cEnq) e a TIPI do NCM."))
    if cst in {"00", "50"} and ipi.get("grupo") == "IPITrib" and not v(vipi) and v(aliq) > 0:
        alertas.append(alerta("IPI_ZERADO", "IPI", ATENCAO, f"Item {n}: CST {cst} (tributado) com IPI zerado.", campo="vIPI", item=n, dados=dados,
                              motivo="CST tributado, alíquota positiva e valor zerado.", recomendacao="Verificar a base de cálculo do IPI."))
    comp = comparar(vipi, vbc, aliq, ctx) if v(vbc) else {"comparavel": False, "esperado": None, "diferenca": None, "divergente": False}
    status = "OK"
    if comp["comparavel"] and comp["divergente"]:
        status = severidade_diferenca(comp["diferenca"], comp["esperado"])
        alertas.append(alerta("IPI_VALOR_DIVERGENTE", "IPI", status, f"Divergência de IPI no item {n}.", campo="vIPI", valor_xml=vipi,
                              valor_calculado=comp["esperado"], diferenca=comp["diferenca"], item=n, dados=dados,
                              motivo=f"Base {moeda(vbc)} × {pct(aliq)} = {moeda(comp['esperado'])}.",
                              recomendacao="Validar a alíquota da TIPI para o NCM e a base de cálculo."))
    if v(ipi.get("qUnid")) and ipi.get("vUnid") is not None:
        esperado = round(v(ipi["qUnid"]) * v(ipi["vUnid"]), 2)
        if abs(v(vipi) - esperado) > max(v(ctx.get("tol_abs")), 0.01):
            alertas.append(alerta("IPI_PAUTA_DIVERGENTE", "IPI", DIVERGENCIA, f"Item {n}: IPI por unidade divergente.", campo="vIPI", valor_xml=vipi,
                                  valor_calculado=esperado, diferenca=round(v(vipi) - esperado, 2), item=n, dados=dados,
                                  motivo="Quantidade × valor por unidade difere do IPI informado.", recomendacao="Validar a pauta (vUnid) e a quantidade tributável."))
    linhas.append(_row(n, "IPI", cst, vbc, aliq, vipi, comp["esperado"], comp["diferenca"], status))
    return alertas, linhas


def avaliar_pis_cofins(doc, it, ctx):
    alertas, linhas = [], []
    n = it.get("numero_item")
    for nome, chave in (("PIS", "pis"), ("COFINS", "cofins")):
        g = it.get(chave) or {}
        if not g:
            alertas.append(alerta(f"{nome}_AUSENTE", nome, ATENCAO, f"Item {n}: grupo de {nome} não informado.", campo=nome, item=n,
                                  dados={"item": n, "descricao": it.get("descricao")}, motivo=f"Todo item da NF-e deve informar o {nome}.",
                                  recomendacao="Verificar o leiaute do emissor."))
            continue
        cst, vbc, aliq, valor = g.get("CST") or "", g.get("vBC"), g.get("p"), g.get("v")
        dados = {"item": n, "descricao": it.get("descricao"), "ncm": it.get("ncm"), "CST": cst, "vBC": vbc, "aliquota": aliq, "valor": valor}
        if cst in PISCOFINS_CST_SEM_VALOR and v(valor) > 0:
            alertas.append(alerta(f"{nome}_CST_INCOMPATIVEL", nome, CRITICO, f"Item {n}: CST {cst} de {nome} com valor de {moeda(valor)}.", campo="CST", valor_xml=cst, item=n, dados=dados,
                                  motivo="O CST indica monofásico, alíquota zero, isenção, suspensão ou não incidência, mas há valor destacado.",
                                  recomendacao=f"Validar o CST do {nome} e o enquadramento do produto (NCM)."))
        if cst in PISCOFINS_CST_TRIBUTADO_ALIQ and not v(valor):
            alertas.append(alerta(f"{nome}_NAO_INFORMADO", nome, ATENCAO, f"Item {n}: CST {cst} (tributado) com {nome} zerado.", campo="valor", valor_xml=valor, item=n, dados=dados,
                                  motivo="CST tributável com valor zerado.", recomendacao=f"Verificar base e alíquota do {nome}."))
        if cst == "01" and aliq is not None and v(aliq) > 0 and round(v(aliq), 2) not in ALIQ_PADRAO[nome]:
            alertas.append(alerta(f"{nome}_ALIQ_INCOMUM", nome, ATENCAO, f"Item {n}: alíquota de {nome} {pct(aliq)} diferente das alíquotas básicas.",
                                  campo="aliquota", valor_xml=aliq, valor_calculado=" ou ".join(pct(x) for x in ALIQ_PADRAO[nome]), item=n, dados=dados,
                                  motivo=f"As alíquotas básicas são {pct(ALIQ_PADRAO[nome][0])} (cumulativo) e {pct(ALIQ_PADRAO[nome][1])} (não cumulativo).",
                                  recomendacao="Validar se há regime diferenciado para o produto antes de concluir."))
        comp = comparar(valor, vbc, aliq, ctx)
        status = "OK"
        if comp["comparavel"] and comp["divergente"]:
            status = severidade_diferenca(comp["diferenca"], comp["esperado"])
            alertas.append(alerta(f"{nome}_VALOR_DIVERGENTE", nome, status, f"Divergência de {nome} no item {n}.", campo="valor", valor_xml=valor,
                                  valor_calculado=comp["esperado"], diferenca=comp["diferenca"], item=n, dados=dados,
                                  motivo=f"Base {moeda(vbc)} × {pct(aliq)} = {moeda(comp['esperado'])}.",
                                  recomendacao=f"Validar a base (ex.: exclusão do ICMS da base) e a alíquota do {nome}."))
        if g.get("qBCProd") and g.get("vAliqProd") is not None:
            esperado = round(v(g["qBCProd"]) * v(g["vAliqProd"]), 2)
            if abs(v(valor) - esperado) > max(v(ctx.get("tol_abs")), 0.01):
                alertas.append(alerta(f"{nome}_QTDE_DIVERGENTE", nome, DIVERGENCIA, f"Item {n}: {nome} por quantidade divergente.", campo="valor",
                                      valor_xml=valor, valor_calculado=esperado, diferenca=round(v(valor) - esperado, 2), item=n, dados=dados,
                                      motivo="Quantidade × alíquota em reais difere do valor informado.", recomendacao="Validar a alíquota por unidade."))
        linhas.append(_row(n, nome, cst, vbc, aliq, valor, comp["esperado"], comp["diferenca"], status))
    return alertas, linhas
