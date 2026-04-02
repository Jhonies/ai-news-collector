# 🤖 AI News Collector — Local & Robusto

Sistema profissional de coleta de notícias sobre Inteligência Artificial, rodando **100% localmente** com custo zero. Usa Playwright para renderizar páginas JavaScript, Trafilatura para extração de conteúdo limpo e Ollama para gerar resumos sem precisar de nenhuma API externa.

---

## ✨ Diferenciais desta versão

| Característica | Detalhe |
|---|---|
| **Zero custo** | Resumos gerados por LLM local via Ollama |
| **Robusto** | Playwright renderiza páginas com JavaScript (SPAs, paywalls leves) |
| **Conteúdo limpo** | Trafilatura remove anúncios, menus e elementos inúteis automaticamente |
| **Sem duplicatas** | SQLite com constraint UNIQUE na URL — impossível inserir duas vezes |
| **Offline-first** | Funciona sem internet após coleta (banco local) |
| **Privacidade total** | Nenhum dado sai da sua máquina |

---

## 📁 Estrutura de Pastas

```
ai_news_collector/
├── data/
│   └── news.db          ← Banco SQLite (criado automaticamente)
├── exports/
│   └── 2026-04-01.md   ← Exportações em Markdown por data
├── scripts/
│   ├── collector.py     ← Pipeline principal (execute este)
│   ├── processor.py     ← Integração com Ollama
│   ├── database.py      ← Operações SQLite
│   └── viewer.py        ← Visualizador no terminal
├── .env.exemplo         ← Template de configuração
├── requirements.txt
└── README.md
```

---

## ⚡ Instalação Passo a Passo

### Passo 1 — Instalar o Ollama

O Ollama é o servidor de IA que roda os modelos localmente.

**Linux:**
```bash
curl -fsSL https://ollama.com/install.sh | sh
```

**Mac:**
Baixe em: https://ollama.com/download

**Windows:**
Baixe o instalador em: https://ollama.com/download/windows

Após instalar, verifique:
```bash
ollama --version
```

---

### Passo 2 — Baixar um modelo de IA

```bash
# Recomendado (bom equilíbrio velocidade/qualidade, ~4.7GB):
ollama pull llama3

# Alternativas mais leves (para máquinas com menos RAM):
ollama pull phi3          # ~2.3GB — muito rápido
ollama pull gemma2:2b     # ~1.6GB — o mais leve

# Alternativa de alta qualidade (requer GPU ou paciência):
ollama pull mistral       # ~4.1GB
```

> **Quanto de RAM preciso?**
> - phi3 / gemma2:2b → 4GB RAM
> - llama3 / mistral → 8GB RAM
> - modelos 13B+ → 16GB+ RAM

---

### Passo 3 — Configurar o projeto Python

```bash
# Clone ou copie os arquivos para uma pasta
cd ai_news_collector

# Crie e ative o ambiente virtual
python3 -m venv venv
source venv/bin/activate      # Linux/Mac
# venv\Scripts\activate       # Windows

# Instale as dependências
pip install -r requirements.txt

# Instale o navegador do Playwright (só precisa fazer uma vez)
playwright install chromium
```

---

### Passo 4 — Configurar o .env

```bash
cp .env.exemplo .env
```

Abra `.env` e ajuste se necessário (os padrões já funcionam):

```env
OLLAMA_MODEL=llama3    # Mude para phi3 se sua máquina for mais modesta
DB_PATH=./data/news.db
MAX_NOTICIAS=12
```

---

## 🚀 Como Usar

### Coletar notícias agora

```bash
# Certifique-se de que o Ollama está rodando:
ollama serve   # Deixe em outro terminal, ou rode em background

# Execute o coletor:
python scripts/collector.py
```

O script irá:
1. Ler os feeds RSS das fontes configuradas
2. Abrir cada URL com Playwright (navegador headless)
3. Extrair o conteúdo limpo com Trafilatura
4. Gerar resumo + headline com seu modelo local
5. Salvar tudo no SQLite
6. Exportar um `.md` em `exports/`

---

### Ver as notícias do dia no terminal

```bash
python scripts/viewer.py

# Notícias de uma data específica:
python scripts/viewer.py 2026-04-01

# Estatísticas gerais do banco:
python scripts/viewer.py --stats
```

---

### Verificar se o Ollama está funcionando

```bash
# Testa a conexão e gera um resumo de exemplo:
python scripts/processor.py
```

---

## ⏰ Automação Diária

### Opção 1 — Crontab (Linux/Mac)

```bash
crontab -e
```

Adicione (ajuste os caminhos):
```bash
# Roda todo dia às 08:00
0 8 * * * ollama serve & sleep 10 && cd /caminho/do/projeto && /caminho/venv/bin/python scripts/collector.py >> /caminho/do/projeto/coletor.log 2>&1
```

### Opção 2 — Agendador de Tarefas (Windows)

