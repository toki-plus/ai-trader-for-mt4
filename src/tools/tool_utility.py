import re
import math
import json
import logging
import hashlib
import asyncio
from typing import Union
from . import tool_market
from .tool_portfolio import get_order_details
logger = logging.getLogger(__name__)
async def calculate_atr(symbol: str, timeframe: int, period: int = 14, count: int = 100) -> dict:
    data_response = await tool_market.get_historical_candles(symbol, timeframe, count)
    if data_response.get("status") != "success": return data_response
    candles = data_response.get("data", [])
    if not isinstance(candles, list) or len(candles) < period + 1:
        return {"status": "error", "message": f"Insufficient data for ATR calculation. Need at least {period + 1} candles, got {len(candles)}."}
    true_ranges = []
    try:
        for i in range(1, len(candles)):
            high, low, prev_close = candles[i].get('high'), candles[i].get('low'), candles[i-1].get('close')
            if high is None or low is None or prev_close is None: return {"status": "error", "message": f"Candle data is incomplete."}
            true_ranges.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
        if len(true_ranges) < period: return {"status": "error", "message": f"Not enough True Range values to calculate ATR."}
        atr = sum(true_ranges[:period]) / period
        for i in range(period, len(true_ranges)): atr = ((atr * (period - 1)) + true_ranges[i]) / period
        return {"status": "success", "data": {"atr": atr}}
    except Exception as e:
        logger.error("An unexpected error during ATR calculation: %s", e, exc_info=True)
        return {"status": "error", "message": f"An unexpected error during ATR calculation: {e}"}
async def calculate_ema(candles: list, period: int, price_type: str = "close") -> dict:
    if price_type not in ['open', 'high', 'low', 'close']: return {"status": "error", "message": "Invalid price_type."}
    if not isinstance(candles, list) or len(candles) < period: return {"status": "error", "message": f"Insufficient data for EMA calculation."}
    prices = [c.get(price_type) for c in candles if c.get(price_type) is not None]
    if len(prices) < period: return {"status": "error", "message": "Not enough valid price points."}
    ema_values = []
    sma = sum(prices[:period]) / period
    ema_values.append(sma)
    k = 2 / (period + 1)
    for i in range(period, len(prices)):
        ema = (prices[i] * k) + (ema_values[-1] * (1 - k))
        ema_values.append(ema)
    return {"status": "success", "data": {"ema_values": ema_values}}
async def calculate_lot_size(risk_amount_usd: float, entry_price: float, sl_price: float, contract_size: float, lot_step: float, min_lot: float, max_lot: float) -> dict:
    try:
        risk_amount_usd = float(risk_amount_usd)
        entry_price = float(entry_price)
        sl_price = float(sl_price)
        contract_size = float(contract_size)
        lot_step = float(lot_step)
        min_lot = float(min_lot)
        max_lot = float(max_lot)
        if risk_amount_usd <= 0:
            return {"status": "error", "message": "Risk amount (risk_amount_usd) must be a positive value."}
        if contract_size <= 0 or lot_step <= 0:
            return {"status": "error", "message": "Contract size and lot step must be positive."}
        risk_per_unit = abs(entry_price - sl_price)
        if risk_per_unit <= 1e-9:
            return {"status": "error", "message": "Entry price and SL price are too close to calculate a meaningful lot size."}
        ideal_lots = risk_amount_usd / (risk_per_unit * contract_size)
        if ideal_lots < min_lot:
            return {
                "status": "warning",
                "message": f"Calculated lots ({ideal_lots:.4f}) is below the minimum required lot size ({min_lot}). Cannot open trade.",
                "data": {"calculated_lots": ideal_lots, "adjusted_lots": 0.0}
            }
        num_steps = math.floor(ideal_lots / lot_step)
        adjusted_lots = min(num_steps * lot_step, max_lot)
        if adjusted_lots < min_lot:
            return {
                "status": "warning",
                "message": f"Final adjusted lots ({adjusted_lots:.4f}) is below the minimum required lot size ({min_lot}). No trade possible.",
                "data": {"calculated_lots": ideal_lots, "adjusted_lots": 0.0}
            }
        return {
            "status": "success",
            "data": {
                "calculated_lots": ideal_lots,
                "adjusted_lots": round(adjusted_lots, 5)
            }
        }
    except Exception as e:
        logger.error("Error in lot size calculation: %s", e, exc_info=True)
        return {"status": "error", "message": f"Error in lot size calculation: {e}"}
