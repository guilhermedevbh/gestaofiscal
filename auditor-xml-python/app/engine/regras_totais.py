"""Conferência dos totais da NF-e: soma dos itens × ICMSTot e recomposição do valor da nota."""
from .alertas import CRITICO, DIVERGENCIA, alerta
from .calculos import comparar_valores, moeda, v

CAMPOS = [
    ("vBC", "Base do ICMS", lambda it: (it.get("icms") or {}).get("vBC")),
    ("vICMS", "ICMS", lambda it: (it.get("icms") or {}).get("vICMS")),
    ("vBCST", "Base do ICMS-ST", lambda it: (it.get("icms") or {}).get("vBCST")),
    ("vST", "ICMS-ST", lambda it: (it.get("icms") or {}).get("vICMSST")),
    ("vFCP", "FCP", lambda it: (it.get("icms") or {}).get("vFCP")),
    ("vFCPST", "FCP-ST", lambda it: (it.get("icms") or {}).get("vFCPST")),
    ("vIPI", "IPI", lambda it: (it.get("ipi") or {}).get("vIPI")),
    ("vPIS", "PIS", lambda it: (it.get("pis") or {}).get("v")),
    ("vCOFINS", "COFINS", lambda it: (it.get("cofins") or {}).get("v")),
    ("vProd", "Produtos", lambda it: it.get("valor_total") if it.get("ind_tot", "1") != "0" else 0.0),
    ("vFrete", "Frete", lambda it: it.get("frete")),
    ("vSeg", "Seguro", lambda it: it.get("seguro")),
    ("vDesc", "Descontos", lambda it: it.get("desconto")),
    ("vOutro", "Outras despesas", lambda it: it.get("outras_despesas")),
]


def avaliar_totais(doc: dict, ctx: dict):
    alertas = []
    tot = doc.get("totais") or {}
    itens = doc.get("itens") or []
    if not tot or not itens:
        return alertas
    for campo, rotulo, getter in CAMPOS:
        if tot.get(campo) is None:
            continue
        soma = round(sum(v(getter(it)) for it in itens), 2)
        comp = comparar_valores(tot.get(campo), soma, ctx)
        if comp["divergente"]:
            alertas.append(alerta(f"TOTAL_{campo}_DIVERGENTE", "Totais", DIVERGENCIA, f"Total de {rotulo} da nota diferente da soma dos itens.",
                                  campo=campo, valor_xml=tot.get(campo), valor_calculado=soma, diferenca=comp["diferenca"],
                                  dados={"campo": campo, "total_informado": tot.get(campo), "soma_itens": soma, "itens": len(itens)},
                                  motivo=f"Soma dos itens = {moeda(soma)}; total informado = {moeda(tot.get(campo))}.",
                                  recomendacao="Validar arredondamentos e itens com valores fora do total (indTot)."))
    # Recomposição do vNF (regra de validação da SEFAZ)
    if tot.get("vNF") is not None:
        esperado = (v(tot.get("vProd")) - v(tot.get("vDesc")) - v(tot.get("vICMSDeson")) + v(tot.get("vST")) + v(tot.get("vFCPST"))
                    + v(tot.get("vFrete")) + v(tot.get("vSeg")) + v(tot.get("vOutro")) + v(tot.get("vII")) + v(tot.get("vIPI")) + v(tot.get("vIPIDevol")))
        servicos = (doc.get("totais_issqn") or {}).get("vServ")
        esperado = round(esperado + v(servicos), 2)
        comp = comparar_valores(tot.get("vNF"), esperado, ctx)
        if comp["divergente"]:
            # Desoneração pode ou não ser abatida (indDeduzDeson) — por isso a diferença igual ao vICMSDeson é tratada como divergência simples
            alternativo = round(esperado + v(tot.get("vICMSDeson")), 2)
            if abs(v(tot.get("vNF")) - alternativo) <= max(v(ctx.get("tol_abs")), 0.01):
                return alertas
            grav = CRITICO if abs(comp["diferenca"]) > 1 else DIVERGENCIA
            alertas.append(alerta("TOTAL_VNF_DIVERGENTE", "Totais", grav, "Valor total da NF-e não fecha com a composição dos totais.",
                                  campo="vNF", valor_xml=tot.get("vNF"), valor_calculado=esperado, diferenca=comp["diferenca"],
                                  dados={k: tot.get(k) for k in ("vProd", "vDesc", "vICMSDeson", "vST", "vFCPST", "vFrete", "vSeg", "vOutro", "vII", "vIPI", "vIPIDevol", "vNF")},
                                  motivo="vNF = vProd − vDesc − vICMSDeson + vST + vFCPST + vFrete + vSeg + vOutro + vII + vIPI + vIPIDevol (+ serviços).",
                                  recomendacao="Validar os totais da nota antes da entrada/pagamento."))
    return alertas
