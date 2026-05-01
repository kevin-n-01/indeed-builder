from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

app = typer.Typer(
    help="Oasis — job search & application tailor",
    add_completion=False,
    invoke_without_command=True,
)
console = Console()


@app.callback()
def default(ctx: typer.Context) -> None:
    """Launch the interactive menu when called with no subcommand."""
    if ctx.invoked_subcommand is None:
        from oasis.tui import launch
        launch()


def _pick_file(label: str, current: str = "") -> str:
    """Open a native file dialog. Falls back to text input if no display is available."""
    doc_types = [("Documents", "*.pdf *.docx *.PDF *.DOCX"), ("All files", "*.*")]
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        console.print(f"[cyan]Opening file browser for {label}...[/cyan]")
        path = filedialog.askopenfilename(
            title=f"Select your {label}",
            filetypes=doc_types,
            initialfile=current or "",
        )
        root.destroy()
        if path:
            return path
        # User closed the dialog without selecting
        console.print(f"[dim]No file selected — keeping: {current or 'none'}[/dim]")
        return current
    except Exception:
        # No display / tkinter not available (Linux dev environment)
        return Prompt.ask(f"{label} path (PDF or DOCX)", default=current or "")


# ── setup ────────────────────────────────────────────────────────────────────

@app.command()
def setup() -> None:
    """First-time setup: API key, job preferences, document paths."""
    from oasis.config import (
        get_api_key, load_config, save_config, set_api_key,
        OasisConfig,
    )

    console.print(Panel.fit("[bold cyan]Oasis Setup[/bold cyan]", border_style="cyan"))
    config = load_config()

    # API key (optional — only needed for oasis apply)
    existing_key = get_api_key()
    if existing_key:
        update = Confirm.ask("Anthropic API key already set. Update it?", default=False)
        if update:
            key = Prompt.ask("Anthropic API key", password=True)
            set_api_key(key)
    else:
        console.print(
            "[dim]Anthropic API key is optional. It's only needed for [bold]oasis apply[/bold] "
            "(document tailoring). Leave blank to skip — you can still search for jobs.[/dim]"
        )
        key = Prompt.ask("Anthropic API key (press Enter to skip)", password=True, default="")
        if key:
            set_api_key(key)
        else:
            console.print("[dim]Skipped — run [bold]oasis setup[/bold] later to add it.[/dim]")

    # Job preferences
    console.print("\n[dim]Separate multiple values with commas, e.g. [bold]UX Designer, Product Manager[/bold][/dim]")
    terms_input = Prompt.ask(
        "Job titles / search terms",
        default=", ".join(config.search_terms) if config.search_terms else "",
    )
    config.search_terms = [t.strip() for t in terms_input.split(",") if t.strip()]

    locs_input = Prompt.ask(
        "Locations (city/state, or 'Remote')",
        default=", ".join(config.locations) if config.locations else "",
    )
    config.locations = [l.strip() for l in locs_input.split(",") if l.strip()]

    jt = Prompt.ask(
        "Job type",
        choices=["fulltime", "parttime", "contract", "any"],
        default=config.job_type,
    )
    config.job_type = jt  # type: ignore[assignment]
    config.remote = Confirm.ask("Include remote jobs?", default=config.remote)

    # Document paths (optional — only needed for oasis apply)
    console.print(
        "\n[dim]Document paths are only needed for [bold]oasis apply[/bold]. "
        "Press Enter to open a file browser, or skip.[/dim]"
    )

    if Confirm.ask("Select resume file now?", default=bool(config.resume_path)):
        resume = _pick_file("resume", config.resume_path)
        if resume and not Path(resume).exists():
            console.print(f"[yellow]Warning: file not found: {resume}[/yellow]")
        config.resume_path = resume
        if resume:
            console.print(f"[green]Resume:[/green] {resume}")

    if Confirm.ask("Select cover letter file now?", default=bool(config.cover_letter_path)):
        cl = _pick_file("cover letter", config.cover_letter_path)
        if cl and not Path(cl).exists():
            console.print(f"[yellow]Warning: file not found: {cl}[/yellow]")
        config.cover_letter_path = cl
        if cl:
            console.print(f"[green]Cover letter:[/green] {cl}")

    save_config(config)
    console.print("[green]Setup complete! Run [bold]oasis search[/bold] to find jobs.[/green]")


