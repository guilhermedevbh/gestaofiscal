"""Estrutura fiscal única usada por todo o motor, independentemente do padrão do XML."""
import re


def so_digitos_ou_alfa(valor: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", str(valor or "")).upper()


def parte_vazia() -> dict:
    return {"documento": "", "nome": "", "ie": "", "im": "", "municipio": "", "codigo_municipio": "", "uf": "", "crt": ""}


def documento_vazio(tipo: str, padrao: str = "") -> dict:
    return {
        "tipo": tipo,                 # NFE | NFSE | CTE | DESCONHECIDO
        "padrao": padrao,
        "modelo": "",
        "numero": "",
        "serie": "",
        "chave": "",
        "codigo_verificacao": "",
        "data_emissao": "",
        "data_saida": "",             # saída (NF-e) / competência ou prestação (NFS-e)
        "natureza_operacao": "",
        "tipo_operacao": "",          # 0 entrada / 1 saída (NF-e)
        "finalidade": "",
        "destino_operacao": "",       # 1 interna / 2 interestadual / 3 exterior
        "consumidor_final": "",
        "emitente": parte_vazia(),
        "destinatario": parte_vazia(),
        "municipio": "",
        "uf": "",
        "valor_total": 0.0,
        "itens": [],
        "totais": {},
        "servico": {},
        "retencoes": {"irrf": 0.0, "inss": 0.0, "pis": 0.0, "cofins": 0.0, "csll": 0.0, "iss": 0.0},
        "valor_liquido": None,
        "informacoes_adicionais": "",
        "status_documento": "",
        "protocolo": "",
        "erros_leitura": [],
        "avisos_leitura": [],
    }


def descricao_finalidade(codigo: str) -> str:
    return {"1": "Normal", "2": "Complementar", "3": "Ajuste", "4": "Devolução de mercadoria"}.get(str(codigo), str(codigo or ""))


def descricao_tipo_operacao(codigo: str) -> str:
    return {"0": "Entrada", "1": "Saída"}.get(str(codigo), str(codigo or ""))


def descricao_destino(codigo: str) -> str:
    return {"1": "Operação interna", "2": "Operação interestadual", "3": "Operação com exterior"}.get(str(codigo), str(codigo or ""))
