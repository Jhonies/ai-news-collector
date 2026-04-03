"""
scripts/collector.py — Pipeline principal de coleta.

Fluxo:
  1. Le os feeds RSS configurados no .env
  2. Filtra URLs ja presentes no banco (evita duplicatas)
  3. Para cada URL nova:
     a. Playwright renderiza a pagina (suporte a SPAs/JavaScript)
     b. Trafilatura extrai o conteudo limpo (sem anuncios, menus etc.)
     c. Ollama gera resumo + headline localmente
     d. Resultado e salvo no SQLite
  4. Exporta um .md do dia

Execute: python scripts/collector.py
"""

from __future__ import annotations

import asyncio
import datetime
from email.utils import parsedate_to_datetime
import logging
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

# ── Carrega variaveis do .env ──────────────────────────────────────────────
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

import requests
from bs4 import BeautifulSoup
import trafilatura
from playwright.async_api import async_playwright, Page, Browser

# Modulos locais
sys.path.insert(0, str(Path(__file__).parent))
from database import init_db, url_exists, insert_news, export_markdown, DB_PATH
from processor import gerar_resumo, ollama_disponivel, DEFAULT_MODEL


# ──────────────────────────────────────────
#  CONFIGURACOES
# ──────────────────────────────────────────

OLLAMA_MODEL  = os.getenv("OLLAMA_MODEL", DEFAULT_MODEL)
DB_FILE       = Path(os.getenv("DB_PATH", str(DB_PATH)))
EXPORTS_DIR   = Path(__file__).parent.parent / "exports"
MAX_NOTICIAS  = int(os.getenv("MAX_NOTICIAS", "12"))
DIAS_RECENTES = int(os.getenv("DIAS_RECENTES", "3"))  # Ignora artigos mais antigos que N dias
LOG_LEVEL     = os.getenv("LOG_LEVEL", "INFO")

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Fontes RSS — pode sobrescrever via .env com lista separada por virgula
_FONTES_DEFAULT = ",".join([
    "https://feeds.arstechnica.com/arstechnica/technology-lab",
    "https://venturebeat.com/category/ai/feed/",
    "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    "https://techcrunch.com/category/artificial-intelligence/feed/",
    "https://www.technologyreview.com/feed/",
    "https://huggingface.co/blog/feed.xml",
])
_FONTES_ENV = os.getenv("SOURCES_RSS", "").strip()
SOURCES_RSS = [
    s.strip()
    for s in (_FONTES_ENV or _FONTES_DEFAULT).split(",")
    if s.strip()
]

# User-agent para requests de RSS
RSS_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


# ──────────────────────────────────────────
#  ETAPA 1 — COLETA DE LINKS VIA RSS
# ──────────────────────────────────────────

def _parsear_data_publicacao(tag) -> datetime.datetime | None:
    """Parseia tag de data RSS (RFC 2822) ou Atom (ISO 8601). Retorna None se falhar."""
    if not tag:
        return None
    texto = tag.get_text(strip=True)
    # RFC 2822 — usado em <pubDate> do RSS
    try:
        return parsedate_to_datetime(texto)
    except Exception:
        pass
    # ISO 8601 — usado em <published>/<updated> do Atom
    try:
        return datetime.datetime.fromisoformat(texto.replace("Z", "+00:00"))
    except Exception:
        pass
    return None


