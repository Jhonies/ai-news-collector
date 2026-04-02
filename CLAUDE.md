# CLAUDE.md

> Instruções canônicas para o agente Claude operar neste repositório.
> Leia este arquivo integralmente antes de qualquer intervenção no código.

---

## 1. Project Vision

**AI News Collector** é um pipeline de monitoramento de tendências em Inteligência Artificial que opera integralmente no ambiente local, sem dependência de APIs externas pagas.

O fluxo de execução segue quatro estágios ordenados:

```
RSS Feeds → Playwright (render) → Trafilatura (extract) → Ollama (summarize) → SQLite (persist)
```

Cada estágio é implementado em um módulo dedicado com responsabilidade única. O objetivo final é produzir, diariamente, um arquivo `.md` estruturado com o conteúdo completo e resumido das principais notícias de IA, acessível localmente e exportável para qualquer destino.

**Não existe dependência de nuvem no caminho crítico.** Privacidade e custo zero são restrições de produto, não preferências.

---

## 2. Guiding Principles

### 2.1 Arquitetura e Responsabilidades

- Cada módulo (`collector.py`, `processor.py`, `database.py`) possui **uma única responsabilidade**. Não misture lógica de scraping com lógica de persistência.
- Funções devem ser **pequenas e nomeadas com verbos de ação**: `extrair_conteudo`, `inserir_noticia`, `gerar_resumo`. Nunca `process`, `handle` ou `do_stuff`.
- Dependências entre módulos fluem em **uma única direção**: `collector.py` importa `processor.py` e `database.py`; estes dois não se importam entre si.
- Prefira **composição a herança**. Este projeto não usa classes para organização de namespace — use módulos para isso.

### 2.2 Assincronicidade

- Todo I/O de rede (Playwright, requests de RSS) deve ser **assíncrono com `asyncio`**.
- Nunca use `time.sleep()` dentro de corrotinas — substitua por `asyncio.sleep()`.
- O contexto do Playwright (`async with async_playwright()`) deve ser aberto **uma única vez** por execução do pipeline e compartilhado entre todas as extrações. Não abra e feche o browser por notícia.
- Limite a concorrência com `asyncio.Semaphore` se paralelizar extrações. O valor padrão seguro é `semaphore = asyncio.Semaphore(3)`.

### 2.3 Logs e Observabilidade

- **Sem emojis em mensagens de log técnico.** Emojis são permitidos apenas na saída de resumo exportada para o usuário final (arquivos `.md`).
- Use prefixos padronizados nos logs do pipeline:
  - `[INFO]` — fluxo normal
  - `[WARN]` — condição recuperável (ex: conteúdo vazio, timeout)
  - `[ERROR]` — falha que interrompe o processamento de um item
  - `[SKIP]` — item ignorado intencionalmente (duplicata, filtro)
- Nunca use `print()` para logs de sistema. Use o módulo `logging` com nível configurável via variável de ambiente `LOG_LEVEL` (padrão: `INFO`).

### 2.4 Tratamento de Erros

- **Nunca capture `Exception` genérica sem re-raise ou log explícito do tipo.**
- Erros de rede (Playwright, requests) devem ser tratados por item — uma falha não interrompe o pipeline inteiro.
- Funções que podem falhar retornam `None` ou um tipo explícito de resultado, nunca levantam exceções para fluxo de controle.
- Use o padrão:

```python
try:
    resultado = operacao_que_pode_falhar()
except requests.Timeout:
    logging.warning("[WARN] Timeout ao acessar %s", url)
    return None
except requests.RequestException as exc:
    logging.error("[ERROR] Falha de rede: %s", exc)
    return None
```

---

## 3. Technical Constraints

### 3.1 Hardware e Modelo LLM

- O ambiente de desenvolvimento opera com **restrições reais de RAM e armazenamento**.
- O modelo canônico é **`phi3:latest`** (Phi-3 Mini, ~2.3 GB). Esta não é uma preferência — é uma restrição de hardware.
- **Nunca sugira substituir `phi3` por modelos maiores** (llama3, mistral, mixtral) sem confirmação explícita do operador. Modelos acima de 4 GB de peso podem inviabilizar a execução.
- Parâmetros de inferência devem favorecer velocidade sobre criatividade: `temperature=0.2`, `num_predict=500`. Não aumente esses valores sem justificativa de qualidade documentada.
- O Ollama é acessado via HTTP local (`http://localhost:11434`). Nunca assuma que está disponível — sempre verifique com `ollama_disponivel()` antes de qualquer inferência.

### 3.2 Banco de Dados

- O banco é **SQLite single-file** em `data/news.db`. Não proponha migração para PostgreSQL, MySQL ou qualquer banco servidor sem requisito explícito.
- A constraint `UNIQUE` na coluna `url` é a única garantia de deduplicação — não implemente deduplicação em memória como substituto.
- Toda escrita usa `INSERT OR IGNORE` — nunca `INSERT OR REPLACE`, pois isso destruiria registros existentes.
- Habilite `PRAGMA journal_mode=WAL` em todas as conexões para suportar leituras concorrentes sem bloqueio.

### 3.3 Scraping

- O Playwright usa **Chromium headless** com imagens e fontes bloqueadas por padrão (performance).
- Trafilatura é a **única** biblioteca de extração de conteúdo. Não introduza `newspaper3k`, `readability-lxml` ou extração manual por seletores CSS sem justificativa de caso específico.
- Respeite um intervalo mínimo de **1 segundo entre requisições** ao mesmo domínio (`asyncio.sleep(1)`).

---

## 4. Commands

### Ambiente

```bash
# Criar e ativar ambiente virtual
python3 -m venv venv && source venv/bin/activate

# Instalar todas as dependências
pip install -r requirements.txt

# Instalar navegador do Playwright (executar uma única vez)
playwright install chromium
```

