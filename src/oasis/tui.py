from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, ScrollableContainer, Vertical
from textual.screen import Screen
from textual.widgets import (
    Button, DataTable, Footer, Header, Input,
    Label, ListItem, ListView, LoadingIndicator,
    Static, TabbedContent, TabPane,
)

from oasis.search import Job

PAGE_SIZE = 20


# ── helpers ───────────────────────────────────────────────────────────────────

def _open_url(url: str) -> None:
    """Open a URL in the system browser, handling macOS, WSL, and Linux."""
    if sys.platform == "darwin":
        subprocess.Popen(["open", url])
        return
    # Detect WSL by checking for /proc/version containing "microsoft"
    try:
        wsl = "microsoft" in Path("/proc/version").read_text().lower()
    except OSError:
        wsl = False
    if wsl:
        # Hand off to Windows via cmd.exe — escaping spaces in the URL
        subprocess.Popen(["cmd.exe", "/c", "start", "", url])
        return
    # Native Linux — try xdg-open, fall back to webbrowser
    try:
        subprocess.Popen(["xdg-open", url])
    except FileNotFoundError:
        import webbrowser
        webbrowser.open(url)

def _pick_file_sync(label: str, current: str = "") -> str:
    doc_types = [("Documents", "*.pdf *.docx *.PDF *.DOCX"), ("All files", "*.*")]
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askopenfilename(
            title=f"Select your {label}",
            filetypes=doc_types,
            initialfile=current or "",
        )
        root.destroy()
        return path or current
    except Exception:
        return current


# ── main menu ─────────────────────────────────────────────────────────────────

class MainMenuScreen(Screen):
    BINDINGS: ClassVar = [Binding("q", "app.quit", "Quit", priority=True)]

    CSS = """
    MainMenuScreen { align: center middle; }
    #menu-box { width: 46; height: auto; border: round $accent; padding: 1 2; }
    #menu-title { text-style: bold; color: $accent; text-align: center; margin-bottom: 1; }
    #menu-subtitle { color: $text-muted; text-align: center; margin-bottom: 1; }
    ListView { height: auto; border: none; }
    ListItem { padding: 0 1; }
    ListItem:hover { background: $accent 20%; }
    """

    def compose(self) -> ComposeResult:
        with Container(id="menu-box"):
            yield Label("✦  O A S I S", id="menu-title")
            yield Label("Job Search & Application Tailor", id="menu-subtitle")
            yield ListView(
                ListItem(Label("  Search Jobs"), id="item-search"),
                ListItem(Label("  View History"), id="item-history"),
                ListItem(Label("  My Documents"), id="item-documents"),
                ListItem(Label("  Settings"), id="item-settings"),
                ListItem(Label("  Quit"), id="item-quit"),
                id="main-menu",
            )
        yield Footer()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        mapping = {
            "item-search":    lambda: self.app.push_screen(SearchScreen()),
            "item-history":   lambda: self.app.push_screen(HistoryScreen()),
            "item-documents": lambda: self.app.push_screen(DocumentsScreen()),
            "item-settings":  lambda: self.app.push_screen(SettingsScreen()),
            "item-quit":      lambda: self.app.exit(),
        }
        action = mapping.get(event.item.id or "")
        if action:
            action()


# ── search screen ─────────────────────────────────────────────────────────────

