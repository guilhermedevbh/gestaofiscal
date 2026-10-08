# Auditoria Fiscal de XML (serviço Python)

Serviço que **lê, interpreta, confere, recalcula, compara, alerta, explica e registra** XMLs de NF-e (modelo 55/65) e NFS-e.
A aba **📄 Leitura XML / Auditoria Fiscal** do site `Gestao_Fiscal_2026_CRPD_v10.html` é a interface deste serviço.

## Instalação e uso (Windows)
1. Instale o **Python 3.9 ou superior**: https://www.python.org/downloads/ (marque *Add python.exe to PATH*).
2. Dê dois cliques em **`iniciar-auditor-xml.cmd`**.
   - Na primeira vez, ele cria o banco e o usuário **administrador**.
   - O **token de acesso é exibido uma única vez**: guarde-o.
3. No site, abra **Auditoria → Leitura XML / Auditoria Fiscal**, informe o token e clique em **Conectar**.
4. Opcional (recomendado): `pip install defusedxml` acrescenta uma camada extra contra XML malicioso.

Outros comandos:
```
python gerenciar.py criar-usuario "Ana Fiscal" analista   # perfis: admin | analista | consulta
python gerenciar.py usuarios
python gerenciar.py desativar "Ana Fiscal"
python -m unittest -v                                     # testes automatizados
```

## Banco de dados do site (tudo o que é salvo no site)
O mesmo serviço também guarda **todos os dados do site** e o **registro de validações**.

1. Inicie o serviço com `iniciar-auditor-xml.cmd`.
2. No site, clique no indicador **🗄 Banco** no topo da página.
3. Informe o token e clique em **Conectar**. Conectar pela aba Leitura XML também liga a sincronização.

**O que fica salvo (tabela `dados_site`):**
- Controle de Correções, Quadro Kanban, calendários, certidões, Validador SPED, auditoria de XML e simulações.
- Cada gravação gera uma nova versão em `dados_site_versoes`.
- As versões antigas **nunca são apagadas**: triggers impedem alteração e exclusão.
- No painel, **Dados salvos → Versões** mostra cada versão e permite restaurar qualquer uma delas.

**Sem conexão:**
- O site continua salvando no navegador.
- As alterações ficam numa fila e são enviadas automaticamente quando o banco for conectado.

**Dois computadores alterando o mesmo módulo:**
- As listas de registros são mescladas por `id`.
- Para cada registro, vale a alteração mais recente.
- Nenhuma versão se perde.

**Registro de validações (tabela `registro_validacoes`, somente inclusão):**
- O que é registrado:
  - finalizações e reaberturas do Controle de Correções;
  - validações SPED;
  - XMLs auditados e decisões sobre divergências;
  - consultas fiscais;
  - ações em Notas fiscais.
- Cada registro guarda o usuário do site, o usuário do token, a data/hora e o IP.
- O painel tem filtros e exportação em CSV.

**Perfis:** perfil *consulta* apenas lê; *analista* e *admin* gravam.

Para a equipe usar o **mesmo banco** em vários computadores, o serviço precisa rodar em um servidor da rede atrás de HTTPS (veja Segurança). Na configuração padrão, ele atende apenas este computador (127.0.0.1).

## Planilha de correções do SharePoint → Controle de Correções
A aba **Controle de Correções** recebe automaticamente as alterações da planilha **CORREÇÕES CRPD.xlsx** (site SETORFISCAL).

**Como é lida:** o SharePoint não é acessado pela internet. A biblioteca é sincronizada pelo **OneDrive** e o serviço lê o arquivo local (`app/planilha.py`, somente biblioteca padrão). Por isso não é preciso registrar um aplicativo no Azure nem guardar senha.

**Configuração (uma vez):**
1. No SharePoint, abra SETORFISCAL → Documentos e clique em **Sincronizar**.
2. No Explorador de Arquivos, clique com o botão direito na planilha → **Sempre manter neste dispositivo**.
3. No site, abra Controle de Correções → **⚙ Configurar** → **Localizar automaticamente** (ou cole o caminho) → **Salvar e sincronizar**. É preciso um token *admin*.
   - Alternativa: definir a variável de ambiente `XML_AUDITOR_PLANILHA` com o caminho.

**Funcionamento:**
- **Verificação:** o site consulta a planilha a cada 30 s. O serviço só relê o arquivo quando a data ou o tamanho mudam.
- **Linhas novas:** viram correções novas, com responsável (já com a cor da equipe), motivo, datas e status.
- **Linhas alteradas:** aplicam somente os campos que mudaram **na planilha** desde a última leitura. O que foi feito no site (início, finalização, observações) é preservado.
- **Autoria:** o histórico registra *"Planilha SharePoint — nome de quem salvou"*, lido de `docProps/core.xml`, e o Registro de validações recebe um resumo de cada sincronização.
- **Linhas apagadas da planilha:** não apagam registros do site.

## Arquitetura
```
Upload (server.py) → Segurança (security.py) → Parser (parser.py) → Normalizador (normalizers/)
→ Motor fiscal (engine/motor.py + regras_*.py) → Alertas (engine/alertas.py) → Explicador (engine/explicador.py)
→ Banco SQLite (database.py) → JSON para a interface
```

