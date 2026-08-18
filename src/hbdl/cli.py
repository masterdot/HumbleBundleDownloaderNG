"""CLI entry point. See CONCEPT.md section 9 for the full command surface
(only `auth login`, `auth check`, and `list` are implemented in M1)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import typer

from hbdl import auth, config, i18n
from hbdl.api import Client
from hbdl.catalog import build_catalog, sync_catalog_cache
from hbdl.downloader.direct import download_all, verify_only
from hbdl.downloader.strategy import STRATEGIES
from hbdl.state import open_store

app = typer.Typer(no_args_is_help=True, add_completion=False)
auth_app = typer.Typer(no_args_is_help=True, help="Login/Session verwalten")
app.add_typer(auth_app, name="auth")
web_app = typer.Typer(no_args_is_help=True, help="Weboberflaeche (optional, `pip install hbdl[web]`).")
app.add_typer(web_app, name="web")
config_app = typer.Typer(no_args_is_help=True, help="config.toml lesen/schreiben (dest, workers, strategy, cookie_file).")
app.add_typer(config_app, name="config")

CONFIG_KEYS = ("dest", "workers", "strategy", "lang", "cookie_file")


@config_app.command("show")
def config_show(
    output_format: str = typer.Option("table", "--format", help="table oder json"),
) -> None:
    """Zeigt die aktuell wirksame Konfiguration (config.toml, sonst Defaults)."""
    cfg = config.Config.load()
    data = {
        "dest": str(cfg.dest),
        "workers": cfg.workers,
        "strategy": cfg.strategy,
        "lang": cfg.lang,
        "cookie_file": str(cfg.cookie_file) if cfg.cookie_file else None,
    }
    if output_format == "json":
        typer.echo(json.dumps(data, indent=2))
        return
    for key, value in data.items():
        typer.echo(f"{key:12s} = {value}")


@config_app.command("set")
def config_set(
    key: str = typer.Argument(..., help=f"Einer von: {', '.join(CONFIG_KEYS)}."),
    value: str = typer.Argument(...),
) -> None:
    """Setzt einen Konfigurationswert dauerhaft in config.toml. Andere bereits
    gesetzte Werte bleiben dabei erhalten (load -> ein Feld aendern -> save)."""
    if key not in CONFIG_KEYS:
        typer.secho(i18n.t("cli.config.unknown_key", key=key, allowed=", ".join(CONFIG_KEYS)), fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    cfg = config.Config.load()
    if key == "dest":
        cfg.dest = Path(value).expanduser()
    elif key == "workers":
        try:
            cfg.workers = int(value)
        except ValueError:
            typer.secho(i18n.t("error.workers_not_integer"), fg=typer.colors.RED, err=True)
            raise typer.Exit(1)
    elif key == "strategy":
        if value not in STRATEGIES:
            typer.secho(i18n.t("error.unknown_strategy", value=value, allowed=", ".join(STRATEGIES)), fg=typer.colors.RED, err=True)
            raise typer.Exit(1)
        cfg.strategy = value
    elif key == "lang":
        if value not in config.LANGUAGES:
            typer.secho(i18n.t("cli.config.unknown_lang", value=value, allowed=", ".join(config.LANGUAGES)), fg=typer.colors.RED, err=True)
            raise typer.Exit(1)
        cfg.lang = value
    elif key == "cookie_file":
        cfg.cookie_file = Path(value).expanduser()

    cfg.save()
    typer.secho(i18n.t("cli.config.set_saved", key=key, value=value, path=config.CONFIG_FILE), fg=typer.colors.GREEN)


@auth_app.command("login")
def auth_login(
    headless: bool = typer.Option(False, help="Browserfenster nicht anzeigen (nur fuer wiederholtes Login mit bereits gespeicherten Browser-Daten sinnvoll)."),
) -> None:
    """Oeffnet ein Browserfenster fuer den manuellen Login und speichert den Session-Cookie."""
    try:
        auth.guided_login(headless=headless)
    except auth.AuthError as exc:
        typer.secho(i18n.t(exc.key, **exc.key_kwargs) if exc.key else str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    typer.secho(i18n.t("cli.auth.login_success"), fg=typer.colors.GREEN)


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
        typer.secho(i18n.t(exc.key, **exc.key_kwargs) if exc.key else str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    typer.secho(i18n.t("cli.auth.check_ok", count=info["order_count"]), fg=typer.colors.GREEN)


@app.command("list")
def list_items(
    cookie: Optional[str] = typer.Option(None, help="Roher _simpleauth_sess-Wert."),
    cookie_file: Optional[Path] = typer.Option(None, help="Netscape cookies.txt mit _simpleauth_sess."),
    workers: Optional[int] = typer.Option(None, help="Parallele Order-Detail-Abfragen. Default: config.toml, sonst 3."),
    output_format: str = typer.Option("table", "--format", help="table oder json"),
) -> None:
    """Nur Discovery: listet alle Dateien der Bibliothek auf, laedt nichts herunter."""
    workers = workers if workers is not None else config.Config.load().workers
    try:
        session = auth.resolve_session(cookie=cookie, cookie_file=cookie_file)
    except auth.AuthError as exc:
        typer.secho(i18n.t(exc.key, **exc.key_kwargs) if exc.key else str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    client = Client(session)
    items = build_catalog(client, workers=workers)

    with open_store() as store:
        sync_catalog_cache(store, items)

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
    typer.echo(i18n.t("cli.list.found_count", count=len(items)), err=True)


@app.command("sync")
def sync(
    dest: Optional[Path] = typer.Option(
        None,
        help="Zielverzeichnis fuer heruntergeladene Dateien. "
        "Default-Praezedenz: HBDL_DEST-Env > config.toml > ./HumbleLibrary.",
    ),
    cookie: Optional[str] = typer.Option(None, help="Roher _simpleauth_sess-Wert."),
    cookie_file: Optional[Path] = typer.Option(None, help="Netscape cookies.txt mit _simpleauth_sess."),
    workers: Optional[int] = typer.Option(None, help="Parallele Downloads/Order-Abfragen. Default: config.toml, sonst 3."),
    strategy: Optional[str] = typer.Option(
        None,
        help="auto (Torrent wenn verfuegbar, sonst direct) | direct | torrent (v1: speichert nur die .torrent-Datei). "
        "Default: config.toml, sonst auto.",
    ),
    platform: Optional[str] = typer.Option(None, help="Komma-getrennte Plattform-Filter, z.B. windows,ebook."),
    dry_run: bool = typer.Option(False, help="Nur planen/auflisten, nichts herunterladen."),
    verify_only_flag: bool = typer.Option(False, "--verify-only", help="Bestehende Dateien gegen Manifest neu hashen, keine Downloads."),
) -> None:
    """Ermittelt die Bibliothek und laedt alle (gefilterten) Dateien herunter."""
    cfg = config.Config.load()
    dest = config.resolve_dest(dest)
    workers = workers if workers is not None else cfg.workers
    strategy = strategy if strategy is not None else cfg.strategy
    if strategy not in STRATEGIES:
        typer.secho(i18n.t("error.unknown_strategy", value=strategy, allowed=", ".join(STRATEGIES)), fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    try:
        session = auth.resolve_session(cookie=cookie, cookie_file=cookie_file)
    except auth.AuthError as exc:
        typer.secho(i18n.t(exc.key, **exc.key_kwargs) if exc.key else str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    client = Client(session)
    items = build_catalog(client, workers=workers)

    with open_store() as store:
        # Cache the *full* discovered catalog (before the --platform filter
        # below) so the web library browser reflects the whole account, not
        # just whatever this particular sync run chose to download.
        sync_catalog_cache(store, items)

        if platform:
            wanted = {p.strip().lower() for p in platform.split(",")}
            items = [i for i in items if i.platform.lower() in wanted]

        if not items:
            typer.echo(i18n.t("cli.sync.no_items"))
            return

        total_bytes = sum(i.file_size for i in items)
        typer.echo(i18n.t("cli.sync.total_summary", count=len(items), gib=total_bytes / (1024**3)))

        if dry_run:
            for item in items:
                typer.echo(f"  {item.human_name} / {item.platform} / {item.filename}")
            return

        dest.mkdir(parents=True, exist_ok=True)
        if verify_only_flag:
            report = verify_only(items, dest, store)
        else:
            report = download_all(client, items, dest, store, workers=workers, strategy=strategy)

    typer.echo("")
    if verify_only_flag:
        typer.secho(
            i18n.t("cli.sync.verify_summary", succeeded=len(report.succeeded), failed=len(report.failed)),
            fg=typer.colors.GREEN,
        )
    else:
        typer.secho(
            i18n.t("cli.sync.download_summary", succeeded=len(report.succeeded), skipped=len(report.skipped)),
            fg=typer.colors.GREEN,
        )

    if getattr(report, "circuit_breaker_tripped", False):
        typer.secho(i18n.t("cli.sync.circuit_breaker"), fg=typer.colors.RED, err=True)

    if report.warnings:
        typer.secho(i18n.t("cli.sync.warnings_heading", count=len(report.warnings)), fg=typer.colors.YELLOW, err=True)
        for result in report.warnings:
            typer.secho(f"  {result.item.human_name}/{result.item.filename}: {result.warning}", fg=typer.colors.YELLOW, err=True)

    if report.failed:
        typer.secho(i18n.t("cli.sync.failed_heading", count=len(report.failed)), fg=typer.colors.RED, err=True)
        for result in report.failed:
            typer.secho(f"  {result.item.human_name}/{result.item.filename}: {result.error}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)


@web_app.command("serve")
def web_serve(
    host: str = typer.Option("127.0.0.1", help="Bind-Adresse."),
    port: int = typer.Option(8000, help="Port."),
    reload: bool = typer.Option(False, help="Auto-Reload fuer Entwicklung (nur mit Quellcode-Checkout sinnvoll)."),
) -> None:
    """Startet die Weboberflaeche (FastAPI/uvicorn). Steuert denselben Downloader
    wie die CLI -- fuehre nicht gleichzeitig `hbdl sync` und einen laufenden
    Web-Job gegen denselben Zielordner aus (siehe CONCEPT_WEB.md)."""
    try:
        import uvicorn

        from hbdl.web.app import create_app  # noqa: F401  (import-availability check)
    except ImportError as exc:
        typer.secho(i18n.t("cli.web.missing_deps"), fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc

    if reload:
        uvicorn.run("hbdl.web.app:create_app", factory=True, host=host, port=port, reload=True)
    else:
        uvicorn.run(create_app(), host=host, port=port)


def main() -> None:
    # Set once here rather than per-command: every command body (and, via
    # `hbdl web serve`, the whole web UI process) runs after this point, so a
    # single call covers both entry points. `--help` text is generated at
    # Typer-decorator/import time, before this runs, so it stays static-
    # English regardless (see CONCEPT_WEB.md M14).
    i18n.set_lang(config.resolve_lang())
    app()


if __name__ == "__main__":
    main()
