import json
import logging
logger = logging.getLogger(__name__)
from .tool_market import get_historical_candles, get_current_price
def _find_pin_bar(candles: list) -> dict:
    if not candles:
        return {"found": False, "message": "Not enough candles."}
    last_closed_candle = candles[-1]
    try:
        high, low = last_closed_candle.get('high', 0), last_closed_candle.get('low', 0)
        open_p, close_p = last_closed_candle.get('open', 0), last_closed_candle.get('close', 0)
        price_range = high - low
        if price_range < 1e-9:
            return {"found": False, "message": "Zero range candle."}
        body_size = abs(open_p - close_p)
        upper_wick = high - max(open_p, close_p)
        lower_wick = min(open_p, close_p) - low
        is_small_body = body_size < price_range * 0.33
        is_bullish_pin = is_small_body and lower_wick > price_range * 0.6 and upper_wick < price_range * 0.2
        is_bearish_pin = is_small_body and upper_wick > price_range * 0.6 and lower_wick < price_range * 0.2
        if is_bullish_pin:
            is_candle_bullish = close_p > open_p
            recommended_tool = "buy" if is_candle_bullish else "buylimit"
            result = {
                "found": True,
                "type": "Bullish Pin Bar",
                "candle": last_closed_candle,
                "recommended_tool": recommended_tool,
            }
            if recommended_tool == "buylimit":
                result["entry_price"] = low + lower_wick * (2 / 3)
            return result
        if is_bearish_pin:
            is_candle_bearish = close_p < open_p
            recommended_tool = "sell" if is_candle_bearish else "selllimit"
            result = {
                "found": True,
                "type": "Bearish Pin Bar",
                "candle": last_closed_candle,
                "recommended_tool": recommended_tool,
            }
            if recommended_tool == "selllimit":
                result["entry_price"] = high - upper_wick * (2 / 3)
            return result
        return {"found": False, "message": "No valid Pin Bar found in the last closed candle."}
    except (KeyError, TypeError):
        return {"found": False, "message": "Invalid candle data format."}
def _find_engulfing_pattern(candles: list) -> dict:
    if len(candles) < 2:
        return {"found": False, "message": "Not enough closed candles."}
    engulfing_candle = candles[-1]
    engulfed_candle = candles[-2]
    engulfed_is_bullish = engulfed_candle.get('close', 0) > engulfed_candle.get('open', 0)
    engulfing_is_bullish = engulfing_candle.get('close', 0) > engulfing_candle.get('open', 0)
    if engulfed_is_bullish == engulfing_is_bullish:
        return {"found": False, "message": "Candles have the same color."}
    engulfed_body_max = max(engulfed_candle.get('open', 0), engulfed_candle.get('close', 0))
    engulfed_body_min = min(engulfed_candle.get('open', 0), engulfed_candle.get('close', 0))
    engulfing_body_max = max(engulfing_candle.get('open', 0), engulfing_candle.get('close', 0))
    engulfing_body_min = min(engulfing_candle.get('open', 0), engulfing_candle.get('close', 0))
    if engulfing_body_max >= engulfed_body_max and engulfing_body_min <= engulfed_body_min:
        optimal_entry = 0.0
        engulfing_body_size = engulfing_body_max - engulfing_body_min
        if engulfing_is_bullish:
            optimal_entry = engulfing_body_max - engulfing_body_size * (1 / 3)
        else:
            optimal_entry = engulfing_body_min + engulfing_body_size * (1 / 3)
        return {
            "found": True,
            "type": "Bullish Engulfing" if engulfing_is_bullish else "Bearish Engulfing",
            "engulfing_candle": engulfing_candle,
            "engulfed_candle": engulfed_candle,
            "optimal_entry": optimal_entry
        }
    return {"found": False, "message": "No Engulfing pattern found."}
