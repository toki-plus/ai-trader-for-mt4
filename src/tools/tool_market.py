import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Union
from ..bridge.mt4_bridge import mt4_bridge
from ..utils.data_cache_manager import cache_manager
logger = logging.getLogger(__name__)
def _get_tf_string(minutes: int) -> str:
    if not isinstance(minutes, int) or minutes <= 0: return ""
    if minutes >= 43200: return f"MN{minutes // 43200}"
    if minutes >= 10080: return f"W{minutes // 10080}"
    if minutes >= 1440: return f"D{minutes // 1440}"
    if minutes >= 60: return f"H{minutes // 60}"
    return f"M{minutes}"
def _tf_string_to_minutes(timeframe_str: str) -> int:
    if not isinstance(timeframe_str, str) or len(timeframe_str) < 2: return 0
    unit = timeframe_str[0].upper()
    try:
        value = int(timeframe_str[1:])
        if unit == 'M': return value
        if unit == 'H': return value * 60
        if unit == 'D': return value * 1440
        if unit == 'W': return value * 10080
        if unit == 'N': return value * 43200
    except (ValueError, TypeError):
        return 0
    return 0
async def get_symbol_info(symbol: str) -> dict:
    logger.debug("get_symbol_info called with: symbol='%s'", symbol)
    try:
        client = mt4_bridge.get_client()
        info = await client.get_symbol_info(symbol)
        logger.debug("Successfully got symbol info for '%s'", symbol)
        return info
    except Exception as e:
        error_message = f"An unexpected system error in get_symbol_info: {e}"
        logger.error(error_message, exc_info=True)
        return {"status": "error", "message": error_message}
async def get_historical_candles(symbol: str, timeframe: Union[int, str], count: int) -> dict:
    if isinstance(timeframe, int):
        timeframe_str = _get_tf_string(timeframe)
    else:
        timeframe_str = timeframe
    if not timeframe_str:
        return {"status": "error", "message": f"Invalid timeframe: {timeframe}"}
    request_count = count + 1
    try:
        client = mt4_bridge.get_client()
        live_data_resp = await client.get_market_data(symbol, timeframe_str, request_count)
        if live_data_resp.get("status") == "success":
            raw_bars = live_data_resp.get("data", [])
            if len(raw_bars) > 1:
                closed_bars_from_live_fetch = raw_bars[:-1]
                cache_manager.save_data(symbol, timeframe_str, closed_bars_from_live_fetch)
            else:
                 logger.debug(f"Not enough live bars for {symbol}_{timeframe_str} to update cache meaningfully.")
        else:
            logger.debug(f"Failed to fetch live data for {symbol}_{timeframe_str}. Reason: {live_data_resp.get('message')}. Relying entirely on potentially stale cache.")
        final_data_from_cache = cache_manager.load_data(symbol, timeframe_str, check_expiry=True) or []
        final_data_to_return = final_data_from_cache[-count:]
        if len(final_data_to_return) < count:
            log_level = logging.WARNING if len(final_data_to_return) < count * 0.9 else logging.INFO
            logger.log(
                log_level,
                f"Data for {symbol}_{timeframe_str} is insufficient. "
                f"Required: {count}, Available: {len(final_data_to_return)}. "
                f"This is common on initial run. Returning what's available."
            )
        return {"status": "success", "data": final_data_to_return}
    except Exception as e:
        logger.error(f"An unexpected error in get_historical_candles for {symbol}_{timeframe_str}: {e}", exc_info=True)
        return {"status": "error", "message": f"System error fetching data: {e}"}
async def get_current_prices(symbols: List[str]) -> Dict[str, Dict]:
    client = mt4_bridge.get_client()
    if not client.is_connected():
        return {s: {"status": "error", "message": "MT4 not connected"} for s in symbols}
    unique_symbols = list(set(symbols))
    await asyncio.sleep(0.1)
    prices = {}
    for symbol in unique_symbols:
        if symbol in client.market_data:
            prices[symbol] = {
                "status": "success",
                "data": client.market_data[symbol]
            }
        else:
            prices[symbol] = {
                "status": "error",
                "message": f"Price data for {symbol} not available in real-time stream."
            }
    return prices
async def get_current_price(symbol: str) -> dict:
    prices = await get_current_prices([symbol])
    return prices.get(symbol, {"status": "error", "message": "Symbol not found in price response."})
