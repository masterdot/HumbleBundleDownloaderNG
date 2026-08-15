"""CLI entry point. See CONCEPT.md section 9 for the full command surface
(only `auth login`, `auth check`, and `list` are implemented in M1)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import typer

from hbdl import auth, config
from hbdl.api import Client
from hbdl.catalog import build_catalog
from hbdl.downloader.direct import download_all
from hbdl.state import open_store

app = typer.Typer(no_args_is_help=True, add_completion=False)
auth_app = typer.Typer(no_args_is_help=True, help="Login/Session verwalten")
app.add_typer(auth_app, name="auth")


@auth_app.command("login")
def auth_login(
    headless: bool = typer.Option(False, help="Browserfenster nicht anzeigen (nur fuer wiederholtes Login mit bereits gespeicherten Browser-Daten sinnvoll)."),
) -> None:
    """Oeffnet ein Browserfenster fuer den manuellen Login und speichert den Session-Cookie."""
    try:
        auth.guided_login(headless=headless)
    except auth.AuthError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    typer.secho("Login erfolgreich, Session gespeichert.", fg=typer.colors.GREEN)


@auth_app.command("check")
def auth_check(
    cookie: Optional[str] = typer.Option(None, help="Roher _simpleauth_sess-Wert."),
    cookie_file: Optional[Path] = typer.Option(None, help="Netscape cookies.txt mit _simpleauth_sess."),
) -> None:
    """Validiert den aktuell verfuegbaren Cookie gegen die Humble-Bundle-API."""
    try:
        session = auth.resolve_session(cookie=cookie, cookie_file=cookie_file)
        info = auth.check_session(session)
    except auth.AuthError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    typer.secho(f"OK - {info['order_count']} Bestellungen gefunden.", fg=typer.colors.GREEN)


@app.command("list")
def list_items(
    cookie: Optional[str] = typer.Option(None, help="Roher _simpleauth_sess-Wert."),
    cookie_file: Optional[Path] = typer.Option(None, help="Netscape cookies.txt mit _simpleauth_sess."),
    workers: int = typer.Option(config.DEFAULT_WORKERS, help="Parallele Order-Detail-Abfragen."),
    output_format: str = typer.Option("table", "--format", help="table oder json"),
) -> None:
    """Nur Discovery: listet alle Dateien der Bibliothek auf, laedt nichts herunter."""
    try:
        session = auth.resolve_session(cookie=cookie, cookie_file=cookie_file)
    except auth.AuthError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    client = Client(session)
    items = build_catalog(client, workers=workers)

    if output_format == "json":
        payload = [
            {
                "human_name": i.human_name,
                "subproduct_name": i.subproduct_name,
                "platform": i.platform,
                "variant_name": i.variant_name,
                "filename": i.filename,
                "file_size": i.file_size,
                "has_torrent": i.torrent_url is not None,
            }
            for i in items
        ]
        typer.echo(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    for item in items:
        torrent_flag = "T" if item.torrent_url else " "
        typer.echo(f"[{torrent_flag}] {item.human_name} / {item.platform} / {item.filename} ({item.file_size} bytes)")
    typer.echo(f"\n{len(items)} Dateien gefunden.", err=True)


@app.command("sync")
def sync(
    dest: Path = typer.Option(config.DEFAULT_DEST, help="Zielverzeichnis fuer heruntergeladene Dateien."),
    cookie: Optional[str] = typer.Option(None, help="Roher _simpleauth_sess-Wert."),
    cookie_file: Optional[Path] = typer.Option(None, help="Netscape cookies.txt mit _simpleauth_sess."),
    workers: int = typer.Option(config.DEFAULT_WORKERS, help="Parallele Downloads/Order-Abfragen."),
    strategy: str = typer.Option(config.DEFAULT_STRATEGY, help="direct (in M2 einzige Option; auto/torrent folgen in M4)."),
    platform: Optional[str] = typer.Option(None, help="Komma-getrennte Plattform-Filter, z.B. windows,ebook."),
    dry_run: bool = typer.Option(False, help="Nur planen/auflisten, nichts herunterladen."),
) -> None:
    """Ermittelt die Bibliothek und laedt alle (gefilterten) Dateien herunter."""
    if strategy != "direct":
        typer.secho(
            f"Strategie '{strategy}' ist erst ab Meilenstein M4 verfuegbar; verwende 'direct'.",
            fg=typer.colors.YELLOW,
            err=True,
        )
        strategy = "direct"

    try:
        session = auth.resolve_session(cookie=cookie, cookie_file=cookie_file)
    except auth.AuthError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    client = Client(session)
    items = build_catalog(client, workers=workers)

    if platform:
        wanted = {p.strip().lower() for p in platform.split(",")}
        items = [i for i in items if i.platform.lower() in wanted]

    if not items:
        typer.echo("Keine Dateien zu verarbeiten (Bibliothek leer oder Filter zu eng).")
        return

    total_bytes = sum(i.file_size for i in items)
    typer.echo(f"{len(items)} Dateien, {total_bytes / (1024**3):.2f} GiB gesamt.")

    if dry_run:
        for item in items:
            typer.echo(f"  {item.human_name} / {item.platform} / {item.filename}")
        return

    dest.mkdir(parents=True, exist_ok=True)
    with open_store() as store:
        report = download_all(client, items, dest, store, workers=workers)

    typer.echo("")
    typer.secho(f"{len(report.succeeded)} heruntergeladen, {len(report.skipped)} uebersprungen (bereits vorhanden).", fg=typer.colors.GREEN)
    if report.failed:
        typer.secho(f"{len(report.failed)} fehlgeschlagen:", fg=typer.colors.RED, err=True)
        for result in report.failed:
            typer.secho(f"  {result.item.human_name}/{result.item.filename}: {result.error}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
