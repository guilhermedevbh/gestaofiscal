"""Análise de CFOP e NCM — sempre como POSSÍVEL divergência; nunca afirma erro sem evidência suficiente."""
import re
import unicodedata

from .alertas import ATENCAO, DIVERGENCIA, alerta

ROTULO_NCM = "Possível divergência — necessita validação fiscal."

# Palavras da descrição × capítulos/posições de NCM usualmente esperados (heurística conservadora)
INDICIOS_NCM = [
    (("cerveja", "chope", "chopp"), ("2203",), "cervejas e chopes (posição 2203)"),
    (("refrigerante",), ("2202",), "refrigerantes (posição 2202)"),
    (("agua mineral",), ("2201", "2202"), "águas (posições 2201/2202)"),
    (("gasolina", "diesel", "querosene", "oleo lubrificante", "lubrificante"), ("27", "3403", "3811"), "combustíveis e lubrificantes (capítulo 27 / 3403)"),
    (("medicamento", "comprimido", "capsula", "xarope"), ("30",), "produtos farmacêuticos (capítulo 30)"),
    (("pneu",), ("4011", "4012"), "pneus (posições 4011/4012)"),
    (("cimento",), ("2523",), "cimentos (posição 2523)"),
    (("parafuso", "porca", "arruela"), ("7318", "7415", "7616", "3926"), "parafusos e afins (7318 e correlatas)"),
    (("notebook", "computador", "laptop"), ("8471",), "máquinas de processamento de dados (posição 8471)"),
    (("celular", "smartphone"), ("8517",), "telefones (posição 8517)"),
    (("papel a4", "papel sulfite", "resma"), ("4802",), "papel de escrita (posição 4802)"),
    (("cafe",), ("0901", "2101"), "café (posições 0901/2101)"),
]

SAIDA_DEVOLUCAO = re.compile(r"^[567](20[1-9]|21[0-9]|41[0-3]|55[3-6]|66[01]|92[0-9])")
ENTRADA_DEVOLUCAO = re.compile(r"^[123](20[1-9]|21[0-9]|41[01]|50[34]|55[3-4]|66[01]|91[0-9])")


def _norm(s: str) -> str:
    return unicodedata.normalize("NFD", str(s or "").lower()).encode("ascii", "ignore").decode()


def avaliar_cfop(doc: dict, it: dict):
    alertas = []
    n, cfop = it.get("numero_item"), re.sub(r"\D", "", it.get("cfop") or "")
    if not cfop:
        alertas.append(alerta("CFOP_AUSENTE", "CFOP", ATENCAO, f"Item {n}: CFOP não informado.", campo="CFOP", item=n,
                              dados={"item": n, "descricao": it.get("descricao")}, motivo="Todo item da NF-e deve ter CFOP.",
                              recomendacao="Verificar o leiaute do emissor."))
        return alertas
    tp, dest = doc.get("tipo_operacao"), doc.get("destino_operacao")
    nat = _norm(doc.get("natureza_operacao"))
    uf_emit, uf_dest = (doc.get("emitente") or {}).get("uf"), (doc.get("destinatario") or {}).get("uf")
    dados = {"item": n, "CFOP": cfop, "tpNF": tp, "idDest": dest, "natureza": doc.get("natureza_operacao"), "UF emitente": uf_emit, "UF destinatário": uf_dest}
    d = cfop[0]
    msg = "O CFOP informado merece validação considerando a natureza da operação e a UF envolvida."

    def add(tipo, texto, motivo, grav=ATENCAO):
        alertas.append(alerta(tipo, "CFOP", grav, f"Item {n}: possível divergência de CFOP — {texto}", campo="CFOP", valor_xml=cfop, item=n, dados=dados,
                              motivo=motivo, recomendacao=msg + " " + ROTULO_NCM))

    if tp == "1" and d in "123":
        add("CFOP_ENTRADA_EM_SAIDA", f"CFOP de entrada ({cfop}) em nota de saída.", "Nota de saída (tpNF=1) deve usar CFOP iniciado por 5, 6 ou 7.", DIVERGENCIA)
    if tp == "0" and d in "567":
        add("CFOP_SAIDA_EM_ENTRADA", f"CFOP de saída ({cfop}) em nota de entrada.", "Nota de entrada (tpNF=0) deve usar CFOP iniciado por 1, 2 ou 3.", DIVERGENCIA)
    esperado = {"1": "15", "2": "26", "3": "37"}.get(dest or "")
    if esperado and d not in esperado:
        add("CFOP_DESTINO", f"CFOP {cfop} incompatível com o destino da operação ({ {'1': 'interna', '2': 'interestadual', '3': 'exterior'}[dest] }).",
            "Operação interna usa CFOP 1/5, interestadual 2/6 e exterior 3/7.")
    if uf_emit and uf_dest and dest == "1" and uf_emit != uf_dest:
        add("CFOP_UF_DIFERENTES", f"operação marcada como interna, mas UFs diferentes ({uf_emit} → {uf_dest}).", "idDest=1 indica operação dentro do mesmo estado.")
    if "devolu" in nat and not (SAIDA_DEVOLUCAO.match(cfop) or ENTRADA_DEVOLUCAO.match(cfop)):
        add("CFOP_NATUREZA_DEVOLUCAO", f"natureza indica devolução, mas o CFOP {cfop} não é de devolução.", "Devoluções usam CFOPs específicos (ex.: x.201–x.209, x.410–x.413).")
    if "venda" in nat and cfop[1:2] not in ("1", "4") and cfop[1:3] not in ("65",) and cfop[1:4] not in ("551", "922", "933"):
        add("CFOP_NATUREZA_VENDA", f"natureza indica venda, mas o CFOP {cfop} não é de venda.", "Vendas usam, em regra, CFOPs x.101–x.124 ou x.401–x.405.")
    if ("remessa" in nat or "transferencia" in nat) and cfop[1:2] in ("1",) and "venda" not in nat:
        add("CFOP_NATUREZA_REMESSA", f"natureza indica remessa/transferência, mas o CFOP {cfop} é de compra/venda.", "Remessas usam x.9xx e transferências x.15x/x.55x.")
    if doc.get("finalidade") == "4" and not (SAIDA_DEVOLUCAO.match(cfop) or ENTRADA_DEVOLUCAO.match(cfop)):
        add("CFOP_FINALIDADE_DEVOLUCAO", f"NF-e de devolução (finNFe=4) com CFOP {cfop}.", "A finalidade devolução exige CFOP de devolução.")
    return alertas


