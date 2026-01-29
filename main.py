import sys
import qasync
import logging
import asyncio
import multiprocessing
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QObject, pyqtSignal
sys.path.insert(0, './')
from src.utils.constants import APP_VERSION
from src.gui.style import STYLESHEET
from src.gui.main_window import MainWindow
from src.app.trading_engine import TradingEngine
from src.services.config_manager import ConfigManager
from src.services.logger_config import setup_logging
class LogEmitter(QObject):
    log_signal = pyqtSignal(list)
def main():
    multiprocessing.freeze_support()
    app = QApplication(sys.argv)
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)
    log_emitter = LogEmitter()
    setup_logging(gui_signal=log_emitter.log_signal)
    logger = logging.getLogger(__name__)
    logger.info("License verification successful. Application starting...")
    logger.info("Logging system initialized and connected to GUI signal.")
    try:
        config_manager = ConfigManager('config/mt4_config.json', 'config/strategy_profiles.json')
        trading_engine = TradingEngine(config_manager)
        window = MainWindow(trading_engine, config_manager, loop)
        log_emitter.log_signal.connect(window.append_log_message)
        window.show()
        logger.info("Main window displayed.")
        with loop:
            sys.exit(loop.run_forever())
    except Exception as e:
        logging.getLogger(__name__).critical(f"A critical error occurred during application startup: {e}", exc_info=True)
        sys.exit(1)
if __name__ == "__main__":
    main()