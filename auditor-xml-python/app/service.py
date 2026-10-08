"""Orquestração: Upload → Parser → Normalizador → Motor Fiscal → Alertas → Explicador → Banco → JSON."""
import os
import sqlite3

from . import config, database
from .engine import explicador, motor
from .engine.alertas import ERRO_LEITURA, ROTULO_STATUS
from .normalizers import normalizar
from .parser import detectar_tipo
from .security import UploadInvalido, XMLInseguro, parse_xml_seguro, sha256, validar_upload


def _armazenar(data: bytes, hash_xml: str) -> str:
    """Grava o XML renomeado pelo hash, fora da área pública. Nunca usa o nome enviado pelo usuário no caminho."""
    nome = f"{hash_xml}.xml"
    destino = (config.XML_DIR / nome).resolve()
    if destino.parent != config.XML_DIR.resolve():
        raise UploadInvalido("Caminho de armazenamento inválido.")
    if not destino.exists():
        tmp = destino.with_suffix(".tmp")
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, destino)
        try:
            os.chmod(destino, 0o600)
        except OSError:
            pass
    return nome


def analisar_xml(data: bytes) -> dict:
    """Parser + normalizador + motor + explicações, sem gravar (usado também pelos testes)."""
    root = parse_xml_seguro(data)
    deteccao = detectar_tipo(root)
    doc = normalizar(root, deteccao)
    ctx = database.obter_config()
    resultado = motor.executar(doc, ctx)
    explicador.explicar_todos(resultado["alertas"], doc)
    return {"documento": doc, "resultado": resultado}


def processar_upload(nome_arquivo: str, content_type: str, data: bytes, usuario: dict, ip: str = "") -> dict:
    nome_usuario = usuario["nome"]
    try:
        nome_limpo = validar_upload(nome_arquivo, content_type, data)
    except UploadInvalido as exc:
        database.registrar_historico(nome_usuario, "UPLOAD_RECUSADO", arquivo=str(nome_arquivo)[:120], resultado="RECUSADO",
                                     detalhes={"motivo": str(exc), "seguranca": isinstance(exc, XMLInseguro)}, ip=ip)
        return {"ok": False, "status": ERRO_LEITURA, "status_rotulo": ROTULO_STATUS[ERRO_LEITURA], "erro": str(exc), "arquivo": str(nome_arquivo)[:120]}

    hash_xml = sha256(data)
    try:
        analise = analisar_xml(data)
    except UploadInvalido as exc:
        database.registrar_historico(nome_usuario, "LEITURA_FALHOU", arquivo=nome_limpo, hash_xml=hash_xml, resultado=ERRO_LEITURA,
                                     detalhes={"motivo": str(exc)}, ip=ip)
        return {"ok": False, "status": ERRO_LEITURA, "status_rotulo": ROTULO_STATUS[ERRO_LEITURA], "erro": str(exc), "arquivo": nome_limpo, "hash": hash_xml}

    doc, resultado = analise["documento"], analise["resultado"]
    if doc["tipo"] == "DESCONHECIDO":
        database.registrar_historico(nome_usuario, "LEITURA_FALHOU", arquivo=nome_limpo, hash_xml=hash_xml, resultado=ERRO_LEITURA,
                                     detalhes={"motivo": "Tipo de documento não identificado"}, ip=ip)
        return {"ok": False, "status": ERRO_LEITURA, "status_rotulo": ROTULO_STATUS[ERRO_LEITURA],
                "erro": "O XML não é uma NF-e nem uma NFS-e reconhecida.", "arquivo": nome_limpo, "hash": hash_xml}

    existente, motivo = database.buscar_duplicado(hash_xml, doc.get("chave"), doc.get("numero"), doc.get("serie"),
                                                  doc["emitente"].get("documento"), doc["tipo"])
    if existente:
        database.registrar_historico(nome_usuario, "DUPLICIDADE_DETECTADA", documento_id=existente["id"], arquivo=nome_limpo, hash_xml=hash_xml,
                                     resultado="DUPLICADO", detalhes={"criterio": motivo}, ip=ip)
        return {"ok": False, "duplicado": True, "arquivo": nome_limpo, "hash": hash_xml, "criterio": motivo,
                "mensagem": "⚠️ Este documento já foi importado anteriormente.", "existente": existente,
                "existente_status_rotulo": ROTULO_STATUS.get(existente["status"], existente["status"])}

    arquivo_interno = _armazenar(data, hash_xml)
    try:
        doc_id = database.salvar_documento(doc, resultado, arquivo_original=nome_limpo, arquivo_xml=arquivo_interno, hash_xml=hash_xml, usuario=nome_usuario)
    except sqlite3.IntegrityError:  # dois envios simultâneos do mesmo arquivo
        existente, motivo = database.buscar_duplicado(hash_xml, "", "", "", "", doc["tipo"])
        return {"ok": False, "duplicado": True, "arquivo": nome_limpo, "hash": hash_xml, "criterio": motivo or "mesmo arquivo",
                "mensagem": "⚠️ Este documento já foi importado anteriormente.", "existente": existente,
                "existente_status_rotulo": ROTULO_STATUS.get((existente or {}).get("status"), "")}
    database.registrar_historico(nome_usuario, "UPLOAD_PROCESSADO", documento_id=doc_id, arquivo=nome_limpo, hash_xml=hash_xml, resultado=resultado["status"],
                                 detalhes={"tipo": doc["tipo"], "numero": doc.get("numero"), "alertas": resultado["resumo"]["qtd_alertas"],
                                           "gravidades": sorted({a["gravidade"] for a in resultado["alertas"]})}, ip=ip)
    return {"ok": True, "id": doc_id, "arquivo": nome_limpo, "hash": hash_xml, "status": resultado["status"],
            "status_rotulo": ROTULO_STATUS[resultado["status"]], "resumo": resultado["resumo"],
            "tipo": doc["tipo"], "numero": doc.get("numero"), "emitente": doc["emitente"].get("nome"), "avisos": doc.get("avisos_leitura")}
