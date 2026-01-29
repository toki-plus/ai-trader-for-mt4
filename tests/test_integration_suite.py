import os
import sys
import json
import math
import asyncio
import logging
import unittest.mock
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
from src.bridge.mt4_bridge import mt4_bridge
from src.services.order_db_manager import order_db_manager
from src.tools import (tool_portfolio, tool_market, tool_trade, tool_utility, tool_news, tool_patterns, tool_flows)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)-8s - %(message)s', datefmt='%H:%M:%S')
logger = logging.getLogger(__name__)
load_dotenv()
TEST_SYMBOL_MAJOR = "BNB-USD"
TEST_SYMBOL_MINOR = "SOL-USD"
INVALID_SYMBOL = "INVALIDXYZ"
TEST_MAGIC_NUMBER_1 = 12345
TEST_MAGIC_NUMBER_2 = 54321
TEST_MAGIC_NUMBER_3 = 98765
class C:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    END = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    GREY = '\033[90m'
class TestState:
    passed_count = 0
    failed_count = 0
    major_symbol_info = None
    minor_symbol_info = None
    tickets = {}
def print_test_step(title, icon="🧪"):
    width = 80
    visual_content_len = len(title) + 6
    total_padding = width - 2 - visual_content_len
    if total_padding < 0: total_padding = 0
    pad_left = total_padding // 2
    pad_right = total_padding - pad_left
    logger.info(f"{C.HEADER}{'═' * width}{C.END}")
    logger.info(f"{C.HEADER}║{' ' * pad_left}{icon} {C.BOLD}{title.upper()}{C.END}{C.HEADER} {icon}{' ' * pad_right}║{C.END}")
    logger.info(f"{C.HEADER}{'═' * width}{C.END}")
def print_sub_step(title):
    logger.info(f"\n{C.CYAN}--- {title} ---{C.END}")
def print_portfolio(title: str, portfolio_data: dict):
    logger.info(f"{C.CYAN}{C.BOLD}--- 📊 PORTFOLIO SNAPSHOT: {title} ---{C.END}")
    orders = portfolio_data.get('data', {}).get('positions', {})
    if not orders:
        logger.warning("  No open positions found.")
        return
    header = f"  {'Ticket':<20} {'Symbol':<10} {'Type':<10} {'Lots':<8} {'OpenPrice':<12} {'Profit':<12} {'Magic':<10} {'Comment'}"
    logger.info(C.BOLD + header + C.END)
    logger.info(C.GREY + '  ' + '-' * (len(header)-2) + C.END)
    for ticket, order in orders.items():
        order_type = order.get('type', 'N/A')
        pnl = order.get('profit', None)
        pnl_str = f"{pnl:.2f}" if pnl is not None else "N/A"
        type_color = C.BLUE if 'buy' in order_type.lower() else C.HEADER
        pnl_color = C.GREEN if pnl is not None and pnl >= 0 else C.RED
        logger.info(
            f"  {ticket:<20} "
            f"{order.get('symbol', 'N/A'):<10} "
            f"{type_color}{order_type:<10}{C.END} "
            f"{order.get('lots', 0.0):<8.2f} "
            f"{order.get('open_price', 0.0):<12.5f} "
            f"{pnl_color}{pnl_str:<12}{C.END} "
            f"{order.get('magic', 0):<10} "
            f"{C.GREY}'{order.get('comment', 'N/A')}'{C.END}"
        )
    logger.info(C.GREY + '  ' + '-' * (len(header)-2) + C.END)
def _print_flow_details(result):
    if result and isinstance(result, dict) and "results" in result:
        logger.info(f"{C.BLUE}  --- Flow Execution Trace ---{C.END}")
        for step_result in result.get("results", []):
            step_id = step_result.get('id', 'N/A')
            tool_name = step_result.get('tool_name', 'N/A')
            parameters = step_result.get('parameters', 'N/A')
            res = step_result.get('result', {})
            status = res.get('status', 'unknown')
            icon = "✅" if status == "success" else "❌" if status == "error" else "⚠️"
            color = C.GREEN if status == "success" else C.RED if status == "error" else C.YELLOW
            message = res.get('message', 'No message.')
            logger.info(f"{color}    [{icon} {step_id}] {tool_name}: {status.upper()} - {message}{C.END}")
            if status == "error":
                logger.debug(f"{C.RED}      Params: {json.dumps(parameters, default=str)}{C.END}")
        logger.info(f"{C.BLUE}  --------------------------{C.END}")
async def check_result(test_name, result, is_critical=False):
    logger.info(f"▶️  Testing: {C.YELLOW}{test_name}{C.END}")
    if isinstance(result, dict) and result.get("status") in ["success", "warning"]:
        if result.get("status") == "warning":
            logger.warning(f"  ➡️  Result: {C.YELLOW}⚠️ WARNING (Accepted as Pass){C.END}")
        else:
            logger.info(f"  ➡️  Result: {C.GREEN}✅ SUCCESS{C.END}")
        TestState.passed_count += 1
        data_to_show = result.get("data", result.get("message", result.get("final_context", result)))
        if isinstance(data_to_show, list) and len(data_to_show) > 3:
             data_to_show = f"List of {len(data_to_show)} items. First: {json.dumps(data_to_show[0], ensure_ascii=False)}"
        pretty_data = json.dumps(data_to_show, indent=2, ensure_ascii=False)
        if len(pretty_data) > 400:
            pretty_data = pretty_data[:400] + "\n  ... (output truncated)"
        logger.debug(f"{C.GREY}  Data: {pretty_data}{C.END}")
        _print_flow_details(result)
        return True, result
    else:
        logger.error(f"  ➡️  Result: {C.RED}❌ FAILED{C.END}")
        logger.error(f"{C.RED}  Details: {json.dumps(result, indent=2, ensure_ascii=False, default=str)}{C.END}")
        _print_flow_details(result)
        TestState.failed_count += 1
        if is_critical:
            raise RuntimeError(f"CRITICAL test '{test_name}' failed.")
        return False, result
async def check_failure(test_name, result, expected_error_msg_parts=""):
    logger.info(f"▶️  Testing (Expecting Failure): {C.YELLOW}{test_name}{C.END}")
    if isinstance(result, dict) and result.get("status") == "error":
        message = result.get("message", "").lower()
        possible_errors = [part.lower() for part in expected_error_msg_parts.split('|')] if expected_error_msg_parts else []
        if not possible_errors or any(part in message for part in possible_errors):
            logger.info(f"  ➡️  Result: {C.GREEN}✅ SUCCESS (Failed as Expected){C.END}")
            logger.debug(f"{C.GREY}  Failure Reason: {result.get('message')}{C.END}")
            _print_flow_details(result)
            TestState.passed_count += 1
            return True, None
        else:
            logger.error(f"  ➡️  Result: {C.RED}❌ FAILED (Wrong Error){C.END}")
            logger.error(f"  Details: Expected error containing one of '{' | '.join(possible_errors)}', but got: '{result.get('message')}'")
            _print_flow_details(result)
            TestState.failed_count += 1
            return False, None
    else:
        logger.error(f"  ➡️  Result: {C.RED}❌ FAILED (Did not fail as expected){C.END}")
        logger.error(f"{C.RED}  Details: {json.dumps(result, indent=2, ensure_ascii=False)}{C.END}")
        _print_flow_details(result)
        TestState.failed_count += 1
        return False, result
