# Gestão Fiscal — site + banco de dados (serviço Python) em um único endereço https://
# Os dados ficam no disco persistente montado em /data (configurado na hospedagem).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    XML_AUDITOR_DATA=/data \
    XML_AUDITOR_SITE=/app/site/index.html \
    XML_AUDITOR_HOST=0.0.0.0 \
    XML_AUDITOR_CONFIAR_PROXY=1

WORKDIR /app
# (roda como root dentro do contêiner porque o disco persistente da hospedagem é montado com dono root)
RUN pip install --no-cache-dir defusedxml==0.7.1 && mkdir -p /data

COPY auditor-xml-python/app ./app
COPY auditor-xml-python/gerenciar.py ./gerenciar.py
COPY Gestao_Fiscal_2026_CRPD_v10.html ./site/index.html

EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8765')+'/health',timeout=4)"
CMD ["python", "gerenciar.py", "servidor"]
