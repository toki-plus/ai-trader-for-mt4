import re
import json
import logging
import asyncio
from datetime import datetime
from typing import List, Dict, Any, Optional
from . import tool_market
from . import tool_portfolio
from . import tool_utility
from . import tool_patterns
from ..services.order_db_manager import order_db_manager
logger = logging.getLogger(__name__)
async def _resolve_placeholders(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    resolved_params = {}
    for key, value in params.items():
        if isinstance(value, str):
            matches = re.findall(r'\{([a-zA-Z0-9_.]+)\}', value)
            if not matches:
                resolved_params[key] = value
                continue
            if len(matches) == 1 and f"{{{matches[0]}}}" == value:
                path = matches[0]
                try:
                    parts = path.split('.')
                    current_val = context[parts[0]]
                    for part in parts[1:]:
                        if isinstance(current_val, dict):
                            current_val = current_val.get(part)
                        elif isinstance(current_val, list) and part.isdigit():
                            current_val = current_val[int(part)]
                        else:
                            raise KeyError(f"Invalid part '{part}' in path '{path}'.")
                    resolved_params[key] = current_val
                except (KeyError, TypeError, IndexError) as e:
                    raise ValueError(f"Could not resolve placeholder '{value}'. Error: {e}")
            else:
                def repl(m):
                    path = m.group(1)
                    try:
                        parts = path.split('.')
                        current_val = context[parts[0]]
                        for part in parts[1:]:
                            if isinstance(current_val, dict):
                                current_val = current_val.get(part)
                            elif isinstance(current_val, list) and part.isdigit():
                                current_val = current_val[int(part)]
                            else:
                                raise KeyError(f"Invalid part '{part}'.")
                        return str(current_val)
                    except Exception as e:
                        raise ValueError(f"Failed to resolve embedded placeholder '{{{path}}}'. Error: {e}")
                resolved_string = re.sub(r'\{([a-zA-Z0-9_.]+)\}', repl, value)
                resolved_params[key] = resolved_string
        else:
            resolved_params[key] = value
    return resolved_params
async def execute_trade_flow(flow: List[Dict], signal_tf: int) -> Dict[str, Any]:
    logger.debug(f"Executing trade flow with {len(flow)} steps for signal_tf={signal_tf}.")
    context = {}
    results_trace = []
    temp_db_id = None
    failed_step_info = {}
    if not isinstance(flow, list) or not all(isinstance(i, dict) for i in flow):
        return {"status": "error", "message": "Invalid flow format. 'flow' must be a list of dictionaries."}
    try:
        current_tool_registry = tool_registry
        for step in flow:
            step_id = step.get("id")
            tool_name = step.get("tool_name")
            params = step.get("parameters", {})
            if not all([step_id, tool_name]):
                raise ValueError(f"Invalid step format in flow: {step}. 'id' and 'tool_name' are required.")
            failed_step_info = {"step_id": step_id, "tool_name": tool_name, "raw_params": params}
            resolved_params = await _resolve_placeholders(params, context)
            failed_step_info["resolved_params"] = resolved_params
            trade_tool_names = {'buy', 'sell', 'buylimit', 'selllimit'}
            if tool_name in trade_tool_names:
                trade_type = 'buy' if 'buy' in tool_name else 'sell'
                calculation_price = resolved_params.get('calculation_price')
                if calculation_price:
                    entry_price_for_calc = float(calculation_price)
                    logger.warning(f"Using provided 'calculation_price' ({calculation_price}) for pre-trade calculations.")
                elif tool_name in {'buy', 'sell'}:
                    price_resp = await tool_market.get_current_price(resolved_params['symbol'])
                    if price_resp.get('status') == 'success':
                        entry_price_for_calc = price_resp['data']['ask'] if trade_type == 'buy' else price_resp['data']['bid']
                    else:
                        raise ValueError("Could not fetch current price for market order pre-calculation.")
                else:
                    entry_price_for_calc = resolved_params.get('price', 0.0)
                if entry_price_for_calc > 0:
                    comment = resolved_params.get('comment', '')
                    initial_rr_ratio = 1.0
                    ladder_resp = await tool_utility.calculate_ladder_prices_pre_trade(
                        open_price=entry_price_for_calc,
                        sl_price=resolved_params.get('sl_price', 0.0),
                        trade_type=trade_type,
                        symbol=resolved_params.get('symbol'),
                        comment=comment,
                        initial_rr_ratio=initial_rr_ratio
                    )
                    if ladder_resp.get('status') == 'success':
                        ladder_prices = ladder_resp.get('data', {}).get('ladder')
                    else:
                        ladder_prices = None
                        logger.warning(f"Could not pre-calculate ladder prices: {ladder_resp.get('message')}")
                pre_reg_data = {
                    **resolved_params,
                    'type': tool_name,
                    'open_price': entry_price_for_calc,
                    'ladder_prices': ladder_prices
                }
                temp_db_id = await order_db_manager.add_new_order_with_calculations(pre_reg_data, signal_tf=signal_tf)
                if not isinstance(temp_db_id, int):
                    raise ValueError(f"Failed to pre-register order in DB: {temp_db_id}")
            tool_func = current_tool_registry.get_tool(tool_name)
            final_resolved_params = resolved_params.copy()
            final_resolved_params.pop('calculation_price', None)
            result = await tool_func(**final_resolved_params)
            context[step_id] = result
            if tool_name in {'buy', 'sell', 'buylimit', 'selllimit'}:
                try:
                    t = result.get("ticket") if isinstance(result, dict) else None
                    logger.debug(
                        "[TRADE_FLOW_DEBUG] trade step=%s tool=%s returned ticket=%r (type=%s) full_result_keys=%s",
                        step_id, tool_name, t, type(t).__name__,
                        list(result.keys()) if isinstance(result, dict) else None
                    )
                except Exception:
                    logger.exception("[TRADE_FLOW_DEBUG] Failed to log trade ticket")
            results_trace.append({"id": step_id, "tool_name": tool_name, "parameters": resolved_params, "result": result})
            if isinstance(result, dict) and result.get("status") == "error":
                raise ValueError(f"Flow failed at step '{step_id}': {result.get('message', 'Unknown error')}")
        logger.info("Trade flow executed successfully.")
        return {"status": "success", "results": results_trace, "final_context": context}
    except Exception as e:
        error_message = f"Flow execution failed at step '{failed_step_info.get('step_id', 'Unknown')}'. Reason: {e}"
        logger.warning(error_message, exc_info=True)
        trade_id_match = re.search(r"ID=([a-f0-9]{8})", str(failed_step_info.get('resolved_params', '')))
        if "timeout" in str(e).lower() and trade_id_match:
            trade_id = trade_id_match.group(1)
            logger.info(f"Trade execution timed out. Performing final verification for trade ID: {trade_id}")
            await asyncio.sleep(2)
            from . import tool_portfolio
            portfolio_resp = await tool_portfolio.get_portfolio()
            positions = portfolio_resp.get("data", {}).get("positions", {})
            for ticket, order in positions.items():
                if order.get('comment') and trade_id in order.get('comment'):
                    logger.info(f"VERIFICATION SUCCESS: Order {ticket} with trade ID {trade_id} was found in portfolio despite timeout.")
                    successful_result = {
                        "status": "success",
                        "action": failed_step_info.get('tool_name'),
                        "ticket": int(ticket),
                        "message": f"Order placement confirmed via portfolio check after initial timeout. Ticket: {ticket}",
                    }
                    context[failed_step_info.get('step_id')] = successful_result
                    results_trace.append({"id": failed_step_info.get('step_id'), "tool_name": failed_step_info.get('tool_name'), "parameters": failed_step_info.get('resolved_params'), "result": successful_result})
                    return {"status": "success", "results": results_trace, "final_context": context, "warning": "Initial trade execution timed out but was later confirmed."}
        logger.debug(
            f"Failure context: Step ID='{failed_step_info.get('step_id')}', Tool='{failed_step_info.get('tool_name')}', "
            f"Resolved Params='{failed_step_info.get('resolved_params', 'N/A')}'"
        )
        if temp_db_id:
            await order_db_manager.remove_pre_registered_order(temp_db_id)
        return {
            "status": "error",
            "message": error_message,
            "results": results_trace,
            "final_context": context,
        }
def _parse_mt4_time(time_str: Optional[str], fmt: str) -> Optional[datetime]:
    if not time_str or not isinstance(time_str, str):
        return None
    try:
        return datetime.strptime(time_str, fmt)
    except Exception:
        return None
async def _get_db_open_time_str_for_ticket(ticket: int) -> Optional[str]:
    try:
        details = order_db_manager.get_order_details(int(ticket))
        if isinstance(details, dict):
            ot = details.get("open_time")
            return ot if isinstance(ot, str) and ot.strip() else None
    except Exception:
        logger.debug(f"DB open_time lookup failed for ticket={ticket}", exc_info=True)
    return None
async def execute_prepare_flow(signal_tf: int) -> Dict[str, Any]:
    logger.debug("Executing prepare flow...")
    try:
        server_time_resp, portfolio_resp = await asyncio.gather(
            tool_market.get_server_time(),
            tool_portfolio.get_portfolio()
        )
        if server_time_resp.get("status") != "success":
            return server_time_resp
        if portfolio_resp.get("status") != "success":
            return portfolio_resp
        server_time_str = server_time_resp.get("data", {}).get("server_time")
        server_dt = _parse_mt4_time(server_time_str, '%Y.%m.%d %H:%M')
        if server_dt is None:
            return {"status": "error", "message": f"Invalid server_time format: {server_time_str}"}
        portfolio_data = portfolio_resp.get("data", {})
        positions = portfolio_data.get("positions", {})
        logger.debug(
            "[PREPARE_FLOW_DEBUG] positions type=%s size=%d sample_keys_types=%s",
            type(positions).__name__,
            len(positions) if isinstance(positions, dict) else -1,
            [(k, type(k).__name__) for k in list(positions.keys())[:5]] if isinstance(positions, dict) else None
        )
        stale_pending_orders = []
        management_proposals = []
        market_positions: Dict[int, Dict[str, Any]] = {}
        symbols_to_price = set()
        for ticket, order in positions.items():
            logger.debug(
                "[PREPARE_FLOW_DEBUG] iter position ticket=%r (type=%s) order_type=%r symbol=%r",
                ticket, type(ticket).__name__, (order.get("type") if isinstance(order, dict) else None),
                (order.get("symbol") if isinstance(order, dict) else None)
            )
            order_type = (order.get("type") or "").lower()
            if "limit" in order_type or "stop" in order_type:
                db_open_time_str = await _get_db_open_time_str_for_ticket(ticket)
                open_time_str = db_open_time_str or order.get("open_time")
                open_dt = _parse_mt4_time(open_time_str, '%Y.%m.%d %H:%M:%S')
                if open_dt is None:
                    open_dt = _parse_mt4_time(open_time_str, '%Y.%m.%d %H:%M')
                if open_dt is None:
                    logger.debug(f"Skipping stale check: unparseable open_time='{open_time_str}' ticket={ticket}")
                    continue
                age_minutes = (server_dt - open_dt).total_seconds() / 60.0
                if age_minutes > float(signal_tf):
                    stale_pending_orders.append({"ticket": int(ticket), "symbol": order.get("symbol"), "age_minutes": age_minutes})
            elif "buy" in order_type or "sell" in order_type:
                market_positions[ticket] = order
                if order.get("symbol"):
                    symbols_to_price.add(order.get("symbol"))
        prices_resp = await tool_market.get_current_prices(list(symbols_to_price))
        current_prices = {symbol: data['data'] for symbol, data in prices_resp.items() if data.get('status') == 'success'}
        logger.debug(f"[PREPARE_FLOW_DEBUG] Current Prices for Proposal Check: {current_prices}")
        def get_management_level_from_code(code: str) -> int:
            if not code or code == 'N': return 0
            num_part = re.search(r'\d+', code)
            return int(num_part.group(0)) if num_part else 0
        for ticket, order in market_positions.items():
            logger.debug(f"--- [PREPARE_FLOW_DEBUG] Analyzing Ticket: {ticket}, Order: {order} ---")
            symbol = order.get("symbol")
            current_price_data = current_prices.get(symbol)
            if not current_price_data:
                logger.debug(f"[PREPARE_FLOW_DEBUG] No current price data for symbol {symbol}, skipping ticket {ticket}.")
                continue
            ladder_resp = await tool_utility.calculate_profit_ladder_levels(ticket, initial_rr_ratio=1.0)
            if ladder_resp.get("status") != "success":
                logger.debug(f"[PREPARE_FLOW_DEBUG] Failed to calculate ladder for ticket {ticket}: {ladder_resp.get('message')}")
                continue
            ladder = ladder_resp.get("data", {}).get("ladder", {}) or {}
            comment = order.get("comment", "") or ""
            management_match = re.search(r'M=([A-Z0-9]+)', comment)
            management_status = management_match.group(1) if management_match else 'N'
            management_level = get_management_level_from_code(management_status)
            raw_type = (order.get("type") or "").lower()
            is_buy = "buy" in raw_type
            market_price = current_price_data['bid'] if is_buy else current_price_data['ask']
            logger.debug(f"[PREPARE_FLOW_DEBUG] Ticket={ticket}, Mgmt_Status='{management_status}'(lv.{management_level}), Market_Price={market_price}")
            highest_triggered_level = 0
            for i in range(8, 0, -1):
                level_key = f"tp{i}"
                level_data = ladder.get(level_key)
                if not level_data or level_data.get("price") is None: continue
                trigger_price = level_data["price"]
                condition_met = (is_buy and market_price >= trigger_price) or ((not is_buy) and market_price <= trigger_price)
                if condition_met:
                    highest_triggered_level = i
                    break
            if highest_triggered_level > management_level:
                action_level_key = f"tp{highest_triggered_level}"
                action_data = ladder.get(action_level_key, {})
                action_str = action_data.get("action")
                management_code = action_data.get("management_code")

                if action_str and "NO_ACTION" not in action_str and management_code:
                    proposal = {
                        "ticket": int(ticket),
                        "symbol": symbol,
                        "current_management_status": management_status,
                        "highest_triggered_level": highest_triggered_level,
                        "proposed_action": action_str,
                        "management_code_to_update": management_code,
                        "ladder": ladder
                    }
                    management_proposals.append(proposal)
                    logger.debug(f"[PROPOSAL_LOGIC] CREATED proposal for ticket {ticket}: Price hit TP{highest_triggered_level}, which is higher than current management level '{management_status}'.")
                else:
                    logger.debug(f"[PROPOSAL_LOGIC] Price hit TP{highest_triggered_level} but no valid action/code found. Action: {action_str}, Code: {management_code}")
            else:
                logger.debug(f"[PROPOSAL_LOGIC] No new proposal for ticket {ticket}. Highest triggered level ({highest_triggered_level}) not greater than management level ({management_level}).")
        de_risked_tickets = []
        for ticket, order in market_positions.items():
            comment = order.get("comment", "")
            if not comment:
                continue
            management_match = re.search(r'M=([A-Z0-9]+)', comment)
            if management_match:
                status_code = management_match.group(1)
                if status_code.startswith('P') or status_code.startswith('S'):
                    de_risked_tickets.append(int(ticket))
        if de_risked_tickets:
            logger.info(f"Identified {len(de_risked_tickets)} de-risked trades. These will be excluded from portfolio risk calculation. Trade IDs: {de_risked_tickets}")
        risk_resp = await tool_portfolio.calculate_portfolio_risk(tickets_to_exclude=de_risked_tickets)
        try:
            logger.debug("[PREPARE_FLOW_DEBUG] === FINAL REPORT DEBUG START ===")
            logger.debug("[PREPARE_FLOW_DEBUG] stale_pending_orders_to_delete count=%d", len(stale_pending_orders))
            logger.debug("[PREPARE_FLOW_DEBUG] management_proposals count=%d", len(management_proposals))
            for idx, p in enumerate(management_proposals[:10]):
                logger.debug(
                    "[PREPARE_FLOW_DEBUG] proposal[%d] keys=%s",
                    idx, list(p.keys()) if isinstance(p, dict) else type(p)
                )
                if isinstance(p, dict):
                    logger.debug(
                        "[PREPARE_FLOW_DEBUG] proposal[%d].ticket=%r (type=%s) symbol=%r current_status=%r highest_triggered_level=%r",
                        idx,
                        p.get("ticket"), type(p.get("ticket")).__name__,
                        p.get("symbol"),
                        p.get("current_management_status"),
                        p.get("highest_triggered_level"),
                    )
            logger.debug("[PREPARE_FLOW_DEBUG] === FINAL REPORT DEBUG END ===")
        except Exception:
            logger.exception("[PREPARE_FLOW_DEBUG] Failed while dumping final report debug")
        return {
            "status": "success",
            "data": {
                "server_time_utc": server_dt.isoformat(),
                "portfolio_snapshot": portfolio_data,
                "stale_pending_orders_to_delete": stale_pending_orders,
                "management_proposals": management_proposals,
                "portfolio_risk": risk_resp.get("data")
            }
        }
    except Exception as e:
        logger.error(f"Error in execute_prepare_flow: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}
async def execute_scan_flow(trading_symbols: List[str], signal_tf: int, trend_tf: int, location_tf: int) -> Dict[str, Any]:
    logger.debug(f"Executing scan flow for symbols: {', '.join(trading_symbols)}")
    semaphore = asyncio.Semaphore(3)
    async def scan_symbol(symbol):
        async with semaphore:
            try:
                activity_resp, pa_scan, struct_scan, trend_analysis, loc_analysis, price_resp, symbol_info_resp = await asyncio.gather(
                    tool_market.is_market_active(symbol, signal_tf),
                    tool_patterns.scan_for_price_action(symbol, signal_tf),
                    tool_patterns.scan_for_structures(symbol, signal_tf),
                    tool_utility.analyze_trend_with_ema(symbol, trend_tf),
                    tool_utility.analyze_location_and_structure(symbol, location_tf),
                    tool_market.get_current_price(symbol),
                    tool_market.get_symbol_info(symbol)
                )
                if not activity_resp.get("data", {}).get("active"):
                    return {"status": "inactive", "reason": activity_resp.get("data", {}).get("reason")}
                if symbol_info_resp.get("status") != "success" or price_resp.get("status") != "success":
                    return {"status": "error", "message": f"Could not get critical symbol/price info. SymbolInfo: {symbol_info_resp.get('message')}, Price: {price_resp.get('message')}"}
                spread_analysis_result = await tool_utility.calculate_spread_analysis(
                    symbol_info_resp.get("data"),
                    price_resp.get("data")
                )
                return {
                    "status": "success",
                    "price_action_signals": pa_scan.get("data"),
                    "structure_signals": struct_scan.get("data"),
                    "trend_context": trend_analysis.get("data"),
                    "location_context": loc_analysis.get("data"),
                    "current_price": price_resp.get("data"),
                    "symbol_info": symbol_info_resp.get("data"),
                    "spread_analysis": spread_analysis_result.get("data")
                }
            except Exception as e:
                logger.error(f"Error scanning symbol {symbol}: {e}", exc_info=True)
                return {"status": "error", "message": str(e)}
    tasks = [scan_symbol(s) for s in trading_symbols]
    results = await asyncio.gather(*tasks)
    final_report = dict(zip(trading_symbols, results))
    return {"status": "success", "data": final_report}
async def execute_management_flow(management_actions: List[Dict]) -> Dict[str, Any]:
    logger.info(f"Executing management flow with {len(management_actions)} actions.")
    if not isinstance(management_actions, list):
        return {"status": "error", "message": "Invalid input: `management_actions` must be a list of dictionaries."}
    reg = tool_registry
    close_order_tool = reg.get_tool('close_order')
    modify_order_tool = reg.get_tool('modify_order_sl_tp')
    close_partial_tool = reg.get_tool('close_partial_order')
    get_portfolio_tool = reg.get_tool('get_portfolio')
    results = []
    for action_item in management_actions:
        action = action_item.get("action")
        ticket = action_item.get("ticket")
        status_to_update = action_item.get("update_management_status_to")
        try:
            result = {}
            if action == "delete_stale":
                result = await close_order_tool(ticket)
            elif action == "move_sl":
                new_sl = action_item.get("new_sl_price")
                order_details_resp = await tool_portfolio.get_order_details(ticket)
                if order_details_resp.get('status') != 'success':
                    result = {"status": "error", "message": f"Failed to get order details for safety check: {order_details_resp.get('message')}"}
                else:
                    order_data = order_details_resp['data']
                    current_price_resp = await tool_market.get_current_price(order_data['symbol'])
                    if current_price_resp.get('status') != 'success':
                        result = {"status": "error", "message": f"Failed to get current price for safety check: {current_price_resp.get('message')}"}
                    else:
                        is_buy = 'buy' in order_data.get('type', '').lower()
                        current_bid = current_price_resp['data']['bid']
                        current_ask = current_price_resp['data']['ask']
                        if (is_buy and new_sl >= current_bid) or (not is_buy and new_sl <= current_ask):
                            result = {"status": "warning", "message": f"Skipping SL move for {ticket}. New SL {new_sl} is invalid relative to market price (Bid: {current_bid}, Ask: {current_ask})."}
                            logger.warning(result['message'])
                        else:
                            result = await modify_order_tool(ticket, new_sl_price=new_sl)
                            if result.get("status") == "success" and status_to_update:
                                await order_db_manager.update_management_status(ticket, status_to_update)
            elif action == "close_partial":
                lots = action_item.get("lots_to_close")
                result = await close_partial_tool(ticket, lots_to_close=lots)
                if result.get("status") == "success" and status_to_update:
                    new_ticket = result.get("new_ticket")
                    if new_ticket:
                        await order_db_manager.update_management_status(new_ticket, status_to_update)
                    else:
                        logger.warning(f"Partial close of {ticket} succeeded but no new ticket found. Cannot update management status.")
            elif action == "close_partial_and_move_sl":
                lots = action_item.get("lots_to_close")
                sl_price = action_item.get("move_sl_to_price")
                logger.info(f"Executing partial close on {ticket} (lots={lots}) then moving SL to {sl_price}")
                partial_res = await close_partial_tool(ticket, lots_to_close=lots)
                if partial_res.get("status") == "success":
                    new_ticket = partial_res.get("new_ticket")
                    if not new_ticket or str(new_ticket) == str(ticket):
                        logger.warning(f"⚠️ Partial close returned ticket {new_ticket} (same as old or None). Starting RECOVERY SCAN for successor of {ticket}...")
                        found_successor = False
                        for attempt in range(1, 6):
                            logger.debug(f"🔍 [Attempt {attempt}/5] Scanning portfolio for successor order...")
                            await asyncio.sleep(1.0)
                            portfolio_data = await get_portfolio_tool()
                            positions = portfolio_data.get("data", {}).get("positions", {}) if isinstance(portfolio_data, dict) and "data" in portfolio_data else portfolio_data.get("positions", {})
                            for pos_id, pos_data in positions.items():
                                if pos_data.get("extends") == ticket or (f"from #{ticket}" in pos_data.get("comment", "")):
                                    new_ticket = pos_id
                                    logger.info(f"✅ FOUND SUCCESSOR: New ticket is {new_ticket} (found via {'extends' if pos_data.get('extends') == ticket else 'comment'})")
                                    found_successor = True
                                    break
                            if found_successor: break
                        if not found_successor:
                            logger.error(f"❌ Failed to find successor order for {ticket} after 5 attempts. Using old ticket (will likely fail).")
                            new_ticket = ticket
                    logger.info(f"Proceeding to move SL for new ticket {new_ticket} to {sl_price}")
                    sl_res = {}
                    order_details_resp = await tool_portfolio.get_order_details(new_ticket)
                    if order_details_resp.get('status') != 'success':
                        sl_res = {"status": "error", "message": f"Failed to get new order {new_ticket} details for safety check: {order_details_resp.get('message')}"}
                    else:
                        order_data = order_details_resp['data']
                        current_price_resp = await tool_market.get_current_price(order_data['symbol'])
                        if current_price_resp.get('status') != 'success':
                            sl_res = {"status": "error", "message": f"Failed to get current price for safety check: {current_price_resp.get('message')}"}
                        else:
                            is_buy = 'buy' in order_data.get('type', '').lower()
                            current_bid = current_price_resp['data']['bid']
                            current_ask = current_price_resp['data']['ask']
                            if (is_buy and sl_price >= current_bid) or (not is_buy and sl_price <= current_ask):
                                sl_res = {"status": "warning", "message": f"Skipping SL move for {new_ticket}. New SL {sl_price} is invalid relative to market price (Bid: {current_bid}, Ask: {current_ask})."}
                                logger.warning(sl_res['message'])
                            else:
                                sl_res = await modify_order_tool(new_ticket, new_sl_price=sl_price)
                    if sl_res.get("status") == "success" and status_to_update:
                        await order_db_manager.update_management_status(new_ticket, status_to_update)
                    result = {"status": "success", "partial_close_result": partial_res, "move_sl_result": sl_res}
                else:
                    result = {"status": "error", "message": "Partial close failed, so SL move was not attempted.", "details": partial_res}
            else:
                result = {"status": "error", "message": f"Unknown action: {action}"}
            results.append({"ticket": ticket, "action": action, **result})
        except Exception as e:
            logger.error(f"Error executing management action {action} for ticket {ticket}: {e}", exc_info=True)
            results.append({"ticket": ticket, "action": action, "status": "error", "message": str(e)})
    return {"status": "success", "data": {"execution_summary": results}}
class ToolRegistry:
    def __init__(self):
        self._tools = {}
        from . import (tool_market, tool_news, tool_patterns, tool_portfolio, tool_trade, tool_utility)
        self._register_tools([tool_market, tool_news, tool_patterns, tool_portfolio, tool_trade, tool_utility])
    def _register_tools(self, tool_modules: List):
        for module in tool_modules:
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if callable(attr) and not attr_name.startswith('_'):
                    self.register(attr_name, attr)
        self.register("execute_trade_flow", execute_trade_flow)
        self.register("execute_prepare_flow", execute_prepare_flow)
        self.register("execute_scan_flow", execute_scan_flow)
        self.register("execute_management_flow", execute_management_flow)
        logger.info(f"ToolRegistry: Registered {len(self._tools)} tools.")
    def register(self, name: str, tool: callable):
        self._tools[name] = tool
    def get_tool(self, name: str) -> callable:
        tool = self._tools.get(name)
        if not tool:
            raise ValueError(f"Tool '{name}' not found in registry.")
        return tool
tool_registry = ToolRegistry()