def _find_inside_bar(candles: list, current_price: dict) -> dict:
    if len(candles) < 2:
        return {"found": False, "message": "Not enough candles for Inside Bar check (needs 2)."}
    mother_candle = candles[-2]
    inside_candle = candles[-1]
    is_inside_geometry = inside_candle.get('high') < mother_candle.get('high') and inside_candle.get('low') > mother_candle.get('low')
    if not is_inside_geometry:
        return {"found": False, "message": "No strict Inside Bar geometry found."}
    try:
        mother_range = mother_candle.get('high') - mother_candle.get('low')
        if mother_range < 1e-9:
            return {"found": False, "message": "Inside Bar rejected. Mother candle has a near-zero range."}
        inside_high = inside_candle.get('high')
        inside_low = inside_candle.get('low')
        current_ask = current_price.get('ask')
        current_bid = current_price.get('bid')
        if not all([inside_high, inside_low, current_ask, current_bid]):
             return {"found": False, "message": "Incomplete candle or price data for breakout check."}
        breakout_up = current_ask > inside_high
        breakout_down = current_bid < inside_low
        breakout_status = "NO_BREAKOUT"
        recommended_direction = None
        if breakout_up and breakout_down:
            breakout_status = "WHIPSAW"
        elif breakout_up:
            breakout_status = "BREAKOUT_UP"
            recommended_direction = "buy"
        elif breakout_down:
            breakout_status = "BREAKOUT_DOWN"
            recommended_direction = "sell"
        return {
            "found": True,
            "type": "Inside Bar",
            "mother_candle": mother_candle,
            "inside_candle": inside_candle,
            "breakout_status": breakout_status,
            "recommended_direction": recommended_direction,
            "recommended_tool": "market_order" if recommended_direction else None
        }
    except (TypeError, KeyError) as e:
        return {"found": False, "message": f"Error during Inside Bar quality check: {e}"}
def _find_demand_supply_zones(candles: list, base_max_candles: int = 5, strength_mult: float = 1.5) -> dict:
    if len(candles) < 20:
        return {"found": False, "zones": [], "message": f"Not enough candles for meaningful zone analysis. Required: 20, available: {len(candles)}."}
    zones, i = [], len(candles) - 2
    while i > base_max_candles:
        leg_out_candle = candles[i+1]
        leg_out_range = abs(leg_out_candle['high'] - leg_out_candle['low'])
        if leg_out_range < 1e-9:
            i -= 1
            continue
        base_candles, is_base_valid = [], False
        for j in range(1, base_max_candles + 1):
            if i - j + 1 < 0: break
            base_candidate = candles[i - j + 1]
            if abs(base_candidate['high'] - base_candidate['low']) < leg_out_range / strength_mult:
                base_candles.insert(0, base_candidate)
                is_base_valid = True
            else:
                break
        if not is_base_valid:
            i -= 1
            continue
        base_start_index = i - len(base_candles) + 1
        if base_start_index - 1 < 0:
            i -=1
            continue
        leg_in_candle = candles[base_start_index - 1]
        leg_in_is_bullish = leg_in_candle['close'] > leg_in_candle['open']
        leg_out_is_bullish = leg_out_candle['close'] > leg_out_candle['open']
        base_high, base_low = max(c['high'] for c in base_candles), min(c['low'] for c in base_candles)
        zone_type = None
        if not leg_in_is_bullish and leg_out_is_bullish: zone_type = "DBR Demand Zone"
        elif leg_in_is_bullish and leg_out_is_bullish: zone_type = "RBR Demand Zone"
        elif leg_in_is_bullish and not leg_out_is_bullish: zone_type = "RBD Supply Zone"
        elif not leg_in_is_bullish and not leg_out_is_bullish: zone_type = "DBD Supply Zone"
        if zone_type:
            zones.append({"type": zone_type, "top": base_high, "bottom": base_low, "start_time": base_candles[0]['time'], "end_time": base_candles[-1]['time'], "fresh": True})
            i = base_start_index - 1
        else:
            i -= 1
    sorted_zones = sorted(zones, key=lambda z: z['start_time'], reverse=True)
    return {"found": len(sorted_zones) > 0, "zones": sorted_zones[:5], "message": "Demand/Supply zones identified." if len(sorted_zones) > 0 else "No valid Demand/Supply zones found."}
