import os
import gc
import re
import asyncio
import logging
from datetime import timedelta
from PyQt5.QtCore import QObject, pyqtSignal
from .agent import BaseAgentMT4
from ..bridge.mt4_bridge import mt4_bridge
from ..tools import get_all_tools, tool_market
from ..tools.tool_news import get_news_summary_for_cycle
from ..services.order_db_manager import order_db_manager
logger = logging.getLogger(__name__)
class TradingEngine(QObject):
    status_update = pyqtSignal(str, str)
    positions_update = pyqtSignal(dict)
    connection_status = pyqtSignal(bool)
    finished = pyqtSignal()
    def __init__(self, config_manager):
        super().__init__()
        self.config_manager = config_manager
        self._is_running = False
        self.agent = None
        self.current_config = {}
        self.heartbeat_task = None
        self.main_task = None
        self.loop = None
        self.symbol_info_cache = {}
    async def start_with_loop(self, trading_config, loop):
        logger.info("TradingEngine: start_with_loop() method called.")
        self._is_running = True
        self.current_config = trading_config
        self.loop = loop
        gc.collect()
        try:
            logger.info("TradingEngine: Creating main_loop task.")
            self.main_task = self.loop.create_task(self.main_loop())
            await self.main_task
        except asyncio.CancelledError:
            logger.info("TradingEngine: main_task was cancelled externally.")
        except Exception as e:
            logger.critical(f"FATAL ERROR in TradingEngine main_task: {e}", exc_info=True)
            self.status_update.emit("Engine Error", "status_label_error")
        finally:
            logger.info("TradingEngine: Cleaning up after trading task...")
            self.agent = None
            self.main_task = None
            logger.info("TradingEngine: Cleanup complete.")
            self.finished.emit()
    def stop(self):
        if not self._is_running:
            logger.warning("TradingEngine: Stop called but not running.")
            return
        logger.info("TradingEngine: Stop called.")
        self._is_running = False
        if self.agent:
            self.agent._is_running = False
        if self.main_task and not self.main_task.done():
            logger.info("TradingEngine: Cancelling main task.")
            self.main_task.cancel()
    async def main_loop(self):
        logger.info("TradingEngine: main_loop() coroutine started.")
        is_first_cycle = True
        try:
            logger.info("TradingEngine: Attempting to initialize systems...")
            initialization_successful = await self.initialize_systems()
            if not initialization_successful:
                logger.error("TradingEngine: System initialization failed. main_loop will exit.")
                self.connection_status.emit(False)
                self.status_update.emit("Init Failed", "status_label_error")
                return
            logger.info("TradingEngine: Systems initialized successfully. Starting heartbeat task.")
            self.heartbeat_task = asyncio.create_task(self.heartbeat_loop())
            logger.info("TradingEngine: Entering the main trading cycle loop.")
            while self._is_running:
                try:
                    client = mt4_bridge.get_client()
                    srv_dt = await client.get_server_time()
                    if not srv_dt:
                        self.status_update.emit("Connecting to MT4...", "status_label_pending")
                        self.connection_status.emit(False)
                        await asyncio.sleep(2)
                        continue
                    self.connection_status.emit(True)
                    if is_first_cycle:
                        logger.info("First cycle detected. Waiting 2s for EA to settle before initial sync.")
                        await asyncio.sleep(2)
                        logger.info("Performing initial data synchronization...")
                        self.status_update.emit("Syncing initial data...", "status_label_pending")
                        if hasattr(mt4_bridge, 'force_sync'):
                           await mt4_bridge.force_sync()
                        logger.info("Initial data synchronization complete.")
                        is_first_cycle = False
                    server_time_str = srv_dt.strftime("%Y-%m-%d %H:%M:%S")
                    logger.info(f"CYCLE START @ {server_time_str}", extra={"type": "cycle_start", "content": {"time": server_time_str}})
                    self.status_update.emit(f"Running Cycle ({server_time_str})...", "status_label_ok")
                    news_summary = ""
                    try:
                        model_config = self.current_config.get("enabled_model")
                        if model_config:
                            news_summary = await get_news_summary_for_cycle(model_config=model_config)
                        if news_summary:
                            logger.info(news_summary, extra={"type": "news_summary"})
                        else:
                            logger.info("No significant news summary generated for this cycle.")
                    except Exception as e:
                        logger.error(f"News fetch failed: {e}")
                    if self.agent:
                        self.agent._is_running = self._is_running
                        await self.agent.run_trading_session(srv_dt, news_summary)
                    logger.info("Cycle Execution Finished.")
                    srv_dt_after = await client.get_server_time()
                    if not srv_dt_after:
                        await asyncio.sleep(5)
                        continue
                    strategy_profile = self.current_config.get('strategy_profile', {})
                    tf_minutes = strategy_profile.get('signal_tf', 60)
                    if not isinstance(tf_minutes, int) or tf_minutes <= 0: tf_minutes = 60
                    current_minutes_total = srv_dt_after.hour * 60 + srv_dt_after.minute
                    remainder_minutes = current_minutes_total % tf_minutes
                    current_seconds_in_cycle = remainder_minutes * 60 + srv_dt_after.second
                    total_cycle_seconds = tf_minutes * 60
                    seconds_to_candle_close = total_cycle_seconds - current_seconds_in_cycle
                    final_sleep_seconds = seconds_to_candle_close + 2
                    next_wake_time = srv_dt_after + timedelta(seconds=final_sleep_seconds)
                    log_msg = f"Wait for next candle... (Wake up at MT4: {next_wake_time.strftime('%H:%M:%S')})"
                    logger.info(f"{log_msg}. Sleeping for {final_sleep_seconds:.1f}s.")
                    self.status_update.emit(log_msg, "status_label_pending")
                    step = 0.5
                    slept = 0.0
                    while slept < final_sleep_seconds and self._is_running:
                        await asyncio.sleep(step)
                        slept += step
                    logger.info(f"TradingEngine: main_loop cycle finished. Will sleep until next candle.")
                except asyncio.CancelledError:
                    logger.info("Main trading cycle inner loop cancelled.")
                    break
                except Exception as e:
                    logger.error(f"Critical Loop Error: {e}", exc_info=True)
                    self.status_update.emit("Error - Retrying in 10s", "status_label_error")
                    await asyncio.sleep(10)
        except asyncio.CancelledError:
            logger.info("Main trading loop task received cancellation. Performing cleanup.")
        finally:
            if self.heartbeat_task and not self.heartbeat_task.done():
                self.heartbeat_task.cancel()
                try: await self.heartbeat_task
                except asyncio.CancelledError: pass
            await mt4_bridge.shutdown()
            self.status_update.emit("Stopped", "status_label_stopped")
            logger.info("TradingEngine: main_loop() coroutine is finishing.")
    async def heartbeat_loop(self):
        while not mt4_bridge._initialized:
            if not self._is_running: return
            await asyncio.sleep(0.5)
        try:
            while self._is_running:
                try:
                    current_prices = {}
                    symbols = self.current_config.get("trading_symbols", [])
                    if symbols:
                        prices_resp = await tool_market.get_current_prices(symbols)
                        if prices_resp:
                            current_prices = {
                                symbol: data['data']
                                for symbol, data in prices_resp.items()
                                if data and data.get('status') == 'success' and 'data' in data
                            }
                            if current_prices:
                                await order_db_manager.proactive_update_tp_levels(current_prices)
                    current_positions = order_db_manager.get_enhanced_portfolio()
                    if current_positions:
                        position_symbols = {pos['symbol'] for pos in current_positions.values() if pos.get('symbol')}
                        symbols_to_fetch = [s for s in position_symbols if s not in self.symbol_info_cache]
                        if symbols_to_fetch:
                            fetched_infos = await asyncio.gather(*(tool_market.get_symbol_info(s) for s in symbols_to_fetch), return_exceptions=True)
                            for i, symbol in enumerate(symbols_to_fetch):
                                info_resp = fetched_infos[i]
                                if isinstance(info_resp, dict) and info_resp.get('status') == 'success':
                                    self.symbol_info_cache[symbol] = info_resp['data']
                                else:
                                    logger.warning(f"Could not cache symbol info for {symbol} in heartbeat.")
                        for ticket, order in current_positions.items():
                            symbol = order.get('symbol')
                            order_type = order.get('type', '').lower()
                            market_price = 0.0
                            if symbol and symbol in current_prices:
                                price_data = current_prices.get(symbol, {})
                                if 'buy' in order_type:
                                    market_price = price_data.get('bid', 0.0)
                                elif 'sell' in order_type:
                                    market_price = price_data.get('ask', 0.0)
                            order['current_price'] = market_price
                            order['next_tp_profit'] = None
                            comment = order.get('comment_ai') or order.get('comment', '')
                            if comment and 'L=' in comment and symbol in self.symbol_info_cache:
                                match = re.search(r'L=(\d+)', comment)
                                if match:
                                    current_level = int(match.group(1))
                                    next_level = current_level + 1
                                    next_tp_price = order.get(f'tp{next_level}_price')
                                    open_price = order.get('open_price')
                                    lots = order.get('lots')
                                    contract_size = self.symbol_info_cache[symbol].get('contract_size')
                                    if all([open_price, lots, contract_size, next_tp_price]):
                                        profit_per_lot_contract = abs(next_tp_price - open_price) * contract_size
                                        next_tp_profit_val = profit_per_lot_contract * lots
                                        order['next_tp_profit'] = next_tp_profit_val
                    if current_positions is not None:
                        self.positions_update.emit(current_positions)
                    is_connected = mt4_bridge.get_client().is_connected()
                    self.connection_status.emit(is_connected)
                    await asyncio.sleep(3)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Heartbeat loop error: {e}", exc_info=True)
                    self.connection_status.emit(False)
                    await asyncio.sleep(3)
        except asyncio.CancelledError:
            logger.info("Heartbeat loop task received cancellation. Exiting.")
        finally:
            logger.info("Heartbeat loop finished.")
    async def initialize_systems(self):
        logger.info("TradingEngine.initialize_systems: Starting initialization.")
        try:
            self.status_update.emit("Initializing MT4 Bridge...", "status_label_pending")
            symbol_overrides = self.config_manager.config.get("agent_config", {}).get("symbol_overrides", {})
            raw_symbols = self.current_config.get("trading_symbols", [])
            unique_symbols = list(set(raw_symbols))
            self.current_config["trading_symbols"] = unique_symbols
            logger.info(f"TradingEngine.initialize_systems: MT4_DATA_PATH is '{self.current_config['mt4_data_path']}'.")
            logger.info("TradingEngine.initialize_systems: Calling mt4_bridge.initialize()...")
            await mt4_bridge.initialize(
                mt4_data_path=self.current_config["mt4_data_path"],
                symbol_overrides=symbol_overrides,
                initial_subscribe_symbols=unique_symbols,
            )
            logger.info("TradingEngine.initialize_systems: mt4_bridge.initialize() returned.")
            self.status_update.emit("MT4 Connected", "status_label_ok")
            await order_db_manager.clean_temporary_orders()
            self.status_update.emit("Initializing Agent...", "status_label_pending")
            tools = get_all_tools()
            strategy_profile = self.current_config.get('strategy_profile')
            if not strategy_profile: raise ValueError("No strategy profile selected.")
            num_symbols = len(unique_symbols)
            dynamic_max_steps = 8 + num_symbols * 2
            logger.info(f"Agent Config: {num_symbols} symbols, Max Steps: {dynamic_max_steps}")
            model_config = self.current_config["enabled_model"]
            model_id_clean = model_config['model_id'].replace('/', '_').replace('-', '_')
            agent_signature = f"mt4_gui_agent_{model_id_clean}"
            api_key = os.getenv('TEMP_LLM_API_KEY')
            api_base = os.getenv('TEMP_LLM_API_BASE')
            logger.info("TradingEngine.initialize_systems: Creating BaseAgentMT4 instance...")
            self.agent = BaseAgentMT4(
                signature=agent_signature,
                basemodel=model_config["model_id"],
                trading_symbols=unique_symbols,
                tools=tools,
                openai_api_key=api_key,
                openai_base_url=api_base,
                max_steps=dynamic_max_steps,
                strategy_profile=strategy_profile
            )
            self.agent._is_running = self._is_running
            logger.info("TradingEngine.initialize_systems: Calling agent.initialize()...")
            await self.agent.initialize()
            logger.info("TradingEngine.initialize_systems: agent.initialize() returned.")
            self.status_update.emit("Agent Ready", "status_label_ok")
            logger.info("TradingEngine.initialize_systems: Initialization complete and successful.")
            return True
        except Exception as e:
            logger.critical(f"TradingEngine.initialize_systems: FAILED during initialization: {e}", exc_info=True)
            await mt4_bridge.shutdown()
            return False