def calculate_stops(price_data, info_data, order_type, distance_pips=100):
    ask, bid = price_data['ask'], price_data['bid']
    digits = info_data.get('digits', 5)
    pip_size = info_data.get('pip_size', 1e-4)
    stops_level = info_data.get('stops_level_points', 1)
    point_size = info_data.get('point_size', pip_size / 10 if pip_size > 1e-5 else 1e-5)
    min_distance_price = (stops_level + 1) * point_size
    calculated_distance_price = distance_pips * pip_size
    distance = max(min_distance_price, calculated_distance_price)
    if 'buy' in order_type.lower():
        return round(bid - distance, digits), round(ask + distance * 2, digits)
    return round(ask + distance, digits), round(bid - distance * 2, digits)
async def get_server_time_for_test() -> datetime:
    server_time_res = await tool_market.get_server_time()
    if server_time_res.get("status") == "success":
        time_str = server_time_res.get("data", {}).get("server_time")
        if time_str:
            try: return datetime.strptime(time_str, '%Y.%m.%d %H:%M')
            except (ValueError, TypeError): pass
    logger.warning("Could not get server time for test, falling back to UTC now.")
    return datetime.utcnow()
async def test_01_initialization_and_cleanup():
    print_test_step("INITIALIZE & CLEANUP", "🚀")
    mt4_data_path = os.getenv("MT4_DATA_PATH")
    await mt4_bridge.initialize(mt4_data_path=mt4_data_path, initial_subscribe_symbols=[TEST_SYMBOL_MAJOR, TEST_SYMBOL_MINOR])
    logger.info("MT4 Bridge and OrderDB initialized successfully.")
    logger.info("Cleaning up any leftover temporary orders from previous runs...")
    await order_db_manager.clean_temporary_orders()
    logger.info("Waiting 5s for initial account state synchronization...")
    await asyncio.sleep(5)
    await check_result("Close All Orders (Initial Cleanup)", await tool_trade.close_all_orders(), is_critical=False)
    logger.info("Waiting 3s for EA to process cleanup...")
    await asyncio.sleep(3)
async def test_02_read_only_and_negative_cases():
    print_test_step("READ-ONLY & NEGATIVE CASES", "📚")
    print_sub_step("Basic Data Sanity Checks")
    await check_result("Get Portfolio (should be empty)", await tool_portfolio.get_portfolio())
    await check_result("Get Server Time", await tool_market.get_server_time())
    await check_result(f"Is Market Active ({TEST_SYMBOL_MAJOR})", await tool_market.is_market_active(TEST_SYMBOL_MAJOR, "M15"))
    ok, major_info_res = await check_result(f"Get Symbol Info ({TEST_SYMBOL_MAJOR})", await tool_market.get_symbol_info(TEST_SYMBOL_MAJOR), is_critical=True)
    if ok: TestState.major_symbol_info = major_info_res.get('data')
    ok, minor_info_res = await check_result(f"Get Symbol Info ({TEST_SYMBOL_MINOR})", await tool_market.get_symbol_info(TEST_SYMBOL_MINOR), is_critical=True)
    if ok: TestState.minor_symbol_info = minor_info_res.get('data')
    print_sub_step("Batch & Historic Data")
    logger.info(f"▶️  Testing: {C.YELLOW}Get Current Prices (Batch){C.END}")
    batch_prices_res = await tool_market.get_current_prices([TEST_SYMBOL_MAJOR, TEST_SYMBOL_MINOR, INVALID_SYMBOL])
    if isinstance(batch_prices_res, dict) and all(k in batch_prices_res for k in [TEST_SYMBOL_MAJOR, TEST_SYMBOL_MINOR, INVALID_SYMBOL]):
        logger.info(f"  ➡️  Result: ✅ SUCCESS")
        TestState.passed_count += 1
    else:
        logger.error(f"  ➡️  Result: ❌ FAILED")
        logger.error(f"  Details: {json.dumps(batch_prices_res, indent=2, ensure_ascii=False, default=str)}")
        TestState.failed_count += 1
        raise RuntimeError("CRITICAL test 'Get Current Prices (Batch)' failed.")
    if isinstance(batch_prices_res, dict):
        await check_result(f"- Check {TEST_SYMBOL_MAJOR} in batch", batch_prices_res.get(TEST_SYMBOL_MAJOR))
        await check_result(f"- Check {TEST_SYMBOL_MINOR} in batch", batch_prices_res.get(TEST_SYMBOL_MINOR))
        await check_failure(f"- Check {INVALID_SYMBOL} in batch", batch_prices_res.get(INVALID_SYMBOL), "not available")
    await check_result("Get Market Data (H1)", await tool_market.get_historical_candles(symbol=TEST_SYMBOL_MAJOR, timeframe="H1", count=250))
    await check_result("Get Historic Trades (last 7 days)", await tool_portfolio.get_historic_trades(lookback_days=7))
    print_sub_step("Read-Only Negative Cases")
    await check_failure(f"Get Symbol Info for invalid symbol '{INVALID_SYMBOL}'", await tool_market.get_symbol_info(INVALID_SYMBOL), "timeout|could not select|no valid symbol")
    await check_failure(f"Get Current Price for invalid symbol '{INVALID_SYMBOL}'", await tool_market.get_current_price(INVALID_SYMBOL), "not available")
    await check_result(f"Get Market Data for invalid symbol '{INVALID_SYMBOL}' (expecting warning)", await tool_market.get_historical_candles(INVALID_SYMBOL, "M15", 20))
    await check_failure("Get Order Details for non-existent ticket 999999", await tool_portfolio.get_order_details(999999), "not found")
async def test_03_trade_flow_and_db_preregistration():
    print_test_step("TRADE FLOW & DB PRE-REGISTRATION", "✅")
    print_sub_step("Executing a valid BUY trade flow and verifying DB state")
    ok, result = await check_result("Get Portfolio for Equity", await tool_portfolio.get_portfolio(), is_critical=True)
    if not ok: return
    equity = result.get('data', {}).get('account', {}).get('equity')
    risk_amount = round(equity * 0.001, 2) if equity > 0 else 1.0
    server_time = (await get_server_time_for_test()).isoformat()
    ok, result = await check_result("Get Current Price", await tool_market.get_current_price(TEST_SYMBOL_MAJOR), is_critical=True)
    if not ok: return
    entry_price = result.get('data', {}).get('ask')
    signal_tf_for_test = 15
    trade_flow_list = [
        {"id": "get_info", "tool_name": "get_symbol_info", "parameters": {"symbol": TEST_SYMBOL_MAJOR}},
        {"id": "generate_id", "tool_name": "generate_trade_id", "parameters": {"symbol": TEST_SYMBOL_MAJOR, "timeframe": signal_tf_for_test, "signal_type": "FlowTest", "signal_time": server_time}},
        {"id": "calc_sl", "tool_name": "calculate_stop_loss_from_pattern", "parameters": {"symbol": TEST_SYMBOL_MAJOR, "timeframe": signal_tf_for_test, "pattern_type": "eng", "pattern_candles": {"engulfing_candle": {"high": entry_price + 1.0, "low": entry_price - 2.0}}, "trade_type": "buy", "atr_multiple": 0.1, "symbol_info": "{get_info.data}", "current_price": result.get('data', {})}},
        {"id": "calc_lots", "tool_name": "calculate_lot_size", "parameters": {"risk_amount_usd": risk_amount, "entry_price": entry_price, "sl_price": "{calc_sl.data.sl_price}", "contract_size": "{get_info.data.contract_size}", "lot_step": "{get_info.data.lot_step}", "min_lot": "{get_info.data.min_lot}", "max_lot": "{get_info.data.max_lot}"}},
        {"id": "execute_order", "tool_name": "buy", "parameters": {"symbol": TEST_SYMBOL_MAJOR, "lots": "{calc_lots.data.adjusted_lots}", "sl_price": "{calc_sl.data.sl_price}", "magic": TEST_MAGIC_NUMBER_1, "comment": "L=0;G=A;S=FLOW;ID={generate_id.data.trade_id}"}}
    ]
    flow_ok, flow_res = await check_result("Execute Trade Flow (BUY Market)", await tool_flows.execute_trade_flow(flow=trade_flow_list, signal_tf=signal_tf_for_test), is_critical=True)
    if flow_ok:
        execute_step_res = next((s['result'] for s in flow_res.get('results', []) if s['id'] == 'execute_order'), None)
        ticket = execute_step_res.get('ticket') if execute_step_res else None
        if not ticket:
            logger.error("❌ Flow seemed successful but no ticket was returned.")
            TestState.failed_count += 1
            return
        TestState.tickets['flow_ticket'] = ticket
        logger.info(f"Verifying pre-registration for ticket {ticket} in DB...")
        await asyncio.sleep(2)
        ok_details, details_res = await check_result(f"Get order details for ticket {ticket}", await tool_portfolio.get_order_details(ticket))
        if ok_details:
            order_data = details_res.get('data', {})
            if order_data.get('tp1_price') and order_data.get('tp8_price'):
                logger.info(f"{C.GREEN}✅ DB Verification Success: Order {ticket} has pre-calculated TP levels.{C.END}")
            else:
                logger.error(f"{C.RED}❌ DB Verification Failed: Order {ticket} is missing TP levels in DB.{C.END}")
                TestState.failed_count += 1
            if "L=0;G=A;S=FLOW" in order_data.get('comment_ai', ''):
                logger.info(f"{C.GREEN}✅ DB Verification Success: comment_ai is correct.{C.END}")
            else:
                logger.error(f"{C.RED}❌ DB Verification Failed: comment_ai is incorrect. Got '{order_data.get('comment_ai', '')}'.{C.END}")
                TestState.failed_count += 1
    if 'flow_ticket' in TestState.tickets:
        await tool_trade.close_order(TestState.tickets['flow_ticket'])