# ── search ───────────────────────────────────────────────────────────────────

@app.command()
def search(
    term: Optional[str] = typer.Option(None, "--term", "-t", help="Comma-separated job titles, overrides saved config"),
    location: Optional[str] = typer.Option(None, "--location", "-l", help="Comma-separated locations, overrides saved config"),
    limit: int = typer.Option(50, "--limit", "-n", help="Max results per search combination"),
) -> None:
    """Search for jobs and open the interactive browser."""
    from oasis.browse import browse_jobs
    from oasis.config import load_config
    from oasis.database import filter_unseen, set_status, upsert_jobs
    from oasis.search import Job, search_jobs

    config = load_config()

    s_terms = [t.strip() for t in term.split(",")] if term else config.search_terms
    s_locs = [l.strip() for l in location.split(",")] if location else config.locations

    if not s_terms:
        console.print("[red]No search terms configured. Run [bold]oasis setup[/bold] first.[/red]")
        raise typer.Exit(1)

    terms_str = ", ".join(s_terms)
    locs_str = ", ".join(s_locs) if s_locs else "any location"
    console.print(f"[cyan]Searching for [bold]{terms_str}[/bold] in [bold]{locs_str}[/bold]...[/cyan]")
    combos = len(s_terms) * max(len(s_locs), 1)
    if combos > 1:
        console.print(f"[dim]Running {combos} search combination(s) and deduplicating...[/dim]")

    with console.status("Fetching jobs from Indeed + LinkedIn..."):
        jobs = search_jobs(
            search_terms=s_terms,
            locations=s_locs,
            job_type=config.job_type,
            remote=config.remote,
            results_wanted=limit,
        )

    if not jobs:
        console.print("[yellow]No jobs found. Try a different search term or location.[/yellow]")
        raise typer.Exit(0)

    # Persist to DB and filter already-seen
    raw = [j.model_dump() for j in jobs]
    upsert_jobs(raw)
    unseen_raw = filter_unseen(raw)

    # Rebuild Job objects with DB-assigned IDs
    unseen: list[Job] = []
    for r in unseen_raw:
        j = Job(**{k: v for k, v in r.items() if k != "_id"})
        j.id = r.get("_id", "")
        unseen.append(j)

    console.print(
        f"[green]{len(jobs)} jobs found — [bold]{len(unseen)}[/bold] new (not previously seen)[/green]"
    )

    if not unseen:
        console.print("[yellow]All jobs have already been seen. Use [bold]oasis history[/bold] to review past jobs.[/yellow]")
        raise typer.Exit(0)

    selected, rejected = browse_jobs(unseen)

    for job in rejected:
        if job.id:
            set_status(job.id, "rejected")

    if not selected:
        console.print("[yellow]No jobs selected for application.[/yellow]")
        raise typer.Exit(0)

    console.print(f"[green]{len(selected)} job(s) selected. Run [bold]oasis apply[/bold] to tailor your documents.[/green]")

    # Persist selection to a temp file so `oasis apply` picks it up
    import json
    from oasis.config import OASIS_DIR
    selected_path = OASIS_DIR / "pending_applications.json"
    selected_path.write_text(json.dumps([j.model_dump() for j in selected], indent=2))


# ── apply ────────────────────────────────────────────────────────────────────