async def analyze_trend_with_ema(symbol: str, timeframe: int, period: int = 89, candles_to_fetch: int = 150) -> dict:
    market_data_result = await tool_market.get_historical_candles(symbol, timeframe, candles_to_fetch)
    if market_data_result.get("status") != "success": return {"status": "error", "message": f"Failed to fetch market data: {market_data_result.get('message')}"}
    candles = market_data_result.get("data")
    if not candles or len(candles) < period: return {"status": "error", "message": f"Not enough candle data ({len(candles)}) for EMA({period})."}
    ema_result = await calculate_ema(candles, period, "close")
    if ema_result.get("status") != "success": return ema_result
    ema_values = ema_result["data"]["ema_values"]
    try:
        current_price = candles[-1]['close']
        latest_ema, previous_ema = ema_values[-1], ema_values[-2]
        trend = "RANGING"
        analysis = f"Price ({current_price}) is {'above' if current_price > latest_ema else 'below'} EMA({period}) ({latest_ema:.4f}). "
        if current_price > latest_ema and latest_ema > previous_ema:
            trend = "UPTREND"
            analysis += f"EMA is rising. Conclusion: UPTREND."
        elif current_price < latest_ema and latest_ema < previous_ema:
            trend = "DOWNTREND"
            analysis += f"EMA is falling. Conclusion: DOWNTREND."
        else:
            analysis += f"EMA is not in a clear trend. Conclusion: RANGING."
        return {"status": "success", "data": {"trend": trend, "analysis": analysis}}
    except IndexError:
        return {"status": "error", "message": "Not enough EMA values for trend analysis."}
async def analyze_location_and_structure(symbol: str, timeframe: int, candles_to_fetch: int = 250) -> dict:
    market_data_result = await tool_market.get_historical_candles(symbol, timeframe, candles_to_fetch)
    if market_data_result.get("status") != "success": return {"status": "error", "message": f"Failed to fetch market data: {market_data_result.get('message')}"}
    candles = market_data_result.get("data")
    if not candles or len(candles) < 20: return {"status": "error", "message": "Not enough candle data for analysis."}
    prices = [c.get("close") for c in candles[-20:]]
    middle_band = sum(prices) / 20
    variance = sum([(p - middle_band) ** 2 for p in prices]) / 20
    std_dev = math.sqrt(variance)
    upper_band, lower_band = middle_band + (2 * std_dev), middle_band - (2 * std_dev)
    current_price = candles[-1]['close']
    location_bias = "NEUTRAL"
    if current_price >= upper_band: location_bias = "EXTREME_HIGH (SHORT bias)"
    elif current_price <= lower_band: location_bias = "EXTREME_LOW (LONG bias)"
    if len(candles) < 15:
        rsi_condition, rsi = "NOT_CALCULATED (not enough data)", -1
    else:
        all_prices = [c.get("close") for c in candles]
        deltas = [all_prices[i] - all_prices[i-1] for i in range(1, len(all_prices))]
        gains, losses = [d if d > 0 else 0 for d in deltas], [-d if d < 0 else 0 for d in deltas]
        avg_gain, avg_loss = sum(gains[:14]) / 14, sum(losses[:14]) / 14
        for i in range(14, len(gains)):
            avg_gain = (avg_gain * 13 + gains[i]) / 14
            avg_loss = (avg_loss * 13 + losses[i]) / 14
        rs = avg_gain / avg_loss if avg_loss != 0 else float('inf')
        rsi = 100 - (100 / (1 + rs))
        rsi_condition = "NEUTRAL"
        if rsi >= 70: rsi_condition = "OVERBOUGHT (SHORT signal confirmation)"
        elif rsi <= 30: rsi_condition = "OVERSOLD (LONG signal confirmation)"
    return {"status": "success", "data": {"location_bias_from_bbands": location_bias, "rsi_condition": rsi_condition, "summary": f"Location on {timeframe}min: Price is {current_price:.4f}. BBands [{lower_band:.4f}, {upper_band:.4f}], suggests {location_bias}. RSI(14) is {rsi:.2f}, indicating {rsi_condition}."}}