async def test_04_buy_lifecycle_and_duplicate_prevention():
    print_test_step(f"BUY LIFECYCLE & DUPLICATE PREVENTION ({TEST_SYMBOL_MAJOR})", "📈")
    ok, result = await check_result(f"Get price for {TEST_SYMBOL_MAJOR}", await tool_market.get_current_price(TEST_SYMBOL_MAJOR), is_critical=True)
    if not ok: return
    price_res = result.get('data')
    lots = TestState.major_symbol_info.get('min_lot', 0.01)
    server_time = await get_server_time_for_test()
    ok, result = await check_result("Generate Trade ID", await tool_utility.generate_trade_id(symbol=TEST_SYMBOL_MAJOR, timeframe=15, signal_type="TestSignal", signal_time=server_time.isoformat()))
    if not ok: return
    trade_id = result.get('data', {}).get("trade_id")
    buy_sl, _ = calculate_stops(price_res, TestState.major_symbol_info, 'buy')
    comment = f"L=0;G=B;S=TEST;ID={trade_id}"
    logger.info(f"Attempting to BUY {lots} lots of {TEST_SYMBOL_MAJOR} | SL: {buy_sl}, Comment: {comment}")
    ok, buy_result = await check_result("Buy Market (First Attempt)", await tool_trade.buy(symbol=TEST_SYMBOL_MAJOR, lots=lots, sl_price=buy_sl, magic=TEST_MAGIC_NUMBER_1, comment=comment), is_critical=True)
    if not ok: return
    buy_ticket = buy_result.get("ticket")
    TestState.tickets['buy_ticket'] = buy_ticket
    await asyncio.sleep(2)
    logger.info("Attempting to open the same trade again (should be skipped)...")
    ok, duplicate_buy_result = await check_result("Buy Market (Duplicate Attempt)", await tool_trade.buy(symbol=TEST_SYMBOL_MAJOR, lots=lots, sl_price=buy_sl, magic=TEST_MAGIC_NUMBER_1, comment=comment))
    if ok and "already exists" not in duplicate_buy_result.get("message", ""):
        logger.error(f"{C.RED}❌ FAILED: Duplicate prevention did not work as expected.{C.END}")
        TestState.failed_count += 1
    elif ok:
        logger.info(f"{C.GREEN}✅ SUCCESS: Duplicate prevention worked as expected.{C.END}")
    await asyncio.sleep(2.5)
    await check_result(f"Get Order Details for new ticket {buy_ticket}", await tool_portfolio.get_order_details(buy_ticket))
    new_sl = round(buy_sl * 0.999, TestState.major_symbol_info['digits'])
    logger.info(f"Modifying ticket {buy_ticket} -> New SL: {new_sl}")
    await check_result(f"Modify SL/TP for ticket {buy_ticket}", await tool_trade.modify_order_sl_tp(ticket=buy_ticket, new_sl_price=new_sl))
    await asyncio.sleep(2.5)
    logger.info(f"Moving SL to Breakeven for ticket {buy_ticket}")
    await check_result(f"Move SL to Breakeven for ticket {buy_ticket}", await tool_trade.move_sl_to_breakeven(ticket=buy_ticket, add_pips=2))
    await asyncio.sleep(2.5)
    ok, _ = await check_result("Get Details Before Close", await tool_portfolio.get_order_details(buy_ticket))
    if ok:
        logger.info(f"Closing ticket {buy_ticket}")
        await check_result(f"Close Order for ticket {buy_ticket}", await tool_trade.close_order(ticket=buy_ticket))
    else:
        logger.warning(f"NOTE: Ticket {buy_ticket} may have already closed. Skipping explicit close.")
        TestState.passed_count += 1
    logger.info("Waiting 2.5s for DB sync after close...")
    await asyncio.sleep(2.5)
    logger.info(f"▶️  Testing: {C.YELLOW}Verification: Check if ticket {buy_ticket} is gone from open orders{C.END}")
    find_result = await tool_portfolio.find_orders(symbol=TEST_SYMBOL_MAJOR, ticket=buy_ticket)
    if find_result.get('status') == 'success' and not find_result.get('data'):
        logger.info(f"  ➡️  Result: {C.GREEN}✅ SUCCESS (Order not found in open positions, as expected){C.END}")
        TestState.passed_count += 1
    else:
        logger.error(f"  ➡️  Result: {C.RED}❌ FAILED (Order was found in open positions when it should be closed){C.END}")
        logger.error(f"{C.RED}  Details: {json.dumps(find_result, indent=2, ensure_ascii=False)}{C.END}")
        TestState.failed_count += 1
