"""Regras de ISS (NFS-e e ISSQN da NF-e conjugada) e de retenções federais/municipais."""
import re

from .alertas import ATENCAO, CRITICO, DIVERGENCIA, OK, alerta
from .calculos import comparar, comparar_valores, moeda, pct, severidade_diferenca, v

NOME_RETENCAO = {"irrf": "IRRF", "inss": "INSS", "pis": "PIS", "cofins": "COFINS", "csll": "CSLL", "iss": "ISS"}
# Percentuais usuais de referência (apenas para conferência informativa — não são afirmação de regra aplicável ao caso)
REFERENCIA_RETENCAO = {"irrf": (1.0, 1.5), "inss": (11.0, 3.5), "pis": (0.65,), "cofins": (3.0,), "csll": (1.0,)}


def avaliar_iss(doc: dict, ctx: dict):
    alertas, linhas = [], []
    s = doc.get("servico") or {}
    if doc.get("tipo") != "NFSE":
        return alertas, linhas
    base, aliq, viss = s.get("base_iss"), s.get("aliquota_iss"), s.get("valor_iss")
    v_serv = s.get("valor_servicos")
    simples = str(s.get("optante_simples") or "").strip().lower() in ("1", "true", "sim", "s")
    dados = {"valor_servicos": v_serv, "base_iss": base, "aliquota_iss": aliq, "valor_iss": viss,
             "item_lc116": s.get("item_lc116"), "codigo_servico": s.get("codigo_servico"),
             "municipio_incidencia": s.get("municipio_incidencia"), "iss_retido": s.get("iss_retido")}

    if viss is None and not s.get("iss_retido"):
        alertas.append(alerta("ISS_NAO_INFORMADO", "ISS", ATENCAO if not simples else OK,
                              "ISS não informado no XML." + (" Prestador optante pelo Simples Nacional." if simples else ""),
                              campo="ValorIss", dados=dados,
                              motivo="Não foi encontrado valor de ISS destacado na NFS-e.",
                              recomendacao="Verificar se o serviço é isento/imune, se o prestador recolhe pelo Simples Nacional ou se o ISS é devido em outro município."))
    comp = comparar(viss, base, aliq, ctx) if viss is not None else {"comparavel": False, "esperado": None, "diferenca": None, "divergente": False}
    status = "OK"
    if comp["comparavel"] and comp["divergente"]:
        status = severidade_diferenca(comp["diferenca"], comp["esperado"])
        alertas.append(alerta("ISS_VALOR_DIVERGENTE", "ISS", status, "Divergência no valor do ISS.", campo="ValorIss", valor_xml=viss,
                              valor_calculado=comp["esperado"], diferenca=comp["diferenca"], dados=dados,
                              motivo=f"Base {moeda(base)} × alíquota {pct(aliq)} = {moeda(comp['esperado'])}.",
                              recomendacao="Validar base de cálculo (deduções e descontos incondicionados) e alíquota do município."))
    if aliq is not None and v(aliq) > 0 and (v(aliq) < 2.0 or v(aliq) > 5.0):
        alertas.append(alerta("ISS_ALIQ_FORA_FAIXA", "ISS", ATENCAO, f"Alíquota de ISS de {pct(aliq)} fora da faixa geral de 2% a 5%.",
                              campo="Aliquota", valor_xml=aliq, valor_calculado="2% a 5%", dados=dados,
                              motivo="A LC 116/2003 (com a LC 157/2016) fixa, em regra, mínimo de 2% e máximo de 5%; há exceções legais (subitens 7.02, 7.05 e 16.01).",
                              recomendacao="Confirmar a alíquota na legislação do município de incidência."))
    if base is not None and v_serv is not None:
        base_max = v(v_serv) - v(s.get("deducoes")) - v(s.get("desconto_incondicionado"))
        if v(base) > v(v_serv) + 0.01 or (v(base) < base_max - max(1.0, base_max * 0.01) and not s.get("deducoes")):
            alertas.append(alerta("ISS_BASE_INCONSISTENTE", "ISS", DIVERGENCIA, "Base de cálculo do ISS inconsistente com o valor dos serviços.",
                                  campo="BaseCalculo", valor_xml=base, valor_calculado=round(base_max, 2), diferenca=round(v(base) - base_max, 2), dados=dados,
                                  motivo="Base esperada = valor dos serviços − deduções − desconto incondicionado.",
                                  recomendacao="Validar deduções legais, descontos incondicionados e a base informada."))
    item = s.get("item_lc116") or ""
    if not item and not s.get("codigo_servico"):
        alertas.append(alerta("ISS_SEM_CODIGO_SERVICO", "ISS", ATENCAO, "Código do serviço / item da LC 116 não informado.", campo="ItemListaServico", dados=dados,
                              motivo="Sem o código do serviço não é possível conferir alíquota, retenção e local de incidência.",
                              recomendacao="Solicitar ao prestador a NFS-e com o item da lista de serviços."))
    elif item and not re.match(r"^\d{2}\.\d{2}$", item):
        alertas.append(alerta("ISS_CODIGO_FORMATO", "ISS", ATENCAO, f"Item da LC 116 em formato não padrão: {item}.", campo="ItemListaServico", valor_xml=item, dados=dados,
                              motivo="O item da lista de serviços segue o formato NN.NN.", recomendacao="Confirmar o código do serviço com o prestador."))
    elif item and int(item[:2]) > 40:
        alertas.append(alerta("ISS_CODIGO_INEXISTENTE", "ISS", DIVERGENCIA, f"Item {item} não existe na lista da LC 116 (grupos 01 a 40).", campo="ItemListaServico",
                              valor_xml=item, dados=dados, motivo="A lista anexa à LC 116/2003 vai do grupo 01 ao 40.",
                              recomendacao="Possível código de serviço incompatível — necessita validação fiscal."))
    mi, mp = s.get("municipio_incidencia"), (doc.get("emitente") or {}).get("codigo_municipio")
    if mi and mp and re.sub(r"\D", "", mi) and re.sub(r"\D", "", mp) and re.sub(r"\D", "", mi) != re.sub(r"\D", "", mp):
        alertas.append(alerta("ISS_MUNICIPIO_DIFERENTE", "ISS", ATENCAO, "Município de incidência do ISS diferente do município do prestador.",
                              campo="MunicipioIncidencia", valor_xml=mi, valor_calculado=mp, dados=dados,
                              motivo="Nos casos do art. 3º da LC 116/2003 o ISS é devido no local da prestação/tomador.",
                              recomendacao="Validar o local de incidência, a retenção e o cadastro do prestador no município do tomador (CPOM, quando houver)."))
    if s.get("iss_retido"):
        alertas.append(alerta("RETENCAO_ISS", "ISS", ATENCAO, f"Foi identificada retenção de ISS no valor de {moeda(s.get('valor_iss_retido'))}.",
                              campo="IssRetido", valor_xml=s.get("valor_iss_retido"), dados=dados,
                              motivo="O tomador é responsável pelo recolhimento do ISS retido e o valor reduz o líquido a pagar.",
                              recomendacao="Validar a retenção, emitir a guia do ISS retido no prazo do município e ajustar o valor a pagar."))
    linhas.append({"imposto": "ISS", "item": None, "cst_csosn": s.get("item_lc116"), "base_calculo": base, "aliquota": aliq, "valor": viss,
                   "valor_calculado": comp["esperado"], "diferenca": comp["diferenca"], "status": status})
    return alertas, linhas