def coletar_links_rss(feed_url: str) -> list[dict]:
    """
    Parseia um feed RSS/Atom e retorna lista de dicts com artigos recentes:
    {"titulo": str, "url": str, "fonte": str}

    Ignora artigos publicados ha mais de DIAS_RECENTES dias.
    """
    try:
        resp = requests.get(feed_url, headers=RSS_HEADERS, timeout=15)
        resp.raise_for_status()
    except requests.Timeout:
        logger.warning("[WARN] Timeout ao acessar feed %s", feed_url)
        return []
    except requests.RequestException as exc:
        logger.error("[ERROR] Falha ao acessar feed %s: %s", feed_url, exc)
        return []

    soup = BeautifulSoup(resp.content, "xml")
    fonte = urlparse(feed_url).netloc.replace("www.", "").replace("feeds.", "")

    agora = datetime.datetime.now(tz=datetime.timezone.utc)
    limite = agora - datetime.timedelta(days=DIAS_RECENTES)

    itens: list[dict] = []
    for item in soup.find_all(["item", "entry"]):
        titulo_tag = item.find(["title"])
        link_tag   = item.find(["link", "id"])

        if not titulo_tag or not link_tag:
            continue

        url    = link_tag.get("href") or link_tag.get_text(strip=True)
        titulo = titulo_tag.get_text(strip=True)

        if not url or not titulo:
            continue

        # Filtra artigos mais antigos que DIAS_RECENTES
        data_tag = item.find(["pubDate", "published", "updated"])
        data_pub = _parsear_data_publicacao(data_tag)
        if data_pub and data_pub < limite:
            continue

        itens.append({"titulo": titulo, "url": url.strip(), "fonte": fonte})

    return itens


# ──────────────────────────────────────────
#  ETAPA 2 — EXTRACAO VIA PLAYWRIGHT + TRAFILATURA
# ──────────────────────────────────────────

# Frases que indicam pagina de challenge de bot (Cloudflare, Akamai, etc.)
_BOT_CHALLENGE_MARKERS = frozenset([
    "enable javascript and cookies to continue",
    "verification successful",
    "just a moment",
    "checking your browser before accessing",
    "ddos protection by cloudflare",
    "please wait while we verify",
])


async def extrair_conteudo_playwright(url: str, browser: Browser) -> str | None:
    """
    Renderiza a URL com Chromium e extrai o conteudo editorial com Trafilatura.

    Bloqueia requisicoes de imagem e fonte para reduzir latencia.
    Retorna None se a extracao falhar ou produzir conteudo vazio.
    """
    page: Page = await browser.new_page()

    try:
        # Bloqueia recursos desnecessarios para acelerar o carregamento
        await page.route(
            "**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,ttf,eot,ico}",
            lambda route: route.abort()
        )
        await page.route("**/{analytics,tracking,ads,doubleclick}**",
                         lambda route: route.abort())

        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)

        # Aguarda o conteudo principal aparecer (heuristica)
        try:
            await page.wait_for_selector(
                "article, main, [class*='content'], [class*='article']",
                timeout=5_000
            )
        except TimeoutError:
            pass  # Pagina sem seletor obvio — continua com o HTML completo

        html = await page.content()

    except TimeoutError:
        logger.warning("[WARN] Timeout ao renderizar %s", url)
        return None
    except Exception as exc:
        logger.error("[ERROR] Playwright falhou para %s: %s", url, type(exc).__name__)
        return None
    finally:
        await page.close()

    texto = trafilatura.extract(
        html,
        include_comments=False,
        include_tables=True,
        no_fallback=False,
        favor_recall=True,
    )

    if not texto:
        return None

    # Detecta paginas de challenge de bot: conteudo muito curto com frases conhecidas
    if len(texto) < 500:
        texto_lower = texto.lower()
        if any(marker in texto_lower for marker in _BOT_CHALLENGE_MARKERS):
            logger.warning("[WARN] Pagina de verificacao de bot detectada, pulando: %s", url[:70])
            return None

    return texto


# ──────────────────────────────────────────
#  PIPELINE ASSINCRONO PRINCIPAL
# ──────────────────────────────────────────