### Ollama

```bash
# Iniciar o servidor Ollama em background
ollama serve &

# Baixar o modelo canônico do projeto
ollama pull phi3

# Verificar modelos disponíveis localmente
ollama list

# Testar a integração Ollama → processor.py
python scripts/processor.py
```

### Pipeline

```bash
# Executar o pipeline completo (coleta + extração + resumo + persistência)
python scripts/collector.py

# Visualizar notícias do dia no terminal
python scripts/viewer.py

# Visualizar notícias de uma data específica
python scripts/viewer.py 2026-04-01

# Exibir estatísticas do banco
python scripts/viewer.py --stats
```

### Banco de Dados

```bash
# Resetar o banco (DESTRUTIVO — apaga todos os dados)
rm data/news.db && python scripts/database.py

# Inspecionar o banco via CLI do SQLite
sqlite3 data/news.db

# Consultas úteis dentro do sqlite3:
# .tables
# SELECT title, source, created_at FROM news ORDER BY created_at DESC LIMIT 10;
# SELECT source, COUNT(*) as total FROM news GROUP BY source ORDER BY total DESC;
# SELECT COUNT(*) FROM news WHERE date(created_at) = date('now');
```

### Automação (crontab)

```bash
# Abrir o crontab para edição
crontab -e

# Linha recomendada: executa todo dia às 08:00
# 0 8 * * * ollama serve & sleep 10 && cd /caminho/do/projeto && /caminho/venv/bin/python scripts/collector.py >> logs/coletor.log 2>&1
```

---

## 5. Code Style

### 5.1 Tipagem

- **Type hints são obrigatórios** em todas as assinaturas de função — parâmetros e retorno.
- Use `from __future__ import annotations` no topo de cada módulo para habilitar avaliação lazy de tipos.
- Para retornos que podem ser nulos, use `X | None` (Python 3.10+), nunca `Optional[X]`.
- Para coleções, use os tipos nativos: `list[str]`, `dict[str, int]`, `tuple[str, ...]`.

```python
# Correto
def inserir_noticia(url: str, titulo: str, conteudo: str | None) -> int | None:
    ...

# Errado
def inserir_noticia(url, titulo, conteudo=None):
    ...
```

### 5.2 Strings e Formatação

- **F-strings em toda interpolação de strings.** Proibido usar `%` ou `.format()`.
- Para strings multilinhas em prompts do LLM, use f-strings com parênteses — nunca concatenação com `+`.

```python
# Correto
prompt = (
    f"Analise o seguinte artigo sobre IA:\n\n"
    f"Titulo: {titulo}\n\n"
    f"Conteudo:\n{conteudo[:3500]}"
)

# Errado
prompt = "Analise o seguinte artigo sobre IA:\n\nTitulo: " + titulo + "\n\n..."
```

### 5.3 Caminhos de Arquivo

- **Sempre use `pathlib.Path`** para manipulação de caminhos. Proibido `os.path.join`, `os.makedirs` ou concatenação de strings para caminhos.

```python
# Correto
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "news.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# Errado
import os
DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "news.db")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
```

### 5.4 Configuração e Constantes

- Todas as constantes configuráveis ficam no topo do módulo, em `SCREAMING_SNAKE_CASE`.
- Valores que podem variar por ambiente são carregados via `os.getenv()` com fallback explícito.
- **Nunca hardcode caminhos absolutos** no código-fonte.

```python
OLLAMA_BASE_URL  = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL     = os.getenv("OLLAMA_MODEL", "phi3")
MAX_NOTICIAS     = int(os.getenv("MAX_NOTICIAS", "12"))
REQUEST_TIMEOUT  = 30  # segundos — não configurável por ambiente, é um limite de segurança
```

### 5.5 Estrutura de Funções

- Funções com mais de 30 linhas são candidatas a refatoração.
- Parâmetros booleanos como `flag=True` em chamadas de função são um code smell — prefira enums ou funções separadas.
- Funções assíncronas têm o prefixo de verbo normalmente: `async def extrair_conteudo(...)`, sem sufixo `_async`.

### 5.6 Documentação Interna

- Docstrings são obrigatórias em funções públicas (as que não começam com `_`).
- Use o estilo de uma linha para funções simples; estilo Google para funções com múltiplos parâmetros ou comportamento não óbvio.
- Comentários inline (`#`) explicam **por quê**, não **o quê**. O código explica o quê.

```python
def url_existe(url: str, db_path: Path = DB_PATH) -> bool:
    """Verifica se uma URL já foi persistida no banco, evitando reprocessamento."""
    ...

async def extrair_conteudo_playwright(url: str, browser: Browser) -> str | None:
    """
    Renderiza a URL com Chromium e extrai o conteúdo editorial com Trafilatura.

    Bloqueia requisições de imagem e fonte para reduzir latência.
    Retorna None se a extração falhar ou produzir conteúdo vazio.
    """
    ...
```

---

## 6. Out of Scope

As seguintes mudanças **não devem ser implementadas** sem decisão explícita documentada:

- Substituição do SQLite por qualquer banco servidor
- Introdução de frameworks web (FastAPI, Flask, Django) sem requisito de API documentado
- Uso de modelos Ollama acima de 4 GB sem confirmação de hardware
- Paralelização de chamadas ao Ollama (o servidor local não é thread-safe por padrão)
- Dependências que requerem compilação nativa (ex: `psycopg2`, extensões C) sem justificativa
- Qualquer chamada a APIs externas pagas no caminho crítico do pipeline

---

*Este arquivo é a fonte de verdade para decisões de arquitetura e estilo neste repositório.*
*Em caso de conflito entre este documento e comentários no código, este documento prevalece.*