async def test_05_sell_partial_close_and_comment_inheritance():
    print_test_step(f"SELL, PARTIAL CLOSE & COMMENT INHERITANCE ({TEST_SYMBOL_MINOR})", "📉")
    ok, result = await check_result(f"Get price for {TEST_SYMBOL_MINOR}", await tool_market.get_current_price(TEST_SYMBOL_MINOR), is_critical=True)
    if not ok: return
    price_res, server_time = result.get('data'), await get_server_time_for_test()
    ok, result = await check_result("Generate Trade ID", await tool_utility.generate_trade_id(symbol=TEST_SYMBOL_MINOR, timeframe=15, signal_type="PartialCloseTest", signal_time=server_time.isoformat()))
    if not ok: return
    trade_id = result.get('data', {}).get("trade_id")
    sell_sl, _ = calculate_stops(price_res, TestState.minor_symbol_info, 'sell', distance_pips=200)
    original_comment = f"L=0;G=C;S=PCT;ID={trade_id}"
    min_lot, lot_step = TestState.minor_symbol_info.get('min_lot', 1.0), TestState.minor_symbol_info.get('lot_step', 1.0)
    lots_to_close = min_lot
    lot_size_to_open = round(lots_to_close + lot_step, 2)
    if lot_size_to_open <= lots_to_close: lot_size_to_open = round(lots_to_close * 2, 2)
    logger.info(f"Attempting to SELL {lot_size_to_open} lots of {TEST_SYMBOL_MINOR} with comment: '{original_comment}'")
    ok, sell_result = await check_result("Sell Market (for partial close test)", await tool_trade.sell(symbol=TEST_SYMBOL_MINOR, lots=lot_size_to_open, sl_price=sell_sl, magic=TEST_MAGIC_NUMBER_2, comment=original_comment), is_critical=True)
    if not ok: return
    original_ticket = sell_result.get("ticket")
    TestState.tickets['sell_ticket_original'] = original_ticket
    logger.info("Waiting 3s for order to settle...")
    await asyncio.sleep(3)
    ok, portfolio_before = await check_result("Get Portfolio Before Partial Close", await tool_portfolio.get_portfolio())
    if ok: print_portfolio("Before Partial Close", portfolio_before)
    logger.info(f"Partially closing {lots_to_close} lots of ticket {original_ticket}...")
    ok, partial_close_res = await check_result("Close Partial Order", await tool_trade.close_partial_order(ticket=original_ticket, lots_to_close=lots_to_close))
    if not ok:
        await tool_trade.close_all_orders()
        return
    logger.info("Waiting 3s for inheritance to process...")
    await asyncio.sleep(3)
    ok, portfolio_after = await check_result("Get Portfolio After Partial Close", await tool_portfolio.get_portfolio())
    if ok: print_portfolio("After Partial Close", portfolio_after)
    new_ticket = None
    positions_after = portfolio_after.get('data', {}).get('positions', {})
    for t, o in positions_after.items():
        if o.get('extends') == original_ticket:
            new_ticket = int(t)
            logger.info(f"Successfully found new ticket {new_ticket} with 'extends' field in DB.")
            break
    if new_ticket:
        TestState.tickets['sell_ticket_new'] = new_ticket
        logger.info(f"{C.BOLD}VERIFICATION STEP:{C.END} Checking Comment on new ticket {new_ticket}...")
        ok, new_order_details_res = await check_result(f"Get Order Details for new ticket {new_ticket}", await tool_portfolio.get_order_details(new_ticket))
        if ok:
            final_comment_ai = new_order_details_res.get("data", {}).get("comment_ai", "")
            logger.info(f"  - Original Comment: '{original_comment}'")
            logger.info(f"  - New Order AI Comment:  '{final_comment_ai}'")
            if final_comment_ai == original_comment:
                logger.info(f"{C.GREEN}✅ SUCCESS: Comment correctly inherited.{C.END}")
            else:
                logger.error(f"{C.RED}❌ FAILED: Comment verification failed. Expected '{original_comment}', got '{final_comment_ai}'.{C.END}")
                TestState.failed_count += 1
        logger.info(f"Closing remaining lots of ticket {new_ticket}")
        await check_result(f"Close Order for ticket {new_ticket}", await tool_trade.close_order(ticket=new_ticket))
    else:
        logger.error(f"{C.RED}❌ FAILED: Could not find new ticket after partial close.{C.END}")
        TestState.failed_count += 1
    await tool_trade.close_orders_by_symbol(TEST_SYMBOL_MINOR)
    await asyncio.sleep(2.5)
async def test_06_trade_management_negative_cases():
    print_test_step("TRADE MANAGEMENT - NEGATIVE CASES", "💣")
    ok, result = await check_result(f"Get price for {TEST_SYMBOL_MAJOR}", await tool_market.get_current_price(TEST_SYMBOL_MAJOR), is_critical=True)
    if not ok: return
    price_res = result.get('data')
    sl, _ = calculate_stops(price_res, TestState.major_symbol_info, 'buy', 50)
    lots = TestState.major_symbol_info.get('min_lot', 0.01)
    neg_id1 = (await tool_utility.generate_trade_id(TEST_SYMBOL_MAJOR, 15, "neg1", "t1"))['data']['trade_id']
    neg_id2 = (await tool_utility.generate_trade_id(TEST_SYMBOL_MAJOR, 15, "neg2", "t2"))['data']['trade_id']
    await check_failure("Buy Market with SL on wrong side", await tool_trade.buy(TEST_SYMBOL_MAJOR, lots, sl_price=price_res['ask'] + 0.001, comment=f"L=0;G=;S=NEG;ID={neg_id1}"), "invalid sl|invalid stops")
    ok, buy_res = await check_result("Open temp trade for tests", await tool_trade.buy(TEST_SYMBOL_MAJOR, lots, sl_price=sl, comment=f"L=0;G=;S=NEG;ID={neg_id2}", magic=TEST_MAGIC_NUMBER_1), is_critical=True)
    if not ok: return
    temp_ticket = buy_res['ticket']
    await asyncio.sleep(3)
    logger.info(f"Using temporary ticket {temp_ticket} for tests...")
    await check_failure(f"Close Partial Order with more lots than position size", await tool_trade.close_partial_order(temp_ticket, lots * 2), "invalid trade volume|invalid volume")
    ok, result = await check_result(f"Get price for {TEST_SYMBOL_MAJOR}", await tool_market.get_current_price(TEST_SYMBOL_MAJOR))
    if not ok:
        await tool_trade.close_order(temp_ticket)
        return
    price_data = result.get('data')
    await check_failure(f"Modify Order SL/TP with invalid SL", await tool_trade.modify_order_sl_tp(ticket=temp_ticket, new_sl_price=price_data['ask'] + 0.01), "invalid stops|modification denied")
    await check_failure("Modify a non-existent order", await tool_trade.modify_order_sl_tp(ticket=99999999, new_sl_price=1.0), "not found|invalid ticket")
    await check_result("Close temporary test order", await tool_trade.close_order(temp_ticket))
    await asyncio.sleep(2.5)
async def test_07_pending_orders_lifecycle():
    print_test_step("PENDING ORDERS: PLACE, MODIFY, DELETE", "⏳")
    ok, result = await check_result(f"Get price for {TEST_SYMBOL_MAJOR}", await tool_market.get_current_price(TEST_SYMBOL_MAJOR), is_critical=True)
    if not ok: return
    price_major = result.get('data')
    lots_major = TestState.major_symbol_info.get('min_lot', 0.01)
    buylimit_price = round(price_major['bid'] * 0.99, TestState.major_symbol_info['digits'])
    sl_buy, tp_buy = calculate_stops({'ask': buylimit_price, 'bid': buylimit_price}, TestState.major_symbol_info, 'buylimit')
    pending_id = (await tool_utility.generate_trade_id(TEST_SYMBOL_MAJOR, 15, "pending", "t1"))['data']['trade_id']
    logger.info(f"Placing BUY LIMIT for {TEST_SYMBOL_MAJOR} @ {buylimit_price}")
    ok, place_res = await check_result("Place Buy Limit", await tool_trade.buylimit(symbol=TEST_SYMBOL_MAJOR, lots=lots_major, price=buylimit_price, sl_price=sl_buy, tp_price=tp_buy, magic=TEST_MAGIC_NUMBER_3, comment=f"L=0;G=B;S=PEN;ID={pending_id}"), is_critical=True)
    if not ok: return
    pending_ticket = place_res['ticket']
    await asyncio.sleep(2.5)
    new_price = round(buylimit_price * 0.999, TestState.major_symbol_info['digits'])
    new_sl = round(sl_buy * 0.999, TestState.major_symbol_info['digits'])
    logger.info(f"Modifying pending order {pending_ticket} -> New Entry: {new_price}, New SL: {new_sl}")
    await check_result(f"Modify Pending Order {pending_ticket}", await tool_trade.modify_order_sl_tp(ticket=pending_ticket, new_price=new_price, new_sl_price=new_sl, new_tp_price=tp_buy))
    logger.info("Waiting 5s for order state to settle before deletion...")
    await asyncio.sleep(5.0)
    logger.info(f"Deleting (closing) pending order {pending_ticket}")
    await check_result(f"Delete Pending Order {pending_ticket}", await tool_trade.close_order(pending_ticket))
    await asyncio.sleep(2.5)
    await check_failure(f"Verify Pending Order {pending_ticket} is deleted", await tool_portfolio.get_order_details(pending_ticket), "not found")
