"""The History window: every conversation, searchable, resumable.

Left, the list — grouped by day, pinned ones on top, filtered by kind or by a
full-text search. Right, the selected conversation, read-only, with what can be
done to it: resume, rename, pin, export to Markdown, delete.

The last filter, *Mes sessions Claude Code*, swaps the source for the
transcripts Claude Code keeps in ~/.claude/projects. Those are read-only here:
they can be read and exported, never resumed, renamed or deleted from this
window — they belong to Claude Code, not to this app.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTextBrowser,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .claude_transcripts import TranscriptSession, as_markdown, list_sessions
from .history import KINDS, Conversation, HistoryStore, group_by_date

#: The pseudo-kind that switches to Claude Code's own transcripts.
TRANSCRIPTS = "__transcripts__"

_ROLE = Qt.ItemDataRole.UserRole
_SEARCH_DELAY_MS = 180


class HistoryWindow(QDialog):
    """Browse, search and act on past conversations."""

    #: A conversation id to continue in the answer panel.
    resume_requested = Signal(int)

    def __init__(self, store: HistoryStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Historique")
        self.setObjectName("panel")
        self.resize(980, 620)
        self._store = store
        self._current: Conversation | TranscriptSession | None = None

        self._search = QLineEdit(self)
        self._search.setObjectName("search")
        self._search.setPlaceholderText("Rechercher dans toutes les discussions…")
        self._search.setClearButtonEnabled(True)
        # Debounced: FTS is fast, but rebuilding the tree on every keystroke of
        # a fast typist makes the list flicker.
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(_SEARCH_DELAY_MS)
        self._debounce.timeout.connect(self.refresh)
        self._search.textChanged.connect(lambda _t: self._debounce.start())

        self._kind = QComboBox(self)
        self._kind.addItem("Tout", "")
        for key, label in KINDS.items():
            self._kind.addItem(label, key)
        self._kind.addItem("Mes sessions Claude Code", TRANSCRIPTS)
        self._kind.currentIndexChanged.connect(lambda _i: self.refresh())
        # The filter sizes to its labels; the search field gets the rest.
        self._kind.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self._search.setMinimumWidth(180)

        self._tree = QTreeWidget(self)
        self._tree.setHeaderHidden(True)
        self._tree.setRootIsDecorated(False)
        self._tree.currentItemChanged.connect(lambda item, _prev: self._show(item))

        self._count = QLabel("", self)
        self._count.setObjectName("caption")

        filters = QHBoxLayout()
        filters.addWidget(self._search, 1)
        filters.addWidget(self._kind)

        left = QWidget(self)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addLayout(filters)
        left_layout.addWidget(self._tree, 1)
        left_layout.addWidget(self._count)

        self._view = QTextBrowser(self)
        self._view.setOpenExternalLinks(True)
        self._view.setPlaceholderText("Choisissez une discussion à gauche.")

        self._resume = QPushButton("Reprendre", self)
        self._resume.setDefault(True)
        self._resume.clicked.connect(self._on_resume)
        self._rename = QPushButton("Renommer", self)
        self._rename.clicked.connect(self._on_rename)
        self._pin = QPushButton("Épingler", self)
        self._pin.clicked.connect(self._on_pin)
        self._export = QPushButton("Exporter…", self)
        self._export.clicked.connect(self._on_export)
        self._delete = QPushButton("Supprimer", self)
        self._delete.setObjectName("danger")
        self._delete.clicked.connect(self._on_delete)

        actions = QHBoxLayout()
        actions.addWidget(self._delete)
        actions.addStretch(1)
        actions.addWidget(self._export)
        actions.addWidget(self._pin)
        actions.addWidget(self._rename)
        actions.addWidget(self._resume)

        right = QWidget(self)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(self._view, 1)
        right_layout.addLayout(actions)

        splitter = QSplitter(self)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([360, 620])

        wipe = QPushButton("Tout effacer…", self)
        wipe.setObjectName("quiet")
        wipe.clicked.connect(self._on_clear_all)
        close = QPushButton("Fermer", self)
        close.clicked.connect(self.hide)
        bottom = QHBoxLayout()
        bottom.addWidget(wipe)
        bottom.addStretch(1)
        bottom.addWidget(close)

        layout = QVBoxLayout(self)
        layout.addWidget(splitter, 1)
        layout.addLayout(bottom)
        self._update_actions()

    # -- listing ------------------------------------------------------------

    @property
    def _showing_transcripts(self) -> bool:
        return self._kind.currentData() == TRANSCRIPTS

    def refresh(self) -> None:
        selected = self._selected_key()
        self._tree.clear()
        text = self._search.text().strip()

        if self._showing_transcripts:
            sessions = list_sessions()
            if text:
                needle = text.casefold()
                sessions = [
                    s
                    for s in sessions
                    if needle in s.title.casefold() or needle in s.project.casefold()
                ]
            for session in sessions:
                item = QTreeWidgetItem([f"{session.title}\n{session.project}"])
                item.setData(0, _ROLE, ("transcript", session))
                self._tree.addTopLevelItem(item)
            self._count.setText(f"{len(sessions)} session(s) — lecture seule")
        else:
            kind = self._kind.currentData() or None
            if text:
                hits = self._store.search(text, kind=kind)
                for hit in hits:
                    item = QTreeWidgetItem(
                        [f"{hit.conversation.title or 'Sans titre'}\n{hit.snippet}"]
                    )
                    item.setData(0, _ROLE, ("conversation", hit.conversation))
                    self._tree.addTopLevelItem(item)
                self._count.setText(f"{len(hits)} résultat(s)")
            else:
                conversations = self._store.conversations(kind=kind)
                for label, group in group_by_date(conversations):
                    header = QTreeWidgetItem([label])
                    header.setFlags(Qt.ItemFlag.ItemIsEnabled)
                    font = header.font(0)
                    font.setBold(True)
                    header.setFont(0, font)
                    self._tree.addTopLevelItem(header)
                    for conversation in group:
                        marker = "📌 " if conversation.pinned else ""
                        kind_label = KINDS.get(conversation.kind, conversation.kind)
                        local = conversation.updated_at.astimezone()
                        item = QTreeWidgetItem(
                            [
                                f"{marker}{conversation.title or 'Sans titre'}\n"
                                f"{kind_label} · {local:%d/%m %H:%M}"
                            ]
                        )
                        item.setData(0, _ROLE, ("conversation", conversation))
                        self._tree.addTopLevelItem(item)
                self._count.setText(f"{len(conversations)} discussion(s)")

        self._reselect(selected)

    def _selected_key(self):
        item = self._tree.currentItem()
        data = item.data(0, _ROLE) if item else None
        if not data:
            return None
        kind, value = data
        return (kind, value.id if kind == "conversation" else value.session_id)

    def _reselect(self, key) -> None:
        for index in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(index)
            data = item.data(0, _ROLE)
            if not data:
                continue
            kind, value = data
            ident = value.id if kind == "conversation" else value.session_id
            if key is None or (kind, ident) == key:
                self._tree.setCurrentItem(item)
                return
        self._show(None)

    # -- showing ------------------------------------------------------------

    def _show(self, item) -> None:
        data = item.data(0, _ROLE) if item else None
        if not data:
            self._current = None
            self._view.clear()
            self._update_actions()
            return
        kind, value = data
        self._current = value
        if kind == "transcript":
            self._view.setMarkdown(as_markdown(value))
        else:
            fresh = self._store.conversation(value.id)
            self._current = fresh or value
            self._view.setMarkdown(self._store.export_markdown(value.id))
        self._update_actions()

    def _update_actions(self) -> None:
        current = self._current
        own = isinstance(current, Conversation)
        self._export.setEnabled(current is not None)
        for button in (self._rename, self._pin, self._delete):
            button.setEnabled(own)
        # Resuming needs the Claude Code session id; a conversation that never
        # got an answer has none.
        self._resume.setEnabled(own and bool(current.sdk_session_id))
        self._resume.setToolTip(
            ""
            if not own or current.sdk_session_id
            else "Cette discussion n'a jamais reçu de réponse : rien à reprendre."
        )
        self._pin.setText("Désépingler" if own and current.pinned else "Épingler")

    # -- actions ------------------------------------------------------------

    def _on_resume(self) -> None:
        if isinstance(self._current, Conversation):
            self.resume_requested.emit(self._current.id)
            self.hide()

    def _on_rename(self) -> None:
        if not isinstance(self._current, Conversation):
            return
        title, ok = QInputDialog.getText(
            self, "Renommer", "Nouveau titre :", text=self._current.title
        )
        if ok and title.strip():
            self._store.rename(self._current.id, title)
            self.refresh()

    def _on_pin(self) -> None:
        if isinstance(self._current, Conversation):
            self._store.pin(self._current.id, not self._current.pinned)
            self.refresh()

    def _on_delete(self) -> None:
        if not isinstance(self._current, Conversation):
            return
        answer = QMessageBox.question(
            self,
            "Supprimer",
            f"Supprimer « {self._current.title or 'Sans titre'} » ? "
            "Les messages et les miniatures de captures sont effacés.",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._store.delete(self._current.id)
            self._current = None
            self.refresh()

    def _on_export(self) -> None:
        current = self._current
        if current is None:
            return
        if isinstance(current, Conversation):
            text, name = self._store.export_markdown(current.id), current.title
        else:
            text, name = as_markdown(current), current.title
        safe = "".join(c for c in (name or "discussion") if c.isalnum() or c in " -_")[
            :60
        ]
        path, _filter = QFileDialog.getSaveFileName(
            self,
            "Exporter en Markdown",
            str(Path.home() / f"{safe.strip() or 'discussion'}.md"),
            "Markdown (*.md)",
        )
        if path:
            Path(path).write_text(text, encoding="utf-8")

    def _on_clear_all(self) -> None:
        answer = QMessageBox.warning(
            self,
            "Tout effacer",
            "Effacer toutes les discussions, y compris les épinglées ? "
            "C'est définitif. Vos sessions Claude Code ne sont pas touchées.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._store.clear()
            self._current = None
            self.refresh()

    def open_history(self) -> None:
        self.refresh()
        self.show()
        self.raise_()
        self.activateWindow()
        self._search.setFocus()