def avaliar_issqn_nfe(doc: dict, it: dict, ctx: dict):
    """ISSQN em NF-e conjugada (serviço dentro da NF-e)."""
    alertas, linhas = [], []
    g = it.get("issqn") or {}
    if not g:
        return alertas, linhas
    n = it.get("numero_item")
    comp = comparar(g.get("vISSQN"), g.get("vBC"), g.get("vAliq"), ctx)
    status = "OK"
    if comp["comparavel"] and comp["divergente"]:
        status = severidade_diferenca(comp["diferenca"], comp["esperado"])
        alertas.append(alerta("ISSQN_NFE_DIVERGENTE", "ISS", status, f"Divergência de ISSQN no item {n}.", campo="vISSQN", valor_xml=g.get("vISSQN"),
                              valor_calculado=comp["esperado"], diferenca=comp["diferenca"], item=n, dados=dict(g, item=n),
                              motivo="Base × alíquota do ISSQN difere do valor informado.", recomendacao="Validar base e alíquota municipal."))
    linhas.append({"imposto": "ISS", "item": n, "cst_csosn": g.get("cListServ"), "base_calculo": g.get("vBC"), "aliquota": g.get("vAliq"),
                   "valor": g.get("vISSQN"), "valor_calculado": comp["esperado"], "diferenca": comp["diferenca"], "status": status})
    return alertas, linhas


