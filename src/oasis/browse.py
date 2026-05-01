from __future__ import annotations

import webbrowser
from typing import ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Header, Label, Static
from textual.containers import ScrollableContainer

from oasis.search import Job


class DescriptionModal(ModalScreen):
    BINDINGS: ClassVar = [Binding("escape", "dismiss", "Close", priority=True)]

    def __init__(self, job: Job) -> None:
        super().__init__()
        self._job = job

    def compose(self) -> ComposeResult:
        with ScrollableContainer(id="modal-container"):
            yield Label(f"[bold]{self._job.title}[/bold] — {self._job.company}", id="modal-title")
            yield Static(self._job.description or "No description available.", id="modal-body")

    def on_mount(self) -> None:
        container = self.query_one("#modal-container")
        container.styles.width = "80%"
        container.styles.height = "80%"
        container.styles.background = "darkblue"
        container.styles.padding = (1, 2)


class JobBrowser(App):
    CSS = """
    DataTable { height: 1fr; }
    #modal-container { border: solid $accent; }
    #modal-title { padding: 0 1; text-style: bold; }
    #modal-body { padding: 0 1; }
    #status-bar { height: 1; background: $surface; padding: 0 1; color: $text-muted; }
    """

    # priority=True ensures these fire even when DataTable has focus
    BINDINGS: ClassVar = [
        Binding("space", "toggle_select", "Select", show=True, priority=True),
        Binding("o", "open_url", "Open URL", show=True, priority=True),
        Binding("d", "show_description", "Description", show=True, priority=True),
        Binding("r", "reject", "Reject", show=True, priority=True),
        Binding("enter", "confirm", "Confirm", show=True, priority=True),
        Binding("q", "quit_no_confirm", "Quit", show=True, priority=True),
    ]

    def __init__(self, jobs: list[Job]) -> None:
        super().__init__()
        self._jobs = jobs
        self._selected: set[int] = set()
        self._rejected: set[int] = set()

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield DataTable(cursor_type="row", zebra_stripes=True)
        yield Static("", id="status-bar")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("", "Title", "Company", "Location", "Salary")
        self._refresh_table()
        self.title = f"Oasis — {len(self._jobs)} jobs found"
        self.sub_title = "SPACE=select  O=open  D=description  R=reject  ENTER=confirm"

    def _refresh_table(self) -> None:
        table = self.query_one(DataTable)
        table.clear()
        for i, job in enumerate(self._jobs):
            if i in self._rejected:
                continue
            mark = "[green]✓[/green]" if i in self._selected else " "
            table.add_row(
                mark,
                job.title[:48],
                job.company[:28],
                (job.location or "")[:22],
                job.salary[:15] if job.salary else "—",
                key=str(i),
            )

    def _current_job_index(self) -> int | None:
        table = self.query_one(DataTable)
        cursor = table.cursor_row
        keys = list(table.rows.keys())
        if not keys or cursor >= len(keys):
            return None
        return int(keys[cursor].value)

    def _set_status(self, msg: str) -> None:
        self.query_one("#status-bar", Static).update(msg)

    def action_toggle_select(self) -> None:
        idx = self._current_job_index()
        if idx is None:
            return
        if idx in self._selected:
            self._selected.discard(idx)
            self._set_status(f"Deselected: {self._jobs[idx].title}")
        else:
            self._selected.add(idx)
            self._set_status(f"Selected: {self._jobs[idx].title} ({len(self._selected)} total)")
        self._refresh_table()

    def action_open_url(self) -> None:
        idx = self._current_job_index()
        if idx is None:
            return
        url = self._jobs[idx].job_url
        if not url:
            self._set_status("No URL available for this job.")
            return
        self._set_status(f"Opening: {url[:80]}")
        try:
            webbrowser.open(url)
        except Exception as e:
            self._set_status(f"Could not open browser: {e} — URL: {url}")

    def action_show_description(self) -> None:
        idx = self._current_job_index()
        if idx is None:
            return
        self.push_screen(DescriptionModal(self._jobs[idx]))

    def action_reject(self) -> None:
        idx = self._current_job_index()
        if idx is None:
            return
        name = self._jobs[idx].title
        self._selected.discard(idx)
        self._rejected.add(idx)
        self._set_status(f"Rejected: {name}")
        self._refresh_table()

    def action_confirm(self) -> None:
        self.exit(
            result={
                "selected": [self._jobs[i] for i in self._selected],
                "rejected": [self._jobs[i] for i in self._rejected],
            }
        )

    def action_quit_no_confirm(self) -> None:
        self.exit(result={"selected": [], "rejected": [self._jobs[i] for i in self._rejected]})


def browse_jobs(jobs: list[Job]) -> tuple[list[Job], list[Job]]:
    """Launch TUI, return (selected_jobs, rejected_jobs)."""
    result = JobBrowser(jobs).run()
    if result is None:
        return [], []
    return result["selected"], result["rejected"]
