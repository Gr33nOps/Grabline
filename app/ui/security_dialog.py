"""The security report dialog: an advisory summary of a finished download -
risk level, findings, checksums (MD5/SHA-1/SHA-256/SHA-512/CRC32), the local
virus-scan result, and the VirusTotal lookup when a key is set.

Nothing here blocks or deletes. It informs; the user decides.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.core.security import Risk, SecurityReport, check_file
from app.core.settings import Settings

_COLORS = {Risk.OK: "#2ea043", Risk.CAUTION: "#d29922", Risk.WARNING: "#cf222e"}


class _CheckThread(QThread):
    done = Signal(object)

    def __init__(self, work: Callable[[], SecurityReport]) -> None:
        super().__init__()
        self._work = work

    def run(self) -> None:
        self.done.emit(self._work())


def _render(report: SecurityReport) -> str:
    lines = [f"Verdict: {report.level.label}", ""]
    for finding in report.findings:
        lines.append(f"• {finding}")
    if report.virustotal is not None and report.virustotal.known:
        vt = report.virustotal
        lines.append("")
        lines.append(
            f"VirusTotal: {vt.malicious} malicious / {vt.suspicious} suspicious "
            f"of {vt.total} engines"
        )
        if vt.permalink:
            lines.append(f"  {vt.permalink}")
    elif report.virustotal is not None and not report.virustotal.known:
        lines.append("")
        lines.append("VirusTotal: this file is not in their database yet.")
    if report.checksums:
        lines.append("")
        lines.append("── Checksums ──")
        for algorithm, digest in report.checksums.items():
            lines.append(f"{algorithm.upper():<7} {digest}")
    return "\n".join(lines)


class SecurityDialog(QDialog):
    def __init__(
        self,
        path: Path,
        url: str,
        settings: Settings,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Grabline - security check")
        self.setMinimumSize(560, 460)
        layout = QVBoxLayout(self)
        self._verdict = QLabel(f"Checking {path.name} …")
        self._verdict.setStyleSheet("font-size: 15px; font-weight: 600;")
        layout.addWidget(self._verdict)
        note = QLabel(
            "This is advice, not a verdict - a flagged file is kept and stays "
            "usable. Antivirus false positives are common; judge by where the "
            "file came from."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: gray;")
        layout.addWidget(note)

        self._text = QPlainTextEdit()
        self._text.setReadOnly(True)
        self._text.setStyleSheet("font-family: monospace;")
        layout.addWidget(self._text)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        copy = buttons.addButton("Copy", QDialogButtonBox.ButtonRole.ActionRole)
        copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(self._text.toPlainText()))
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

        self._thread = _CheckThread(
            lambda: check_file(
                path,
                url=url,
                virustotal_key=settings.virustotal_key,
                run_local_scan=True,
                proxy=settings.proxy,
            )
        )
        self._thread.done.connect(self._show)
        self._thread.start()

    def _show(self, report: object) -> None:
        assert isinstance(report, SecurityReport)
        color = _COLORS[report.level]
        self._verdict.setText(report.level.label)
        self._verdict.setStyleSheet(f"font-size: 15px; font-weight: 600; color: {color};")
        self._text.setPlainText(_render(report))

    def done(self, result: int) -> None:
        if self._thread.isRunning():
            self._thread.wait(3000)
        super().done(result)