def _find_swing_points(candles: list, lookback: int = 5):
    swings = []
    if len(candles) < 2 * lookback + 1: return []
    for i in range(lookback, len(candles) - lookback):
        is_high = all(candles[i]['high'] >= candles[i-j]['high'] and candles[i]['high'] >= candles[i+j]['high'] for j in range(1, lookback + 1))
        is_low = all(candles[i]['low'] <= candles[i-j]['low'] and candles[i]['low'] <= candles[i+j]['low'] for j in range(1, lookback + 1))
        if is_high: swings.append({'type': 'high', 'index': i, 'price': candles[i]['high'], 'time': candles[i]['time']})
        elif is_low: swings.append({'type': 'low', 'index': i, 'price': candles[i]['low'], 'time': candles[i]['time']})
    return swings
def _check_gartley(p, tol=0.0786): return abs((abs(p[2]['price']-p[1]['price'])/abs(p[1]['price']-p[0]['price']))-0.618)<=tol and 0.382<=(abs(p[3]['price']-p[2]['price'])/abs(p[2]['price']-p[1]['price']))<=0.886 and abs((abs(p[4]['price']-p[1]['price'])/abs(p[1]['price']-p[0]['price']))-0.786)<=tol and 1.272<=(abs(p[4]['price']-p[3]['price'])/abs(p[3]['price']-p[2]['price']))<=1.618
def _check_bat(p, tol=0.05): return 0.382<=(abs(p[2]['price']-p[1]['price'])/abs(p[1]['price']-p[0]['price']))<=0.5 and 0.382<=(abs(p[3]['price']-p[2]['price'])/abs(p[2]['price']-p[1]['price']))<=0.886 and abs((abs(p[4]['price']-p[1]['price'])/abs(p[1]['price']-p[0]['price']))-0.886)<=tol
def _check_butterfly(p, tol=0.07): return abs((abs(p[2]['price']-p[1]['price'])/abs(p[1]['price']-p[0]['price']))-0.786)<=tol and 1.272<=(abs(p[4]['price']-p[0]['price'])/abs(p[1]['price']-p[0]['price']))<=1.618
def _check_cypher(p, tol=0.05):
    try:
        return 0.382<=(abs(p[2]['price']-p[1]['price'])/abs(p[1]['price']-p[0]['price']))<=0.618 and 1.272<=((p[3]['price']-p[0]['price'])/(p[1]['price']-p[0]['price']))<=1.414 and abs((abs(p[4]['price']-p[3]['price'])/abs(p[3]['price']-p[0]['price']))-0.786)<=tol
    except (ZeroDivisionError, IndexError):
        return False
def _internal_find_harmonic_patterns(candles: list, symbol: str, timeframe: int) -> dict:
    if len(candles) < 50:
        return {"found": False, "message": f"Not enough candles for harmonic pattern analysis. Required: 50, available: {len(candles)}."}
    swings = _find_swing_points(candles, lookback=5)
    if len(swings) < 5:
        return {"found": False, "message": "Not enough swing points detected in closed candles."}
    for i in range(len(swings) - 5, -1, -1):
        p = swings[i:i+5]
        p_types = [s['type'] for s in p]
        if p_types[0] == p_types[1] or p_types[1] == p_types[2] or p_types[2] == p_types[3] or p_types[3] == p_types[4]:
            continue
        point_labels = ['X', 'A', 'B', 'C', 'D']
        points_map = {label: {'index': p[idx]['index'], 'price': p[idx]['price'], 'time': p[idx]['time'], 'type': p[idx]['type']} for idx, label in enumerate(point_labels)}
        if any(abs(p1['price'] - p2['price']) < 1e-9 for p1, p2 in [(points_map['X'], points_map['A']), (points_map['A'], points_map['B']), (points_map['B'], points_map['C'])]):
            continue
        is_bullish = points_map['D']['type'] == 'low'
        is_bearish = points_map['D']['type'] == 'high'
        if not (is_bullish or is_bearish):
            continue
        checks = {"Gartley": _check_gartley, "Bat": _check_bat, "Butterfly": _check_butterfly, "Cypher": _check_cypher}
        for name, check_func in checks.items():
            if check_func(p):
                return {
                    "found": True,
                    "type": f"Bullish {name}" if is_bullish else f"Bearish {name}",
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "completion_price_D": points_map['D']['price'],
                    "points": points_map
                }
    return {"found": False, "message": "No complete classic harmonic patterns (XABCD) found in recent swings."}