@app.command()
def apply() -> None:
    """Tailor resume + cover letter for each selected job and save outputs."""
    import json
    from oasis.config import OASIS_DIR, load_config, get_api_key, output_dir
    from oasis.database import set_status
    from oasis.documents import apply_changes, extract_paragraphs
    from oasis.scraper import scrape_company
    from oasis.search import Job
    from oasis.tailor import tailor_documents

    config = load_config()
    api_key = get_api_key()
    if not api_key:
        console.print(
            "[red]No Anthropic API key found.[/red] "
            "Run [bold]oasis setup[/bold] and enter your key from [link=https://console.anthropic.com]console.anthropic.com[/link]."
        )
        raise typer.Exit(1)

    for doc_label, doc_path in [("resume", config.resume_path), ("cover letter", config.cover_letter_path)]:
        if not doc_path or not Path(doc_path).exists():
            console.print(f"[red]Cannot find {doc_label}: {doc_path!r}. Run [bold]oasis setup[/bold] to set paths.[/red]")
            raise typer.Exit(1)

    pending_path = OASIS_DIR / "pending_applications.json"
    if not pending_path.exists():
        console.print("[red]No pending applications. Run [bold]oasis search[/bold] first.[/red]")
        raise typer.Exit(1)

    jobs = [Job(**j) for j in json.loads(pending_path.read_text())]
    out = output_dir()

    console.print(f"\n[cyan]Tailoring documents for {len(jobs)} job(s)...[/cyan]\n")

    resume_paras = extract_paragraphs(config.resume_path)
    cover_paras = extract_paragraphs(config.cover_letter_path)

    for i, job in enumerate(jobs, 1):
        console.print(f"[bold][[{i}/{len(jobs)}]][/bold] {job.title} at {job.company}")

        with console.status("  Scraping company website..."):
            company_info = scrape_company(_company_url(job)) if job.job_url else ""

        if not company_info:
            console.print("  [yellow]⚠ Could not scrape company website — continuing without company context[/yellow]")

        with console.status("  Tailoring with Claude..."):
            result = tailor_documents(
                api_key=api_key,
                job_title=job.title,
                company=job.company,
                job_description=job.description,
                company_info=company_info,
                resume_paragraphs=resume_paras,
                cover_paragraphs=cover_paras,
            )

        slug = _slug(f"{job.company}_{job.title}")
        resume_out = str(out / f"{slug}_resume.docx")
        cover_out = str(out / f"{slug}_cover_letter.docx")

        apply_changes(config.resume_path, result.resume_changes, resume_out)
        apply_changes(config.cover_letter_path, result.cover_letter_changes, cover_out)

        if job.id:
            set_status(job.id, "applied")

        console.print(f"  [green]✓ Saved:[/green] {resume_out}")
        console.print(f"  [green]✓ Saved:[/green] {cover_out}\n")

    pending_path.unlink(missing_ok=True)
    console.print(f"[bold green]Done! All files saved to {out}[/bold green]")


# ── history ──────────────────────────────────────────────────────────────────

@app.command()
def history(
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter by status: applied, rejected, new"),
    applied: bool = typer.Option(False, "--applied", help="Show applied jobs"),
    rejected: bool = typer.Option(False, "--rejected", help="Show rejected jobs"),
) -> None:
    """Show past jobs tracked in the database."""
    from oasis.database import get_history

    filter_status = status
    if applied:
        filter_status = "applied"
    elif rejected:
        filter_status = "rejected"

    rows = get_history(filter_status)

    if not rows:
        label = f" with status '{filter_status}'" if filter_status else ""
        console.print(f"[yellow]No jobs found{label}.[/yellow]")
        return

    table = Table(title=f"Job History ({len(rows)} records)", show_lines=False)
    table.add_column("Status", style="cyan", width=10)
    table.add_column("Title", width=35)
    table.add_column("Company", width=22)
    table.add_column("Location", width=18)
    table.add_column("First Seen", width=12)

    status_colors = {"applied": "green", "rejected": "red", "new": "yellow", "skipped": "dim"}

    for row in rows:
        s = row["status"]
        color = status_colors.get(s, "white")
        date = (row["first_seen"] or "")[:10]
        table.add_row(
            f"[{color}]{s}[/{color}]",
            (row["title"] or "")[:35],
            (row["company"] or "")[:22],
            (row["location"] or "")[:18],
            date,
        )

    console.print(table)


# ── helpers ───────────────────────────────────────────────────────────────────

def _slug(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", text)[:60]


def _company_url(job) -> str:
    """Best-effort: derive company homepage from the job URL domain."""
    if not job.job_url:
        return ""
    from urllib.parse import urlparse
    parsed = urlparse(job.job_url)
    # If it's an Indeed URL, we don't have the company's own domain
    if "indeed.com" in parsed.netloc or "linkedin.com" in parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


if __name__ == "__main__":
    app()
