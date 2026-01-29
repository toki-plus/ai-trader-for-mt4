import sys
import json
import logging
import threading
from datetime import datetime
from PyQt5.QtCore import QTimer
class BColors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    MAGENTA = '\033[95m'
class ColorFormatter(logging.Formatter):
    def __init__(self, fmt=None, datefmt=None, style='%', use_colors=True):
        super().__init__(fmt, datefmt, style)
        self.use_colors = use_colors
        if self.use_colors and sys.platform != 'win32':
            self.FORMATS = {
                logging.DEBUG: BColors.OKCYAN + fmt + BColors.ENDC,
                logging.INFO: BColors.OKGREEN + fmt + BColors.ENDC,
                logging.WARNING: BColors.WARNING + fmt + BColors.ENDC,
                logging.ERROR: BColors.FAIL + fmt + BColors.ENDC,
                logging.CRITICAL: BColors.BOLD + BColors.FAIL + fmt + BColors.ENDC,
            }
        else:
            self.FORMATS = {level: fmt for level in [logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR, logging.CRITICAL]}
    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt, self.datefmt)
        return formatter.format(record)
class QSignalHandler(logging.Handler):
    def __init__(self, gui_signal):
        super().__init__()
        self.gui_signal = gui_signal
        self.log_buffer = []
        self.buffer_lock = threading.Lock()
        self.flush_timer = QTimer()
        self.flush_timer.setInterval(200)
        self.flush_timer.timeout.connect(self.flush_buffer)
        self.flush_timer.start()
        self._ignored_patterns = [
            "[EA INFO] Successfully subscribed to:",
            "Initializing MT4 Bridge",
            "Agent Config:",
            "Registering tools...",
            "Agent mt4_gui_agent",
            "First cycle detected.",
            "Performing initial data synchronization...",
            "Initial data synchronization complete.",
            "MATCH: Found",
            "Starting trading session:",
        ]
    def emit(self, record):
        msg = record.getMessage()
        if record.levelno == logging.INFO:
            for pattern in self._ignored_patterns:
                if pattern in msg:
                    return
        log_payload = {
            'timestamp': datetime.fromtimestamp(record.created).strftime('%Y-%m-%d %H:%M:%S'),
            'level': record.levelname,
            'message': self.format(record),
            'name': record.name,
        }
        if hasattr(record, 'type'):
            log_payload['type'] = record.type
        if hasattr(record, 'content'):
            log_payload['content'] = record.content
        with self.buffer_lock:
            self.log_buffer.append(log_payload)
    def flush_buffer(self):
        if self.log_buffer:
            with self.buffer_lock:
                logs_to_emit = self.log_buffer
                self.log_buffer = []
            if logs_to_emit:
                self.gui_signal.emit(logs_to_emit)
class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_object = {
            'log_timestamp_utc': datetime.utcfromtimestamp(record.created).isoformat(),
            'level': record.levelname,
            'message': record.getMessage(),
            'logger_name': record.name,
        }
        if hasattr(record, 'type'):
            log_object['type'] = record.type
        if hasattr(record, 'content'):
            log_object['content'] = record.content
        return json.dumps(log_object, ensure_ascii=False)
def setup_logging(gui_signal, level=logging.INFO):
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    third_party_loggers = ["openai", "httpcore", "httpx"]
    for logger_name in third_party_loggers:
        logging.getLogger(logger_name).setLevel(logging.WARNING)
    terminal_handler = logging.StreamHandler(sys.stdout)
    terminal_formatter = ColorFormatter(
        '%(asctime)s - %(name)s - %(levelname)-8s - %(message)s',
        '%H:%M:%S'
    )
    terminal_handler.setFormatter(terminal_formatter)
    root_logger.addHandler(terminal_handler)
    gui_handler = QSignalHandler(gui_signal)
    gui_handler.setLevel(level)
    gui_formatter = logging.Formatter('%(message)s')
    gui_handler.setFormatter(gui_formatter)
    root_logger.addHandler(gui_handler)