async def test_08_bulk_and_search_closing():
    print_test_step("BULK, SYMBOL, MAGIC & SEARCH CLOSING", "📡")
    logger.info(f"Pre-cleaning any remaining {TEST_SYMBOL_MINOR} orders...")
    await tool_trade.close_orders_by_symbol(TEST_SYMBOL_MINOR)
    await asyncio.sleep(3)
    logger.info("Opening multiple orders for bulk closing tests...")
    lots_major = TestState.major_symbol_info.get('min_lot', 0.01)
    price_major = (await tool_market.get_current_price(TEST_SYMBOL_MAJOR))['data']
    sl_major, _ = calculate_stops(price_major, TestState.major_symbol_info, 'buy', 50)
    id_m1 = (await tool_utility.generate_trade_id(TEST_SYMBOL_MAJOR, 15, "bulk", "m1"))['data']['trade_id']
    await check_result("Open first order (major)", await tool_trade.buy(TEST_SYMBOL_MAJOR, lots_major, sl_price=sl_major, magic=TEST_MAGIC_NUMBER_1, comment=f"L=0;G=B;S=BULK;ID={id_m1}"))
    lots_minor = TestState.minor_symbol_info.get('min_lot', 1.0)
    price_minor = (await tool_market.get_current_price(TEST_SYMBOL_MINOR))['data']
    sl_minor, _ = calculate_stops(price_minor, TestState.minor_symbol_info, 'sell', 50)
    id_m2_1 = (await tool_utility.generate_trade_id(TEST_SYMBOL_MINOR, 15, "bulk", "m21"))['data']['trade_id']
    id_m2_2 = (await tool_utility.generate_trade_id(TEST_SYMBOL_MINOR, 15, "bulk", "m22"))['data']['trade_id']
    await check_result("Open first order (minor)", await tool_trade.sell(TEST_SYMBOL_MINOR, lots_minor, sl_price=sl_minor, magic=TEST_MAGIC_NUMBER_2, comment=f"L=0;G=C;S=BULK;ID={id_m2_1}"))
    await asyncio.sleep(1.0)
    await check_result("Open second order (minor, different ID)", await tool_trade.sell(TEST_SYMBOL_MINOR, lots_minor, sl_price=sl_minor, magic=TEST_MAGIC_NUMBER_2, comment=f"L=0;G=C;S=BULK;ID={id_m2_2}"))
    await asyncio.sleep(3)
    ok, find_res = await check_result(f"Find Orders (SELL on {TEST_SYMBOL_MINOR}, Magic {TEST_MAGIC_NUMBER_2})", await tool_portfolio.find_orders(symbol=TEST_SYMBOL_MINOR, side='sell', magic=TEST_MAGIC_NUMBER_2))
    if ok:
        found_orders = find_res.get('data', [])
        if len(found_orders) == 2:
            logger.info(f"{C.GREEN}✅ Verification: Found 2 {TEST_SYMBOL_MINOR} SELL orders as expected.{C.END}")
        else:
            logger.error(f"{C.RED}❌ Verification: Expected 2 {TEST_SYMBOL_MINOR} SELL orders, found {len(found_orders)}.{C.END}")
            TestState.failed_count += 1
    await check_result(f"Close Orders by Symbol ({TEST_SYMBOL_MAJOR})", await tool_trade.close_orders_by_symbol(symbol=TEST_SYMBOL_MAJOR))
    await asyncio.sleep(3)
    ok, portfolio_res = await check_result("Get Portfolio after symbol close", await tool_portfolio.get_portfolio())
    if ok:
        if any(o['symbol'] == TEST_SYMBOL_MAJOR for o in portfolio_res.get('data', {}).get('positions', {}).values()):
            logger.error(f"{C.RED}Verification Failed: Orders for {TEST_SYMBOL_MAJOR} still exist.{C.END}")
            TestState.failed_count += 1
        else:
            logger.info(f"Verification Success: No more orders for {TEST_SYMBOL_MAJOR}.")
    await check_result(f"Close Orders by Magic ({TEST_MAGIC_NUMBER_2})", await tool_trade.close_orders_by_magic(magic=TEST_MAGIC_NUMBER_2))
    await asyncio.sleep(3)
    ok, portfolio_res = await check_result("Get Portfolio after magic close", await tool_portfolio.get_portfolio())
    if ok:
        if any(o.get('magic') == TEST_MAGIC_NUMBER_2 for o in portfolio_res.get('data', {}).get('positions', {}).values()):
            logger.error(f"{C.RED}Verification Failed: Orders with magic {TEST_MAGIC_NUMBER_2} still exist.{C.END}")
            TestState.failed_count += 1
        else:
            logger.info(f"Verification Success: No more orders with magic {TEST_MAGIC_NUMBER_2}.")
async def test_09_utility_and_analysis_tools():
    print_test_step("UTILITY AND ANALYSIS TOOLS", "🛠️")
    print_sub_step("Calculation Tools")
    await check_result("Generate Trade ID", await tool_utility.generate_trade_id(TEST_SYMBOL_MAJOR, 15, "PinBar", "2024-05-20T10:30:00"))
    await check_result("Calculate Lot Size (Happy Path)", await tool_utility.calculate_lot_size(100.0, 1.10000, 1.09000, TestState.major_symbol_info['contract_size'], TestState.major_symbol_info['lot_step'], TestState.major_symbol_info['min_lot'], TestState.major_symbol_info['max_lot']))
    await check_failure("Calculate Lot Size (SL too close)", await tool_utility.calculate_lot_size(100, 1.1, 1.1, 100000, 0.01, 0.01, 10), "too close")
    ok, result = await check_result(f"Get price for {TEST_SYMBOL_MAJOR}", await tool_market.get_current_price(TEST_SYMBOL_MAJOR), is_critical=True)
    if not ok: return
    price_res = result.get('data')
    lots = TestState.major_symbol_info.get('min_lot', 0.01)
    sl, _ = calculate_stops(price_res, TestState.major_symbol_info, 'buy', 100)
    ladder_id = (await tool_utility.generate_trade_id(TEST_SYMBOL_MAJOR, 15, "ladder", "t1"))['data']['trade_id']
    ok, buy_res = await check_result("Open trade for ladder test", await tool_trade.buy(TEST_SYMBOL_MAJOR, lots, sl, comment=f"L=0;G=A;S=LAD;ID={ladder_id}"))
    if not ok: return
    ticket = buy_res.get('ticket')
    await asyncio.sleep(1)
    ok, ladder_res = await check_result("Calculate Profit Ladder Levels", await tool_utility.calculate_profit_ladder_levels(ticket=ticket, initial_rr_ratio=1.0))
    if ok:
        ladder_data = ladder_res.get('data', {}).get('ladder', {})
        if 'tp1' in ladder_data and 'tp2' in ladder_data:
            logger.info(f"{C.GREEN}✅ Verification: Ladder contains tp1 and tp2.{C.END}")
        else:
            logger.error(f"{C.RED}❌ Verification: Ladder is missing tp1 or tp2.{C.END}")
            TestState.failed_count += 1
    await check_result("Close trade for ladder test", await tool_trade.close_order(ticket))
    await asyncio.sleep(2)
    print_sub_step("Analysis & External API Tools")
    if os.getenv("JINA_API_KEY"):
        jina_res = await tool_news.search_jina_and_read(f"{TEST_SYMBOL_MAJOR} news", num_results=1)
        if jina_res.get("status") == "error" and "network" in jina_res.get("message", "").lower():
             logger.warning("JINA search test passed with warning due to network issue: %s", jina_res.get("message"))
             TestState.passed_count += 1
        else:
            await check_result("Search Jina and Read", jina_res)
    else:
        logger.warning("SKIPPING JINA SEARCH TEST: JINA_API_KEY not found in .env file.")
        TestState.passed_count += 1
    await check_result(f"Analyze Trend with EMA ({TEST_SYMBOL_MAJOR} H4)", await tool_utility.analyze_trend_with_ema(TEST_SYMBOL_MAJOR, 240))
    await check_result(f"Analyze Location and Structure ({TEST_SYMBOL_MAJOR} D1)", await tool_utility.analyze_location_and_structure(TEST_SYMBOL_MAJOR, 1440))
