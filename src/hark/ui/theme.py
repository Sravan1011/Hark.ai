"""Colors and the application stylesheet (dark theme)."""

BG = "#0f1115"
SIDEBAR = "#14161b"
CARD = "#1a1d23"
CARD_HOVER = "#20242b"
BORDER = "#262a32"
TEXT = "#e8eaed"
MUTED = "#9aa0a8"
FAINT = "#6b7079"
ACCENT = "#8b6cff"
ACCENT_HOVER = "#9d82ff"
ACCENT_SOFT = "#2a2346"
SUCCESS = "#3ecf8e"
WARNING = "#f5a524"
DANGER = "#ff5d6c"
RECORDING = "#ff4d6d"

STYLESHEET = f"""
* {{ font-size: 10.5pt; color: {TEXT}; }}
QMainWindow, QWidget#Page, QStackedWidget, QScrollArea, QScrollArea > QWidget > QWidget {{
    background: {BG};
}}
QWidget#Sidebar {{ background: {SIDEBAR}; border-right: 1px solid {BORDER}; }}
QLabel {{ background: transparent; }}
QLabel#Brand {{ font-size: 15pt; font-weight: 700; }}
QLabel#PageTitle {{ font-size: 19pt; font-weight: 700; }}
QLabel#PageSubtitle, QLabel#Muted {{ color: {MUTED}; }}
QLabel#Faint {{ color: {FAINT}; font-size: 9.5pt; }}
QLabel#SectionTitle {{ font-size: 12pt; font-weight: 600; }}
QLabel#StatValue {{ font-size: 21pt; font-weight: 700; }}
QLabel#StatLabel {{ color: {MUTED}; font-size: 9.5pt; }}

QFrame#Card {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 14px; }}
QFrame#Row {{ background: transparent; border: none; border-bottom: 1px solid {BORDER}; }}
QFrame#Row:hover {{ background: {CARD_HOVER}; }}

QPushButton#NavButton {{
    text-align: left; padding: 9px 14px; border: none; border-radius: 9px;
    color: {MUTED}; background: transparent; font-weight: 500;
}}
QPushButton#NavButton:hover {{ background: {CARD}; color: {TEXT}; }}
QPushButton#NavButton:checked {{ background: {ACCENT_SOFT}; color: {TEXT}; }}

QPushButton {{
    background: {CARD_HOVER}; border: 1px solid {BORDER}; border-radius: 9px;
    padding: 7px 14px; font-weight: 500;
}}
QPushButton:hover {{ border-color: {FAINT}; }}
QPushButton:disabled {{ color: {FAINT}; }}
QPushButton#Primary {{ background: {ACCENT}; border: none; color: white; }}
QPushButton#Primary:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#Primary:disabled {{ background: {ACCENT_SOFT}; color: {MUTED}; }}
QPushButton#Danger {{ color: {DANGER}; }}
QPushButton#Icon {{ background: transparent; border: none; padding: 4px; border-radius: 7px; }}
QPushButton#Icon:hover {{ background: {CARD_HOVER}; }}
QPushButton#Segment {{ border-radius: 8px; padding: 6px 14px; background: transparent; }}
QPushButton#Segment:checked {{ background: {ACCENT}; border-color: {ACCENT}; color: white; }}

QLineEdit, QPlainTextEdit, QTextEdit, QComboBox {{
    background: {BG}; border: 1px solid {BORDER}; border-radius: 9px; padding: 7px 10px;
    selection-background-color: {ACCENT};
}}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QPlainTextEdit#NoteBody {{ background: transparent; border: none; font-size: 11.5pt; padding: 0; }}
QLineEdit#NoteTitle {{ background: transparent; border: none; font-size: 17pt; font-weight: 700;
    padding: 0; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {CARD}; border: 1px solid {BORDER};
    selection-background-color: {ACCENT_SOFT}; }}

QListWidget {{ background: transparent; border: none; outline: none; }}
QListWidget::item {{ padding: 9px 10px; border-radius: 9px; margin: 1px 0; }}
QListWidget::item:hover {{ background: {CARD}; }}
QListWidget::item:selected {{ background: {ACCENT_SOFT}; color: {TEXT}; }}

QProgressBar {{ background: {BG}; border: 1px solid {BORDER}; border-radius: 5px; height: 8px;
    text-align: center; font-size: 8pt; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {FAINT}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 5px;
    border: 1px solid {FAINT}; background: {BG}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {BORDER}; border-radius: 4px; min-width: 30px; }}

QToolTip {{ background: {CARD}; color: {TEXT}; border: 1px solid {BORDER}; padding: 5px; }}
QMenu {{ background: {CARD}; border: 1px solid {BORDER}; padding: 5px; border-radius: 9px; }}
QMenu::item {{ padding: 6px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background: {ACCENT_SOFT}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 6px; }}
QMessageBox {{ background: {CARD}; }}
"""