class SearchScreen(Screen):
    """Shows saved criteria, lets her edit inline, then kicks off the search."""

    BINDINGS: ClassVar = [Binding("escape", "app.pop_screen", "Back", priority=True)]

    CSS = """
    SearchScreen { align: center middle; }
    #search-box { width: 60; height: auto; border: round $accent; padding: 1 2; }
    #search-title { text-style: bold; color: $accent; margin-bottom: 1; }
    .field-label { color: $text-muted; margin-top: 1; }
    Input { margin-bottom: 0; }
    #search-btn { margin-top: 1; width: 100%; }
    """

    def compose(self) -> ComposeResult:
        from oasis.config import load_config
        config = load_config()

        with Container(id="search-box"):
            yield Label("Search Jobs", id="search-title")
            yield Label("Job titles (comma-separated)", classes="field-label")
            yield Input(
                value=", ".join(config.search_terms),
                placeholder="e.g. UX Designer, Product Manager",
                id="input-terms",
            )
            yield Label("Locations (comma-separated, or leave blank for any)", classes="field-label")
            yield Input(
                value=", ".join(config.locations),
                placeholder="e.g. Austin TX, Remote",
                id="input-locs",
            )
            yield Button("Search →", id="search-btn", variant="primary")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "search-btn":
            self._run_search()

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        self._run_search()

    def _run_search(self) -> None:
        from oasis.config import load_config, save_config
        config = load_config()

        terms_raw = self.query_one("#input-terms", Input).value
        locs_raw = self.query_one("#input-locs", Input).value

        terms = [t.strip() for t in terms_raw.split(",") if t.strip()]
        locs  = [l.strip() for l in locs_raw.split(",") if l.strip()]

        if not terms:
            self.notify("Enter at least one job title.", severity="warning")
            return

        # Persist any edits back to config
        config.search_terms = terms
        config.locations = locs
        save_config(config)

        self.app.push_screen(LoadingScreen(terms, locs, config))


# ── loading screen ────────────────────────────────────────────────────────────

class LoadingScreen(Screen):
    CSS = """
    LoadingScreen { align: center middle; }
    #loading-box { width: 50; height: auto; border: round $accent; padding: 1 2; }
    #loading-label { text-align: center; margin-bottom: 1; }
    LoadingIndicator { height: 3; }
    """

    def __init__(self, terms: list[str], locs: list[str], config) -> None:
        super().__init__()
        self._terms = terms
        self._locs = locs
        self._config = config

    def compose(self) -> ComposeResult:
        locs_str = ", ".join(self._locs) if self._locs else "any location"
        with Container(id="loading-box"):
            yield Label(
                f"Searching for [bold]{', '.join(self._terms)}[/bold]\nin [bold]{locs_str}[/bold]",
                id="loading-label",
            )
            yield LoadingIndicator()
        yield Footer()

    def on_mount(self) -> None:
        self.run_worker(self._do_search, thread=True)

    def _do_search(self) -> None:
        from oasis.database import filter_unseen, upsert_jobs
        from oasis.search import search_jobs

        jobs = search_jobs(
            search_terms=self._terms,
            locations=self._locs,
            job_type=self._config.job_type,
            remote=self._config.remote,
            results_wanted=self._config.results_wanted,
        )

        raw = [j.model_dump() for j in jobs]
        upsert_jobs(raw)
        unseen_raw = filter_unseen(raw)

        unseen: list[Job] = []
        for r in unseen_raw:
            j = Job(**{k: v for k, v in r.items() if k != "_id"})
            j.id = r.get("_id", "")
            unseen.append(j)

        self.app.call_from_thread(self._show_results, jobs, unseen)

    def _show_results(self, all_jobs: list[Job], unseen: list[Job]) -> None:
        if not unseen:
            self.app.pop_screen()  # back to search
            self.notify(
                f"All {len(all_jobs)} jobs already seen. Check History for past results.",
                severity="warning",
                timeout=6,
            )
            return
        # Replace this screen with the browser (can't go "back" to loading)
        self.app.switch_screen(JobBrowserScreen(unseen))


# ── job browser ───────────────────────────────────────────────────────────────