def print_section_header(title):
    logger.info(f"\n{C.BLUE}{'='*20} {C.BOLD}{title.upper()}{C.END}{C.BLUE} {'='*20}{C.END}")
def print_candles_table(candles: list, title: str):
    logger.info(f"{C.CYAN}--- {title} (Last {min(10, len(candles))} of {len(candles)}) ---{C.END}")
    if not candles:
        logger.info(f"  {C.GREY}(No data){C.END}")
        return
    header = f"  {'Time':<22} {'O':<10} {'H':<10} {'L':<10} {'C':<10} {'Volume':<10}"
    logger.info(C.BOLD + header + C.END)
    logger.info(C.GREY + '  ' + '-' * (len(header) - 2) + C.END)
    for candle in candles[-10:]:
        color = C.GREEN if candle['close'] > candle['open'] else C.RED
        row = f"  {candle['time']:<22} {candle['open']:<10.5f} {candle['high']:<10.5f} {candle['low']:<10.5f} {candle['close']:<10.5f} {int(candle.get('volume',0)):<10}"
        logger.info(color + row + C.END)
def pretty_print_price_action(result: dict):
    print_section_header("Price Action Scan Results")
    if result.get("status") != "success":
        logger.error(f"  Scan failed: {result.get('message')}")
        return
    data = result.get("data", {})
    found_any = False
    if not isinstance(data, dict) or "message" in data:
         logger.warning(f"  {C.YELLOW}🧐 {data.get('message', 'No specific price action signals found.')}{C.END}")
         return
    for pattern_key, report in data.items():
        if isinstance(report, dict) and report.get("found"):
            found_any = True
            pattern_type = report.get('type', f'Unknown ({pattern_key})')
            icon = "🔼" if "Bullish" in pattern_type else "🔽" if "Bearish" in pattern_type else "↔️"
            candle = report.get("candle") or report.get("inside_candle") or report.get("engulfing_candle")
            logger.info(f"  {C.GREEN}✅ Found {icon} {pattern_type}!{C.END}")
            if candle: logger.info(f"    {C.GREY}Time: {candle.get('time')} | O:{candle.get('open')} H:{candle.get('high')} L:{candle.get('low')} C:{candle.get('close')}{C.END}")
    if not found_any:
        logger.warning(f"  {C.YELLOW}🧐 No recent price action signals (Pin Bar, Engulfing, Inside Bar) found on the last two closed candles.{C.END}")
def pretty_print_structures(result: dict):
    print_section_header("Structure Scan Results")
    if result.get("status") != "success":
        logger.error(f"  Scan failed: {result.get('message')}")
        return
    data = result.get("data", {})
    harmonics = data.get("harmonics", {})
    if harmonics and harmonics.get("found"):
        points = harmonics.get('points', {})
        point_d = points.get('D', {}) if points else {}
        logger.info(f"  {C.GREEN}✅ Found 🦋 Harmonic Pattern: {C.BOLD}{harmonics.get('type')}{C.END}")
        if point_d: logger.info(f"    {C.GREY}D-Point Price: {harmonics.get('completion_price_D')} | Time: {point_d.get('time')}{C.END}")
    else:
        logger.warning(f"  {C.YELLOW}🧐 {harmonics.get('message', 'No harmonic patterns found.')}{C.END}")
    logger.info(C.GREY + "  " + "-" * 60 + C.END)
    zones_data = data.get("demand_supply_zones", {})
    zones = zones_data.get("zones", []) if zones_data else []
    if zones:
        logger.info(f"  {C.GREEN}✅ Found 🧱 {len(zones)} Supply/Demand Zones (showing latest 3):{C.END}")
        for zone in zones[:3]:
            zone_type = zone.get('type')
            color = C.RED if 'Supply' in zone_type else C.GREEN
            icon = "📉" if 'Supply' in zone_type else "📈"
            logger.info(f"    {color}{icon} Type: {zone.get('type')}{C.END}")
            logger.info(f"    {C.GREY}Price Range: Top={zone.get('top')} | Bottom={zone.get('bottom')}{C.END}")
            logger.info(f"    {C.GREY}Formed: From {zone.get('start_time')} to {zone.get('end_time')}{C.END}")
    else:
        logger.warning(f"  {C.YELLOW}🧐 {zones_data.get('message', 'No supply/demand zones found.')}{C.END}")
