"""
scripts/viewer.py — Visualizador de noticias no terminal.

Uso:
  python scripts/viewer.py              # Noticias de hoje
  python scripts/viewer.py 2026-04-01  # Noticias de uma data especifica
  python scripts/viewer.py --stats     # Estatisticas gerais do banco
"""

from __future__ import annotations

import datetime
import os
import sqlite3
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

sys.path.insert(0, str(Path(__file__).parent))
from database import get_today_news, get_news_by_date, get_stats, export_markdown, DB_PATH

DB_FILE     = Path(os.getenv("DB_PATH", str(DB_PATH)))
EXPORTS_DIR = Path(__file__).parent.parent / "exports"

# Cores ANSI para o terminal
RESET  = "\033[0m"
BOLD   = "\033[1m"
CYAN   = "\033[96m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
GRAY   = "\033[90m"
WHITE  = "\033[97m"


def exibir_noticia(noticia: sqlite3.Row, indice: int) -> None:
    """Formata e imprime uma noticia no terminal."""
    print(f"\n{CYAN}{BOLD}--- [{indice}] {noticia['title']}{RESET}")
    print(f"{GRAY}{noticia['source']}  |  {noticia['created_at']}{RESET}")
    print(f"{GRAY}{noticia['url']}{RESET}")

    if noticia["headline"]:
        print(f"\n{YELLOW}{BOLD}Headline: {noticia['headline']}{RESET}")

    if noticia["summary"]:
        print(f"\n{WHITE}Resumo:{RESET}")
        for linha in noticia["summary"].split("\n"):
            if linha.strip():
                print(f"   {linha.strip()}")

    print()


def modo_stats() -> None:
    """Exibe estatisticas gerais do banco no terminal."""
    stats = get_stats(DB_FILE)
    print(f"\n{CYAN}{BOLD}Estatisticas do Banco{RESET}")
    print(f"   Total de noticias : {BOLD}{stats['total']}{RESET}")
    print(f"   Coletadas hoje    : {BOLD}{stats['today']}{RESET}")
    print(f"\n{CYAN}Por fonte:{RESET}")
    for s in stats["sources"]:
        print(f"   {s['source']:<40} {s['count']:>4} noticias")
    print()


def main() -> None:
    """Ponto de entrada do visualizador."""
    args = sys.argv[1:]

    if "--stats" in args:
        modo_stats()
        return

    # Determina a data
    if args and args[0] != "--stats":
        data = args[0]
        noticias = get_news_by_date(data, DB_FILE)
    else:
        data = datetime.date.today().isoformat()
        noticias = get_today_news(DB_FILE)

    print(f"\n{CYAN}{BOLD}AI News — {data}{RESET}")
    print(f"{GRAY}{'─' * 55}{RESET}")

    if not noticias:
        print(f"\n{YELLOW}Nenhuma noticia encontrada para {data}.{RESET}")
        print("Execute: python scripts/collector.py\n")
        return

    print(f"\n{GREEN}{len(noticias)} noticias encontradas.{RESET}")

    for i, n in enumerate(noticias, 1):
        exibir_noticia(n, i)

    # Oferece exportar como Markdown
    print(f"{GRAY}{'━' * 55}{RESET}")
    print("Exportar como Markdown? [s/N] ", end="")
    try:
        resp = input().strip().lower()
        if resp == "s":
            arq = export_markdown(data, EXPORTS_DIR, DB_FILE)
            print(f"{GREEN}Salvo em: {arq}{RESET}\n")
    except (KeyboardInterrupt, EOFError):
        print()


if __name__ == "__main__":
    main()