def avaliar_ncm(doc: dict, it: dict):
    alertas = []
    n = it.get("numero_item")
    ncm = re.sub(r"\D", "", it.get("ncm") or "")
    cest = re.sub(r"\D", "", it.get("cest") or "")
    icms = it.get("icms") or {}
    codigo = icms.get("CST") or icms.get("CSOSN") or ""
    dados = {"item": n, "descricao": it.get("descricao"), "NCM": ncm, "CEST": cest, "origem": it.get("origem"), "CFOP": it.get("cfop"), "CST/CSOSN": codigo}

    def add(tipo, texto, motivo, grav=ATENCAO):
        alertas.append(alerta(tipo, "NCM", grav, f"Item {n}: {texto}", campo="NCM", valor_xml=ncm or it.get("ncm"), item=n, dados=dados,
                              motivo=motivo, recomendacao=ROTULO_NCM + " Confirmar a classificação na TIPI/NESH com a descrição técnica do produto."))

    if len(ncm) != 8:
        add("NCM_FORMATO", f"NCM '{it.get('ncm') or ''}' não possui 8 dígitos.", "O NCM deve ter 8 dígitos.", DIVERGENCIA)
        return alertas
    if ncm == "00000000" and str(it.get("cfop") or "")[1:2] not in ("9",) and not (it.get("issqn")):
        add("NCM_GENERICO", "NCM 00000000 usado para mercadoria.", "O código 00000000 é reservado a serviços/itens sem classificação.")
    if cest and len(cest) != 7:
        add("CEST_FORMATO", f"CEST '{it.get('cest')}' não possui 7 dígitos.", "O CEST tem 7 dígitos (SS.III.DD).", DIVERGENCIA)
    if codigo in {"10", "30", "60", "70", "201", "202", "203", "500"} and not cest:
        add("CEST_AUSENTE_ST", f"código {codigo} (substituição tributária) sem CEST.", "Mercadorias em regime de ST devem informar o CEST.")
    desc = _norm(it.get("descricao"))
    for palavras, prefixos, rotulo in INDICIOS_NCM:
        if any(p in desc for p in palavras) and not any(ncm.startswith(p) for p in prefixos):
            add("NCM_DESCRICAO", f"descrição sugere {rotulo}, mas o NCM informado é {ncm[:4]}.{ncm[4:6]}.{ncm[6:]}.",
                "A descrição do produto não corresponde ao capítulo/posição usual — pode ser kit, acessório ou classificação específica.")
            break
    if str(it.get("origem") or "") in {"1", "2", "3", "8"} and doc.get("destino_operacao") == "2" and icms.get("pICMS") not in (None, 4.0) and codigo in {"00", "20", "90"}:
        add("ORIGEM_IMPORTADO_ALIQ", f"origem {it.get('origem')} (importado) em operação interestadual com alíquota {icms.get('pICMS')}%.",
            "Mercadoria importada em operação interestadual costuma usar 4% (Res. Senado 13/2012), salvo exceções (ex.: sem similar nacional).")
    return alertas
