import os
import re
import json
import time
import asyncio
import logging
from collections import deque
from datetime import datetime
from typing import Dict, Any, List
logger = logging.getLogger(__name__)
def _get_timeframe_seconds(timeframe_str: str) -> int:
    if not timeframe_str:
        return 0
    unit = timeframe_str[-1].upper()
    try:
        value = int(timeframe_str[:-1])
    except (ValueError, TypeError):
        return 0
    if unit == 'M':
        return value * 60
    elif unit == 'H':
        return value * 3600
    elif unit == 'D':
        return value * 86400
    elif unit == 'W':
        return value * 604800
    elif unit == 'N':
        return value * 2592000
    return 0
class AI_Client:
    def __init__(self, metatrader_dir_path: str, order_db_manager_instance, symbol_overrides: dict = None, sleep_delay=0.005, max_retry_command_seconds=10, verbose=True, initial_subscribe_symbols: List[str] = None):
        self.request_semaphore = asyncio.Semaphore(1)
        self.metatrader_dir_path = metatrader_dir_path
        self.order_db_manager = order_db_manager_instance
        self.sleep_delay = sleep_delay
        self.max_retry_command_seconds = max_retry_command_seconds
        self.verbose = verbose
        self.initial_subscribe_symbols = initial_subscribe_symbols or []
        try: self.loop = asyncio.get_running_loop()
        except RuntimeError: self.loop = asyncio.get_event_loop()
        self.ai_path = os.path.join(self.metatrader_dir_path, 'AI')
        self.path_orders = os.path.join(self.ai_path, 'AI_Orders.txt')
        self.path_market_data = os.path.join(self.ai_path, 'AI_Market_Data.txt')
        self.path_historic_trades = os.path.join(self.ai_path, 'AI_Historic_Trades.txt')
        self.path_symbol_info = os.path.join(self.ai_path, 'AI_Symbol_Info.txt')
        self.path_messages = os.path.join(self.ai_path, 'AI_Messages.txt')
        self.path_commands_prefix = os.path.join(self.ai_path, 'AI_Commands_')
        self.num_command_files = 50
        self.active = True
        self.account_info: Dict[str, Any] = {}
        self.market_data: Dict[str, Any] = {}
        self.last_messages = deque(maxlen=50)
        self._processed_message_ids = set()
        self._confirmation_events = {}
        self._last_open_orders_update_time = datetime.now()
        self.HEARTBEAT_TIMEOUT_SECONDS = 30
        self.MT4_COMMENT_MAX_LENGTH = 31
        self.data_queue = asyncio.Queue()
        self.listener_task = None
        self.processor_task = None
    def start(self):
        if not os.path.exists(self.ai_path):
            logger.critical("AI directory not found at %s. Is the EA running?", self.ai_path)
            raise FileNotFoundError(f"AI directory not found at {self.ai_path}")
        self.active = True
        self.listener_task = self.loop.create_task(self._data_listener())
        self.processor_task = self.loop.create_task(self._db_processor())
        if self.initial_subscribe_symbols:
            self.subscribe_symbols(self.initial_subscribe_symbols)
    async def stop(self):
        self.active = False
        if self.listener_task:
            self.listener_task.cancel()
            try: await self.listener_task
            except asyncio.CancelledError: pass
        if self.processor_task:
            await self.data_queue.put(None)
            try: await asyncio.wait_for(self.processor_task, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError): pass
        for event, _ in self._confirmation_events.values():
            if not event.is_set():
                event.set()
        logger.info("AI_Client fully stopped and tasks cleared.")
    def _clear_ai_files(self):
        if not os.path.isdir(self.ai_path): return
        for filename in os.listdir(self.ai_path):
            if filename.endswith('.txt'):
                try: os.remove(os.path.join(self.ai_path, filename))
                except OSError: pass
        logger.debug("Cleared all .txt files in AI directory.")
    def is_connected(self) -> bool:
        return (datetime.now() - self._last_open_orders_update_time).total_seconds() < self.HEARTBEAT_TIMEOUT_SECONDS
    async def _data_listener(self):
        while self.active:
            try:
                data_packet = {
                    "orders_text": self._try_read_file(self.path_orders),
                    "historic_trades_text": self._try_read_file(self.path_historic_trades, delete=False),
                    "market_data_text": self._try_read_file(self.path_market_data),
                    "messages_text": self._try_read_file(self.path_messages, delete=True)
                }
                await self.data_queue.put(data_packet)
            except Exception as e:
                logger.error("Error in _data_listener:", exc_info=True)
            await asyncio.sleep(0.1)
    async def _db_processor(self):
        while True:
            try:
                data_packet = await self.data_queue.get()
                if data_packet is None:
                    break
                orders_text = data_packet["orders_text"]
                historic_trades_text = data_packet["historic_trades_text"]
                market_data_text = data_packet["market_data_text"]
                messages_text = data_packet["messages_text"]
                if orders_text:
                    self._last_open_orders_update_time = datetime.now()
                    data = json.loads(orders_text)
                    self.account_info = data.get('account_info', {})
                    raw_open_orders = data.get('orders', {})
                else:
                    raw_open_orders = {}
                raw_historic_trades = json.loads(historic_trades_text) if historic_trades_text else {}
                if market_data_text:
                    self.market_data = json.loads(market_data_text)
                closed_tickets, new_tickets = await self.order_db_manager.sync_from_mt4_data(raw_open_orders, raw_historic_trades)
                for ticket in closed_tickets:
                    logger.debug(f"[DATA_SYNC] Sync identified CLOSED tickets: {closed_tickets}")
                    self._notify_event(f"CLOSE_{ticket}", {"status": "success", "ticket": ticket})
                    self._notify_event(f"PARTIAL_CLOSE_{ticket}", {"status": "success", "old_ticket_closed": ticket})
                for ticket, comment in new_tickets.items():
                    logger.debug(f"[DATA_SYNC] Sync identified NEW tickets: {list(new_tickets.keys())}")
                    if trade_id_match := re.search(r'ID=([a-f0-9]{8})', comment):
                        trade_id = trade_id_match.group(1)
                        self._notify_event(f"OPEN_BY_COMMENT_{trade_id}", {"status": "success", "ticket": ticket})
                if messages_text:
                    await self._process_messages(json.loads(messages_text))
                self.data_queue.task_done()
            except json.JSONDecodeError as e:
                logger.error(f"[PY_JSON_ERROR] Failed to decode JSON in _db_processor. Error: {e}")
                if messages_text:
                    logger.error(f"[PY_JSON_ERROR] Problematic text was: <<< {messages_text} >>>")
            except Exception as e:
                logger.error("Error in _db_processor:", exc_info=True)
        logger.info("DB processor shut down.")
    async def force_sync(self):
        logger.debug("AI_Client: Force sync initiated.")
        try:
            orders_text = self._try_read_file(self.path_orders)
            historic_trades_text = self._try_read_file(self.path_historic_trades, delete=False)
            if orders_text:
                self._last_open_orders_update_time = datetime.now()
                data = json.loads(orders_text)
                self.account_info = data.get('account_info', {})
                raw_open_orders = data.get('orders', {})
            else:
                raw_open_orders = {}
            raw_historic_trades = json.loads(historic_trades_text) if historic_trades_text else {}
            await self.order_db_manager.sync_from_mt4_data(raw_open_orders, raw_historic_trades)
            logger.debug("AI_Client: Force sync completed successfully.")
        except Exception as e:
            logger.error("Error during force sync: %s", e, exc_info=True)
    def _notify_event(self, event_key, result):
        if event_key in self._confirmation_events:
            event, _ = self._confirmation_events[event_key]
            if not event.is_set():
                self._confirmation_events[event_key] = (event, result)
                event.set()
    async def _process_messages(self, messages: Dict[str, Any]):
        for millis_str, msg_obj in sorted(messages.items(), key=lambda item: int(item[0])):
            millis = int(millis_str)
            if millis in self._processed_message_ids: continue
            self._processed_message_ids.add(millis)
            self.last_messages.append(msg_obj)
            message_content = msg_obj.get('message', '')
            msg_type = msg_obj.get('type')
            request_id = msg_obj.get('request_id')
            if msg_type == 'INFO' and "Successfully closed/deleted order:" in message_content:
                try:
                    parts = message_content.split(':')
                    if len(parts) >= 2:
                        ticket_part = parts[1].split(',')[0].strip()
                        if ticket_part.isdigit():
                            ticket = int(ticket_part)
                            logger.debug(f"[EA_MSG_HANDLER] Processing close message for ticket {ticket}.")
                            db_obj = None
                            if hasattr(self, 'order_db_manager') and self.order_db_manager:
                                if hasattr(self.order_db_manager, 'update_order'):
                                    db_obj = self.order_db_manager
                                elif hasattr(self.order_db_manager, 'db') and hasattr(self.order_db_manager.db, 'update_order'):
                                    db_obj = self.order_db_manager.db
                            if db_obj:
                                db_obj.update_order(ticket, status='closed', close_time=datetime.now().isoformat())
                                logger.debug(f"[BRIDGE_DEBUG] DB Sync: Order {ticket} marked closed from EA message.")
                            else:
                                logger.warning("Could not find database object to sync closed order.")
                except Exception as e:
                    logger.error(f"Error eager-syncing closed order: {e}")
            if request_id and request_id in self._confirmation_events:
                if msg_type == 'INFO':
                    ticket_match = re.search(r'order (\d+)', message_content)
                    ticket = int(ticket_match.group(1)) if ticket_match else None
                    self._notify_event(request_id, {"status": "success", "message": message_content, "ticket": ticket})
                    continue
                elif msg_type == 'ERROR':
                    self._notify_event(request_id, {"status": "error", "message": f"{msg_obj.get('error_type', 'EA_ERROR')} - {msg_obj.get('description', 'No description')}"})
                    continue
            if msg_type == 'INFO':
                if message_content.startswith('PARTIAL_CLOSE_NEW_TICKET:'):
                    try:
                        _, old_ticket_str, new_ticket_str = message_content.split(':')
                        old_ticket, new_ticket = int(old_ticket_str), int(new_ticket_str)
                        await self.order_db_manager.perform_comment_inheritance(old_ticket, new_ticket)
                        self._notify_event(f"PARTIAL_CLOSE_{old_ticket}", {"status": "success", "new_ticket": new_ticket})
                    except (ValueError, IndexError) as e:
                        logger.error(f"Error handling PARTIAL_CLOSE_NEW_TICKET: {e}")
                elif "Successfully closed/deleted order:" in message_content:
                    try:
                        ticket_str = message_content.split(':')[1].strip().split(',')[0]
                        ticket = int(ticket_str)
                        self._notify_event(f"CLOSE_{ticket}", {"status": "success", "ticket": ticket})
                    except (ValueError, IndexError) as e:
                        logger.error(f"Error parsing 'closed/deleted' message: {e}")
                elif "Successfully modified order" in message_content:
                    try:
                        match = re.search(r'order (\d+)', message_content)
                        if match:
                            ticket = int(match.group(1))
                            self._notify_event(f"MODIFY_ORDER_{ticket}", {"status": "success", "ticket": ticket})
                    except Exception as e:
                        logger.error(f"Error parsing modify confirmation: {e}")
                elif "Successfully sent order" in message_content:
                    try:
                        match = re.search(r'order (\d+)', message_content)
                        if match:
                            ticket = int(match.group(1))
                            trade_id_match = re.search(r'ID=([a-f0-9]{8})', message_content)
                            if trade_id_match:
                                trade_id = trade_id_match.group(1)
                                self._notify_event(f"OPEN_BY_COMMENT_{trade_id}", {"status": "success", "ticket": ticket})
                    except Exception as e:
                        logger.error(f"Error parsing sent order confirmation: {e}")
                else:
                    logger.info(f"[EA INFO] {message_content}")
            elif msg_type == 'ERROR':
                error_type = msg_obj.get('error_type', 'UNKNOWN_TYPE')
                description = msg_obj.get('description', 'No description')
                logger.debug(f"[EA ERROR] Type: {error_type} | Details: {description}")
    def _try_read_file(self, file_path, delete=False):
        try:
            if os.path.exists(file_path):
                with open(file_path, 'r', encoding='utf-8') as f:
                    text = f.read()
                if delete:
                    os.remove(file_path)
                if text.strip():
                    return text
        except (IOError, PermissionError):
            pass
        return ''
    def _send_command_nowait(self, command: str, content: str, request_id: str):
        for i in range(self.num_command_files):
            file_path = f'{self.path_commands_prefix}{i}.txt'
            if not os.path.exists(file_path):
                try:
                    with open(file_path, 'w', encoding='utf-8') as f:
                        f.write(f'<:{command}|{content}|{request_id}:>')
                    return
                except Exception as e:
                    logger.error("Error sending command:", exc_info=True)
        logger.critical("Failed to send command (no free file slots): %s", command)
    async def _send_command_and_wait(self, command_key: str, command: str, content: str, timeout: float = 15.0):
        async with self.request_semaphore:
            request_id = f"{command_key}_{int(time.time() * 1000)}"
            event = asyncio.Event()
            self._confirmation_events[request_id] = (event, None)
            self._confirmation_events[command_key] = (event, None)
            logger.debug(f"[PY_SEND] Command: '{command}', Content: '{content}', Req_ID: '{request_id}'")
            self._send_command_nowait(command, content, request_id)
            try:
                logger.debug(f"[PY_WAIT] Waiting for event with key '{command_key}' / ID '{request_id}' (Timeout: {timeout}s)")
                start_time = self.loop.time()
                final_result = None
                first_error = None
                while self.loop.time() - start_time < timeout:
                    try:
                        await asyncio.wait_for(event.wait(), timeout=0.1)
                        _, result_by_id = self._confirmation_events.get(request_id, (None, None))
                        _, result_by_key = self._confirmation_events.get(command_key, (None, None))
                        current_result = result_by_id or result_by_key
                        if current_result:
                            if current_result.get("status") == "success":
                                final_result = current_result
                                logger.debug(f"[PY_EVENT_OK] Success event received for {request_id}. Result: {final_result}")
                                break
                            elif current_result.get("status") == "error" and not first_error:
                                first_error = current_result
                                logger.debug(f"[PY_EVENT_WARN] Temporary error received for {request_id}, but will continue waiting for success. Error: {first_error}")
                        event.clear()
                    except asyncio.TimeoutError:
                        continue
                    except asyncio.CancelledError:
                        raise
                if final_result:
                    return final_result
                elif first_error:
                    logger.error(f"[PY_TIMEOUT] Timeout waiting for success event for '{command_key}'. Returning first error received. Error: {first_error}")
                    return first_error
                else:
                    raise asyncio.TimeoutError()
            except asyncio.TimeoutError:
                logger.error(f"[PY_TIMEOUT] Main timeout waiting for any event with key '{command_key}' / ID '{request_id}'")
                return {"status": "error", "message": f"Operation '{command_key}' (req_id: {request_id}) timed out after {timeout}s."}
            finally:
                self._confirmation_events.pop(request_id, None)
                self._confirmation_events.pop(command_key, None)
    def subscribe_symbols(self, symbols: List[str]):
        self._send_command_nowait('SUBSCRIBE_SYMBOLS', ','.join(symbols), f"SUB_{int(time.time()*1000)}")
    async def _wait_for_response_file(self, file_path: str, timeout: float = 10.0) -> dict:
        async with self.request_semaphore:
            start_time = time.monotonic()
            try:
                while time.monotonic() - start_time < timeout:
                    content_str = self._try_read_file(file_path, delete=True)
                    if content_str:
                        try: return json.loads(content_str)
                        except json.JSONDecodeError: return {"status": "error", "message": f"Failed to decode JSON from {os.path.basename(file_path)}."}
                    await asyncio.sleep(0.05)
                return {"status": "error", "message": f"Timeout waiting for {os.path.basename(file_path)}"}
            finally:
                if os.path.exists(file_path):
                    try: os.remove(file_path)
                    except OSError: pass
    async def get_market_data(self, symbol: str, timeframe_str: str, count: int) -> dict:
        request_id = f"RTD_{symbol}_{timeframe_str}_{int(time.time() * 1000)}"
        response_file_path = os.path.join(self.ai_path, f"AI_{request_id}.txt")
        if os.path.exists(response_file_path): os.remove(response_file_path)
        self._send_command_nowait('GET_REALTIME_DATA', f"{symbol},{timeframe_str},{count},{request_id}", request_id)
        response = await self._wait_for_response_file(response_file_path, timeout=10.0)
        response_data = response.get(request_id, {})
        if response_data.get("status") == "success":
            all_bars_dict = response_data.get("data", {})
            if not all_bars_dict:
                return {"status": "warning", "message": f"EA returned empty data block for {symbol}_{timeframe_str}."}
            try:
                sorted_bars = sorted(all_bars_dict.items(), key=lambda item: item[0])
                formatted_bars = [{"time": dt, **data, "volume": data['tick_volume']} for dt, data in sorted_bars]
                return {"status": "success", "data": formatted_bars}
            except Exception as e:
                logger.error(f"Error formatting bar data for {symbol}: {e}", exc_info=True)
                return {"status": "error", "message": f"Failed to process data from EA: {e}"}
        else:
            return {"status": "warning", "message": response_data.get('message', 'Unknown error during market data fetch.')}
    async def get_server_time(self) -> datetime | None:
        request_id = f"SERVER_TIME_{int(time.time() * 1000)}"
        response_file_path = os.path.join(self.ai_path, f"AI_{request_id}.txt")
        if os.path.exists(response_file_path): os.remove(response_file_path)
        self._send_command_nowait('GET_SERVER_TIME', '', request_id)
        response = await self._wait_for_response_file(response_file_path, timeout=5.0)
        response_data = response.get(request_id)
        if response_data and response_data.get('status') == 'success':
            try:
                return datetime.strptime(response_data.get('data'), '%Y.%m.%d %H:%M')
            except (ValueError, TypeError):
                pass
        return None
    async def get_latest_bar_timestamp(self, symbol: str, timeframe_str: str) -> datetime | None:
        request_id = f"LBT_{symbol}_{timeframe_str}_{int(time.time() * 1000)}"
        response_file_path = os.path.join(self.ai_path, f"AI_{request_id}.txt")
        if os.path.exists(response_file_path):
            try:
                os.remove(response_file_path)
            except OSError:
                pass
        self._send_command_nowait('GET_REALTIME_DATA', f"{symbol},{timeframe_str},1,{request_id}", request_id)
        response = await self._wait_for_response_file(response_file_path, timeout=10.0)
        response_data = response.get(request_id, {})
        if response_data.get("status") == "success":
            all_bars_dict = response_data.get("data", {})
            if not all_bars_dict:
                logger.warning(f"EA returned empty bar data block for {symbol}_{timeframe_str} in get_latest_bar_timestamp.")
                return None
            try:
                latest_bar_time_str = list(all_bars_dict.keys())[0]
                return datetime.strptime(latest_bar_time_str, '%Y.%m.%d %H:%M')
            except (ValueError, TypeError, IndexError) as e:
                logger.error(f"Error parsing latest bar timestamp for {symbol}: {e}", exc_info=True)
                return None
        else:
            logger.warning(f"Failed to get latest bar timestamp for {symbol}_{timeframe_str}: {response_data.get('message')}")
            return None
    async def trade(self, action: str, symbol: str, lots: float, price: float, sl_price: float, tp_price: float, *, magic: int = 12345, comment: str = "ai") -> dict:
        safe_comment = comment[:self.MT4_COMMENT_MAX_LENGTH]
        command_str = f"{symbol},{action.lower()},{lots:.8f},{price:.8f},{sl_price:.8f},{tp_price:.8f},{magic},{safe_comment},0"
        trade_id_match = re.search(r'ID=([a-f0-9]{8})', comment)
        if not trade_id_match:
            event_key = f"OPEN_ORDER_{action}_{symbol}_{int(time.time()*1000)}"
        else:
            trade_id = trade_id_match.group(1)
            event_key = f"OPEN_BY_COMMENT_{trade_id}"
        return await self._send_command_and_wait(event_key, 'OPEN_ORDER', command_str, timeout=15.0)
    async def close_order(self, ticket: int, lots: float = 0.0) -> dict:
        if ticket < 0:
            await self.order_db_manager.remove_pre_registered_order(ticket)
            return {"status": "success", "ticket": ticket, "message": "Removed virtual pre-registered order."}
        original_order = self.order_db_manager.get_order_details(ticket)
        if not original_order:
             return {"status": "error", "message": f"Order {ticket} not found in DB before closing."}
        is_partial = lots > 0 and original_order.get('lots', 0.0) > lots and abs(original_order.get('lots', 0.0) - lots) > 1e-9
        event_key = f"PARTIAL_CLOSE_{ticket}" if is_partial else f"CLOSE_{ticket}"
        return await self._send_command_and_wait(event_key, 'CLOSE_ORDER', f"{ticket},{lots:.8f}", timeout=15.0)
    async def modify_order(self, ticket: int, price: float = 0.0, sl: float = 0.0, tp: float = 0.0) -> dict:
        order_info = self.order_db_manager.get_order_details(ticket)
        if not order_info:
            return {"status": "error", "action": "modify_order", "message": f"Order {ticket} not found."}
        order_info = {k.lower(): v for k, v in order_info.items()}
        final_price, final_sl, final_tp = price if price > 0.0 else order_info.get('open_price', 0.0), sl if sl > 0.0 else order_info.get('sl', 0.0), tp if tp > 0.0 else order_info.get('tp', 0.0)
        epsilon = 1e-5
        if not (price > 0.0 and abs(order_info.get('open_price', 0.0) - final_price) > epsilon) and \
           not (sl > 0.0 and abs(order_info.get('sl', 0.0) - final_sl) > epsilon) and \
           not (tp > 0.0 and abs(order_info.get('tp', 0.0) - final_tp) > epsilon):
            return {"status": "success", "action": "modify_order", "ticket": ticket, "message": "No modification needed, target values already set."}
        command_str = f"{ticket},{0.0},{final_price},{final_sl},{final_tp},{0}"
        event_key = f"MODIFY_ORDER_{ticket}"
        return await self._send_command_and_wait(event_key, 'MODIFY_ORDER', command_str, timeout=15.0)
    async def get_historic_trades(self, lookback_days: int) -> dict:
        request_id = f"GET_HISTORIC_TRADES_{int(time.time() * 1000)}"
        response_file_path = os.path.join(self.ai_path, f"AI_{request_id}.txt")
        if os.path.exists(response_file_path): os.remove(response_file_path)
        self._send_command_nowait('GET_HISTORIC_TRADES', str(lookback_days), request_id)
        response = await self._wait_for_response_file(response_file_path, timeout=10.0)
        response_data = response.get(request_id) if isinstance(response, dict) else None
        if response_data and response_data.get('status') == 'success':
            return response_data
        return {"status": "error", "message": f"Failed to get historic trades. Response: {response}"}
    async def get_symbol_info(self, symbol: str) -> dict:
        request_id = f"GET_SYMBOL_INFO_{symbol}_{int(time.time() * 1000)}"
        response_file_path = os.path.join(self.ai_path, f"AI_{request_id}.txt")
        if os.path.exists(response_file_path): os.remove(response_file_path)
        self._send_command_nowait('GET_SYMBOL_INFO', symbol, request_id)
        response = await self._wait_for_response_file(response_file_path, timeout=10.0)
        response_data = response.get(request_id) if isinstance(response, dict) else None
        if response_data and response_data.get('status') == 'success':
            return response_data
        return {"status": "error", "message": f"Failed to get info for {symbol}. Response: {response}"}
    async def _bulk_close_wrapper(self, command: str, content: str = "") -> dict:
        event_key = f"{command}_{content}_{int(time.time()*1000)}"
        self._send_command_nowait(command, content, event_key)
        await asyncio.sleep(3)
        return {"status": "success", "message": f"Command '{command}' sent."}
    async def close_all_orders(self):
        return await self._bulk_close_wrapper('CLOSE_ALL_ORDERS')
    async def close_orders_by_symbol(self, symbol: str):
        if self.order_db_manager:
            await self.order_db_manager.clean_temporary_orders()
        return await self._bulk_close_wrapper('CLOSE_ORDERS_BY_SYMBOL', symbol)
    async def close_orders_by_magic(self, magic: int):
        return await self._bulk_close_wrapper('CLOSE_ORDERS_BY_MAGIC', str(magic))