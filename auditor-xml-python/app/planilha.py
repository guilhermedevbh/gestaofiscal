"""Leitura da planilha de correções (.xlsx) sincronizada do SharePoint pelo OneDrive.

O SharePoint não é acessado pela internet: a biblioteca do site SETORFISCAL é sincronizada no computador pelo OneDrive
(botão "Sincronizar" ou "Adicionar atalho a Meus arquivos") e este módulo lê o arquivo local — sempre a versão mais
recente salva por qualquer pessoa da equipe. Somente biblioteca padrão; XML interno lido com parse_xml_seguro.
"""
import datetime as _dt
import hashlib
import io
import os
import re
import time
import zipfile
from pathlib import Path

from .security import parse_xml_seguro

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
NS_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
NS_PKG = "{http://schemas.openxmlformats.org/package/2006/relationships}"
DATAS_PADRAO = {14, 15, 16, 17, 22, 27, 30, 36, 50, 57}
HORAS_PADRAO = {18, 19, 20, 21, 45, 46, 47}
MAX_ARQUIVO = 50 * 1024 * 1024
MAX_DESCOMPACTADO = 300 * 1024 * 1024
MAX_LINHAS = 20000
MAX_COLUNAS = 80


class PlanilhaErro(Exception):
    pass


def _col(ref: str) -> int:
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group(0):
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def _texto(el) -> str:
    return "".join(t.text or "" for t in el.iter(NS + "t"))


def _tipo_formato(code: str) -> str:
    c = re.sub(r'"[^"]*"|\[[^\]]*\]|\\.', "", code or "").lower()
    tem_data = bool(re.search(r"[dy]", c)) or ("m" in c and not re.search(r"[hs]", c))
    tem_hora = bool(re.search(r"[hs]", c))
    return "datahora" if tem_data and tem_hora else "data" if tem_data else "hora" if tem_hora else ""


def _serial(v: float, tipo: str) -> str:
    base = _dt.datetime(1899, 12, 30) + _dt.timedelta(seconds=round(v * 86400 / 60) * 60)  # arredonda ao minuto (evita 09:15 → 09:14)
    if tipo == "hora" or (v < 1 and tipo != "data"):
        return base.strftime("%H:%M")
    if tipo == "data" or (base.hour == 0 and base.minute == 0):
        return base.strftime("%Y-%m-%d")
    return base.strftime("%Y-%m-%dT%H:%M")


