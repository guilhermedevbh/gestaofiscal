"""Modelo de alerta e cálculo do status automático do documento."""
CRITICO, ATENCAO, DIVERGENCIA, OK = "CRITICO", "ATENCAO", "DIVERGENCIA", "OK"
ROTULO_GRAVIDADE = {CRITICO: "🔴 Crítico", ATENCAO: "🟠 Atenção", DIVERGENCIA: "🟡 Divergência", OK: "🟢 OK"}
ORDEM = {CRITICO: 0, DIVERGENCIA: 1, ATENCAO: 2, OK: 3}

APROVADO = "APROVADO"
APROVADO_COM_ALERTAS = "APROVADO_COM_ALERTAS"
NECESSITA_ANALISE = "NECESSITA_ANALISE"
DIVERGENCIA_FISCAL = "DIVERGENCIA_FISCAL"
ERRO_LEITURA = "ERRO_LEITURA"
ROTULO_STATUS = {
    APROVADO: "🟢 Aprovado",
    APROVADO_COM_ALERTAS: "🟡 Aprovado com alertas",
    NECESSITA_ANALISE: "🟠 Necessita análise",
    DIVERGENCIA_FISCAL: "🔴 Divergência fiscal",
    ERRO_LEITURA: "⚫ Erro na leitura",
}


def alerta(tipo, imposto, gravidade, mensagem, *, campo="", valor_xml=None, valor_calculado=None,
           diferenca=None, motivo="", recomendacao="", item=None, dados=None) -> dict:
    """Cria um alerta. 'dados' guarda os valores do XML que originaram o alerta (transparência)."""
    return {
        "tipo_alerta": tipo,
        "imposto": imposto,
        "gravidade": gravidade,
        "campo": campo,
        "valor_xml": valor_xml,
        "valor_calculado": valor_calculado,
        "diferenca": diferenca,
        "mensagem": mensagem,
        "motivo": motivo,
        "recomendacao": recomendacao,
        "item": item,
        "dados_origem": dados or {},
    }


def calcular_status(alertas: list, erros_leitura: list) -> str:
    """Regras do status automático:
    - erro de leitura → ⚫ ERRO NA LEITURA
    - algum alerta crítico → 🔴 DIVERGÊNCIA FISCAL
    - alguma divergência matemática/cadastral (🟡) → 🟠 NECESSITA ANÁLISE
    - somente alertas de atenção (🟠) → 🟡 APROVADO COM ALERTAS
    - sem alertas (ou apenas 🟢 informativos) → 🟢 APROVADO
    """
    if erros_leitura:
        return ERRO_LEITURA
    gravidades = {a["gravidade"] for a in alertas}
    if CRITICO in gravidades:
        return DIVERGENCIA_FISCAL
    if DIVERGENCIA in gravidades:
        return NECESSITA_ANALISE
    if ATENCAO in gravidades:
        return APROVADO_COM_ALERTAS
    return APROVADO


def ordenar(alertas: list) -> list:
    return sorted(alertas, key=lambda a: (ORDEM.get(a["gravidade"], 9), a.get("imposto") or "", str(a.get("item") or "")))
