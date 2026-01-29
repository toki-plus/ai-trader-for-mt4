import os
import pickle
import logging
from datetime import datetime, timedelta
logger = logging.getLogger(__name__)
class DataCacheManager:
    def __init__(self, cache_dir=".cache", expiry_hours=1.0):
        self.cache_dir = cache_dir
        self.expiry_delta = timedelta(hours=expiry_hours)
        if not os.path.exists(cache_dir):
            os.makedirs(cache_dir)
        logger.info("DataCacheManager Initialized. Cache directory: '%s', Expiry: %.1f hours.", cache_dir, expiry_hours)
    def _get_cache_path(self, symbol: str, timeframe_str: str) -> str:
        return os.path.join(self.cache_dir, f"{symbol.upper()}_{timeframe_str}.pkl")
    def save_data(self, symbol: str, timeframe_str: str, data: list):
        if not data:
            return
        cache_path = self._get_cache_path(symbol, timeframe_str)
        existing_data = self.load_data(symbol, timeframe_str, check_expiry=False) or []
        merged_data_dict = {item['time']: item for item in existing_data}
        for item in data:
            merged_data_dict[item['time']] = item
        sorted_data = sorted(merged_data_dict.values(), key=lambda x: x['time'])
        max_cache_size = 1000
        if len(sorted_data) > max_cache_size:
            final_data_to_cache = sorted_data[-max_cache_size:]
        else:
            final_data_to_cache = sorted_data
        payload = {
            "timestamp": datetime.now(),
            "data": final_data_to_cache
        }
        try:
            with open(cache_path, 'wb') as f:
                pickle.dump(payload, f)
            logger.debug("Saved/Updated %d bars for %s_%s to cache.", len(final_data_to_cache), symbol, timeframe_str)
        except Exception as e:
            logger.warning("Cache Save Error for %s_%s: %s", symbol, timeframe_str, e)
    def load_data(self, symbol: str, timeframe_str: str, check_expiry=True) -> list | None:
        cache_path = self._get_cache_path(symbol, timeframe_str)
        try:
            if not os.path.exists(cache_path):
                return None
            with open(cache_path, 'rb') as f:
                payload = pickle.load(f)
            if check_expiry and (datetime.now() - payload["timestamp"] > self.expiry_delta):
                logger.info("Cache for %s_%s has expired. Fetching fresh data.", symbol, timeframe_str)
                os.remove(cache_path)
                return None
            return payload["data"]
        except Exception as e:
            logger.warning("Cache Load Error for %s_%s: %s", symbol, timeframe_str, e)
            if os.path.exists(cache_path):
                try:
                    os.remove(cache_path)
                except OSError as os_err:
                    logger.error("Failed to remove corrupted cache file %s: %s", cache_path, os_err)
            return None
cache_manager = DataCacheManager()