def avaliar_retencoes(doc: dict, ctx: dict):
    alertas, linhas = [], []
    ret = doc.get("retencoes") or {}
    base_ref = v((doc.get("servico") or {}).get("valor_servicos")) or v(doc.get("valor_total"))
    for chave, valor in ret.items():
        if chave == "iss" or not v(valor):
            continue
        nome = NOME_RETENCAO[chave]
        perc = round(v(valor) / base_ref * 100, 2) if base_ref else None
        dados = {"retencao": nome, "valor": valor, "base_referencia": base_ref, "percentual_efetivo": perc}
        alertas.append(alerta(f"RETENCAO_{nome}", nome, ATENCAO, f"Foi identificada retenção de {nome} no valor de {moeda(valor)}.",
                              campo=f"Valor{nome}", valor_xml=valor, valor_calculado=perc, dados=dados,
                              motivo=f"Retenção de {nome} na fonte ({pct(perc)} do valor do documento).",
                              recomendacao=f"Validar a obrigatoriedade da retenção de {nome}, recolher no prazo e descontar do valor a pagar."))
        refs = REFERENCIA_RETENCAO.get(chave)
        if refs and perc is not None and all(abs(perc - r) > 0.06 for r in refs):
            alertas.append(alerta(f"RETENCAO_{nome}_PERCENTUAL", nome, ATENCAO, f"Percentual de retenção de {nome} ({pct(perc)}) diferente dos percentuais usuais ({', '.join(pct(r) for r in refs)}).",
                                  campo=f"Valor{nome}", valor_xml=perc, valor_calculado=" ou ".join(pct(r) for r in refs), dados=dados,
                                  motivo="O percentual efetivo não coincide com as alíquotas de retenção mais comuns; pode haver base reduzida, dispensa parcial ou erro.",
                                  recomendacao="Necessita validação fiscal — confirmar a base de cálculo e a regra de retenção aplicável ao serviço."))
        linhas.append({"imposto": f"Retenção {nome}", "item": None, "cst_csosn": "", "base_calculo": base_ref, "aliquota": perc,
                       "valor": valor, "valor_calculado": None, "diferenca": None, "status": "OK"})
    if v(ret.get("iss")):
        linhas.append({"imposto": "Retenção ISS", "item": None, "cst_csosn": "", "base_calculo": (doc.get("servico") or {}).get("base_iss"),
                       "aliquota": (doc.get("servico") or {}).get("aliquota_iss"), "valor": ret.get("iss"), "valor_calculado": None, "diferenca": None, "status": "OK"})
    # Valor líquido: bruto − retenções − descontos
    if doc.get("tipo") == "NFSE" and doc.get("valor_liquido_informado") is not None:
        comp = comparar_valores(doc["valor_liquido_informado"], doc.get("valor_liquido_calculado"), ctx)
        if comp["divergente"]:
            alertas.append(alerta("LIQUIDO_DIVERGENTE", "Retenções", DIVERGENCIA, "Valor líquido da NFS-e diferente do cálculo bruto − retenções − descontos.",
                                  campo="ValorLiquido", valor_xml=doc["valor_liquido_informado"], valor_calculado=comp["esperado"], diferenca=comp["diferenca"],
                                  dados={"valor_servicos": doc.get("valor_total"), "retencoes": ret,
                                         "descontos": v((doc.get("servico") or {}).get("desconto_incondicionado")) + v((doc.get("servico") or {}).get("desconto_condicionado"))},
                                  motivo="O valor líquido informado não fecha com o valor bruto menos retenções e descontos.",
                                  recomendacao="Conferir as retenções antes do pagamento ao prestador."))
    return alertas, linhas
