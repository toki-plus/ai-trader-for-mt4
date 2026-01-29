import logging
from .tool_market import get_symbol_info
from ..bridge.mt4_bridge import mt4_bridge
from ..services.order_db_manager import order_db_manager
logger = logging.getLogger(__name__)
async def get_portfolio() -> dict:
    logger.debug("get_portfolio called.")
    try:
        client = mt4_bridge.get_client()
        enhanced_positions = order_db_manager.get_enhanced_portfolio()
        return {
            "status": "success",
            "data": {
                "account": client.account_info,
                "positions": enhanced_positions
            }
        }
    except Exception as e:
        error_message = f"An unexpected system error occurred in get_portfolio: {e}"
        logger.error(error_message, exc_info=True)
        return {"status": "error", "message": error_message}
async def get_order_details(ticket: int) -> dict:
    logger.debug(f"[TOOL_CALL] get_order_details requested for ticket: {ticket}")
    try:
        order_dict = order_db_manager.get_order_details(ticket)
        if order_dict:
            logger.debug(f"[TOOL_DEBUG] Order found. Status: {order_dict.get('status', 'N/A')}, Close Time: {order_dict.get('close_time')}")
        else:
            logger.debug(f"[TOOL_DEBUG] Order {ticket} returned None from DB Manager.")
        if order_dict:
            logger.debug(f"Found details for ticket {ticket} from OrderDB.")
            return {"status": "success", "data": order_dict}
        else:
            logger.warning(f"Order with ticket {ticket} not found in OrderDB.")
            return {"status": "error", "message": f"Order with ticket {ticket} not found in open or recent historic orders."}
    except Exception as e:
        logger.error(f"An unexpected system error in get_order_details for ticket {ticket}: {e}", exc_info=True)
        return {"status": "error", "message": f"An unexpected system error occurred in get_order_details: {e}"}
async def find_orders(symbol: str, side: str = None, magic: int = None, ticket: int = None) -> dict:
    logger.debug(f"find_orders called for symbol: {symbol}, side: {side}, magic: {magic}, ticket: {ticket}")
    try:
        all_enhanced_orders = order_db_manager.get_enhanced_portfolio().values()
        filtered_orders = [
            o for o in all_enhanced_orders
            if (symbol is None or o.get('symbol') == symbol) and
               (side is None or (o.get('type', '') and o.get('type', '').lower().startswith(side.lower()))) and
               (magic is None or o.get('magic') == magic) and
               (ticket is None or o.get('ticket') == ticket)
        ]
        logger.debug(f"Found {len(filtered_orders)} orders matching criteria for {symbol}/{side}/{magic} from OrderDB.")
        return {"status": "success", "data": filtered_orders}
    except Exception as e:
        logger.error(f"An unexpected system error in find_orders for symbol {symbol}: {e}", exc_info=True)
        return {"status": "error", "message": f"An unexpected system error occurred in find_orders: {e}"}
async def get_historic_trades(lookback_days: int = 90) -> dict:
    try:
        client = mt4_bridge.get_client()
        return await client.get_historic_trades(lookback_days)
    except Exception as e:
        logger.error("An unexpected system error in get_historic_trades: %s", e, exc_info=True)
        return {"status": "error", "message": f"An unexpected system error occurred in get_historic_trades: {e}"}
async def calculate_portfolio_risk(tickets_to_exclude: list[int] = None) -> dict:
    logger.debug("calculate_portfolio_risk called.")
    try:
        portfolio_resp = await get_portfolio()
        if portfolio_resp.get("status") != "success":
            return portfolio_resp
        account_info = portfolio_resp.get("data", {}).get("account", {})
        positions = portfolio_resp.get("data", {}).get("positions", {})
        equity = account_info.get("equity", 0.0)
        if equity <= 0:
            return {"status": "error", "message": "Account equity is zero or negative."}
        all_positions_count = len(positions)
        market_positions = {k: v for k, v in positions.items() if v.get("type") and ('buy' in v.get("type") or 'sell' in v.get("type")) and 'limit' not in v.get("type") and 'stop' not in v.get("type")}
        if not market_positions:
            return {"status": "success", "data": {"open_positions_count": all_positions_count, "open_market_positions_count": 0, "total_risk_usd": 0.0, "risk_percentage": 0.0, "equity": equity}}
        total_risk_usd = 0.0
        positions_with_risk = 0
        for ticket, order in market_positions.items():
            if tickets_to_exclude and int(ticket) in tickets_to_exclude:
                logger.debug(f"Excluding de-risked ticket {ticket} from portfolio risk calculation.")
                continue
            sl_price = order.get("sl", 0.0)
            if sl_price > 0:
                open_price = order.get("open_price")
                lots = order.get("lots")
                symbol = order.get("symbol")
                if not all([open_price, lots, symbol]):
                    logger.warning(f"Skipping risk calculation for ticket {ticket} due to incomplete data.")
                    continue
                symbol_info_resp = await get_symbol_info(symbol)
                if symbol_info_resp.get("status") != "success":
                    logger.warning(f"Could not get symbol info for {symbol} to calculate risk for ticket {ticket}.")
                    continue
                symbol_data = symbol_info_resp.get("data", {})
                if not symbol_data:
                    logger.warning(f"Symbol info data block is empty for {symbol}.")
                    continue
                contract_size = symbol_data.get("contract_size")
                if not contract_size:
                    logger.warning(f"Contract size not found for {symbol}.")
                    continue
                risk_per_unit = abs(open_price - sl_price)
                order_risk_usd = risk_per_unit * lots * contract_size
                total_risk_usd += order_risk_usd
                positions_with_risk += 1
        risk_percentage = (total_risk_usd / equity) * 100 if equity > 0 else 0
        return {
            "status": "success",
            "data": {
                "open_positions_count": all_positions_count,
                "open_market_positions_count": len(market_positions),
                "positions_with_risk_defined": positions_with_risk,
                "total_risk_usd": round(total_risk_usd, 2),
                "risk_percentage": round(risk_percentage, 2),
                "equity": round(equity, 2)
            }
        }
    except Exception as e:
        error_message = f"An unexpected system error occurred in calculate_portfolio_risk: {e}"
        logger.error(error_message, exc_info=True)
        return {"status": "error", "message": error_message}