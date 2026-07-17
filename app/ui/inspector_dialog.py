"""The Download Inspector dialog: a read-only report of everything Grabline
learned about a URL - server/IP/CDN, TLS, MIME, headers, cookies, the redirect
chain, mirrors, and the file's checksum.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.core.inspector import InspectionReport, inspect_url
from app.ui import chrome, motion, threads
from app.ui.format import human_bytes


class _InspectThread(QThread):
    done = Signal(object)

    def __init__(self, work: Callable[[], InspectionReport]) -> None:
        super().__init__()
        self._work = work

    def run(self) -> None:
        self.done.emit(self._work())


def _render(report: InspectionReport) -> str:
    lines: list[str] = []

    def section(title: str) -> None:
        lines.append("")
        lines.append(f"── {title} ──")

    if not report.reachable:
        return f"Could not reach the server.\n\n{report.error}"

    section("Overview")
    lines.append(f"URL:          {report.url}")
    if report.final_url != report.url:
        lines.append(f"Final URL:    {report.final_url}")
    if report.status is not None:
        lines.append(f"Status:       HTTP {report.status}")
    if report.response_ms is not None:
        lines.append(f"Response time: {report.response_ms} ms")
    if report.mime_type:
        lines.append(f"MIME type:    {report.mime_type}")
    if report.content_length is not None:
        lines.append(f"Size:         {human_bytes(report.content_length)}")

    section("Server & location")
    if report.ip_addresses:
        lines.append(f"IP:           {', '.join(report.ip_addresses)}")
    if report.reverse_dns:
        lines.append(f"Reverse DNS:  {report.reverse_dns}")
    if report.cdn:
        lines.append(f"CDN:          {report.cdn}")
    if report.server:
        lines.append(f"Server:       {report.server}")
    if not (report.ip_addresses or report.cdn or report.server):
        lines.append("(no server details available)")
    lines.append("(Grabline shows IP/DNS/CDN only - it never sends the address to a geo service.)")

    if report.tls is not None:
        section("TLS / SSL")
        lines.append(f"Protocol:     {report.tls.version}")
        lines.append(f"Cipher:       {report.tls.cipher}")
        lines.append(f"Subject:      {report.tls.subject}")
        lines.append(f"Issuer:       {report.tls.issuer}")
        lines.append(f"Valid from:   {report.tls.valid_from}")
        lines.append(f"Valid until:  {report.tls.valid_until}")

    if report.redirect_chain:
        section("Redirect chain")
        for status, location in report.redirect_chain:
            lines.append(f"  {status} → {location}")
        lines.append(f"  {report.status} → {report.final_url}")

    if report.mirrors:
        section("Mirrors")
        for mirror in report.mirrors:
            lines.append(f"  {mirror}")

    if report.checksum:
        section("Checksum")
        lines.append(f"SHA-256:      {report.checksum}")

    if report.cookies:
        section(f"Cookies ({len(report.cookies)})")
        for cookie in report.cookies:
            lines.append(f"  {cookie}")

    section(f"HTTP headers ({len(report.headers)})")
    for name, value in report.headers:
        lines.append(f"  {name}: {value}")

    return "\n".join(lines).strip()


class InspectorDialog(chrome.Dialog):
    def __init__(
        self,
        url: str,
        *,
        mirrors: tuple[str, ...] = (),
        checksum_work: Callable[[], str] | None = None,
        headers: dict[str, str] | None = None,
        proxy: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._mirrors = mirrors
        self._checksum_work = checksum_work
        self.setWindowTitle("Download inspector")
        self.setMinimumSize(620, 480)
        layout = QVBoxLayout(self)
        self._status = QLabel(f"Inspecting {url} …")
        layout.addWidget(self._status)
        # A visible loading state while the probe runs - never a blank window.
        self._loading_bar = motion.SmoothProgressBar()
        self._loading_bar.set_indeterminate(True)
        layout.addWidget(self._loading_bar)
        self._loading_note = QLabel("Gathering information… (network probe, DNS, TLS)")
        layout.addWidget(self._loading_note)
        self._text = QPlainTextEdit()
        self._text.setReadOnly(True)
        self._text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._text.setStyleSheet("font-family: monospace;")
        self._text.hide()  # shown when the report lands
        layout.addWidget(self._text)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        copy = buttons.addButton("Copy", QDialogButtonBox.ButtonRole.ActionRole)
        copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(self._text.toPlainText()))
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

        self._thread = _InspectThread(lambda: self._gather(url, headers, proxy))
        self._thread.done.connect(self._show)
        threads.retain(self._thread)  # survives dialog close; see app/ui/threads
        self._thread.start()

    def _gather(
        self, url: str, headers: dict[str, str] | None, proxy: str | None
    ) -> InspectionReport:
        """Runs on the worker thread: the network probe, then the (possibly
        slow) file checksum and the stored mirrors, all off the UI thread."""
        report = inspect_url(url, headers=headers, proxy=proxy)
        checksum = ""
        if self._checksum_work is not None:
            try:
                checksum = self._checksum_work()
            except OSError:
                checksum = ""
        return InspectionReport(
            **{**report.__dict__, "mirrors": self._mirrors, "checksum": checksum}
        )

    def _show(self, report: object) -> None:
        assert isinstance(report, InspectionReport)
        self._loading_bar.set_indeterminate(False)
        self._loading_bar.hide()
        self._loading_note.hide()
        self._text.show()
        self._status.setText(
            "Unreachable" if not report.reachable else f"HTTP {report.status} · done"
        )
        self._text.setPlainText(_render(report))
