"""Regras de ICMS, ICMS-ST, FCP e DIFAL (NF-e)."""
from .alertas import ATENCAO, CRITICO, DIVERGENCIA, OK, alerta
from .calculos import comparar, moeda, pct, severidade_diferenca, v

CST_TRIBUTADO = {"00", "10", "20", "70", "90"}
CST_SEM_ICMS_PROPRIO = {"40", "41", "50", "60"}
CST_COM_ST = {"10", "30", "70", "90"}
CSOSN_COM_ST = {"201", "202", "203"}
CSOSN_SEM_DESTAQUE = {"102", "103", "300", "400", "500"}
ALIQ_INTERESTADUAIS = {4.0, 7.0, 12.0}


def _imposto_row(item, nome, cst, base, aliq, valor, calc=None, dif=None, status="OK"):
    return {"imposto": nome, "item": item, "cst_csosn": cst, "base_calculo": base, "aliquota": aliq,
            "valor": valor, "valor_calculado": calc, "diferenca": dif, "status": status}


def avaliar_item(doc: dict, it: dict, ctx: dict):
    alertas, linhas = [], []
    icms = it.get("icms") or {}
    n = it.get("numero_item")
    crt = (doc.get("emitente") or {}).get("crt", "")
    if not icms:
        alertas.append(alerta("ICMS_AUSENTE", "ICMS", ATENCAO, f"Item {n}: grupo de ICMS não informado.", campo="ICMS", item=n,
                              motivo="Todo item de mercadoria da NF-e deve informar a situação tributária do ICMS.",
                              recomendacao="Verificar o leiaute do emissor e a situação tributária do item.", dados={"descricao": it.get("descricao")}))
        return alertas, linhas
    cst, csosn = icms.get("CST") or "", icms.get("CSOSN") or ""
    codigo = cst or csosn
    vbc, aliq, vicms = icms.get("vBC"), icms.get("pICMS"), icms.get("vICMS")
    dados = {"item": n, "descricao": it.get("descricao"), "ncm": it.get("ncm"), "cfop": it.get("cfop"),
             "CST/CSOSN": codigo, "vBC": vbc, "pICMS": aliq, "vICMS": vicms}

    # Regime x tipo de código (CST para regime normal, CSOSN para Simples Nacional)
    if crt == "3" and csosn:
        alertas.append(alerta("ICMS_CSOSN_REGIME_NORMAL", "ICMS", CRITICO, f"Item {n}: CSOSN {csosn} informado por emitente do regime normal (CRT 3).",
                              campo="CST/CSOSN", valor_xml=csosn, item=n, dados=dict(dados, CRT=crt),
                              motivo="CSOSN é próprio do Simples Nacional; o regime normal utiliza CST.",
                              recomendacao="Validar o CRT do emitente e o código de situação tributária do item."))
    if crt == "1" and cst and not csosn:
        alertas.append(alerta("ICMS_CST_SIMPLES", "ICMS", ATENCAO, f"Item {n}: CST {cst} informado por emitente do Simples Nacional (CRT 1).",
                              campo="CST/CSOSN", valor_xml=cst, item=n, dados=dict(dados, CRT=crt),
                              motivo="Emitentes do Simples Nacional normalmente informam CSOSN.",
                              recomendacao="Confirmar o regime do emitente e a regra do item (pode haver exceção, como sublimite)."))

    # ICMS próprio
    if v(vicms) > 0 and not v(vbc):
        alertas.append(alerta("ICMS_SEM_BASE", "ICMS", CRITICO, f"Item {n}: ICMS de {moeda(vicms)} informado sem base de cálculo.",
                              campo="vBC", valor_xml=vbc, valor_calculado=None, item=n, dados=dados,
                              motivo="Não é possível existir valor de ICMS sem base de cálculo correspondente.",
                              recomendacao="Validar a base de cálculo, o CST e a forma de cálculo do ICMS no item."))
    comp = comparar(vicms, vbc, aliq, ctx)
    status_linha = "OK"
    if comp["comparavel"] and comp["divergente"]:
        grav = severidade_diferenca(comp["diferenca"], comp["esperado"])
        status_linha = grav
        alertas.append(alerta("ICMS_VALOR_DIVERGENTE", "ICMS", grav, f"Divergência de ICMS no item {n}.", campo="vICMS",
                              valor_xml=vicms, valor_calculado=comp["esperado"], diferenca=comp["diferenca"], item=n, dados=dados,
                              motivo=f"Base {moeda(vbc)} × alíquota {pct(aliq)} = {moeda(comp['esperado'])}, diferente do valor informado {moeda(vicms)}.",
                              recomendacao="Validar base de cálculo, redução de base (pRedBC), alíquota e arredondamento do emissor."))
    if v(vbc) > 0 and v(it.get("valor_total")) > 0:
        base_max = v(it.get("valor_total")) + v(it.get("frete")) + v(it.get("seguro")) + v(it.get("outras_despesas")) + v((it.get("ipi") or {}).get("vIPI"))
        if v(vbc) > base_max + max(1.0, base_max * 0.01):
            alertas.append(alerta("ICMS_BASE_MAIOR", "ICMS", DIVERGENCIA, f"Item {n}: base do ICMS maior que o valor da operação.", campo="vBC",
                                  valor_xml=vbc, valor_calculado=round(base_max, 2), diferenca=round(v(vbc) - base_max, 2), item=n, dados=dados,
                                  motivo="A base do ICMS próprio supera a soma de produto, frete, seguro, outras despesas e IPI.",
                                  recomendacao="Verificar se há inclusão indevida de valores na base ou se o caso é ICMS-ST."))

    # CST × valor
    if cst in CST_SEM_ICMS_PROPRIO and v(vicms) > 0:
        alertas.append(alerta("ICMS_CST_INCOMPATIVEL", "ICMS", CRITICO, f"Item {n}: CST {cst} com ICMS destacado de {moeda(vicms)}.",
                              campo="CST", valor_xml=cst, item=n, dados=dados,
                              motivo=f"O CST {cst} indica operação sem destaque de ICMS próprio (isenta, não tributada, suspensa ou ST já recolhida).",
                              recomendacao="Validar CST, operação e a regra de tributação aplicável ao item."))
    if cst in {"00", "20"} and not v(vicms):
        alertas.append(alerta("ICMS_ZERADO_TRIBUTADO", "ICMS", ATENCAO, f"Item {n}: CST {cst} (tributado) com ICMS zerado.",
                              campo="vICMS", valor_xml=vicms, item=n, dados=dados,
                              motivo="O CST indica tributação, mas o valor do ICMS está zerado.",
                              recomendacao="Verificar se há benefício fiscal, diferimento ou erro de parametrização."))
    if csosn in CSOSN_SEM_DESTAQUE and v(vicms) > 0:
        alertas.append(alerta("ICMS_CSOSN_COM_DESTAQUE", "ICMS", DIVERGENCIA, f"Item {n}: CSOSN {csosn} com ICMS destacado.",
                              campo="CSOSN", valor_xml=csosn, item=n, dados=dados,
                              motivo="Esse CSOSN não prevê destaque de ICMS próprio no documento.",
                              recomendacao="Validar o CSOSN do item e o regime do emitente."))
    if icms.get("pCredSN") and csosn in {"101", "201", "900"}:
        alertas.append(alerta("ICMS_CREDITO_SN", "ICMS", OK, f"Item {n}: crédito de ICMS do Simples Nacional de {moeda(icms.get('vCredICMSSN'))} ({pct(icms.get('pCredSN'))}).",
                              campo="pCredSN", valor_xml=icms.get("pCredSN"), item=n, dados=dados,
                              motivo="Informação de crédito permitido (art. 23 da LC 123/2006).", recomendacao="Considerar o crédito na escrituração, se aplicável."))

    # Alíquota × destino
    destino = doc.get("destino_operacao")
    if aliq and v(vicms) > 0 and cst in CST_TRIBUTADO | {""}:
        if destino == "2" and round(v(aliq), 2) not in ALIQ_INTERESTADUAIS and (doc.get("destinatario") or {}).get("ind_ie_dest") != "9":
            alertas.append(alerta("ICMS_ALIQ_INTERESTADUAL", "ICMS", ATENCAO, f"Item {n}: alíquota {pct(aliq)} em operação interestadual.",
                                  campo="pICMS", valor_xml=aliq, valor_calculado="4%, 7% ou 12%", item=n, dados=dict(dados, idDest=destino),
                                  motivo="Operações interestaduais com contribuinte normalmente usam 4% (importados), 7% ou 12%.",
                                  recomendacao="Validar CST/CSOSN, operação, UF de origem/destino e a regra tributária aplicável."))
        if destino == "1" and round(v(aliq), 2) == 4.0:
            alertas.append(alerta("ICMS_ALIQ_4_INTERNA", "ICMS", ATENCAO, f"Item {n}: alíquota de 4% em operação interna.",
                                  campo="pICMS", valor_xml=aliq, item=n, dados=dict(dados, idDest=destino),
                                  motivo="A alíquota de 4% é própria de operações interestaduais com importados (Res. Senado 13/2012).",
                                  recomendacao="Validar a alíquota interna aplicável à mercadoria na UF."))

    # ICMS desonerado
    if v(icms.get("vICMSDeson")) > 0:
        alertas.append(alerta("ICMS_DESONERADO", "ICMS", ATENCAO, f"Item {n}: ICMS desonerado de {moeda(icms.get('vICMSDeson'))} (motivo {icms.get('motDesICMS') or '—'}).",
                              campo="vICMSDeson", valor_xml=icms.get("vICMSDeson"), item=n, dados=dados,
                              motivo="Há desoneração de ICMS informada no item.", recomendacao="Conferir o benefício fiscal que fundamenta a desoneração."))

    # ICMS-ST
    vbcst, pst, vst = icms.get("vBCST"), icms.get("pICMSST"), icms.get("vICMSST")
    if cst in CST_COM_ST - {"90"} or csosn in CSOSN_COM_ST:
        if not v(vst) and not v(vbcst):
            alertas.append(alerta("ICMS_ST_AUSENTE", "ICMS-ST", ATENCAO, f"Item {n}: código {codigo} indica ST, mas ICMS-ST não foi informado.",
                                  campo="vICMSST", valor_xml=vst, item=n, dados=dados,
                                  motivo="O CST/CSOSN prevê retenção por substituição tributária e não há base nem valor de ST.",
                                  recomendacao="Validar se a mercadoria está sujeita à ST na UF de destino (protocolo/convênio) e o CEST."))
    if v(vst) > 0 and not v(vbcst):
        alertas.append(alerta("ICMS_ST_SEM_BASE", "ICMS-ST", CRITICO, f"Item {n}: ICMS-ST de {moeda(vst)} sem base de cálculo.",
                              campo="vBCST", valor_xml=vbcst, item=n, dados=dados, motivo="ICMS-ST informado sem a base correspondente.",
                              recomendacao="Validar MVA/IVA, pauta e base de cálculo da ST."))
    st_calc = None
    if v(vbcst) > 0 and pst is not None:
        st_calc = round(max(0.0, v(vbcst) * v(pst) / 100.0 - v(vicms)), 2)
        dif = round(v(vst) - st_calc, 2)
        if abs(dif) > max(v(ctx.get("tol_abs")), st_calc * v(ctx.get("tol_pct")) / 100.0):
            alertas.append(alerta("ICMS_ST_DIVERGENTE", "ICMS-ST", severidade_diferenca(dif, st_calc), f"Divergência de ICMS-ST no item {n}.",
                                  campo="vICMSST", valor_xml=vst, valor_calculado=st_calc, diferenca=dif, item=n,
                                  dados=dict(dados, vBCST=vbcst, pICMSST=pst, vICMSST=vst),
                                  motivo=f"(Base ST {moeda(vbcst)} × {pct(pst)}) − ICMS próprio {moeda(vicms)} = {moeda(st_calc)}.",
                                  recomendacao="Validar MVA ajustada, redução de base da ST, FCP-ST e alíquota interna do destino."))
    if v(vst) > 0 and not it.get("cest"):
        alertas.append(alerta("ICMS_ST_SEM_CEST", "ICMS-ST", ATENCAO, f"Item {n}: ICMS-ST informado sem CEST.",
                              campo="CEST", item=n, dados=dados, motivo="Mercadorias sujeitas à ST devem informar o CEST (Convênio ICMS 142/2018).",
                              recomendacao="Informar o CEST compatível com o NCM e o segmento da mercadoria."))

    # FCP
    if v(icms.get("vFCP")) > 0 or v(icms.get("vFCPST")) > 0:
        alertas.append(alerta("FCP_IDENTIFICADO", "FCP", OK, f"Item {n}: FCP identificado ({moeda(icms.get('vFCP'))} próprio; {moeda(icms.get('vFCPST'))} ST).",
                              campo="vFCP", valor_xml=icms.get("vFCP"), item=n, dados=dict(dados, pFCP=icms.get("pFCP"), vFCPST=icms.get("vFCPST")),
                              motivo="Fundo de Combate à Pobreza destacado no item.", recomendacao="Conferir o percentual do FCP aplicável ao produto na UF."))
        fcp = comparar(icms.get("vFCP"), icms.get("vBCFCP") or vbc, icms.get("pFCP"), ctx)
        if fcp["comparavel"] and fcp["divergente"] and v(icms.get("vFCP")) > 0:
            alertas.append(alerta("FCP_DIVERGENTE", "FCP", DIVERGENCIA, f"Divergência de FCP no item {n}.", campo="vFCP",
                                  valor_xml=icms.get("vFCP"), valor_calculado=fcp["esperado"], diferenca=fcp["diferenca"], item=n, dados=dados,
                                  motivo="Base × percentual do FCP difere do valor informado.", recomendacao="Validar base e percentual do FCP."))

    # DIFAL (ICMSUFDest)
    difal = it.get("difal") or {}
    if difal:
        total_difal = v(difal.get("vICMSUFDest")) + v(difal.get("vFCPUFDest"))
        alertas.append(alerta("DIFAL_IDENTIFICADO", "DIFAL", ATENCAO, f"Item {n}: DIFAL identificado — {moeda(difal.get('vICMSUFDest'))} para a UF de destino e FCP destino {moeda(difal.get('vFCPUFDest'))}.",
                              campo="vICMSUFDest", valor_xml=total_difal, item=n, dados=dict(dados, **{k: difal.get(k) for k in ("vBCUFDest", "pICMSUFDest", "pICMSInter", "pFCPUFDest")}),
                              motivo="Operação interestadual destinada a consumidor final com partilha do ICMS (EC 87/2015).",
                              recomendacao="Validar alíquota interna do destino, alíquota interestadual e o recolhimento do DIFAL."))
        if difal.get("vBCUFDest") is not None and difal.get("pICMSUFDest") is not None and difal.get("pICMSInter") is not None:
            esperado = round(max(0.0, v(difal["vBCUFDest"]) * (v(difal["pICMSUFDest"]) - v(difal["pICMSInter"])) / 100.0), 2)
            dif = round(v(difal.get("vICMSUFDest")) + v(difal.get("vICMSUFRemet")) - esperado, 2)
            if abs(dif) > max(v(ctx.get("tol_abs")), esperado * v(ctx.get("tol_pct")) / 100.0):
                alertas.append(alerta("DIFAL_DIVERGENTE", "DIFAL", DIVERGENCIA, f"Divergência no cálculo do DIFAL do item {n}.", campo="vICMSUFDest",
                                      valor_xml=round(v(difal.get("vICMSUFDest")) + v(difal.get("vICMSUFRemet")), 2), valor_calculado=esperado, diferenca=dif, item=n, dados=dados,
                                      motivo="Base destino × (alíquota interna destino − interestadual) difere do total do DIFAL informado.",
                                      recomendacao="Validar a base única/dupla aplicada pela UF de destino e as alíquotas."))
    elif doc.get("destino_operacao") == "2" and doc.get("consumidor_final") == "1" and (doc.get("destinatario") or {}).get("ind_ie_dest") == "9" and v(vicms) > 0:
        alertas.append(alerta("DIFAL_POSSIVEL_AUSENCIA", "DIFAL", ATENCAO, f"Item {n}: operação interestadual a consumidor final não contribuinte sem grupo de DIFAL.",
                              campo="ICMSUFDest", item=n, dados=dict(dados, idDest="2", indFinal="1", indIEDest="9"),
                              motivo="Nesse tipo de operação normalmente há partilha do ICMS para a UF de destino.",
                              recomendacao="Validar a necessidade do grupo ICMSUFDest e do recolhimento do DIFAL."))

    linhas.append(_imposto_row(n, "ICMS", codigo, vbc, aliq, vicms, comp["esperado"], comp["diferenca"], status_linha))
    if v(vst) or v(vbcst):
        linhas.append(_imposto_row(n, "ICMS-ST", codigo, vbcst, pst, vst, st_calc, None if st_calc is None else round(v(vst) - st_calc, 2)))
    if v(icms.get("vFCP")):
        linhas.append(_imposto_row(n, "FCP", codigo, icms.get("vBCFCP") or vbc, icms.get("pFCP"), icms.get("vFCP")))
    if v(icms.get("vFCPST")):
        linhas.append(_imposto_row(n, "FCP-ST", codigo, icms.get("vBCFCPST"), icms.get("pFCPST"), icms.get("vFCPST")))
    if difal:
        linhas.append(_imposto_row(n, "DIFAL", codigo, difal.get("vBCUFDest"), difal.get("pICMSUFDest"), round(v(difal.get("vICMSUFDest")) + v(difal.get("vFCPUFDest")), 2)))
    return alertas, linhas
