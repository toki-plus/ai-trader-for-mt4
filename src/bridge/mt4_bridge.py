import os
import logging
from typing import List
from .ai_client import AI_Client
from ..services.order_db_manager import order_db_manager
logger = logging.getLogger(__name__)
class MT4Bridge:
    _instance = None
    _initialized = False
    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super().__new__(cls)
        return cls._instance
    async def initialize(self, mt4_data_path: str, symbol_overrides: dict = None, initial_subscribe_symbols: List[str] = None):
        if hasattr(self, 'client') and self.client and self.client.active:
            logger.info("MT4 Bridge already active, shutting down previous instance first.")
            await self.shutdown()
        order_db_manager.reinitialize()
        if not mt4_data_path or not os.path.isdir(mt4_data_path):
            raise ValueError(f"MT4_DATA_PATH invalid: '{mt4_data_path}'.")
        logger.info("Initializing MT4 Bridge (AI)...")
        try:
            self.client = AI_Client(
                metatrader_dir_path=mt4_data_path,
                order_db_manager_instance=order_db_manager,
                symbol_overrides=symbol_overrides or {},
                initial_subscribe_symbols=initial_subscribe_symbols,
            )
            self.client.start()
            self._initialized = True
            logger.debug("MT4 Bridge initialized and started.")
        except Exception as e:
            self._initialized = False
            logger.critical("Failed to initialize AI_Client: %s", e, exc_info=True)
            raise
    async def shutdown(self):
        logger.info("Shutting down MT4 Bridge...")
        if hasattr(self, 'client') and self.client and self.client.active:
            await self.client.stop()
            logger.info("AI_Client stopped.")
        self._initialized = False
        logger.info("MT4 Bridge shut down.")
    def get_client(self):
        if not self._initialized or not hasattr(self, 'client') or not self.client:
            raise RuntimeError("MT4 Bridge not initialized or client missing.")
        return self.client
    async def force_sync(self):
        """Forces an immediate, one-time synchronization of order data."""
        if not self._initialized or not hasattr(self, 'client') or not self.client:
            logger.warning("Cannot force sync, MT4 Bridge is not initialized.")
            return
        await self.client.force_sync()
mt4_bridge = MT4Bridge()