class JobBrowserScreen(Screen):
    BINDINGS: ClassVar = [
        Binding("space",  "toggle_select",    "Select",      show=True, priority=True),
        Binding("o",      "open_url",         "Open URL",    show=True, priority=True),
        Binding("d",      "show_description", "Description", show=True, priority=True),
        Binding("r",      "reject",           "Reject",      show=True, priority=True),
        Binding("n",      "next_page",        "Next 20",     show=True, priority=True),
        Binding("p",      "prev_page",        "Prev 20",     show=True, priority=True),
        Binding("enter",  "confirm",          "Apply",       show=True, priority=True),
        Binding("escape", "app.pop_screen",   "Back",        show=True, priority=True),
    ]

    CSS = """
    JobBrowserScreen { layout: vertical; }
    #browser-header { height: 1; background: $surface; padding: 0 1; }
    DataTable { height: 1fr; }
    #browser-status { height: 1; background: $surface; padding: 0 1; color: $text-muted; }
    """

    def __init__(self, jobs: list[Job]) -> None:
        super().__init__()
        self._all_jobs = jobs
        self._page = 0
        self._selected: set[str] = set()   # job IDs
        self._rejected: set[str] = set()

    @property
    def _page_jobs(self) -> list[Job]:
        start = self._page * PAGE_SIZE
        return self._all_jobs[start : start + PAGE_SIZE]

    @property
    def _total_pages(self) -> int:
        return max(1, (len(self._all_jobs) + PAGE_SIZE - 1) // PAGE_SIZE)

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("", id="browser-header")
        yield DataTable(cursor_type="row", zebra_stripes=True, id="job-table")
        yield Static("", id="browser-status")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("", "Title", "Company", "Location", "Salary")
        self._refresh()

    def _refresh(self) -> None:
        table = self.query_one(DataTable)
        table.clear()

        start = self._page * PAGE_SIZE
        for i, job in enumerate(self._page_jobs):
            if job.id in self._rejected:
                continue
            mark = "[green]✓[/green]" if job.id in self._selected else " "
            table.add_row(
                mark,
                job.title[:48],
                job.company[:28],
                (job.location or "")[:22],
                job.salary[:14] if job.salary else "—",
                key=str(start + i),
            )

        total = len(self._all_jobs)
        end = min(start + PAGE_SIZE, total)
        sel = len(self._selected)
        self.query_one("#browser-header", Static).update(
            f"[bold]Page {self._page + 1}/{self._total_pages}[/bold]  "
            f"Showing {start + 1}–{end} of {total} new jobs  •  "
            f"[green]{sel} selected[/green]"
        )
        self.query_one("#browser-status", Static).update(
            "SPACE=select  O=open  D=desc  R=reject  N=next  P=prev  ENTER=confirm & apply"
        )

    def _current_job(self) -> Job | None:
        table = self.query_one(DataTable)
        keys = list(table.rows.keys())
        if not keys or table.cursor_row >= len(keys):
            return None
        idx = int(keys[table.cursor_row].value)
        if idx >= len(self._all_jobs):
            return None
        return self._all_jobs[idx]

    def _set_status(self, msg: str) -> None:
        self.query_one("#browser-status", Static).update(msg)

    def action_toggle_select(self) -> None:
        job = self._current_job()
        if not job:
            return
        if job.id in self._selected:
            self._selected.discard(job.id)
            self._set_status(f"Deselected: {job.title}")
        else:
            self._selected.add(job.id)
            self._set_status(f"Selected: {job.title} ({len(self._selected)} total)")
        self._refresh()

    def action_open_url(self) -> None:
        job = self._current_job()
        if not job or not job.job_url:
            self._set_status("No URL for this job.")
            return
        self._set_status(f"Opening: {job.job_url[:80]}")
        try:
            _open_url(job.job_url)
        except Exception as e:
            self._set_status(f"Could not open browser — {job.job_url}")

    def action_show_description(self) -> None:
        job = self._current_job()
        if job:
            self.app.push_screen(DescriptionModal(job))

    def action_reject(self) -> None:
        from oasis.database import set_status
        job = self._current_job()
        if not job:
            return
        self._selected.discard(job.id)
        self._rejected.add(job.id)
        if job.id:
            set_status(job.id, "rejected")
        self._set_status(f"Rejected: {job.title}")
        self._refresh()

    def action_next_page(self) -> None:
        if self._page < self._total_pages - 1:
            self._page += 1
            self._refresh()

    def action_prev_page(self) -> None:
        if self._page > 0:
            self._page -= 1
            self._refresh()

    def action_confirm(self) -> None:
        import json
        from oasis.config import OASIS_DIR
        selected = [j for j in self._all_jobs if j.id in self._selected]
        if not selected:
            self.notify("No jobs selected. Use SPACE to select jobs first.", severity="warning")
            return
        OASIS_DIR.mkdir(parents=True, exist_ok=True)
        (OASIS_DIR / "pending_applications.json").write_text(
            json.dumps([j.model_dump() for j in selected], indent=2)
        )
        self.app.switch_screen(ApplyScreen(selected))


# ── description modal ─────────────────────────────────────────────────────────

class DescriptionModal(Screen):
    BINDINGS: ClassVar = [Binding("escape", "app.pop_screen", "Close", priority=True)]

    CSS = """
    DescriptionModal { align: center middle; }
    #desc-box { width: 80%; height: 80%; border: round $accent; background: $surface; }
    #desc-title { padding: 1 2; text-style: bold; background: $accent 30%; }
    #desc-body { padding: 1 2; height: 1fr; overflow-y: scroll; }
    """

    def __init__(self, job: Job) -> None:
        super().__init__()
        self._job = job

    def compose(self) -> ComposeResult:
        with Container(id="desc-box"):
            yield Label(f"{self._job.title} — {self._job.company}", id="desc-title")
            with ScrollableContainer(id="desc-body"):
                yield Static(self._job.description or "No description available.")
        yield Footer()


# ── apply screen ──────────────────────────────────────────────────────────────

class ApplyScreen(Screen):
    """Runs document tailoring for each selected job, showing progress."""

    CSS = """
    ApplyScreen { align: center middle; }
    #apply-box { width: 65; height: auto; border: round $accent; padding: 1 2; }
    #apply-title { text-style: bold; color: $accent; margin-bottom: 1; }
    #apply-log { height: 14; overflow-y: scroll; background: $surface; padding: 0 1; }
    #apply-done-btn { margin-top: 1; width: 100%; }
    """

    def __init__(self, jobs: list[Job]) -> None:
        super().__init__()
        self._jobs = jobs
        self._done = False

    def compose(self) -> ComposeResult:
        with Container(id="apply-box"):
            yield Label(f"Tailoring {len(self._jobs)} application(s)…", id="apply-title")
            yield Static("", id="apply-log")
            yield Button("Back to Menu", id="apply-done-btn", variant="success", disabled=True)
        yield Footer()

    def on_mount(self) -> None:
        self.run_worker(self._do_apply, thread=True)

    def _log(self, msg: str) -> None:
        self.app.call_from_thread(self._append_log, msg)

    def _append_log(self, msg: str) -> None:
        log = self.query_one("#apply-log", Static)
        current = str(log.renderable) if log.renderable else ""
        log.update((current + "\n" + msg).strip())

    def _do_apply(self) -> None:
        from oasis.config import get_api_key, load_config, output_dir
        from oasis.database import set_status
        from oasis.documents import apply_changes, extract_paragraphs
        from oasis.scraper import scrape_company
        from oasis.tailor import tailor_documents
        from urllib.parse import urlparse
        import re

        config = load_config()
        api_key = get_api_key()

        if not api_key:
            self._log("[red]✗ No Anthropic API key — run oasis setup from the terminal.[/red]")
            self.app.call_from_thread(self._finish)
            return

        for doc_label, path in [("resume", config.resume_path), ("cover letter", config.cover_letter_path)]:
            if not path or not Path(path).exists():
                self._log(f"[red]✗ {doc_label} not found: {path!r}[/red]")
                self.app.call_from_thread(self._finish)
                return

        resume_paras = extract_paragraphs(config.resume_path)
        cover_paras  = extract_paragraphs(config.cover_letter_path)
        out = output_dir()

        for i, job in enumerate(self._jobs, 1):
            self._log(f"[bold][{i}/{len(self._jobs)}][/bold] {job.title} @ {job.company}")

            # Company scraping
            company_url = ""
            if job.job_url:
                parsed = urlparse(job.job_url)
                if "indeed.com" not in parsed.netloc and "linkedin.com" not in parsed.netloc:
                    company_url = f"{parsed.scheme}://{parsed.netloc}"
            company_info = scrape_company(company_url) if company_url else ""
            self._log("  ↳ Company info scraped" if company_info else "  ↳ No company URL available")

            # Tailor
            self._log("  ↳ Tailoring with Claude…")
            try:
                result = tailor_documents(
                    api_key=api_key,
                    job_title=job.title,
                    company=job.company,
                    job_description=job.description,
                    company_info=company_info,
                    resume_paragraphs=resume_paras,
                    cover_paragraphs=cover_paras,
                )
            except Exception as e:
                self._log(f"  [red]✗ Tailoring failed: {e}[/red]")
                continue

            slug = re.sub(r"[^a-zA-Z0-9_-]", "_", f"{job.company}_{job.title}")[:60]
            resume_out = str(out / f"{slug}_resume.docx")
            cover_out  = str(out / f"{slug}_cover_letter.docx")

            apply_changes(config.resume_path, result.resume_changes, resume_out)
            apply_changes(config.cover_letter_path, result.cover_letter_changes, cover_out)

            if job.id:
                set_status(job.id, "applied")

            self._log(f"  [green]✓ Saved to ~/oasis-output/[/green]")

        self._log(f"\n[bold green]Done! Files saved to {out}[/bold green]")
        self.app.call_from_thread(self._finish)

    def _finish(self) -> None:
        self.query_one("#apply-done-btn", Button).disabled = False

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "apply-done-btn":
            # Pop back to main menu (pop LoadingScreen was switched, so just pop twice)
            self.app.pop_screen()


# ── history screen ────────────────────────────────────────────────────────────

class HistoryScreen(Screen):
    BINDINGS: ClassVar = [Binding("escape", "app.pop_screen", "Back", priority=True)]

    CSS = """
    HistoryScreen { layout: vertical; }
    TabbedContent { height: 1fr; }
    DataTable { height: 1fr; }
    """

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent("All", "Applied", "Rejected", "New"):
            with TabPane("All", id="tab-all"):
                yield DataTable(id="tbl-all", cursor_type="row", zebra_stripes=True)
            with TabPane("Applied", id="tab-applied"):
                yield DataTable(id="tbl-applied", cursor_type="row", zebra_stripes=True)
            with TabPane("Rejected", id="tab-rejected"):
                yield DataTable(id="tbl-rejected", cursor_type="row", zebra_stripes=True)
            with TabPane("New", id="tab-new"):
                yield DataTable(id="tbl-new", cursor_type="row", zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        for tbl_id, status in [
            ("tbl-all", None),
            ("tbl-applied", "applied"),
            ("tbl-rejected", "rejected"),
            ("tbl-new", "new"),
        ]:
            self._populate(tbl_id, status)

    def _populate(self, tbl_id: str, status: str | None) -> None:
        from oasis.database import get_history
        colors = {"applied": "green", "rejected": "red", "new": "yellow"}

        table = self.query_one(f"#{tbl_id}", DataTable)
        table.add_columns("Status", "Title", "Company", "Location", "First Seen")
        for row in get_history(status):
            s = row["status"]
            c = colors.get(s, "white")
            table.add_row(
                f"[{c}]{s}[/{c}]",
                (row["title"] or "")[:40],
                (row["company"] or "")[:25],
                (row["location"] or "")[:20],
                (row["first_seen"] or "")[:10],
            )


# ── documents screen ──────────────────────────────────────────────────────────

class DocumentsScreen(Screen):
    BINDINGS: ClassVar = [Binding("escape", "app.pop_screen", "Back", priority=True)]

    CSS = """
    DocumentsScreen { align: center middle; }
    #docs-box { width: 60; height: auto; border: round $accent; padding: 1 2; }
    #docs-title { text-style: bold; color: $accent; margin-bottom: 1; }
    .field-label { color: $text-muted; margin-top: 1; }
    .file-row { height: 3; margin-bottom: 0; }
    .file-row Input { width: 1fr; }
    .file-row Button { width: 12; margin-left: 1; }
    #save-btn { margin-top: 1; width: 100%; }
    """

    def compose(self) -> ComposeResult:
        from oasis.config import load_config
        config = load_config()
        with Container(id="docs-box"):
            yield Label("My Documents", id="docs-title")
            yield Label("Resume (PDF or DOCX)", classes="field-label")
            with Horizontal(classes="file-row"):
                yield Input(value=config.resume_path or "", placeholder="No file selected", id="resume-input")
                yield Button("Browse…", id="browse-resume", variant="primary")
            yield Label("Cover Letter (PDF or DOCX)", classes="field-label")
            with Horizontal(classes="file-row"):
                yield Input(value=config.cover_letter_path or "", placeholder="No file selected", id="cover-input")
                yield Button("Browse…", id="browse-cover", variant="primary")
            yield Button("Save", id="save-btn", variant="success")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "browse-resume":
            self.run_worker(self._pick_resume, thread=True)
        elif event.button.id == "browse-cover":
            self.run_worker(self._pick_cover, thread=True)
        elif event.button.id == "save-btn":
            self._save()

    def _pick_resume(self) -> None:
        current = self.query_one("#resume-input", Input).value
        path = _pick_file_sync("resume", current)
        if path and path != current:
            self.app.call_from_thread(
                lambda: self.query_one("#resume-input", Input).__setattr__("value", path)
            )

    def _pick_cover(self) -> None:
        current = self.query_one("#cover-input", Input).value
        path = _pick_file_sync("cover letter", current)
        if path and path != current:
            self.app.call_from_thread(
                lambda: self.query_one("#cover-input", Input).__setattr__("value", path)
            )

    def _save(self) -> None:
        from oasis.config import load_config, save_config
        config = load_config()
        config.resume_path = self.query_one("#resume-input", Input).value
        config.cover_letter_path = self.query_one("#cover-input", Input).value
        save_config(config)
        self.notify("Documents saved!", severity="information")
        self.app.pop_screen()


# ── settings screen ───────────────────────────────────────────────────────────

class SettingsScreen(Screen):
    BINDINGS: ClassVar = [Binding("escape", "app.pop_screen", "Back", priority=True)]

    CSS = """
    SettingsScreen { align: center middle; }
    #settings-box { width: 60; height: auto; border: round $accent; padding: 1 2; }
    #settings-title { text-style: bold; color: $accent; margin-bottom: 1; }
    .field-label { color: $text-muted; margin-top: 1; }
    #save-settings-btn { margin-top: 1; width: 100%; }
    """

    def compose(self) -> ComposeResult:
        from oasis.config import load_config
        config = load_config()
        with Container(id="settings-box"):
            yield Label("Settings", id="settings-title")
            yield Label("Job titles (comma-separated)", classes="field-label")
            yield Input(value=", ".join(config.search_terms), id="inp-terms",
                        placeholder="e.g. UX Designer, Product Manager")
            yield Label("Locations (comma-separated)", classes="field-label")
            yield Input(value=", ".join(config.locations), id="inp-locs",
                        placeholder="e.g. Austin TX, Remote")
            yield Label("Job type (fulltime / parttime / contract / any)", classes="field-label")
            yield Input(value=config.job_type, id="inp-type")
            yield Button("Save Settings", id="save-settings-btn", variant="success")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "save-settings-btn":
            return
        from oasis.config import load_config, save_config
        config = load_config()
        config.search_terms = [t.strip() for t in
                               self.query_one("#inp-terms", Input).value.split(",") if t.strip()]
        config.locations    = [l.strip() for l in
                               self.query_one("#inp-locs", Input).value.split(",") if l.strip()]
        jt = self.query_one("#inp-type", Input).value.strip().lower()
        if jt in ("fulltime", "parttime", "contract", "any"):
            config.job_type = jt  # type: ignore[assignment]
        save_config(config)
        self.notify("Settings saved!", severity="information")
        self.app.pop_screen()


# ── app entry point ───────────────────────────────────────────────────────────

class OasisApp(App):
    TITLE = "Oasis"

    def on_mount(self) -> None:
        self.push_screen(MainMenuScreen())


def launch() -> None:
    OasisApp().run()