Use o **Task Scheduler** nativo do Windows — sem instalar nada extra.

**Passo 1** — Abra o Agendador de Tarefas:
```
Win + R → taskschd.msc → Enter
```

**Passo 2** — Crie a tarefa via PowerShell (mais rápido):

Abra o PowerShell como **Administrador** e execute (ajuste os caminhos):

```powershell
$action = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument '/c "ollama serve & timeout /t 10 & C:\caminho\do\projeto\venv\Scripts\python.exe C:\caminho\do\projeto\scripts\collector.py >> C:\caminho\do\projeto\logs\coletor.log 2>&1"' `
    -WorkingDirectory "C:\caminho\do\projeto"

$trigger = New-ScheduledTaskTrigger -Daily -At "08:00"

$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
    -StartWhenAvailable   # Roda assim que possível se o horário passou (ex: PC estava desligado)

Register-ScheduledTask `
    -TaskName "AINewsCollector" `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -RunLevel Highest
```

**Passo 3** — Verifique se foi criada:
```powershell
Get-ScheduledTask -TaskName "AINewsCollector"
```

**Passo 4** — Teste rodando manualmente:
```powershell
Start-ScheduledTask -TaskName "AINewsCollector"
```

> **Dica:** Se o Ollama já iniciar automaticamente com o Windows (configuração padrão do instalador), remova o `ollama serve &` do comando acima.

Para remover a tarefa:
```powershell
Unregister-ScheduledTask -TaskName "AINewsCollector" -Confirm:$false
```

---

### Opção 3 — Agendador Python simples

```bash
# Crie um arquivo agendar.py:
import time, subprocess, datetime

HORA = 8
while True:
    agora = datetime.datetime.now()
    if agora.hour == HORA and agora.minute == 0:
        subprocess.run(["python", "scripts/collector.py"])
        time.sleep(61)   # Evita rodar duas vezes no mesmo minuto
    time.sleep(30)
```

```bash
# Rode em background:
nohup python agendar.py &
```

---

## 🗄️ Consultando o Banco Diretamente

O banco é um arquivo SQLite padrão — você pode abri-lo com qualquer ferramenta:

```bash
# Via terminal:
sqlite3 data/news.db

# Consultas úteis:
SELECT title, source, created_at FROM news ORDER BY created_at DESC LIMIT 10;
SELECT COUNT(*) FROM news WHERE date(created_at) = date('now');
SELECT source, COUNT(*) FROM news GROUP BY source;
```

**GUIs recomendadas (gratuitas):**
- [DB Browser for SQLite](https://sqlitebrowser.org/) — Windows/Mac/Linux
- [TablePlus](https://tableplus.com/) — Mac/Windows
- Extensão "SQLite Viewer" no VS Code

---

## 🔧 Personalizações

### Adicionar/remover fontes RSS

No `.env`:
```env
SOURCES_RSS=https://openai.com/news/rss.xml,https://deepmind.google/blog/rss.xml,https://huggingface.co/blog/feed.xml
```

Outras fontes recomendadas:
- `https://feeds.arstechnica.com/arstechnica/technology-lab`
- `https://venturebeat.com/category/ai/feed/`
- `https://www.theverge.com/rss/ai-artificial-intelligence/index.xml`
- `https://techcrunch.com/category/artificial-intelligence/feed/`
- `https://www.technologyreview.com/feed/`

### Trocar o modelo Ollama

```env
OLLAMA_MODEL=phi3   # Mais rápido e leve
```

### Aumentar a quantidade de notícias

```env
MAX_NOTICIAS=20
```

---

## 🐛 Solução de Problemas

| Problema | Causa | Solução |
|---|---|---|
| `ConnectionRefusedError` ao chamar Ollama | Ollama não está rodando | Execute `ollama serve` em outro terminal |
| `playwright install` falha | Falta de permissão ou espaço | Rode com `--with-deps`: `playwright install --with-deps chromium` |
| Conteúdo vazio na extração | Site com proteção anti-bot forte | Normal — o script pula e avança |
| Modelo não encontrado | Não foi baixado | `ollama pull llama3` |
| Banco corrompido | Encerramento forçado | Exclua `data/news.db` e recomece |

---

## 🔮 Melhorias Futuras

- **Interface web** — Dashboard Flask/FastAPI para visualizar notícias no navegador
- **Filtro de relevância** — Usar o modelo para pontuar notícias por relevância antes de salvar
- **Deduplicação semântica** — Embeddings locais para detectar notícias sobre o mesmo assunto
- **Envio por Telegram** — Bot que envia o resumo diário direto no celular
- **Análise de tendências** — Extrair tópicos recorrentes semanalmente
- **Export para Obsidian** — Compatibilidade com vault do Obsidian para acesso no celular
- **Suporte a sites sem RSS** — Scraping periódico de páginas sem feed

---

## 📜 Licença

MIT — use, modifique e distribua livremente.
