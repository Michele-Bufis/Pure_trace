from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QLineEdit, QPushButton, QFrame, QScroller,
)
from cryptography.exceptions import InvalidTag
from pure_trace.data_layer import ProfileManager, EncryptionManager, Profile
from pure_trace.logging_setup import get_logger
from pure_trace.ui import theme

log = get_logger(__name__)


class ProfileSelectionDialog(QDialog):
    def __init__(self, pm: ProfileManager, parent=None):
        super().__init__(parent)
        self._pm = pm
        self._profile: Profile | None = None
        self._enc: EncryptionManager | None = None
        self.setWindowTitle("Pure-Trace — Seleziona Profilo")
        # Landscape card sized to fit the 800x480 Raspberry Pi display (the old
        # vertical layout needed ~540 px of height and got squashed on a 480 px
        # screen, making the profile names unreadable).
        self.setMinimumSize(640, 400)
        self.resize(740, 440)
        self.setStyleSheet(f"QDialog{{background:{theme.BG}}}")
        self._build_ui()
        self._load_profiles()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.addStretch()

        card = QFrame()
        card.setStyleSheet(theme.card_qss())
        card.setMaximumSize(700, 380)
        cl = QHBoxLayout(card)
        cl.setContentsMargins(30, 26, 30, 26)
        cl.setSpacing(28)

        # ── left column: brand ───────────────────────────────────────────
        left = QVBoxLayout()
        left.setSpacing(10)
        left.addStretch()
        logo = QLabel("+")
        logo.setFixedSize(56, 56)
        logo.setAlignment(Qt.AlignCenter)
        logo.setStyleSheet(
            f"color:{theme.ACCENT};background:{theme.ACCENT_SF};"
            f"border-radius:15px;font-size:28px;font-weight:bold"
        )
        left.addWidget(logo)
        title = QLabel("Pure-Trace")
        title.setStyleSheet(f"color:{theme.TEXT};font-size:24px;font-weight:700;border:none")
        left.addWidget(title)
        sub = QLabel("Seleziona il profilo\ne inserisci la password")
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color:{theme.MUTED};font-size:13px;border:none")
        left.addWidget(sub)
        left.addStretch()

        # Il dispositivo classifica lo stato del paziente con un semaforo: va
        # detto esplicitamente che non è uno strumento diagnostico.
        disclaimer = QLabel("Prototipo di ricerca.\nNon è un dispositivo medico "
                            "e non va usato a fini diagnostici.")
        disclaimer.setWordWrap(True)
        disclaimer.setStyleSheet(
            f"color:{theme.MUTED};font-size:10px;border:none")
        left.addWidget(disclaimer)
        left_w = QFrame()
        left_w.setFixedWidth(230)
        left_w.setStyleSheet("border:none")
        left_w.setLayout(left)
        cl.addWidget(left_w)

        # vertical divider
        divider = QFrame()
        divider.setFrameShape(QFrame.VLine)
        divider.setStyleSheet(f"color:{theme.BORDER}")
        cl.addWidget(divider)

        # ── right column: profile list + password + login ────────────────
        right = QVBoxLayout()
        right.setSpacing(10)

        right.addWidget(self._field_label("PROFILO"))
        self._list = QListWidget()
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # touch: drag to scroll the patient list (kinetic), tap to select
        QScroller.grabGesture(self._list.viewport(), QScroller.LeftMouseButtonGesture)
        right.addWidget(self._list, stretch=1)

        right.addWidget(self._field_label("PASSWORD"))
        self._pwd = QLineEdit()
        self._pwd.setEchoMode(QLineEdit.Password)
        self._pwd.setPlaceholderText("••••••••")
        self._pwd.returnPressed.connect(self._on_login)
        right.addWidget(self._pwd)

        self._error = QLabel("")
        self._error.setWordWrap(True)
        self._error.setStyleSheet(f"color: {theme.RED}; border:none;")
        right.addWidget(self._error)

        self._btn = QPushButton("Accedi")
        self._btn.setFixedHeight(48)
        self._btn.setFont(QFont("Sans", 14, QFont.Bold))
        self._btn.setStyleSheet(
            f"QPushButton{{background:{theme.ACCENT};color:{theme.ON_ACCENT};"
            f"border:none;border-radius:11px}}"
            f"QPushButton:pressed{{background:{theme.ACCENT_D}}}"
            f"QPushButton:disabled{{background:{theme.SURFACE_2};color:{theme.MUTED}}}"
        )
        self._btn.clicked.connect(self._on_login)
        right.addWidget(self._btn)

        cl.addLayout(right, stretch=1)

        card_row = QHBoxLayout()
        card_row.addStretch(); card_row.addWidget(card); card_row.addStretch()
        outer.addLayout(card_row)
        outer.addStretch()

    @staticmethod
    def _field_label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(theme.section_label_qss())
        return lbl

    def _load_profiles(self) -> None:
        profiles = self._pm.list_profiles()
        if not profiles:
            self._error.setText(
                "Nessun profilo trovato.\nUsa tools/create_profile.py per crearne uno."
            )
            self._btn.setEnabled(False)
            return
        for p in profiles:
            # Solo l'alias: il nome reale è cifrato e non è ancora disponibile.
            item = QListWidgetItem(p.alias)
            item.setData(Qt.UserRole, p)
            self._list.addItem(item)
        self._list.setCurrentRow(0)

    def _on_login(self) -> None:
        item = self._list.currentItem()
        if item is None:
            return
        profile: Profile = item.data(Qt.UserRole)
        password = self._pwd.text()
        try:
            enc = EncryptionManager(profile.dir, password)
        except InvalidTag:
            self._error.setText("Password errata")
            self._pwd.clear()
            self._pwd.setFocus()
            return
        except (OSError, ValueError) as exc:
            # salt.bin o .keycheck mancanti/illeggibili: prima era un
            # FileNotFoundError non catturato che chiudeva l'applicazione.
            log.error("Profilo %s non apribile: %s", profile.id, exc)
            self._error.setText("Profilo danneggiato: impossibile aprirlo")
            return
        # Autenticato: ora si può decifrare il nome reale del paziente.
        self._profile = self._pm.unlock(profile, enc)
        self._enc = enc
        self.accept()

    def get_result(self) -> tuple[Profile, EncryptionManager]:
        return self._profile, self._enc