async def processar_noticia(
    item: dict,
    browser: Browser,
    usar_ollama: bool,
) -> bool:
    """
    Processa uma unica noticia: extrai conteudo, gera resumo e salva.
    Retorna True se inserida com sucesso, False se era duplicata ou falhou.
    """
    url    = item["url"]
    titulo = item["titulo"]
    fonte  = item["fonte"]

    # Verifica duplicata antes de fazer scraping (economiza tempo)
    if url_exists(url, DB_FILE):
        logger.info("[SKIP] Ja existe no banco: %s", titulo[:60])
        return False

    logger.info("[INFO] Extraindo: %s", url[:70])
    conteudo = await extrair_conteudo_playwright(url, browser)

    if not conteudo:
        logger.warning("[WARN] Conteudo vazio — pulando %s", url[:70])
        return False

    logger.info("[INFO] Extraido: %d caracteres", len(conteudo))

    # Geracao de resumo (local via Ollama ou fallback sem resumo)
    if usar_ollama:
        logger.info("[INFO] Gerando resumo com %s", OLLAMA_MODEL)
        resultado = gerar_resumo(titulo, conteudo, model=OLLAMA_MODEL)
        summary  = resultado["summary"]
        headline = resultado["headline"]
    else:
        summary  = "[Ollama offline — configure para gerar resumos automaticos]"
        headline = titulo

    # Persistencia no SQLite
    inserted_id = insert_news(
        url=url,
        title=titulo,
        source=fonte,
        full_content=conteudo,
        summary=summary,
        headline=headline,
        db_path=DB_FILE,
    )

    if inserted_id:
        logger.info("[INFO] Salvo no banco (ID %d)", inserted_id)
        return True

    logger.info("[SKIP] Duplicata detectada na insercao (URL repetida)")
    return False


async def executar_pipeline() -> None:
    """Orquestra o pipeline completo de coleta."""

    hoje = datetime.date.today().isoformat()
    logger.info("=" * 58)
    logger.info("  AI News Collector — %s", hoje)
    logger.info("  Modelo: %s  |  Fontes: %d", OLLAMA_MODEL, len(SOURCES_RSS))
    logger.info("=" * 58)

    # Inicializa banco
    init_db(DB_FILE)

    # Verifica Ollama
    usar_ollama = ollama_disponivel()
    if usar_ollama:
        logger.info("[INFO] Ollama online (%s)", OLLAMA_MODEL)
    else:
        logger.warning("[WARN] Ollama offline — coleta prosseguira SEM resumos automaticos.")
        logger.warning("[WARN] Para ativar: ollama serve & ollama pull phi3")

    # ── Etapa 1: Coleta de links ─────────────────────────────────────────
    logger.info("[INFO] Coletando links dos feeds RSS...")
    candidatos: list[dict] = []
    for feed_url in SOURCES_RSS:
        nome = urlparse(feed_url).netloc.replace("www.", "")
        logger.info("[INFO]   %s", nome)
        itens = coletar_links_rss(feed_url)
        logger.info("[INFO]   %d links encontrados", len(itens))
        candidatos.extend(itens)

    # Remove duplicatas de URL dentro dos proprios candidatos
    vistos: set[str] = set()
    candidatos_unicos: list[dict] = []
    for c in candidatos:
        if c["url"] not in vistos:
            vistos.add(c["url"])
            candidatos_unicos.append(c)

    # Limita ao maximo configurado
    candidatos_unicos = candidatos_unicos[:MAX_NOTICIAS]
    logger.info("[INFO] %d URLs unicas para processar", len(candidatos_unicos))

    # ── Etapa 2: Extracao + Resumo + Persistencia ────────────────────────
    inseridas = 0
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--blink-settings=imagesEnabled=false",
            ],
        )

        for i, item in enumerate(candidatos_unicos, 1):
            logger.info("[%d/%d] %s", i, len(candidatos_unicos), item["titulo"][:65])
            sucesso = await processar_noticia(item, browser, usar_ollama)
            if sucesso:
                inseridas += 1
            # Pausa educada entre requisicoes ao mesmo dominio
            await asyncio.sleep(1)

        await browser.close()

    # ── Etapa 3: Exportacao ──────────────────────────────────────────────
    arquivo_md = export_markdown(hoje, EXPORTS_DIR, DB_FILE)

    logger.info("=" * 58)
    logger.info("  Pipeline concluido!")
    logger.info("  Novas noticias: %d", inseridas)
    logger.info("  Banco: %s", DB_FILE)
    logger.info("  Exportado: %s", arquivo_md)
    logger.info("=" * 58)


# ──────────────────────────────────────────
#  ENTRADA DO SCRIPT
# ──────────────────────────────────────────

if __name__ == "__main__":
    asyncio.run(executar_pipeline())