def ler_xlsx(caminho: str) -> dict:
    p = Path(caminho)
    if p.suffix.lower() not in (".xlsx", ".xlsm"):
        raise PlanilhaErro("O arquivo precisa ser .xlsx.")
    if not p.is_file():
        raise PlanilhaErro("Planilha não encontrada no caminho configurado. Verifique se a pasta do SharePoint está sincronizada pelo OneDrive.")
    if p.stat().st_size > MAX_ARQUIVO:
        raise PlanilhaErro("Planilha maior que 50 MB.")
    dados = None
    for _ in range(3):  # o Excel/OneDrive pode estar gravando o arquivo neste instante
        try:
            dados = p.read_bytes()
            break
        except PermissionError:
            time.sleep(1)
    if dados is None:
        raise PlanilhaErro("A planilha está bloqueada no momento (sendo salva). Nova tentativa em instantes.")
    try:
        z = zipfile.ZipFile(io.BytesIO(dados))
    except zipfile.BadZipFile:
        raise PlanilhaErro("O arquivo não é uma planilha .xlsx válida (talvez ainda esteja sendo baixado pelo OneDrive).")
    with z:
        if sum(i.file_size for i in z.infolist()) > MAX_DESCOMPACTADO:
            raise PlanilhaErro("Planilha recusada: conteúdo descompactado grande demais.")
        nomes = set(z.namelist())

        def xml(nome):
            return parse_xml_seguro(z.read(nome)) if nome in nomes else None

        compart = [_texto(si) for si in (xml("xl/sharedStrings.xml") or [])]
        formatos = {}
        estilos = []
        st = xml("xl/styles.xml")
        if st is not None:
            for nf in st.iter(NS + "numFmt"):
                formatos[int(nf.get("numFmtId"))] = _tipo_formato(nf.get("formatCode"))
            xfs = st.find(NS + "cellXfs")
            for xf in (xfs if xfs is not None else []):
                fid = int(xf.get("numFmtId") or 0)
                estilos.append("datahora" if fid == 22 else "data" if fid in DATAS_PADRAO else "hora" if fid in HORAS_PADRAO else formatos.get(fid, ""))

        rels = {}
        r = xml("xl/_rels/workbook.xml.rels")
        for rel in (r if r is not None else []):
            alvo = rel.get("Target") or ""
            rels[rel.get("Id")] = alvo.lstrip("/") if alvo.startswith("/") else "xl/" + alvo
        abas = []
        wb = xml("xl/workbook.xml")
        for sh in (wb.iter(NS + "sheet") if wb is not None else []):
            if sh.get("state") in ("hidden", "veryHidden"):
                continue
            alvo = rels.get(sh.get(NS_REL + "id"))
            planilha = xml(alvo) if alvo else None
            if planilha is None:
                continue
            linhas = []
            for row in planilha.iter(NS + "row"):
                if len(linhas) >= MAX_LINHAS:
                    break
                idx_linha = int(row.get("r") or len(linhas) + 1) - 1
                while len(linhas) < idx_linha:
                    linhas.append([])
                cel = []
                for c in row.iter(NS + "c"):
                    ref = c.get("r")
                    i = _col(ref) if ref else len(cel)
                    if i >= MAX_COLUNAS:
                        continue
                    t, v = c.get("t"), c.find(NS + "v")
                    if t == "s" and v is not None:
                        val = compart[int(v.text)] if v.text and int(v.text) < len(compart) else ""
                    elif t == "inlineStr":
                        is_ = c.find(NS + "is")
                        val = _texto(is_) if is_ is not None else ""
                    elif t in ("str", "e"):
                        val = v.text if v is not None and t == "str" else ""
                    elif t == "b":
                        val = "VERDADEIRO" if v is not None and v.text == "1" else "FALSO"
                    elif v is not None and v.text not in (None, ""):
                        try:
                            num = float(v.text)
                            s = int(c.get("s") or 0)
                            tipo = estilos[s] if s < len(estilos) else ""
                            val = _serial(num, tipo) if tipo else (int(num) if num.is_integer() else num)
                        except ValueError:
                            val = v.text
                    else:
                        val = ""
                    while len(cel) < i:
                        cel.append("")
                    cel.append(val)
                linhas.append(cel)
            abas.append({"nome": sh.get("name"), "linhas": linhas})

        autor, alterado = "", ""
        core = xml("docProps/core.xml")
        if core is not None:
            for el in core:
                tag = el.tag.split("}")[-1]
                if tag == "lastModifiedBy":
                    autor = (el.text or "").strip()
                elif tag == "modified":
                    alterado = (el.text or "").strip()

    mtime = _dt.datetime.fromtimestamp(p.stat().st_mtime).astimezone().isoformat(timespec="seconds")
    return {"arquivo": p.name, "modificado_em": mtime, "salvo_no_excel_em": alterado, "modificado_por": autor,
            "hash": hashlib.sha256(dados).hexdigest(), "abas": abas}


def localizar(nome_parecido: str = "CORRE", limite: int = 15, segundos: float = 8.0) -> list:
    """Procura a planilha nas pastas sincronizadas do OneDrive/SharePoint do usuário do Windows (sem baixar arquivos)."""
    casa = Path.home()
    bases = [d for d in casa.iterdir() if d.is_dir() and (d.name.lower().startswith("onedrive") or "emtel" in d.name.lower() or "sharepoint" in d.name.lower())] if casa.exists() else []
    achados, inicio = [], time.time()
    alvo = nome_parecido.lower()
    for base in bases:
        for raiz, pastas, arquivos in os.walk(base):
            if time.time() - inicio > segundos or len(achados) >= limite:
                return achados
            pastas[:] = [x for x in pastas if not x.startswith(".")]
            for a in arquivos:
                al = a.lower()
                if al.endswith(".xlsx") and alvo in al and "crpd" in al and not al.startswith("~$"):
                    achados.append(str(Path(raiz) / a))
    return achados