async def scan_for_price_action(symbol: str, timeframe: int, candles_to_check: int = 3) -> dict:
    data_response = await get_historical_candles(symbol, timeframe, candles_to_check)
    if data_response.get("status") != "success":
        return data_response
    price_response = await get_current_price(symbol)
    if price_response.get("status") != "success":
        return {"status": "error", "message": f"Could not get current price for {symbol} to check Inside Bar breakout."}
    current_price = price_response.get("data", {})
    closed_candles = data_response.get("data", [])
    if len(closed_candles) < 2:
        return {"status": "success", "data": {"message": f"Not enough closed candles to scan for patterns (need at least 2, got {len(closed_candles)})."}}
    second_to_last_closed = closed_candles[-2]
    last_closed = closed_candles[-1]
    logger.debug(
        f"[SCAN_VERIFICATION] 'scan_for_price_action' for {symbol} on M{timeframe} is analyzing these last 2 CLOSED candles:\n"
        f"  - Penultimate Closed: {json.dumps(second_to_last_closed, indent=2)}\n"
        f"  - Last Closed       : {json.dumps(last_closed, indent=2)}"
    )
    report = {
        "pin_bar": _find_pin_bar([last_closed]),
        "engulfing": _find_engulfing_pattern([second_to_last_closed, last_closed]),
        "inside_bar": _find_inside_bar([second_to_last_closed, last_closed], current_price),
    }
    found_signal = any(res.get("found") for res in report.values())
    if found_signal:
        return {"status": "success", "data": report}
    else:
        return {"status": "success", "data": {"message": "No recent price action signals (Pin Bar, Engulfing, Inside Bar) found on the last two closed candles."}}
async def scan_for_structures(symbol: str, timeframe: int, candles_to_check: int = 250) -> dict:
    data_response = await get_historical_candles(symbol, timeframe, candles_to_check)
    if data_response.get("status") != "success":
        return data_response
    closed_candles = data_response.get("data", [])
    if not closed_candles:
        return {"status": "info", "message": "No closed candles to scan for structures."}
    report = {
        "harmonics": _internal_find_harmonic_patterns(closed_candles, symbol, timeframe),
        "demand_supply_zones": _find_demand_supply_zones(closed_candles)
    }
    return {"status": "success", "data": report}
def find_fibonacci_retracement(candles: list) -> dict:
    if len(candles) < 20:
        return {"found": False, "message": "Not enough candles for Fibonacci analysis."}
    recent_candles = candles[-250:]
    if not recent_candles:
         return {"found": False, "message": "No candles in recent range."}
    high_point = max(recent_candles, key=lambda c: c['high'])
    low_point = min(recent_candles, key=lambda c: c['low'])
    if high_point['time'] == low_point['time']:
        return {"found": False, "message": "High and low points are the same candle."}
    start_point, end_point = (low_point, high_point) if high_point['time'] > low_point['time'] else (high_point, low_point)
    is_uptrend = high_point['time'] > low_point['time']
    price_range = end_point['high'] - start_point['low'] if is_uptrend else start_point['high'] - end_point['low']
    if price_range < 1e-9:
        return {"found": False, "message": "Price range is zero."}
    fibo_levels = [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]
    level_prices = {}
    for level in fibo_levels:
        if is_uptrend:
            price = end_point['high'] - price_range * level
        else:
            price = end_point['low'] + price_range * level
        level_prices[str(level)] = price
    return {
        "found": True,
        "is_uptrend": is_uptrend,
        "start_point": start_point,
        "end_point": end_point,
        "levels": level_prices
    }
def find_support_resistance_levels(candles: list) -> dict:
    swings = _find_swing_points(candles, lookback=5)
    if not swings:
        return {"found": False, "levels": []}
    recent_swings = swings[-10:]
    supports = [s['price'] for s in recent_swings if s['type'] == 'low']
    resistances = [s['price'] for s in recent_swings if s['type'] == 'high']
    return {"found": True, "supports": supports, "resistances": resistances}
