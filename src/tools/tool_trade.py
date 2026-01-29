import logging
import asyncio
import re
from ..bridge.mt4_bridge import mt4_bridge
from ..services.order_db_manager import order_db_manager
from .tool_market import get_symbol_info, get_current_price
from .tool_portfolio import get_portfolio, get_order_details, find_orders
logger = logging.getLogger(__name__)
def _get_id_from_comment(comment: str) -> str | None:
    if not comment: return None
    match = re.search(r'ID=([a-f0-9]{8})', comment)
    return match.group(1) if match else None
async def _base_trade_execution(action: str, symbol: str, lots: float, sl_price: float, price: float = 0.0, *, tp_price: float = 0.0, magic: int = 12345, comment: str = "ai", **kwargs) -> dict:
    try:
        lots = float(lots)
        price = float(price)
        sl_price = float(sl_price)
        tp_price = float(tp_price)
        if magic: magic = int(magic)
        trade_id = _get_id_from_comment(comment)
        if trade_id:
            logger.debug(f"Checking for duplicate trade ID: {trade_id}")
            portfolio = order_db_manager.get_enhanced_portfolio()
            for ticket, order in portfolio.items():
                if int(ticket) > 0 and order.get('comment') and trade_id in order.get('comment'):
                    existing_sl = order.get('sl', 0.0)
                    logger.info(f"Duplicate trade detected for ID {trade_id}. Returning existing ticket {ticket}.")
                    return {
                        "status": "success",
                        "action": action,
                        "ticket": int(ticket),
                        "message": f"Order already exists with ID {trade_id}. Ticket: {ticket}",
                        "duplicate": True
                    }
        if action == "buy":
            price_info_resp = await get_current_price(symbol)
            if price_info_resp.get('status') != 'success':
                return {"status": "error", "action": action, "message": f"Pre-check failed: Could not get current price. {price_info_resp.get('message')}"}
            if sl_price > 0 and sl_price >= price_info_resp['data']['bid']:
                return {"status": "error", "action": action, "message": f"Pre-check failed: Invalid SL for BUY. SL {sl_price} must be < current Bid {price_info_resp['data']['bid']}."}
        elif action == "sell":
            price_info_resp = await get_current_price(symbol)
            if price_info_resp.get('status') != 'success':
                return {"status": "error", "action": action, "message": f"Pre-check failed: Could not get current price. {price_info_resp.get('message')}"}
            if sl_price > 0 and sl_price <= price_info_resp['data']['ask']:
                return {"status": "error", "action": action, "message": f"Pre-check failed: Invalid SL for SELL. SL {sl_price} must be > current Ask {price_info_resp['data']['ask']}."}
        client = mt4_bridge.get_client()
        return await client.trade(action, symbol, lots, price, sl_price, tp_price, magic=magic, comment=comment)
    except Exception as e:
        logger.error(f"An unexpected system error in {action}: {e}", exc_info=True)
        return {"status": "error", "action": action, "message": f"An unexpected system error occurred: {e}"}
async def buy(symbol: str, lots: float, sl_price: float, *, tp_price: float = 0.0, magic: int = 12345, comment: str = "ai") -> dict:
    return await _base_trade_execution("buy", symbol, lots, sl_price, tp_price=tp_price, magic=magic, comment=comment)
async def sell(symbol: str, lots: float, sl_price: float, *, tp_price: float = 0.0, magic: int = 12345, comment: str = "ai") -> dict:
    return await _base_trade_execution("sell", symbol, lots, sl_price, tp_price=tp_price, magic=magic, comment=comment)
async def buylimit(symbol: str, lots: float, price: float, sl_price: float, *, tp_price: float = 0.0, magic: int = 12345, comment: str = "ai") -> dict:
    return await _base_trade_execution("buylimit", symbol, lots, sl_price, price=price, tp_price=tp_price, magic=magic, comment=comment)
async def selllimit(symbol: str, lots: float, price: float, sl_price: float, *, tp_price: float = 0.0, magic: int = 12345, comment: str = "ai") -> dict:
    return await _base_trade_execution("selllimit", symbol, lots, sl_price, price=price, tp_price=tp_price, magic=magic, comment=comment)
async def modify_order_sl_tp(ticket: int, *, new_price: float = 0.0, new_sl_price: float = 0.0, new_tp_price: float = 0.0) -> dict:
    try:
        client = mt4_bridge.get_client()
        return await client.modify_order(ticket, price=new_price, sl=new_sl_price, tp=new_tp_price)
    except Exception as e:
        logger.error("An unexpected error in modify_order_sl_tp: %s", e, exc_info=True)
        return {"status": "error", "action": "modify_order", "message": f"An unexpected error occurred while modifying order: {e}"}
async def close_order(ticket: int, lots: float = 0.0) -> dict:
    try:
        client = mt4_bridge.get_client()
        return await client.close_order(ticket, lots)
    except Exception as e:
        logger.error("An unexpected error in close_order: %s", e, exc_info=True)
        return {"status": "error", "action": "close_order", "message": f"An unexpected error occurred while closing order: {e}"}