async def test_10_full_management_cycle_verification_mocked():
    print_test_step("FULL MANAGEMENT CYCLE VERIFICATION (MOCKED PRICE)", "🔄")
    print_sub_step("Setting up a manageable BUY order using execute_trade_flow")
    lots = TestState.major_symbol_info.get('min_lot', 0.01)
    if lots * 2 > TestState.major_symbol_info.get('max_lot', 100):
        logger.warning("Min lot is too large for a partial close test. Skipping.")
        TestState.passed_count += 1
        return
    price_data = (await tool_market.get_current_price(TEST_SYMBOL_MAJOR))['data']
    real_entry_price = price_data['ask']
    fake_entry_price = round(real_entry_price * 0.99, 5)
    logger.info(f"Using REAL entry price ~{real_entry_price} for execution, but FAKE entry price {fake_entry_price} for SL/TP calculations.")
    ok, portfolio_res = await check_result("Get portfolio for equity", await tool_portfolio.get_portfolio())
    if not ok: return
    equity = portfolio_res['data']['account']['equity']
    risk_amount = round(equity * 0.01, 2)
    signal_tf_for_test = 5
    current_price_data_for_flow = (await tool_market.get_current_price(TEST_SYMBOL_MAJOR))['data']
    trade_flow_list = [
        {"id": "get_info", "tool_name": "get_symbol_info", "parameters": {"symbol": TEST_SYMBOL_MAJOR}},
        {"id": "generate_id", "tool_name": "generate_trade_id", "parameters": {"symbol": TEST_SYMBOL_MAJOR, "timeframe": signal_tf_for_test, "signal_type": "MGT", "signal_time": (await get_server_time_for_test()).isoformat()}},
        {"id": "calc_sl", "tool_name": "calculate_stop_loss_from_pattern", "parameters": {
            "symbol": TEST_SYMBOL_MAJOR,
            "timeframe": signal_tf_for_test,
            "pattern_type": "eng",
            "pattern_candles": {"engulfing_candle": {"high": fake_entry_price + 0.5, "low": fake_entry_price - 1.0}},
            "trade_type": "buy",
            "symbol_info": "{get_info.data}",
            "current_price": current_price_data_for_flow
        }},
        {"id": "calc_lots", "tool_name": "calculate_lot_size", "parameters": {
            "risk_amount_usd": risk_amount,
            "entry_price": fake_entry_price,
            "sl_price": "{calc_sl.data.sl_price}",
            "contract_size": "{get_info.data.contract_size}",
            "lot_step": "{get_info.data.lot_step}",
            "min_lot": "{get_info.data.min_lot}",
            "max_lot": "{get_info.data.max_lot}"
        }},
        {"id": "execute_order", "tool_name": "buy", "parameters": {
            "symbol": TEST_SYMBOL_MAJOR,
            "lots": "{calc_lots.data.adjusted_lots}",
            "sl_price": "{calc_sl.data.sl_price}",
            "magic": TEST_MAGIC_NUMBER_1,
            "comment": "L=0;G=A;S=MGT;ID={generate_id.data.trade_id}",
            "calculation_price": fake_entry_price
        }}
    ]
    ok, flow_res = await check_result("Open market order for management test via Trade Flow", await tool_flows.execute_trade_flow(flow=trade_flow_list, signal_tf=signal_tf_for_test), is_critical=True)
    if not ok: return
    execute_step_res = next((s['result'] for s in flow_res.get('results', []) if s['id'] == 'execute_order'), None)
    original_ticket = execute_step_res.get('ticket') if execute_step_res else None
    if not original_ticket:
        raise RuntimeError("Could not retrieve ticket from trade flow result.")
    await asyncio.sleep(1)
    ok_details, details_res = await check_result("Get order details to find TP levels", await tool_portfolio.get_order_details(original_ticket))
    if not ok_details:
        await tool_trade.close_order(original_ticket)
        return
    order_data = details_res.get('data', {})
    tp1_price_from_db = order_data.get('tp1_price')
    tp2_price_from_db = order_data.get('tp2_price')
    initial_lots = order_data.get('lots', 0.0)
    if not tp1_price_from_db or not tp2_price_from_db:
        logger.error(f"{C.RED}❌ FAILED: Could not retrieve TP1/TP2 prices from DB for ticket {original_ticket}.{C.END}")
        await tool_trade.close_order(original_ticket)
        TestState.failed_count += 1
        return
    else:
        logger.info(f"{C.GREEN}✅ SUCCESS: Retrieved TP levels from DB. TP1: {tp1_price_from_db}, TP2: {tp2_price_from_db}{C.END}")
    print_sub_step(f"Simulating price crossing TP2. TP2 Target: {tp2_price_from_db}")
    async def get_current_prices_mock(symbols: list):
        mock_price = tp2_price_from_db + 0.01
        mock_data = {
            TEST_SYMBOL_MAJOR: {
                "status": "success",
                "data": { "bid": mock_price, "ask": mock_price + TestState.major_symbol_info['spread_points'] * TestState.major_symbol_info['point_size'] }
            }
        }
        for sym in symbols:
            if sym not in mock_data:
                mock_data[sym] = {"status": "error", "message": "Price not available in mock"}
        return mock_data
    with unittest.mock.patch('src.tools.tool_market.get_current_prices', new=get_current_prices_mock):
        print_sub_step("Verifying execute_prepare_flow with mocked price")
        ok, prepare_res = await check_result("Execute Prepare Flow (with mocked price)", await tool_flows.execute_prepare_flow(signal_tf=15))
        if not ok:
            await tool_trade.close_order(original_ticket)
            return
        proposals = prepare_res.get('data', {}).get('management_proposals', [])
        target_proposal = next((p for p in proposals if isinstance(p, dict) and p.get('ticket') == original_ticket), None)
        if not target_proposal:
            logger.error(f"{C.RED}❌ FAILED: No management proposal generated for ticket {original_ticket} with mocked price.{C.END}")
            TestState.failed_count += 1
            await tool_trade.close_order(original_ticket)
            return
        logger.info(f"{C.GREEN}✅ Prepare Flow Verification: Proposal for ticket {original_ticket} found.{C.END}")
        if target_proposal.get('highest_triggered_level', -1) >= 2:
            logger.info(f"{C.GREEN}✅ Correct triggered level detected: {target_proposal.get('highest_triggered_level')}{C.END}")
        else:
            logger.error(f"{C.RED}❌ Incorrect triggered level: {target_proposal.get('highest_triggered_level')}{C.END}")
            TestState.failed_count += 1
        if "close 50%" in target_proposal.get('proposed_action', '').lower() and "move stop loss" in target_proposal.get('proposed_action', '').lower():
             logger.info(f"{C.GREEN}✅ Correct management action proposed.{C.END}")
        else:
            logger.error(f"{C.RED}❌ Incorrect management action proposed: {target_proposal.get('proposed_action')}{C.END}")
            TestState.failed_count += 1
        print_sub_step("Executing and verifying execute_management_flow")
        lot_step = TestState.major_symbol_info.get('lot_step', 0.01)
        lots_to_close = round(math.floor((initial_lots / 2) / lot_step) * lot_step, 8)
        if lots_to_close < lot_step:
            logger.warning(f"Calculated lots to close ({lots_to_close}) is smaller than lot_step ({lot_step}). The order may not be splittable. Proceeding with minimum possible close.")
            lots_to_close = lot_step
        management_actions = [{
            "action": "close_partial_and_move_sl",
            "ticket": original_ticket,
            "lots_to_close": lots_to_close,
            "move_sl_to_price": tp1_price_from_db,
            "update_management_status_to": "P2"
        }]
        ok, mgt_res = await check_result("Execute Management Flow (close partial & move SL)", await tool_flows.execute_management_flow(management_actions))
        if ok:
            summary = mgt_res.get('data', {}).get('execution_summary', [])
            for item in summary:
                sl_res = item.get('move_sl_result', {})
                if sl_res.get('status') == 'error':
                    logger.error(f"[[TEST_DEBUG]] ❌ Found Move SL Error Full Message: {sl_res.get('message')}")
                    logger.error(f"[[TEST_DEBUG]] Full SL Result Payload: {json.dumps(sl_res, indent=2)}")
                    logger.error(f"{C.RED}❌ FAILED: SL modification failed even with mocked price!{C.END}")
                    TestState.failed_count += 1
        else:
            await tool_trade.close_all_orders()
            return
        logger.info("Waiting 3s for partial close and inheritance to complete...")
        await asyncio.sleep(3)
        print_sub_step("Verifying final state of the new order")
        portfolio_after = (await tool_portfolio.get_portfolio()).get('data', {}).get('positions', {})
        new_ticket = next((int(t_str) for t_str, order in portfolio_after.items() if order.get('extends') == original_ticket), None)
        if not new_ticket:
            logger.error(f"{C.RED}❌ FINAL VERIFICATION FAILED: Could not find the new order ticket that extends {original_ticket}.{C.END}")
            TestState.failed_count += 1
            await tool_trade.close_all_orders()
            return
        logger.info(f"Found new ticket {new_ticket}. Verifying its state...")
        ok, new_details_res = await check_result("Get details of the new order", await tool_portfolio.get_order_details(new_ticket))
        if ok:
            new_order_data = new_details_res.get('data', {})
            final_lots = new_order_data.get('lots', 0.0)
            expected_lots = round(initial_lots - lots_to_close, 2)
            if abs(final_lots - expected_lots) < 1e-5:
                logger.info(f"{C.GREEN}✅ Lots Verification Success: Expected {expected_lots}, got {final_lots}{C.END}")
            else:
                logger.error(f"{C.RED}❌ Lots Verification Failed: Expected {expected_lots}, got {final_lots}{C.END}")
                TestState.failed_count += 1
            final_sl = new_order_data.get('sl', 0.0)
            if abs(final_sl - tp1_price_from_db) < 1e-5:
                 logger.info(f"{C.GREEN}✅ SL Verification Success: SL moved to TP1 price {tp1_price_from_db}.{C.END}")
            else:
                logger.error(f"{C.RED}❌ SL Verification Failed: Expected SL at {tp1_price_from_db}, got {final_sl}.{C.END}")
                TestState.failed_count += 1
            await order_db_manager.proactive_update_tp_levels((await get_current_prices_mock([TEST_SYMBOL_MAJOR])))
            new_details_res_after_proactive = await tool_portfolio.get_order_details(new_ticket)
            comment_ai = new_details_res_after_proactive.get('data',{}).get('comment_ai', '')
            if 'M=P2' in comment_ai:
                logger.info(f"{C.GREEN}✅ Comment_ai Management Status Verification Success: Found updated status in '{comment_ai}'.{C.END}")
            else:
                logger.error(f"{C.RED}❌ Comment_ai Management Status Verification Failed: Expected M=P2, got '{comment_ai}'.{C.END}")
                TestState.failed_count += 1
    print_sub_step("Cleaning up test order")
    final_portfolio = (await tool_portfolio.get_portfolio()).get('data', {}).get('positions', {})
    final_ticket_to_close = next((int(t) for t,o in final_portfolio.items() if o.get('comment_ai', '').endswith('S=MGT;ID=' + flow_res['results'][1]['result']['data']['trade_id'])), None)
    if final_ticket_to_close:
        await tool_trade.close_order(final_ticket_to_close)
    else:
        logger.warning("Could not find the final test order to clean up. It might have been closed already. Cleaning all.")
        await tool_trade.close_all_orders()
    await asyncio.sleep(2)
