"""Inteligência fiscal — explica cada alerta em linguagem simples, citando os dados que o originaram.

É um ASSISTENTE de análise baseado em regras transparentes (sem envio de dados a serviços externos).
Não substitui a validação fiscal: as frases usam "possível", "indício" e "necessita validação"
sempre que a evidência não é conclusiva, e nunca citam legislação que não esteja na regra.
"""
from .alertas import ROTULO_GRAVIDADE
from .calculos import moeda, pct

TITULOS = {
    "RETENCAO_ISS": "ISS retido",
    "ICMS_VALOR_DIVERGENTE": "Divergência de ICMS",
    "ICMS_ST_DIVERGENTE": "Divergência de ICMS-ST",
    "DIFAL_IDENTIFICADO": "DIFAL identificado",
    "TOTAL_VNF_DIVERGENTE": "Total da nota não fecha",
    "LIQUIDO_DIVERGENTE": "Valor líquido divergente",
}


def _e_percentual(a: dict) -> bool:
    campo = str(a.get("campo") or "").lower()
    return "aliq" in campo or campo in ("picms", "pipi", "pfcp", "picmsst", "pcredsn") or a["tipo_alerta"].endswith("_PERCENTUAL")


def _valor(x, percentual: bool):
    if isinstance(x, (int, float)):
        return pct(x) if percentual else moeda(x)
    return str(x) if x not in (None, "") else "—"


def explicar(a: dict, doc: dict) -> dict:
    titulo = TITULOS.get(a["tipo_alerta"]) or a["mensagem"].split(":")[0][:80]
    partes = [a["mensagem"]]
    retencao_simples = a["tipo_alerta"].startswith("RETENCAO_") and not a["tipo_alerta"].endswith("_PERCENTUAL")
    if a.get("valor_xml") is not None and a.get("valor_calculado") is not None and not retencao_simples:
        perc = _e_percentual(a)
        partes.append(f"Valor no XML: {_valor(a['valor_xml'], perc)}; valor calculado/esperado: {_valor(a['valor_calculado'], perc)}"
                      + (f"; diferença: {pct(a['diferenca']).replace('%', ' p.p.') if perc else moeda(a['diferenca'])}." if isinstance(a.get("diferenca"), (int, float)) else "."))
    if a.get("motivo"):
        partes.append(a["motivo"])
    if retencao_simples:
        liquido = doc.get("valor_liquido")
        partes.append(f"O valor retido altera o valor líquido a pagar ao emitente (líquido considerado: {moeda(liquido)}).")
    texto = " ".join(p.strip() for p in partes if p)
    return {
        "titulo": f"{ROTULO_GRAVIDADE.get(a['gravidade'], a['gravidade'])} — {titulo}",
        "explicacao": texto,
        "recomendacao": a.get("recomendacao") or "Necessita validação fiscal.",
        "dados_origem": a.get("dados_origem") or {},
        "aviso": "Análise automática de apoio. Não substitui a validação fiscal do responsável.",
    }


def explicar_todos(alertas: list, doc: dict) -> list:
    for a in alertas:
        a["explicacao"] = explicar(a, doc)
    return alertas
