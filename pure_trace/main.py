import sys
import platform

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QMessageBox, QStackedWidget, QVBoxLayout, QWidget,
)
from pure_trace import config, logging_setup
from pure_trace.data_layer import ProfileManager
from pure_trace.ui import theme
from pure_trace.ui.acquisition_screen import AcquisitionScreen
from pure_trace.ui.archive_screen import ArchiveScreen, TabBar
from pure_trace.ui.profile_dialog import ProfileSelectionDialog


def _is_wsl() -> bool:
    """Whether this Qt process is running through the Windows Linux bridge."""
    return "microsoft" in platform.release().lower()


class MainWindow(QMainWindow):
    def __init__(self, profile, enc):
        super().__init__()
        self.setWindowTitle('Pure-Trace')
        # The redesigned acquisition screen is a landscape two-column layout
        # (wide ECG card + a fixed ~232 px command rail), tuned for the 800x480
        # Raspberry Pi 7" display. Keep the height minimum ≤ 480 so the bottom
        # TabBar still fits short touchscreens; the width minimum leaves room for
        # the rail next to a usable plot.
        self.setMinimumSize(560, 360)

        self._acq     = AcquisitionScreen(profile, enc)
        self._archive = ArchiveScreen(profile, enc)

        self._main_stack = QStackedWidget()
        self._main_stack.addWidget(self._acq)      # page 0
        self._main_stack.addWidget(self._archive)  # page 1

        self._tab_bar = TabBar()
        self._tab_bar.tab_changed.connect(self._on_tab_changed)
        self._tab_bar.legal_requested.connect(self._show_legal_notice)
        self._tab_bar.exit_requested.connect(self.close)

        wrapper = QWidget()
        vbox = QVBoxLayout(wrapper)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)
        vbox.addWidget(self._main_stack)
        vbox.addWidget(self._tab_bar)
        self.setCentralWidget(wrapper)

        self._acq.start_monitoring()

    def _on_tab_changed(self, index: int) -> None:
        self._main_stack.setCurrentIndex(index)
        if index == 1:
            self._archive.load()

    def _show_legal_notice(self) -> None:
        """Show the GPLv3 notice required by the interactive application."""
        notice = QMessageBox(self)
        notice.setWindowTitle("Pure-Trace — Informazioni legali")
        notice.setIcon(QMessageBox.Information)
        notice.setText(
            "Pure-Trace\n"
            "Copyright (C) 2026 Pure-Trace contributors\n\n"
            "Questo programma è software libero distribuito ai sensi della "
            "GNU General Public License versione 3. Puoi ridistribuirlo e "
            "modificarlo secondo i termini della licenza."
        )
        notice.setInformativeText(
            "Il programma è fornito SENZA ALCUNA GARANZIA, inclusa qualsiasi "
            "garanzia implicita di commerciabilità o idoneità a uno scopo specifico.\n\n"
            "La licenza completa, le note sulle dipendenze e il codice sorgente "
            "corrispondente sono disponibili all'indirizzo:\n"
            "https://github.com/Michele-Bufis/Pure_trace"
        )
        notice.exec_()

    def keyPressEvent(self, event):
        # ESC quits — handy on a PC/keyboard during development.
        if event.key() == Qt.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        self._acq.shutdown()
        event.accept()


def main():
    # Il file di log vive accanto ai dati, così su Raspberry Pi resta
    # consultabile anche senza console collegata.
    logging_setup.setup(log_dir=config.DATA_DIR)
    log = logging_setup.get_logger(__name__)
    log.info('Avvio Pure-Trace')

    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setStyleSheet(theme.global_stylesheet())

    pm = ProfileManager()
    dialog = ProfileSelectionDialog(pm)
    if dialog.exec_() != ProfileSelectionDialog.Accepted:
        sys.exit(0)

    profile, enc = dialog.get_result()
    window = MainWindow(profile, enc)
    # Debugging uses the physical device's form factor without changing the
    # desktop resolution.
    if config.DEBUG:
        window.setFixedSize(800, 480)
        window.show()
    # Fullscreen is right for the appliance, but WSLg can display a fullscreen
    # Qt window without forwarding pointer input to it.  Use the window manager
    # while developing through WSL.
    elif _is_wsl():
        window.showMaximized()
    else:
        window.showFullScreen()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