async def get_server_time() -> dict:
    client = mt4_bridge.get_client()
    dt = await client.get_server_time()
    if dt:
        return {"status": "success", "data": {"server_time": dt.strftime('%Y.%m.%d %H:%M'), "server_time_utc": dt.isoformat() + "Z"}}
    return {"status": "error", "message": "Could not retrieve server time from MT4."}
async def get_latest_bar_timestamp(symbol: str, timeframe: Union[int, str]) -> dict:
    if isinstance(timeframe, int):
        timeframe_str = _get_tf_string(timeframe)
    else:
        timeframe_str = timeframe
    if not timeframe_str:
        return {"status": "error", "message": f"Invalid timeframe provided: {timeframe}"}
    try:
        client = mt4_bridge.get_client()
        latest_dt = await client.get_latest_bar_timestamp(symbol, timeframe_str)
        if latest_dt:
            return {
                "status": "success",
                "data": {
                    "timestamp_str": latest_dt.strftime('%Y.%m.%d %H:%M'),
                    "timestamp_dt": latest_dt
                }
            }
        else:
            return {
                "status": "error",
                "message": f"Could not retrieve latest bar timestamp for {symbol} on {timeframe_str} from the bridge."
            }
    except Exception as e:
        logger.error(f"An unexpected system error occurred in get_latest_bar_timestamp for {symbol}: {e}", exc_info=True)
        return {"status": "error", "message": f"An unexpected system error occurred: {e}"}
async def is_market_active(symbol: str, timeframe: Union[int, str], inactivity_threshold_minutes: int = 10) -> dict:
    logger.debug(f"is_market_active called for: {symbol} on timeframe {timeframe}")
    try:
        if isinstance(timeframe, int):
            timeframe_minutes = timeframe
        else:
            timeframe_minutes = _tf_string_to_minutes(timeframe)
        if timeframe_minutes <= 0:
            return {"status": "error", "data": {"active": False, "reason": f"Invalid timeframe provided: {timeframe}"}}
        latest_bar_resp = await get_latest_bar_timestamp(symbol, timeframe)
        if latest_bar_resp.get("status") != "success":
            reason = f"Could not retrieve latest bar timestamp: {latest_bar_resp.get('message')}"
            logger.warning(reason)
            return {"status": "success", "data": {"active": False, "reason": reason}}
        last_candle_dt = latest_bar_resp["data"]["timestamp_dt"]
        server_time_resp = await get_server_time()
        if server_time_resp.get('status') != 'success':
            return {"status": "error", "message": f"Could not get server time for activity check: {server_time_resp.get('message')}"}
        try:
            server_dt_str = server_time_resp['data']['server_time']
            server_dt = datetime.strptime(server_dt_str, '%Y.%m.%d %H:%M')
        except (ValueError, TypeError, KeyError) as e:
            error_msg = f"Could not parse server time string '{server_time_resp.get('data', {}).get('server_time')}'. Error: {e}"
            logger.error(error_msg)
            return {"status": "error", "data": {"active": False, "reason": error_msg}}
        time_diff_minutes = (server_dt - last_candle_dt).total_seconds() / 60
        effective_threshold = max(inactivity_threshold_minutes, timeframe_minutes + 1)
        logger.debug(
            f"Activity Check for {symbol}_{_get_tf_string(timeframe_minutes) if timeframe_minutes > 0 else timeframe}: "
            f"Server Time='{server_dt.strftime('%Y-%m-%d %H:%M')}', "
            f"Last Bar Time='{last_candle_dt.strftime('%Y-%m-%d %H:%M')}', "
            f"Difference={time_diff_minutes:.1f} mins, "
            f"Threshold={effective_threshold} mins."
        )
        if time_diff_minutes >= effective_threshold:
            reason = (f"Market seems inactive. Last candle is from {time_diff_minutes:.1f} minutes ago, "
                      f"which exceeds the effective threshold of {effective_threshold} minutes.")
            return {"status": "success", "data": {"active": False, "reason": reason}}
        return {"status": "success", "data": {"active": True, "reason": "Market is active."}}
    except Exception as e:
        logger.error(f"An unexpected system error occurred in is_market_active for {symbol}: {e}", exc_info=True)
        return {"status": "error", "message": f"An unexpected system error occurred: {e}"}