"""
scripts/database.py — Camada de persistencia com SQLite.
Responsavel por criar o schema, inserir noticias e evitar duplicatas.
"""

from __future__ import annotations

import datetime
import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

# ──────────────────────────────────────────
#  CONFIGURACAO
# ──────────────────────────────────────────

DB_PATH = Path(__file__).parent.parent / "data" / "news.db"

logger = logging.getLogger(__name__)

# Schema SQL — a constraint UNIQUE em `url` e o que evita duplicatas
SCHEMA = """
CREATE TABLE IF NOT EXISTS news (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    url          TEXT    NOT NULL UNIQUE,
    title        TEXT    NOT NULL,
    source       TEXT    NOT NULL,
    full_content TEXT,
    summary      TEXT,
    headline     TEXT,
    created_at   DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_news_created_at ON news(created_at);
CREATE INDEX IF NOT EXISTS idx_news_source     ON news(source);
"""


# ──────────────────────────────────────────
#  GERENCIADOR DE CONEXAO
# ──────────────────────────────────────────

@contextmanager
def get_conn(db_path: Path = DB_PATH) -> Iterator[sqlite3.Connection]:
    """
    Context manager que garante abertura + fechamento seguro da conexao.
    row_factory = Row permite acessar colunas por nome (ex: row["title"]).
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ──────────────────────────────────────────
#  INICIALIZACAO
# ──────────────────────────────────────────

def init_db(db_path: Path = DB_PATH) -> None:
    """Cria o banco e as tabelas se ainda nao existirem."""
    with get_conn(db_path) as conn:
        conn.executescript(SCHEMA)
    logger.info("[INFO] Banco inicializado: %s", db_path)


# ──────────────────────────────────────────
#  OPERACOES CRUD
# ──────────────────────────────────────────

def url_exists(url: str, db_path: Path = DB_PATH) -> bool:
    """Verifica se uma URL ja foi persistida no banco, evitando reprocessamento."""
    with get_conn(db_path) as conn:
        row = conn.execute("SELECT 1 FROM news WHERE url = ?", (url,)).fetchone()
        return row is not None


def insert_news(
    url: str,
    title: str,
    source: str,
    full_content: str,
    summary: str,
    headline: str,
    db_path: Path = DB_PATH,
) -> int | None:
    """
    Insere uma noticia no banco.
    Retorna o ID inserido ou None se a URL ja existia (INSERT OR IGNORE).
    """
    sql = """
        INSERT OR IGNORE INTO news
            (url, title, source, full_content, summary, headline)
        VALUES
            (?, ?, ?, ?, ?, ?)
    """
    with get_conn(db_path) as conn:
        cursor = conn.execute(sql, (url, title, source, full_content, summary, headline))
        return cursor.lastrowid if cursor.rowcount > 0 else None


def get_today_news(db_path: Path = DB_PATH) -> list[sqlite3.Row]:
    """Retorna todas as noticias inseridas hoje."""
    today = datetime.date.today().isoformat()
    sql = """
        SELECT * FROM news
        WHERE date(created_at) = ?
        ORDER BY created_at DESC
    """
    with get_conn(db_path) as conn:
        return conn.execute(sql, (today,)).fetchall()


def get_news_by_date(date_str: str, db_path: Path = DB_PATH) -> list[sqlite3.Row]:
    """Retorna noticias de uma data especifica (formato: YYYY-MM-DD)."""
    sql = "SELECT * FROM news WHERE date(created_at) = ? ORDER BY created_at DESC"
    with get_conn(db_path) as conn:
        return conn.execute(sql, (date_str,)).fetchall()


def get_stats(db_path: Path = DB_PATH) -> dict[str, int | list[dict[str, str | int]]]:
    """Retorna estatisticas gerais do banco."""
    with get_conn(db_path) as conn:
        total = conn.execute("SELECT COUNT(*) FROM news").fetchone()[0]
        today = conn.execute(
            "SELECT COUNT(*) FROM news WHERE date(created_at) = date('now')"
        ).fetchone()[0]
        sources = conn.execute(
            "SELECT source, COUNT(*) as cnt FROM news GROUP BY source ORDER BY cnt DESC"
        ).fetchall()
    return {
        "total": total,
        "today": today,
        "sources": [{"source": r["source"], "count": r["cnt"]} for r in sources],
    }


# ──────────────────────────────────────────
#  EXPORTACAO (formato segue exemplo.md)
# ──────────────────────────────────────────

def _formatar_data_br(iso_str: str) -> str:
    """Converte '2026-04-01 08:01:00' para '01/04/2026 08:01'."""
    try:
        dt = datetime.datetime.fromisoformat(iso_str)
        return dt.strftime("%d/%m/%Y %H:%M")
    except (ValueError, TypeError):
        return iso_str or ""


def export_markdown(date_str: str, output_dir: Path, db_path: Path = DB_PATH) -> Path:
    """
    Gera um arquivo .md com todas as noticias de uma data especifica.
    Formato segue o template definido em exemplo.md.
    """
    noticias = get_news_by_date(date_str, db_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    hora = datetime.datetime.now().strftime("%H-%M")
    output_file = output_dir / f"{date_str}_{hora}.md"

    # Cabecalho — data formatada em PT-BR
    try:
        dt = datetime.date.fromisoformat(date_str)
        data_br = dt.strftime("%d/%m/%Y")
    except ValueError:
        data_br = date_str

    agora = datetime.datetime.now().strftime("%d/%m/%Y as %H:%M")

    linhas = [
        f"# \U0001f916 Noticias de Inteligencia Artificial — {date_str}",
        "",
        f"> Gerado automaticamente em {agora}",
        f"> Total de noticias coletadas: {len(noticias)}",
        "",
        "---",
        "",
    ]

    # Coleta fontes unicas para o rodape
    fontes_unicas: list[str] = []

    for i, n in enumerate(noticias, 1):
        coletado_br = _formatar_data_br(n["created_at"])
        fonte = n["source"]
        if fonte not in fontes_unicas:
            fontes_unicas.append(fonte)

        linhas += [
            f"## {i}. {n['title']}",
            "",
            f"**\U0001f4e3 Headline Instagram:**",
            f"> {n['headline'] or n['title']}",
            "",
            f"**\U0001f4f0 Fonte:** {fonte}  ",
            f"**\U0001f4c5 Coletado em:** {coletado_br}  ",
            f"**\U0001f517 Link:** {n['url']}",
            "",
            f"**\U0001f4dd Resumo (para redes sociais):**",
            "",
            n["summary"] or "*Resumo nao disponivel.*",
            "",
            f"**\U0001f4c4 Conteudo completo:**",
            "",
            n["full_content"] or "*Conteudo nao disponivel.*",
            "",
            "---",
            "",
        ]

    # Rodape com fontes consultadas
    linhas += [
        f"## \U0001f4ca Fontes consultadas nesta edicao",
        "",
    ]
    for fonte in fontes_unicas:
        linhas.append(f"- {fonte}")

    linhas.append("")

    output_file.write_text("\n".join(linhas), encoding="utf-8")
    logger.info("[INFO] Markdown exportado: %s", output_file)
    return output_file


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    init_db()
    stats = get_stats()
    logger.info("[INFO] Total no banco: %d | Hoje: %d", stats["total"], stats["today"])
