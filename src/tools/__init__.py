from . import tool_market, tool_portfolio, tool_trade, tool_utility, tool_patterns, tool_news, tool_flows

def get_all_tools():
    return [
        # Flow Control Tools
        tool_flows.execute_prepare_flow,
        tool_flows.execute_scan_flow,
        tool_flows.execute_management_flow,
        tool_flows.execute_trade_flow,

        # Portfolio & History (still needed for direct queries and by flows)
        tool_portfolio.get_portfolio,
        tool_portfolio.get_order_details,
        tool_portfolio.get_historic_trades,
        tool_portfolio.find_orders,
        tool_portfolio.calculate_portfolio_risk,

        # Market Data & Info (still needed for direct queries and by flows)
        tool_market.get_historical_candles,
        tool_market.get_latest_bar_timestamp,
        tool_market.get_current_prices,
        tool_market.get_current_price,
        tool_market.get_server_time,
        tool_market.get_symbol_info,

        # Trade Execution & Management (still needed for direct queries and by flows)
        tool_trade.buy,
        tool_trade.sell,
        tool_trade.buylimit,
        tool_trade.selllimit,
        tool_trade.modify_order_sl_tp,
        tool_trade.close_order,
        tool_trade.close_partial_order,
        tool_trade.move_sl_to_breakeven,
        tool_trade.close_all_orders,
        tool_trade.close_orders_by_symbol,
        tool_trade.close_orders_by_magic,

        # Utilities, Calculations & Analysis (still needed for direct queries and by flows)
        tool_utility.generate_trade_id,
        tool_utility.calculate_lot_size,
        tool_utility.calculate_stop_loss_from_pattern,
        tool_utility.calculate_profit_ladder_levels,
        tool_utility.calculate_ladder_prices_pre_trade,

        # Standalone Tools
        tool_market.is_market_active,
        tool_patterns.scan_for_price_action,
        tool_patterns.scan_for_structures,
        tool_utility.analyze_trend_with_ema,
        tool_utility.analyze_location_and_structure,
        tool_news.search_jina_and_read,
        tool_utility.calculate_atr,
        tool_utility.calculate_ema,
    ]