async def move_sl_to_breakeven(ticket: int, add_pips: int = 2) -> dict:
    try:
        order_details_response = await get_order_details(ticket)
        if order_details_response.get("status") != "success":
            return {"status": "error", "action": "move_sl_to_breakeven", "message": f"Could not get details for order {ticket}: {order_details_response.get('message')}"}
        order_data = order_details_response["data"]
        order_data = {k.lower(): v for k,v in order_data.items()}
        open_price, order_type, symbol = order_data.get("open_price"), order_data.get("type"), order_data.get("symbol")
        if not all([open_price, order_type, symbol]): return {"status": "error", "action": "move_sl_to_breakeven", "message": "Order data is incomplete."}
        symbol_info_response = await get_symbol_info(symbol)
        if symbol_info_response.get("status") != "success": return {"status": "error", "action": "move_sl_to_breakeven", "message": f"Could not get symbol info for {symbol}."}
        pip_size = symbol_info_response["data"].get("pip_size", 1e-4)
        price_offset = add_pips * pip_size
        new_sl_price = 0.0
        if 'buy' in order_type.lower(): new_sl_price = open_price + price_offset
        elif 'sell' in order_type.lower(): new_sl_price = open_price - price_offset
        else: return {"status": "error", "action": "move_sl_to_breakeven", "message": f"Order type '{order_type}' is not a market position."}
        current_price_response = await get_current_price(symbol)
        if current_price_response.get("status") != "success": return {"status": "error", "action": "move_sl_to_breakeven", "message": f"Could not get current price for {symbol} to validate stop level."}
        current_price_data = current_price_response["data"]
        if ('buy' in order_type.lower() and new_sl_price >= current_price_data['bid']) or \
           ('sell' in order_type.lower() and new_sl_price <= current_price_data['ask']):
            return {"status": "warning", "action": "move_sl_to_breakeven", "message": f"Skipping SL move for {ticket}. Breakeven SL is too close to market."}
        logger.info("Moving SL for ticket %d to breakeven. New SL: %f", ticket, new_sl_price)
        return await modify_order_sl_tp(ticket=ticket, new_sl_price=new_sl_price)
    except Exception as e:
        logger.error("An unexpected system error in move_sl_to_breakeven: %s", e, exc_info=True)
        return {"status": "error", "action": "move_sl_to_breakeven", "message": f"An unexpected error occurred: {e}"}
async def close_partial_order(ticket: int, lots_to_close: float) -> dict:
    return await close_order(ticket, lots_to_close)
async def _wait_for_bulk_close(action_name: str, check_condition, timeout=15.0):
    start_time = asyncio.get_event_loop().time()
    logger.info(f"[{action_name}] Starting verification loop (timeout: {timeout}s)...")
    try:
        while asyncio.get_event_loop().time() - start_time < timeout:
            remaining_orders = await check_condition()
            if not remaining_orders:
                logger.info(f"[{action_name}] ✅ Verification successful. No matching orders found.")
                return True
            tickets_remaining = ", ".join(map(str, remaining_orders.keys())) if isinstance(remaining_orders, dict) else ", ".join(str(o.get('ticket', 'N/A')) for o in remaining_orders)
            logger.debug(f"[{action_name}] Verification pending... {len(remaining_orders)} orders still exist. Tickets: [{tickets_remaining}]. Retrying in 1s...")
            await asyncio.sleep(0.2)
    except Exception as e:
        logger.error(f"[{action_name}] Exception during verification loop: {e}", exc_info=True)
    logger.warning(f"[{action_name}] ⚠️ Verification timed out after {timeout}s.")
    return False
async def _handle_bulk_close(action_name: str, check_condition, close_function):
    try:
        initial_orders = await check_condition()
        if not initial_orders:
            return {"status": "success", "action": action_name, "message": "No matching orders to close."}
        initial_tickets = ", ".join(map(str, initial_orders.keys())) if isinstance(initial_orders, dict) else ", ".join(str(o.get('ticket', 'N/A')) for o in initial_orders)
        logger.info(f"[{action_name}] Found {len(initial_orders)} orders to close. Tickets: [{initial_tickets}]")
        await close_function()
        if await _wait_for_bulk_close(action_name, check_condition):
            return {"status": "success", "action": action_name, "message": "All specified orders have been closed."}
        final_check_orders = await check_condition()
        if not final_check_orders:
             return {"status": "success", "action": action_name, "message": "All specified orders confirmed closed after final check."}
        else:
            failed_tickets = ", ".join(map(str, final_check_orders.keys())) if isinstance(final_check_orders, dict) else ", ".join(str(o.get('ticket', 'N/A')) for o in final_check_orders)
            error_message = f"Failed to close {len(final_check_orders)} order(s) within the timeout. Remaining tickets: [{failed_tickets}]"
            logger.warning(f"[{action_name}] ⚠️ {error_message}")
            return {"status": "warning", "action": action_name, "message": error_message}
    except Exception as e:
        logger.error(f"An unexpected system error in {action_name}: %s", e, exc_info=True)
        return {"status": "error", "action": action_name, "message": f"An unexpected system error occurred: {e}"}
async def close_all_orders() -> dict:
    client = mt4_bridge.get_client()
    async def check():
        portfolio_resp = await get_portfolio()
        return portfolio_resp.get("data", {}).get("positions", {})
    return await _handle_bulk_close("close_all_orders", check, client.close_all_orders)
async def close_orders_by_symbol(symbol: str) -> dict:
    client = mt4_bridge.get_client()
    async def check():
        find_resp = await find_orders(symbol=symbol)
        return find_resp.get("data", [])
    return await _handle_bulk_close("close_orders_by_symbol", check, lambda: client.close_orders_by_symbol(symbol))
async def close_orders_by_magic(magic: int) -> dict:
    client = mt4_bridge.get_client()
    async def check():
        portfolio_resp = await get_portfolio()
        return [order for order in portfolio_resp.get("data", {}).get("positions", {}).values() if order.get('magic') == magic]
    return await _handle_bulk_close("close_orders_by_magic", check, lambda: client.close_orders_by_magic(magic))