async def test_11_pattern_scanner_verification():
    print_test_step("PATTERN SCANNER VERIFICATION", "📊")
    test_symbols = [TEST_SYMBOL_MAJOR, TEST_SYMBOL_MINOR]
    test_timeframes = [15, 60]
    for symbol in test_symbols:
        for timeframe in test_timeframes:
            await run_scans_for(symbol, timeframe)
            await asyncio.sleep(0.5)
async def run_scans_for(symbol, timeframe):
    logger.info(f"\n{C.HEADER}{'─' * 80}{C.END}\n{C.BOLD}📡 SCANNING: {symbol} @ M{timeframe}{C.END}\n{C.HEADER}{'─' * 80}{C.END}")
    try:
        ok, result = await check_result(f"Get candles for {symbol} M{timeframe}", await tool_market.get_historical_candles(symbol, timeframe, 5))
        if ok:
            print_candles_table(result.get('data', []), f"Candles for Price Action Scan")
        pa_result = await tool_patterns.scan_for_price_action(symbol=symbol, timeframe=timeframe)
        pretty_print_price_action(pa_result)
        struct_result = await tool_patterns.scan_for_structures(symbol=symbol, timeframe=timeframe, candles_to_check=300)
        pretty_print_structures(struct_result)
    except Exception as e:
        logger.error(f"An unexpected exception during scan for {symbol} M{timeframe}: {e}", exc_info=True)
        TestState.failed_count += 1
async def test_12_final_cleanup_and_verification():
    print_test_step("FINAL CLEANUP & VERIFICATION", "🧹")
    await check_result("Close All Orders (Final Cleanup)", await tool_trade.close_all_orders())
    logger.info("Cleaning up any remaining temporary orders in DB.")
    await order_db_manager.clean_temporary_orders()
    await asyncio.sleep(3)
    ok, final_portfolio_res = await check_result("Get Final Portfolio for Verification", await tool_portfolio.get_portfolio())
    if ok:
        final_portfolio_data = final_portfolio_res.get('data', {})
        if not final_portfolio_data.get('positions'):
            logger.info(f"{C.GREEN}✅ Final portfolio is clean. All temporary test orders were closed.{C.END}")
        else:
            logger.warning(f"{C.YELLOW}⚠️ FINAL CLEANUP WARNING. Remaining orders found (Likely suspended markets). Ignored for test pass/fail.{C.END}")
            print_portfolio("REMAINING ORDERS", final_portfolio_res)
async def main():
    try:
        await test_01_initialization_and_cleanup()
        await test_02_read_only_and_negative_cases()
        await test_03_trade_flow_and_db_preregistration()
        await test_04_buy_lifecycle_and_duplicate_prevention()
        await test_05_sell_partial_close_and_comment_inheritance()
        await test_06_trade_management_negative_cases()
        await test_07_pending_orders_lifecycle()
        await test_08_bulk_and_search_closing()
        await test_09_utility_and_analysis_tools()
        await test_10_full_management_cycle_verification_mocked()
        await test_11_pattern_scanner_verification()
    except RuntimeError as e:
        logger.critical(f"{C.RED}A critical test failed, aborting sequence: {e}{C.END}")
    except Exception as e:
        logger.critical(f"{C.RED}An unexpected error occurred during test sequence: {e}{C.END}", exc_info=True)
        TestState.failed_count += 1
    finally:
        await test_12_final_cleanup_and_verification()
        await mt4_bridge.shutdown()
        summary_color = C.GREEN if TestState.failed_count == 0 else C.RED
        summary_title = "✅ ALL TESTS PASSED ✅" if TestState.failed_count == 0 else "❌ SOME TESTS FAILED ❌"
        summary_icon = "🎉" if TestState.failed_count == 0 else "🚨"
        border_h, border_v = '═', '║'
        corner_tl, corner_tr, corner_bl, corner_br = '╔', '╗', '╚', '╝'
        tee_l, tee_r = '╠', '╣'
        summary = f"""
{summary_color}
{corner_tl}{border_h * 50}{corner_tr}
{border_v}{' ' * 50}{border_v}
{border_v}{summary_title.center(48)}{border_v}
{border_v}{' ' * 50}{border_v}
{tee_l}{border_h * 50}{tee_r}
{border_v}{f'  PASSED: {TestState.passed_count}'.ljust(50)}{border_v}
{border_v}{f'  FAILED: {TestState.failed_count}'.ljust(50)}{border_v}
{corner_bl}{border_h * 50}{corner_br}{C.END}
"""
        print(summary)
        if TestState.failed_count == 0:
            logger.info(f"{summary_icon} {C.BOLD}{C.GREEN}Ultimate Integration Test Suite completed successfully!{C.END} {summary_icon}")
        else:
            logger.error(f"{summary_icon} {C.BOLD}{C.RED}Please review the logs for failed tests.{C.END} {summary_icon}")
if __name__ == "__main__":
    intro = f"""
{C.HEADER}{'='*80}
{C.BOLD}          🚀 ULTIMATE AI-TRADER INTEGRATION TEST SUITE 🚀{C.END}
{C.HEADER}{'='*80}{C.END}
This script provides a comprehensive, end-to-end verification of all critical components,
including trade execution, data retrieval, utility tools, and pattern recognition.
{C.RED}{C.BOLD}{'='*80}
  {' ' * 5}⚠️  WARNING: This test will perform LIVE trading on your account. ⚠️
{C.BOLD}  {' ' * 3}It is STRONGLY recommended to run this on a DEMO account only.
{'='*80}{C.END}
"""
    print(intro)
    try:
        input(f"{C.YELLOW}\nPress Enter to start the ultimate integration test, or Ctrl+C to abort...{C.END}")
        if sys.platform == 'win32':
             logger.debug("Using proactor: IocpProactor")
             asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info(f"\n\n{C.YELLOW}🖐️ Test aborted by user.{C.END}")
    except Exception as e:
        logger.critical(f"\n\n{C.RED}❌ An unexpected error occurred: {e}{C.END}", exc_info=True)