async def scan_for_all_price_action_history(symbol: str, timeframe: int, candles_to_check: int = 250) -> dict:
    data_response = await get_historical_candles(symbol, timeframe, candles_to_check)
    if data_response.get("status") != "success":
        return data_response
    all_candles = data_response.get("data", [])
    if len(all_candles) < 3:
        return {"status": "success", "data": {"message": "Not enough candles.", "patterns": []}}
    price_response = await get_current_price(symbol)
    current_price = price_response.get("data", {}) if price_response.get("status") == "success" else {}
    found_patterns = []
    for i in range(2, len(all_candles) + 1):
        pin_bar_res = _find_pin_bar(all_candles[:i])
        if pin_bar_res.get("found"):
            found_patterns.append(pin_bar_res)
        engulf_res = _find_engulfing_pattern(all_candles[:i])
        if engulf_res.get("found"):
            found_patterns.append(engulf_res)
        inside_bar_res = _find_inside_bar(all_candles[:i], current_price)
        if inside_bar_res.get("found"):
            inside_bar_res.pop("breakout_status", None)
            inside_bar_res.pop("recommended_direction", None)
            inside_bar_res.pop("recommended_tool", None)
            found_patterns.append(inside_bar_res)
    if found_patterns:
        unique_patterns = []
        seen_times = set()
        for pattern in reversed(found_patterns):
            candle = pattern.get('candle') or pattern.get('engulfing_candle') or pattern.get('inside_candle')
            if candle and candle['time'] not in seen_times:
                unique_patterns.insert(0, pattern)
                seen_times.add(candle['time'])
        return {"status": "success", "data": {"patterns": unique_patterns}}
    return {"status": "success", "data": {"message": "No price action signals found.", "patterns": []}}
async def scan_for_all_structures_history(symbol: str, timeframe: int, candles_to_check: int = 250) -> dict:
    data_response = await get_historical_candles(symbol, timeframe, candles_to_check)
    if data_response.get("status") != "success":
        return data_response
    closed_candles = data_response.get("data", [])
    if not closed_candles:
        return {"status": "info", "message": "No closed candles to scan for structures."}
    def _find_all_harmonic_patterns_for_chart(candles: list, symbol: str, timeframe: int) -> dict:
        MIN_CANDLES_REQUIRED = 50
        if len(candles) < MIN_CANDLES_REQUIRED:
            return {"found": False, "message": f"Not enough candles. Required: {MIN_CANDLES_REQUIRED}, available: {len(candles)}."}
        swings = _find_swing_points(candles, lookback=5)
        if len(swings) < 5:
            return {"found": False, "message": "Not enough swing points detected."}
        found_patterns = []
        for i in range(len(swings) - 4):
            p = swings[i:i+5]
            is_bullish = p[4]['type']=='low' and p[3]['type']=='high' and p[2]['type']=='low' and p[1]['type']=='high' and p[0]['type']=='low'
            is_bearish = p[4]['type']=='high' and p[3]['type']=='low' and p[2]['type']=='high' and p[1]['type']=='low' and p[0]['type']=='high'
            if not (is_bullish or is_bearish) or any(abs(p1['price'] - p2['price']) < 1e-9 for p1, p2 in [(p[0],p[1]), (p[1],p[2]), (p[2],p[3])]):
                continue
            checks = {"Gartley": _check_gartley, "Bat": _check_bat, "Butterfly": _check_butterfly, "Cypher": _check_cypher}
            for name, check_func in checks.items():
                if check_func(p):
                    pattern_data = {
                        "found": True, "type": f"Bullish {name}" if is_bullish else f"Bearish {name}",
                        "symbol": symbol, "timeframe": timeframe, "completion_price_D": p[4]['price'],
                        "points": { 'X': p[0], 'A': p[1], 'B': p[2], 'C': p[3], 'D': p[4] }
                    }
                    found_patterns.append(pattern_data)
                    break
        if found_patterns:
            return {"found": True, "patterns": found_patterns}
        return {"found": False, "message": "No classic harmonic patterns found in history."}
    harmonics_res = _find_all_harmonic_patterns_for_chart(closed_candles, symbol, timeframe)
    report = {
        "harmonics": harmonics_res.get("patterns", []) if harmonics_res.get("found") else [],
        "demand_supply_zones": _find_demand_supply_zones(closed_candles),
        "fibonacci": find_fibonacci_retracement(closed_candles),
        "sr_levels": find_support_resistance_levels(closed_candles)
    }
    return {"status": "success", "data": report}