| Camada | Arquivo | Função |
|---|---|---|
| API | `app/server.py` | Rotas, autenticação por token, perfis, rate limit, CORS, cabeçalhos de segurança |
| Segurança | `app/security.py` | Extensão, MIME, tamanho, conteúdo, bloqueio de DTD/entidades (XXE), nome sanitizado, SHA-256 |
| Parser | `app/parser.py` | Leitura independente de namespace e identificação automática NF-e / NFS-e / CT-e |
| Normalização | `app/normalizers/nfe.py`, `nfse.py`, `cte.py` | Estrutura fiscal única. A NFS-e cobre o Padrão Nacional (ADN), ABRASF 1.0/2.x, São Paulo e um modo genérico por sinônimos |
| Motor fiscal | `app/engine/regras_icms.py` | ICMS, ICMS-ST, FCP, DIFAL, CST × CSOSN × CRT, alíquota × destino |
| | `app/engine/regras_ipi_pis_cofins.py` | IPI, PIS e COFINS (CST, alíquota, valor, quantidade) |
| | `app/engine/regras_iss_retencoes.py` | ISS (alíquota 2–5%, base, item LC 116, município de incidência, retenção) e IRRF/INSS/PIS/COFINS/CSLL |
| | `app/engine/regras_cfop_ncm.py` | CFOP × tipo de operação × destino × natureza; NCM × CEST × descrição (sempre como *possível divergência*) |
| | `app/engine/regras_totais.py` | Soma dos itens × totais e recomposição do vNF |
| Alertas/status | `app/engine/alertas.py` | 🔴 Crítico · 🟠 Atenção · 🟡 Divergência · 🟢 OK; status automático |
| Explicação | `app/engine/explicador.py` | Texto em linguagem simples com os dados de origem, sem afirmar irregularidade |
| Banco | `app/database.py` | Tabelas `documentos_fiscais`, `itens_documento`, `impostos_documento`, `alertas_fiscais`, `historico`, `usuarios` e `configuracoes` |
| Orquestração | `app/service.py` | Pipeline completo, duplicidade e armazenamento do XML |

### Status automático
| Status | Quando é atribuído |
|---|---|
| ⚫ **Erro na leitura** | XML inválido, sem os grupos essenciais ou de tipo não reconhecido |
| 🔴 **Divergência fiscal** | Há ao menos um alerta crítico. Exemplos: imposto sem base, CST incompatível, diferença acima de 5% ou de R$ 100, documento cancelado ou de homologação |
| 🟠 **Necessita análise** | Há divergência matemática ou cadastral (🟡) |
| 🟡 **Aprovado com alertas** | Há apenas pontos de atenção (🟠), como retenções, DIFAL ou ISS em outro município |
| 🟢 **Aprovado** | Nenhuma divergência nas regras automáticas |

### Conferência matemática
- **Imposto esperado** = Base × Alíquota.
- O alerta é gerado quando |informado − esperado| > máx(**tolerância em R$**, **tolerância % × esperado**).
- O administrador ajusta a tolerância na aba **⚙ Configuração**. Os padrões são R$ 0,05 e 0,5%.

## Segurança
- Somente `.xml`, com MIME `application/xml` ou `text/xml`, limite de 5 MB e conteúdo verificado.
- PDF, ZIP, binários, UTF-16 e extensão dupla são recusados.
- **XXE e "billion laughs"**: qualquer `<!DOCTYPE>`/`<!ENTITY>` é recusado antes do parser. O conteúdo nunca é executado.
- Armazenamento em `data/xml/<sha256>.xml`:
  - fora de qualquer pasta pública;
  - renomeado;
  - sem usar o nome enviado pelo usuário, o que impede path traversal.
- **Tokens:** são guardados apenas como hash SHA-256 no banco.
- **Perfis:**
  - *consulta*: somente leitura;
  - *analista*: envia XMLs e analisa/resolve alertas;
  - *admin*: também aprova documentos, configura a tolerância e cria usuários.
- **Rate limit:** por IP e por usuário. Após 10 tokens inválidos o IP é bloqueado por 15 min.
- **CORS:** limitado às origens configuradas.
- **Erros:** nunca expõem stack trace.
- **Histórico fiscal:** somente-inclusão. Triggers no banco impedem `UPDATE`/`DELETE`.
- **Rede:** o serviço escuta somente em `127.0.0.1`. Para uso em rede, coloque-o atrás de HTTPS (proxy reverso) e restrinja o firewall.

## Limitações conhecidas (transparência)
- **Regras de apoio:** as regras fiscais detectam inconsistências e indícios; **não substituem a validação fiscal**. NCM e CFOP são sempre apresentados como "Possível divergência — necessita validação fiscal".
- **Alíquotas estaduais e municipais:** a alíquota interna de cada UF/município não é validada automaticamente. O sistema confere o cálculo (base × alíquota) e faixas gerais (ISS 2–5%, interestadual 4/7/12%).
- **CT-e:** é reconhecido e lido, mas ainda sem regras específicas. A estrutura está pronta (`normalizers/cte.py`).
- **Padrões de NFS-e:** municípios com padrões muito diferentes podem precisar de novos sinônimos no dicionário `SIN` de `normalizers/nfse.py`.
- **"Inteligência fiscal":** é baseada em regras transparentes, executadas localmente, sem envio de dados a serviços externos de IA.
