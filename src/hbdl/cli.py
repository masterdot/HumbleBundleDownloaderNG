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


def main() -> None:
    app()


if __name__ == "__main__":
    main()