async def generate_trade_id(symbol: str, timeframe: int, signal_type: str, signal_time: str) -> dict:
    try:
        id_string = f"{symbol}-{timeframe}-{signal_type}-{signal_time}"
        hashed = hashlib.sha256(id_string.encode('utf-8')).hexdigest()
        return {"status": "success", "data": {"trade_id": hashed[:8]}}
    except Exception as e:
        error_message = f"An unexpected error occurred in generate_trade_id: {e}"
        logger.error(error_message, exc_info=True)
        return {"status": "error", "message": error_message}
def _get_signal_code_from_comment(comment: str) -> str | None:
    if not comment: return None
    match = re.search(r'S=([A-Z]{3})', comment)
    return match.group(1) if match else None
async def _calculate_ladder_prices_logic(open_price: float, sl_price: float, trade_type: str, symbol: str, initial_rr_ratio: float, ladder_steps: int = 8) -> dict:
    try:
        info_resp = await tool_market.get_symbol_info(symbol)
        if info_resp.get("status") != "success":
            return {"status": "error", "message": f"Could not get symbol info for {symbol}: {info_resp.get('message')}"}
        digits = info_resp.get("data", {}).get("digits", 5)
        risk_distance_in_price = abs(open_price - sl_price)
        if risk_distance_in_price <= 1e-9:
             return {"status": "error", "message": "Risk distance is zero, cannot calculate ladder."}
        ladder = {}
        for n in range(1, ladder_steps + 1):
            rr_multiple = initial_rr_ratio + (n - 1)
            profit_distance = risk_distance_in_price * rr_multiple
            tp_price = round(open_price + profit_distance if 'buy' in trade_type.lower() else open_price - profit_distance, digits)
            ladder[f"tp{n}"] = {"price": tp_price}
        return {"status": "success", "data": {"ladder": ladder}}
    except Exception as e:
        logger.error(f"Error in ladder price logic: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}
async def calculate_ladder_prices_pre_trade(open_price: float, sl_price: float, trade_type: str, symbol: str, comment: str, initial_rr_ratio: float, ladder_steps: int = 8) -> dict:
    return await _calculate_ladder_prices_logic(open_price, sl_price, trade_type, symbol, initial_rr_ratio, ladder_steps)
async def calculate_profit_ladder_levels(ticket: int, initial_rr_ratio: float, ladder_steps: int = 8) -> dict:
    try:
        order_details_resp = await get_order_details(ticket)
        if order_details_resp.get("status") != "success": return order_details_resp
        order_data = order_details_resp["data"]
        order_data = {k.lower(): v for k,v in order_data.items()}
        open_price, sl_price, trade_type, symbol, comment = order_data.get("open_price"), order_data.get("sl"), order_data.get("type"), order_data.get("symbol"), order_data.get("comment")
        if not all([open_price, sl_price, trade_type, symbol, comment]):
            return {"status": "error", "message": "Order details are incomplete for ladder calculation."}
        if sl_price == 0.0:
            return {"status": "error", "message": "Cannot calculate profit ladder for an order with no Stop Loss."}
        ladder = {}
        db_has_prices = True
        for i in range(1, ladder_steps + 1):
            tp_price = order_data.get(f'tp{i}_price')
            if tp_price is not None:
                ladder[f'tp{i}'] = {"price": tp_price}
            else:
                db_has_prices = False
                break
        if not db_has_prices:
            logger.debug(f"TP prices for ticket {ticket} not found in DB. Falling back to recalculation.")
            prices_resp = await _calculate_ladder_prices_logic(open_price, sl_price, trade_type, symbol, initial_rr_ratio, ladder_steps)
            if prices_resp.get('status') != 'success':
                return prices_resp
            ladder = prices_resp['data']['ladder']
        signal_code = _get_signal_code_from_comment(comment)
        if signal_code == 'INS':
            for n in range(1, ladder_steps + 1):
                action, m_code = "", ""
                if n == 1:
                    action = "Close 50% of initial lots. Do NOT move Stop Loss."
                    m_code = "P1"
                elif n == 2:
                    action = "Move Stop Loss to TP1 price."
                    m_code = "S1"
                else:
                    action = f"Move Stop Loss to TP{n-1} price."
                    m_code = f"S{n-1}"
                ladder[f"tp{n}"]["action"] = action
                ladder[f"tp{n}"]["management_code"] = m_code
        else:
            for n in range(1, ladder_steps + 1):
                action, m_code = "", ""
                if n == 1:
                    action = "NO_ACTION. This is the reference price for the Stop Loss after TP2 is hit."
                    m_code = ""
                elif n == 2:
                    action = "Close 50% of initial lots AND immediately move Stop Loss to the price of TP1."
                    m_code = "P2"
                else:
                    action = f"Move Stop Loss to TP{n-1} price."
                    m_code = f"S{n-1}"
                ladder[f"tp{n}"]["action"] = action
                ladder[f"tp{n}"]["management_code"] = m_code
        return {"status": "success", "data": {"ladder": ladder}}
    except Exception as e:
        error_message = f"An unexpected system error occurred in calculate_profit_ladder_levels: {e}"
        logger.error(error_message, exc_info=True)
        return {"status": "error", "message": error_message}
async def calculate_stop_loss_from_pattern(
    symbol: str,
    timeframe: int,
    pattern_type: str,
    pattern_candles: Union[dict, str],
    trade_type: str,
    symbol_info: Union[dict, str],
    current_price: Union[dict, str],
    atr_multiple: float = 0.2,
    min_stop_atr_multiple: float = 0.5
) -> dict:
    logger.debug(f"Calculating SL for {pattern_type} on {symbol} using provided market data.")
    if isinstance(pattern_candles, str):
        try:
            pattern_candles = json.loads(pattern_candles)
        except json.JSONDecodeError:
            return {"status": "error", "message": "pattern_candles parameter provided as invalid JSON string."}
    if isinstance(symbol_info, str):
        try:
            symbol_info = json.loads(symbol_info)
        except json.JSONDecodeError:
            return {"status": "error", "message": "symbol_info parameter provided as invalid JSON string."}
    if isinstance(current_price, str):
        try:
            current_price = json.loads(current_price)
        except json.JSONDecodeError:
            return {"status": "error", "message": "current_price parameter provided as invalid JSON string."}
    try:
        if not symbol_info:
            return {"status": "error", "message": "Missing required 'symbol_info' object for SL calculation."}
        if not current_price:
            return {"status": "error", "message": "Missing required 'current_price' object for SL calculation."}
        stops_level_points = symbol_info.get("stops_level_points", 0)
        point_size = symbol_info.get("point_size")
        digits = symbol_info.get("digits", 5)
        current_bid = current_price.get("bid")
        current_ask = current_price.get("ask")
        if point_size is None or current_bid is None or current_ask is None:
             return {"status": "error", "message": "Incomplete data in symbol_info or current_price objects."}
        min_broker_stop_distance_price = stops_level_points * point_size
        atr_resp = await calculate_atr(symbol, timeframe)
        if atr_resp.get("status") != "success":
            return {"status": "error", "message": f"Could not calculate ATR: {atr_resp.get('message')}"}
        atr_value = atr_resp.get("data", {}).get("atr", 0.0)
        if atr_value <= 0: return {"status": "error", "message": "Calculated ATR is zero or negative."}
        atr_buffer = atr_value * atr_multiple
        min_safe_stop_distance_from_atr = atr_value * min_stop_atr_multiple
        logical_sl_price = 0.0
        pt_lower = pattern_type.lower()
        trade_type_lower = trade_type.lower()
        is_buy = 'buy' in trade_type_lower
        entry_price_ref = current_ask if is_buy else current_bid
        if pt_lower == 'pin':
            candle = pattern_candles.get('candle')
            if not candle: return {"status": "error", "message": "Missing 'candle' data for Pin Bar (PIN)."}
            logical_sl_price = candle['low'] if is_buy else candle['high']
        elif pt_lower == 'eng':
            candle = pattern_candles.get('engulfing_candle')
            if not candle: return {"status": "error", "message": "Missing 'engulfing_candle' data for Engulfing pattern (ENG)."}
            logical_sl_price = candle['low'] if is_buy else candle['high']
        elif pt_lower == 'ins':
            candle = pattern_candles.get('mother_candle')
            if not candle: return {"status": "error", "message": "Missing 'mother_candle' data for Inside Bar (INS)."}
            logical_sl_price = candle['low'] if is_buy else candle['high']
            atr_buffer = 0.0
        elif pt_lower == 'har':
            points = pattern_candles.get('points')
            if not points or 'X' not in points: return {"status": "error", "message": "Missing 'points' or 'X' point data for Harmonic pattern (HAR)."}
            logical_sl_price = points['X']['price']
        elif pt_lower == 'zon':
            top, bottom = pattern_candles.get('top'), pattern_candles.get('bottom')
            if top is None or bottom is None: return {"status": "error", "message": "Missing 'top' or 'bottom' data for Zone pattern (ZON)."}
            logical_sl_price = bottom if is_buy else top
        else:
            return {"status": "error", "message": f"Unknown pattern_type: '{pattern_type}'. Valid types are 'PIN', 'ENG', 'INS', 'HAR', 'ZON'."}
        if logical_sl_price == 0.0: return {"status": "error", "message": "Failed to determine logical stop loss price from provided data."}
        pattern_stop_distance = abs(entry_price_ref - logical_sl_price)
        adjustment_info = ""
        if pattern_stop_distance < min_safe_stop_distance_from_atr:
            adjustment_info = f"Pattern SL is too tight ({pattern_stop_distance:.{digits}f}). Widening SL to ATR-based minimum distance ({min_safe_stop_distance_from_atr:.{digits}f})."
            logger.warning(f"[SL SAFETY] {adjustment_info} for {symbol}")
            logical_sl_price = entry_price_ref - min_safe_stop_distance_from_atr if is_buy else entry_price_ref + min_safe_stop_distance_from_atr
        final_sl_price = logical_sl_price - atr_buffer if is_buy else logical_sl_price + atr_buffer
        adjusted_sl = final_sl_price
        broker_adjustment_reason = ""
        if is_buy:
            max_allowed_sl = current_bid - min_broker_stop_distance_price
            if final_sl_price > max_allowed_sl:
                adjusted_sl = max_allowed_sl
                broker_adjustment_reason = f"Adjusted SL from {final_sl_price:.{digits}f} to {adjusted_sl:.{digits}f} to meet broker's minimum stop distance from current bid {current_bid}."
        else:
            min_allowed_sl = current_ask + min_broker_stop_distance_price
            if final_sl_price < min_allowed_sl:
                adjusted_sl = min_allowed_sl
                broker_adjustment_reason = f"Adjusted SL from {final_sl_price:.{digits}f} to {adjusted_sl:.{digits}f} to meet broker's minimum stop distance from current ask {current_ask}."
        if broker_adjustment_reason:
            logger.warning(broker_adjustment_reason)
            adjustment_info += " " + broker_adjustment_reason
        final_sl_price = adjusted_sl
        return {
            "status": "success",
            "data": {
                "sl_price": round(final_sl_price, digits),
                "logical_sl_price": logical_sl_price,
                "atr_buffer_used": atr_buffer,
                "adjustment_info": adjustment_info.strip()
            }
        }
    except Exception as e:
        error_message = f"An unexpected system error occurred in calculate_stop_loss_from_pattern: {e}"
        logger.error(error_message, exc_info=True)
        return {"status": "error", "message": error_message}
async def calculate_spread_analysis(symbol_info: Union[dict, str], current_price: Union[dict, str]) -> dict:
    try:
        if isinstance(symbol_info, str):
            try: symbol_info = json.loads(symbol_info)
            except: return {"status": "error", "message": "symbol_info provided as invalid JSON string"}
        if isinstance(current_price, str):
            try: current_price = json.loads(current_price)
            except: return {"status": "error", "message": "current_price provided as invalid JSON string"}
        if not symbol_info or not current_price:
            return {"status": "error", "message": "Missing symbol_info or current_price data."}
        spread_points = symbol_info.get("spread_points")
        point_size = symbol_info.get("point_size")
        bid_price = current_price.get("bid")
        if spread_points is None or point_size is None or bid_price is None:
            return {"status": "error", "message": "Incomplete data for spread analysis (spread, point, or bid missing)."}
        if bid_price <= 1e-9:
            return {"status": "error", "message": "Cannot calculate spread percentage with a price of zero."}
        spread_in_currency = spread_points * point_size
        spread_percentage = (spread_in_currency / bid_price) * 100
        return {
            "status": "success",
            "data": {
                "spread_in_currency": round(spread_in_currency, 5),
                "spread_percentage": round(spread_percentage, 5)
            }
        }
    except Exception as e:
        logger.error(f"Error in spread analysis calculation: {e}", exc_info=True)
        return {"status": "error", "message": f"An unexpected error occurred during spread analysis: {e}"}
async def calculate_rsi(candles: list, period: int = 14) -> dict:
    if not isinstance(candles, list) or len(candles) < period + 1:
        return {"status": "error", "message": f"Insufficient data for RSI. Need {period + 1}, got {len(candles)}."}
    prices = [c.get("close") for c in candles]
    if None in prices:
        return {"status": "error", "message": "Incomplete candle data, missing 'close' price."}
    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    if len(gains) < period:
        return {"status": "error", "message": f"Not enough price changes to calculate RSI({period})."}
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    rsi_values = []
    if avg_loss == 0:
        rs = float('inf')
    else:
        rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    rsi_values.append(rsi)
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            rs = float('inf')
        else:
            rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        rsi_values.append(rsi)
    return {"status": "success", "data": {"rsi_values": rsi_values}}
async def calculate_bbands(candles: list, period: int = 20, std_dev: float = 2.0, price_type: str = "close") -> dict:
    if price_type not in ['open', 'high', 'low', 'close']:
        return {"status": "error", "message": "Invalid price_type."}
    if not isinstance(candles, list) or len(candles) < period:
        return {"status": "error", "message": f"Insufficient data for Bollinger Bands calculation. Need {period}, got {len(candles)}."}
    prices = [c.get(price_type) for c in candles if c.get(price_type) is not None]
    if len(prices) < period:
        return {"status": "error", "message": "Not enough valid price points."}
    upper_bands, middle_bands, lower_bands = [], [], []
    for i in range(period - 1, len(prices)):
        window = prices[i - period + 1 : i + 1]
        sma = sum(window) / period
        variance = sum([(p - sma) ** 2 for p in window]) / period
        sd = math.sqrt(variance)
        upper_band = sma + (std_dev * sd)
        lower_band = sma - (std_dev * sd)
        middle_bands.append(sma)
        upper_bands.append(upper_band)
        lower_bands.append(lower_band)
    return {
        "status": "success",
        "data": {
            "upper_band": upper_bands,
            "middle_band": middle_bands,
            "lower_band": lower_bands
        }
    }
async def calculate_vegas_tunnel(candles: list, price_type: str = "close") -> dict:
    periods = [144, 169]
    tasks = [calculate_ema(candles, period, price_type) for period in periods]
    results = await asyncio.gather(*tasks)
    tunnel_data = {}
    for i, res in enumerate(results):
        if res['status'] != 'success':
            return {"status": "error", "message": f"Failed to calculate EMA({periods[i]}): {res['message']}"}
        tunnel_data[f'ema_{periods[i]}'] = res['data']['ema_values']
    return {"status": "success", "data": tunnel_data}