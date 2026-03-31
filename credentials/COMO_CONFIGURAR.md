# Como configurar o Google Drive (Service Account)

## Passo a passo (fazer apenas uma vez)

### 1. Criar o projeto no Google Cloud

1. Acesse [console.cloud.google.com](https://console.cloud.google.com)
2. Clique em **Selecionar projeto → Novo projeto**
3. Dê um nome (ex: `postsocial-drive`) e clique em **Criar**

### 2. Ativar a API do Google Drive

1. No menu lateral, vá em **APIs e serviços → Biblioteca**
2. Pesquise por **Google Drive API**
3. Clique em **Ativar**

### 3. Criar a Service Account

1. Vá em **APIs e serviços → Credenciais**
2. Clique em **+ Criar credenciais → Conta de serviço**
3. Preencha um nome (ex: `postsocial-sa`) e clique em **Criar e continuar**
4. Nas permissões, não precisa selecionar nada — apenas clique em **Continuar → Concluir**

### 4. Baixar a chave JSON

1. Na lista de Service Accounts, clique na conta criada
2. Vá na aba **Chaves**
3. Clique em **Adicionar chave → Criar nova chave → JSON**
4. O arquivo será baixado automaticamente
5. **Renomeie para `gdrive_service_account.json`**
6. **Coloque nesta pasta:** `credentials/gdrive_service_account.json`

> ⚠️ NUNCA suba este arquivo para o GitHub. Ele já está no `.gitignore`.

### 5. Compartilhar a pasta do Drive com a Service Account

1. Abra o arquivo `credentials/gdrive_service_account.json`
2. Copie o valor do campo `"client_email"` — será algo como:
   `postsocial-sa@postsocial-drive.iam.gserviceaccount.com`
3. No Google Drive do **cliente**, clique com botão direito na pasta de fotos
4. Clique em **Compartilhar**
5. Cole o e-mail da Service Account e dê permissão de **Leitor**
6. Clique em **Enviar**

### 6. Criar o arquivo postagens.txt (legendas por dia)

Dentro da pasta do Google Drive, crie um arquivo de texto chamado **`postagens.txt`** com as legendas de cada dia da semana:

```
Segunda: Bom dia! Confira os melhores imóveis disponíveis hoje. Entre em contato! #imoveis #leadhouse #comprar
Terça: Oportunidade imperdível! Imóveis com as melhores condições do mercado. #imoveis #oportunidade
Quarta: Você sabia que temos imóveis em ótimas localizações? #imoveis #leadhouse #investimento
Quinta: Encontre o imóvel dos seus sonhos com a gente! #imoveis #sonho #leadhouse
Sexta: Fim de semana chegando! Que tal visitar um dos nossos imóveis? #imoveis #fds
Sábado: Especial de fim de semana! Imóveis com condições especiais. #imoveis #sabado
Domingo: Planeje seu novo lar para a semana que vem! #imoveis #domingo #leadhouse
```

**Regras do arquivo:**
- Uma linha por dia da semana
- Formato: `NomeDoDia: Texto da legenda #hashtag1 #hashtag2`
- Hashtags (palavras com `#`) são separadas automaticamente da legenda
- Aceita: Segunda, Terça, Quarta, Quinta, Sexta, Sábado, Domingo (com ou sem acento)
- Linhas em branco ou começando com `#` são ignoradas

### 7. Organizar as fotos na pasta

As fotos podem ser nomeadas de duas formas:

**Opção A — Nome com o dia (recomendado):**
```
segunda.jpg
terca.png
quarta.jpg
quinta.jpg
sexta.mp4
sabado.jpg
domingo.jpg
```

**Opção B — Qualquer nome (distribuição automática):**
- O app distribui as fotos automaticamente de segunda a domingo
- A 1ª foto vai para Segunda, 2ª para Terça, etc.

### 8. Configurar no dashboard

1. Faça login no PostSocial com uma conta **Pro**
2. No painel, vá até a seção **Google Drive**
3. Cole o link da pasta compartilhada (ex: `https://drive.google.com/drive/folders/XXXXXX`)
4. Clique em **Salvar pasta**
5. Clique em **Sincronizar agora** para importar os arquivos

---

## Para cada novo cliente

Cada cliente **Pro** pode configurar sua própria pasta do Google Drive:

1. O cliente cria/seleciona uma pasta no seu Google Drive
2. O cliente compartilha a pasta com o e-mail da Service Account (você fornece este e-mail)
3. O cliente cola o link da pasta no campo "Google Drive" do dashboard

---

## Variáveis de ambiente opcionais

```env
# Caminho alternativo para o arquivo de credenciais
GDRIVE_CREDENTIALS_PATH=/caminho/para/gdrive_service_account.json
```

---

## Instalação das bibliotecas

```bash
pip install google-api-python-client google-auth
```

Ou via requirements.txt (já incluído):

```bash
pip install -r requirements.txt
```
