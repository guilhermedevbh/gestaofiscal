# Como colocar o Gestão Fiscal na internet (site + banco de dados)

Depois de publicado, a equipe e as pessoas de fora acessam pelo mesmo endereço, por exemplo `https://gestao-fiscal.onrender.com`. Tudo o que for lançado fica salvo no banco de dados do servidor, com histórico de versões.

**Custo estimado:** cerca de **US$ 7,25 por mês** no Render (plano Starter + 1 GB de disco). Precisa de cartão de crédito.

---

## 1. Enviar os arquivos para o GitHub (uma vez)

1. Crie uma conta gratuita em **https://github.com**.
2. Instale o **GitHub Desktop**: https://desktop.github.com.
3. No GitHub Desktop, faça o seguinte:
   - Clique em **File → Add local repository** e escolha a pasta `Desktop\Projeto CRPD\Gestao Fiscal OK`.
   - Se ele perguntar, clique em **create a repository**.
   - Clique em **Publish repository** e **marque "Keep this code private"**. O repositório **precisa ser privado**.
4. O arquivo `.gitignore` já impede o envio do banco local, de senhas (`Credencial*.txt`), de certificados e de arquivos `.env`.

## 2. Criar o servidor no Railway (uma vez) — opção escolhida

O repositório já está no GitHub: **https://github.com/guilhermedevbh/gestao-fiscal** (privado). O arquivo `railway.json` já configura a publicação: Dockerfile, verificação de saúde em `/health` e **1 instância**, que é obrigatório para o banco SQLite.

1. Entre em **https://railway.com** com **"Login with GitHub"**. O plano **Hobby** custa cerca de **US$ 5 por mês**, e esse valor já inclui o uso deste serviço.
2. Clique em **New Project → Deploy from GitHub repo**. Autorize o Railway a ver o repositório `gestao-fiscal` e escolha esse repositório.
3. **Antes de usar o site**, crie o disco do banco de dados:
   - no projeto, clique com o botão direito no serviço (ou use **⌘K / Ctrl+K**) e escolha **Add Volume**;
   - em **Mount path**, coloque `/data` e salve. **Sem o volume, os dados se perdem a cada atualização.**
4. No serviço, abra **Variables → New Variable** e crie as três variáveis:
   - `PORT` = `8765`
   - `XML_AUDITOR_ADMIN_TOKEN_HASH` = `6cf7cbe55108460a2f63c79ec36942311d166dea2de98189ba2cb2dbe5e9663a`
   - `XML_AUDITOR_ADMIN_NOME` = `Guilherme Admin`
5. Abra **Settings → Networking → Generate Domain** e informe a porta **8765**. O Railway cria o endereço, por exemplo `https://gestao-fiscal-production.up.railway.app`.
6. Clique em **Deploy** (ou aguarde o deploy automático). Quando aparecer **Active / Success**, o site está no ar.

O serviço escuta na porta da variável `PORT`, em todas as interfaces, atrás do HTTPS do Railway.

**Cancelar o acesso de alguém no Railway:** clique no serviço → **⋮ → SSH / Shell** (ou use o Railway CLI com `railway ssh`) e rode o comando abaixo, trocando pelo nome da pessoa:
```
python gerenciar.py desativar "Nome"
```

### (Alternativa) Render

1. Crie uma conta em **https://render.com** usando **"Sign in with GitHub"**.
2. Clique em **New → Blueprint** e escolha o repositório criado no passo 1. O Render lê o arquivo `render.yaml`.
3. Ele vai pedir o valor de **`XML_AUDITOR_ADMIN_TOKEN_HASH`**. Cole o valor abaixo, que corresponde ao token de administrador que você já recebeu:
   ```
   6cf7cbe55108460a2f63c79ec36942311d166dea2de98189ba2cb2dbe5e9663a
   ```
4. Clique em **Apply**. A primeira publicação leva de 3 a 5 minutos.
5. O endereço do site aparece no topo da página do serviço, por exemplo `https://gestao-fiscal.onrender.com`.

## 3. Primeiro acesso

1. Abra o endereço, entre com a **senha do site** e clique em **🗄 Banco**.
2. O endereço do banco já vem preenchido. Cole o **token de administrador** e clique em **Conectar**.
3. Deixe marcado **"Conectar automaticamente ao entrar no site"**. Nas próximas vezes, basta a senha do site.

## 4. Levar os dados que já existem para a internet (uma vez)

Os dados atuais estão no navegador deste computador e no banco local. Para enviá-los ao servidor:

1. Abra o site **local** (o arquivo `Gestao_Fiscal_2026_CRPD_v10.html`) e entre com a senha.
2. Clique em **🗄 Banco** e faça o seguinte:
   - em **Endereço do serviço**, coloque o endereço da internet (`https://gestao-fiscal.onrender.com`);
   - cole o token de administrador;
   - clique em **Conectar**.
3. O site envia tudo para o banco da internet. Quando aparecer **🟢 Banco: tudo salvo**, terminou.
4. A partir daí, use **sempre o endereço da internet**.

## 5. Dar acesso à equipe e a pessoas de fora

Cada pessoa recebe o **próprio token**. Assim o banco registra quem fez cada alteração, e um acesso pode ser cancelado sem afetar os outros.

1. No site, abra **Leitura XML / Auditoria Fiscal → ⚙ Configuração → Criar usuário**.
2. Informe o nome e escolha o perfil:
   - **analista**: lança e altera informações. Use para a equipe e para pessoas de fora que vão lançar.
   - **consulta**: só visualiza.
   - **admin**: tudo, inclusive criar usuários. Só para você.
3. Copie o token exibido e entregue à pessoa **de forma privada**, por mensagem direta e nunca em grupo.
4. A pessoa acessa o endereço, entra com a senha do site, clica em **🗄 Banco**, cola o token dela e clica em **Conectar**.

## 6. Atualizar a planilha de correções

1. Abra **Controle de Correções** e clique em **⇪ Enviar planilha**.
2. Escolha o arquivo `.xlsx`. O site lê **todas as abas**, e o mês de cada correção segue o nome da aba (SETEMBRO, OUTUBRO…), a coluna Mês/Competência ou a data da linha.
3. Se a planilha estiver completa, deixe marcada a opção de mover para a lixeira o que não estiver mais nela.
4. As alterações vão para o banco da internet e todos veem em até 1 minuto.

## 7. Segurança e backup

- **HTTPS:** é fornecido pelo Render automaticamente.
- **Tokens:** ficam guardados apenas como hash. A conexão automática guarda o token criptografado com a senha do site.
- **Senha do site:** troque a senha padrão. No navegador, aperte F12 → Console e digite `gfGerarHashSenha('NovaSenhaForte123')`. Depois substitua a linha `GF_AUTH` no HTML e envie pelo GitHub Desktop (**Commit → Push**). O Render publica sozinho.
- **Backup:**
  - o Render faz cópia diária do disco;
  - o botão **Backup JSON** do Controle de Correções baixa uma cópia;
  - o histórico de versões fica em **🗄 Banco → Dados salvos → Versões**.
- **Cancelar o acesso de alguém:** isso precisa ser feito no servidor. No Render, abra **Shell** e rode o comando abaixo, trocando pelo nome da pessoa:
  ```
  python gerenciar.py desativar "Nome"
  ```

## Para publicar uma nova versão do site

Basta salvar as alterações nos arquivos e, no GitHub Desktop, clicar em **Commit** e depois em **Push**. O Render atualiza o site em poucos minutos, e os dados no disco **não são apagados**.
