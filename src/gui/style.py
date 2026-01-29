STYLESHEET = """
QWidget { background-color: #1A1D2A; color: #D0D0D0; font-family: "Segoe UI", "Microsoft YaHei", "PingFang SC", sans-serif; font-size: 10pt; }
QMainWindow { background-color: #1A1D2A; }
QGroupBox { background-color: #24283B; border: 1px solid #25F4EE; border-radius: 8px; margin-top: 1.2em; padding: 10px; }
QGroupBox::title { color: #25F4EE; font-weight: bold; font-size: 11pt; subcontrol-origin: margin; subcontrol-position: top center; padding: 4px 12px; background-color: #1A1D2A; border-radius: 6px; border: 1px solid #25F4EE; }
QPushButton { background-color: #3B3F51; color: #FFFFFF; border: 1px solid #25F4EE; padding: 6px 15px; font-weight: bold; border-radius: 6px; }
QPushButton:hover { background-color: #4A4E60; border-color: #97FEFA; }
QPushButton:pressed { background-color: #25F4EE; color: #1A1D2A; }
QPushButton:disabled { background-color: #4A4E60; color: #888888; border-color: #555555; }
QPushButton#PrimaryButton { background-color: #FE2C55; border-color: #FE2C55; color: #ffffff; }
QPushButton#PrimaryButton:hover { background-color: #FF4D71; border-color: #FF4D71; }
QPushButton#PrimaryButton:pressed { background-color: #D92349; }
QPlainTextEdit, QLineEdit { background-color: #1A1D2A; color: #FFFFFF; border: 1px solid #4A4E60; padding: 6px; border-radius: 6px; selection-background-color: #25F4EE; selection-color: #1A1D2A; }
QPlainTextEdit:focus, QLineEdit:focus { border-color: #25F4EE; }
QTextBrowser { background-color: #1A1D2A; color: #FFFFFF; border: 1px solid #25F4EE; padding: 6px; border-radius: 6px; }
QLabel { color: #E0E0E0; background-color: transparent; }
QLabel#status_label_ok { color: #25F4EE; font-weight: bold; }
QLabel#status_label_error { color: #FE2C55; font-weight: bold; }
QLabel#status_label_pending { color: #F8D800; font-weight: bold; }
QLabel#status_label_stopped { color: #888888; font-weight: bold; }
QComboBox { background-color: #3B3F51; border: 1px solid #25F4EE; border-radius: 5px; padding: 5px; min-width: 6em; }
QComboBox:on { border-bottom-left-radius: 0; border-bottom-right-radius: 0; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: top right; width: 20px; border-left-width: 1px; border-left-color: #25F4EE; border-left-style: solid; border-top-right-radius: 3px; border-bottom-right-radius: 3px; }
QComboBox::down-arrow { image: url(:/icons/down_arrow.png); }
QComboBox QAbstractItemView { background-color: #1A1D2A; border: 1px solid #25F4EE; color: #D0D0D0; selection-background-color: #FE2C55; }
QSpinBox, QDoubleSpinBox { background-color: #3B3F51; border: 1px solid #25F4EE; border-radius: 5px; padding: 5px; color: #FFFFFF; min-width: 6em; }
QSpinBox:disabled, QDoubleSpinBox:disabled { background-color: #4A4E60; color: #888888; border-color: #555555; }
QCheckBox::indicator:checked { background-color: #FE2C55; border: 2px solid #FE2C55; }
QStatusBar { background-color: #1A1D2A; border-top: 1px solid #25F4EE; color: #25F4EE; font-weight: bold; }
QStatusBar::item { border: none; }
QProgressBar { border: 1px solid #4A4E60; border-radius: 5px; text-align: center; color: #FFFFFF; background-color: #3B3F51; }
QProgressBar::chunk { background-color: #25F4EE; border-radius: 5px; }
QSlider::groove:horizontal { border: 1px solid #3B3F51; height: 4px; background: #3B3F51; margin: 2px 0; border-radius: 2px; }
QSlider::handle:horizontal { background: #25F4EE; border: 1px solid #25F4EE; width: 16px; height: 16px; margin: -8px 0; border-radius: 8px; }
QSlider::handle:horizontal:hover { background: #97FEFA; border: 1px solid #97FEFA; }
QScrollBar:vertical, QScrollBar:horizontal { border: none; background-color: #24283B; width: 10px; margin: 0px; }
QScrollBar::handle:vertical, QScrollBar::handle:horizontal { background-color: #4A4E60; border-radius: 5px; min-height: 20px; min-width: 20px; }
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover { background-color: #25F4EE; }
QScrollBar::add-line, QScrollBar::sub-line { border: none; background: none; height: 0; width: 0; }
QScrollBar::up-arrow:vertical, QScrollBar::down-arrow:vertical, QScrollBar::left-arrow:horizontal, QScrollBar::right-arrow:horizontal { background: none; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical, QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: none; }
QMenuBar { background-color: #1A1D2A; border-bottom: 1px solid #25F4EE; spacing: 10px; }
QMenuBar::item { background-color: transparent; color: #D0D0D0; padding: 6px 12px; border-radius: 5px; }
QMenuBar::item:selected, QMenuBar::item:hover { background-color: #3B3F51; color: #FFFFFF; }
QMenu { background-color: #24283B; border: 1px solid #4A4E60; border-radius: 5px; padding: 5px; }
QMenu::item { color: #D0D0D0; padding: 8px 25px; margin: 2px 0; border-radius: 4px; border: 1px solid transparent; }
QMenu::item:selected { background-color: #FE2C55; color: #FFFFFF; }
QMenu::item:disabled { color: #707070; background-color: transparent; }
QMenu::separator { height: 1px; background-color: #4A4E60; margin: 5px 0px; }
QMessageBox { background-color: #24283B; }
QMessageBox QLabel { color: #FFFFFF; background-color: transparent; }
QTableWidget { background-color: #1A1D2A; border: 1px solid #25F4EE; border-radius: 6px; gridline-color: #3B3F51; }
QHeaderView::section { background-color: #3B3F51; color: #25F4EE; padding: 5px; border: 1px solid #1A1D2A; font-weight: bold; }
QTableCornerButton::section { background-color: #3B3F51; border: 1px solid #1A1D2A; }
QTableWidget::item { padding: 5px; border-bottom: 1px solid #3B3F51; }
QTableWidget::item:alternate { background-color: #24283B; }
QTableWidget::item:selected { background-color: #FE2C55; color: #FFFFFF; }
"""