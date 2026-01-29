import json
import re
import os
import time
import logging
import sqlite3
import asyncio
from typing import Dict, Union, Tuple, Set
from datetime import datetime
logger = logging.getLogger(__name__)
class OrderDBManager:
    def __init__(self, db_path=".db/orders.sqlite"):
        self._db_path = db_path
        self._db_conn = None
        self.init_timestamp = time.time()
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._db_lock = asyncio.Lock()
        self._connect()
        self._create_tables_if_needed()
    @property
    def _conn(self):
        if self._db_conn is None:
            logger.debug("Database connection is closed. Re-establishing connection...")
            self._connect()
        return self._db_conn
    def _connect(self):
        try:
            self._db_conn = sqlite3.connect(self._db_path, check_same_thread=False)
            self._db_conn.row_factory = sqlite3.Row
            logger.debug("Successfully connected to OrderDB at %s", self._db_path)
        except sqlite3.Error as e:
            logger.critical("Failed to connect to OrderDB: %s", e, exc_info=True)
            self._db_conn = None
            raise
    def _create_tables_if_needed(self):
        if self._conn is None: return
        cursor = self._conn.cursor()
        try:
            tp_fields = ", ".join([f"tp{i}_price REAL" for i in range(1, 9)])
            sql_create_open_orders_table = f"""
            CREATE TABLE IF NOT EXISTS open_orders (
                ticket INTEGER PRIMARY KEY, symbol TEXT, type TEXT, lots REAL,
                open_price REAL, open_time TEXT, sl REAL, tp REAL, profit REAL,
                commission REAL, swap REAL, comment TEXT, magic INTEGER,
                extends INTEGER, last_updated TEXT, comment_ai TEXT, _creation_timestamp REAL,
                signal_tf INTEGER,
                {tp_fields}
            );
            """
            tp_fields_historic = ", ".join([f"tp{i}_price REAL" for i in range(1, 9)])
            sql_create_historic_orders_table = f"""
            CREATE TABLE IF NOT EXISTS historic_orders (
                ticket INTEGER PRIMARY KEY, symbol TEXT, type TEXT, lots REAL,
                open_price REAL, open_time TEXT, close_price REAL, close_time TEXT,
                sl REAL, tp REAL, profit REAL, commission REAL, swap REAL,
                comment TEXT, magic INTEGER, comment_ai TEXT,
                signal_tf INTEGER,
                {tp_fields_historic}
            );
            """
            cursor.execute(sql_create_open_orders_table)
            cursor.execute(sql_create_historic_orders_table)
            self._conn.commit()
        except sqlite3.Error as e:
            logger.error("Failed to create DB tables: %s", e, exc_info=True)
        finally:
            cursor.close()
    async def sync_from_mt4_data(self, raw_open_orders: dict, raw_historic_trades: dict) -> Tuple[Set[int], Dict[int, str]]:
        if self._db_conn is None:
            logger.error("Cannot sync, DB connection is not available.")
            return set(), {}
        if not raw_open_orders and self.init_timestamp and (time.time() - self.init_timestamp < 15):
            logger.debug("[DB_SYNC] MT4 open orders data is not available yet. Skipping sync cycle to prevent data loss.")
            return set(), {}
        async with self._db_lock:
            cursor = self._conn.cursor()
            final_closed_tickets = set()
            final_new_tickets = {}
            updated_tickets_for_logging = set()
            inherited_tickets_for_logging = set()
            try:
                cursor.execute("SELECT ticket, _creation_timestamp, comment FROM open_orders")
                db_open_orders_info = {row['ticket']: dict(row) for row in cursor.fetchall()}
                db_open_tickets = set(db_open_orders_info.keys())
                mt4_open_tickets = {int(t) for t in raw_open_orders.keys() if t.isdigit()}
                potentially_closed_tickets = {t for t in db_open_tickets if t > 0 and t not in mt4_open_tickets}
                for ticket in potentially_closed_tickets:
                    order_in_db = db_open_orders_info.get(ticket)
                    if order_in_db and order_in_db.get('_creation_timestamp') and (time.time() - order_in_db['_creation_timestamp'] < 10):
                        logger.debug(f"[DB_SYNC] Ticket {ticket} was created recently. Deferring closure check.")
                        continue
                    final_closed_tickets.add(ticket)
                    self._move_order_to_history(cursor, ticket, raw_historic_trades)
                current_time = time.time()
                for ticket in list(db_open_tickets):
                    if ticket < 0 and (current_time - db_open_orders_info.get(ticket, {}).get('_creation_timestamp', 0) > 60):
                        cursor.execute("DELETE FROM open_orders WHERE ticket=?", (ticket,))
                        logger.debug(f"Deleted stale pre-registered order {ticket}.")
                for ticket_str, order in raw_open_orders.items():
                    ticket = int(ticket_str)
                    if ticket in db_open_tickets:
                        cursor.execute("SELECT sl, tp FROM open_orders WHERE ticket = ?", (ticket,))
                        db_state = cursor.fetchone()
                        if db_state:
                            mt4_sl = order.get('SL')
                            mt4_tp = order.get('TP')
                            if db_state['sl'] != mt4_sl or db_state['tp'] != mt4_tp:
                                logger.debug(f"[DB_COMPARE_SL_BEFORE] SL/TP change detected for ticket {ticket}.")
                                cursor.execute("SELECT * FROM open_orders WHERE ticket = ?", (ticket,))
                                full_db_state_before = dict(cursor.fetchone())
                                pretty_data = json.dumps(full_db_state_before, indent=4)
                                logger.debug(f"[DB_COMPARE_SL_BEFORE] DB state for ticket {ticket} before update:\n{pretty_data}")
                                updated_tickets_for_logging.add(ticket)
                        cursor.execute("""
                            UPDATE open_orders SET
                                profit = ?, commission = ?, swap = ?, sl = ?, tp = ?, lots = ?,
                                last_updated = ?, comment = ?, open_price = ?, open_time = ?, type = ?, symbol = ?, magic = ?
                            WHERE ticket = ?
                        """, (
                            order.get('pnl'), order.get('commission'), order.get('swap'),
                            order.get('SL'), order.get('TP'), order.get('lots'),
                            datetime.now().isoformat(), order.get('comment'),
                            order.get('open_price'), order.get('open_time'),
                            order.get('type'), order.get('symbol'), order.get('magic'),
                            ticket
                        ))
                        if cursor.rowcount > 0:
                            updated_tickets_for_logging.add(ticket)
                    else:
                        cursor.execute("SELECT * FROM historic_orders WHERE ticket=?", (ticket,))
                        restored_order_row = cursor.fetchone()
                        if restored_order_row:
                            logger.info(f"Restoring incorrectly archived order {ticket} from history.")
                            restored_data = dict(restored_order_row)
                            restored_data.update({
                                'profit': order.get('pnl'),
                                'commission': order.get('commission'),
                                'swap': order.get('swap'),
                                'sl': order.get('SL'),
                                'tp': order.get('TP'),
                                'lots': order.get('lots'),
                                'comment': order.get('comment'),
                                'last_updated': datetime.now().isoformat()
                            })
                            restored_data.pop('close_price', None)
                            restored_data.pop('close_time', None)
                            columns = ', '.join(restored_data.keys())
                            placeholders = ', '.join(['?'] * len(restored_data))
                            cursor.execute(f"INSERT OR REPLACE INTO open_orders ({columns}) VALUES ({placeholders})", tuple(restored_data.values()))
                            cursor.execute("DELETE FROM historic_orders WHERE ticket=?", (ticket,))
                            logger.debug(f"Successfully restored order {ticket} to open_orders table.")
                        else:
                            trade_id = self._get_id_from_comment(order.get('comment'))
                            temp_id = None
                            if trade_id:
                                cursor.execute("SELECT ticket FROM open_orders WHERE ticket < 0 AND comment_ai LIKE ?", (f'%ID={trade_id}%',))
                                row = cursor.fetchone()
                                if row: temp_id = row['ticket']
                            if temp_id:
                                self._confirm_pre_registered_order_internal(cursor, temp_id, ticket, order)
                            else:
                                is_from_partial_close = order.get('comment', '').startswith('from #')
                                cursor.execute("""
                                    INSERT INTO open_orders (ticket, symbol, type, lots, open_price, open_time, sl, tp, profit,
                                                        commission, swap, comment, magic, last_updated, _creation_timestamp, comment_ai)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """, (
                                    ticket, order.get('symbol'), order.get('type'), order.get('lots'), order.get('open_price'),
                                    order.get('open_time'), order.get('SL'), order.get('TP'), order.get('pnl'),
                                    order.get('commission'), order.get('swap'), order.get('comment'),
                                    order.get('magic'), datetime.now().isoformat(), time.time(),
                                    order.get('comment') if not is_from_partial_close else None
                                ))
                        final_new_tickets[ticket] = order.get('comment')
                cursor.execute("SELECT ticket, comment, comment_ai, extends FROM open_orders WHERE comment LIKE 'from #%' AND (comment_ai IS NULL OR comment_ai = comment)")
                orders_needing_inheritance = cursor.fetchall()
                for row in orders_needing_inheritance:
                    new_ticket, mt4_comment = row['ticket'], row['comment']
                    try:
                        old_ticket_str = mt4_comment.split('#')[1]
                        if old_ticket_str.isdigit():
                            old_ticket = int(old_ticket_str)
                            inherited_tickets_for_logging.add(new_ticket)
                            logger.info(f"Detected order {new_ticket} from partial close of {old_ticket}. Triggering inheritance.")
                            await self.perform_comment_inheritance(old_ticket, new_ticket, cursor)
                    except (IndexError, ValueError) as e:
                        logger.warning(f"Could not parse old ticket from comment '{mt4_comment}' for new ticket {new_ticket}: {e}")
                self._conn.commit()
                if final_new_tickets:
                    try:
                        logger.debug(f"[DB_SNAPSHOT_SYNCED] Found {len(final_new_tickets)} new/confirmed/restored tickets to log.")
                        for ticket in final_new_tickets.keys():
                            synced_order = self.get_order_details(ticket)
                            if synced_order:
                                pretty_data = json.dumps(synced_order, indent=4, ensure_ascii=False)
                                logger.debug(f"[DB_SNAPSHOT_SYNCED] Data after MT4 sync for ticket {ticket}:\n{pretty_data}")
                            else:
                                logger.warning(f"[DB_SNAPSHOT_SYNCED] Failed to fetch synced order {ticket} immediately after commit.")
                    except Exception as log_e:
                        logger.error(f"[DB_SNAPSHOT_SYNCED] Error during logging: {log_e}")
                if updated_tickets_for_logging:
                    for ticket in updated_tickets_for_logging:
                        final_state = self.get_order_details(ticket)
                        if final_state:
                            pretty_data = json.dumps(final_state, indent=4)
                            logger.debug(f"[DB_COMPARE_SL_AFTER] DB state for ticket {ticket} after sync commit:\n{pretty_data}")
                if inherited_tickets_for_logging:
                    for ticket in inherited_tickets_for_logging:
                        final_state = self.get_order_details(ticket)
                        if final_state:
                            pretty_data = json.dumps(final_state, indent=4)
                            logger.debug(f"[DB_COMPARE_INHERIT_CHILD_AFTER] DB state for new ticket {ticket} after inheritance commit:\n{pretty_data}")
                return final_closed_tickets, final_new_tickets
            except sqlite3.Error as e:
                logger.error("Error during DB sync: %s", e, exc_info=True)
                self._conn.rollback()
                return set(), {}
            finally:
                if cursor: cursor.close()
    def _move_order_to_history(self, cursor: sqlite3.Cursor, ticket: int, raw_historic_trades: dict):
        logger.debug(f"[DB_SYNC] Attempting to move ticket {ticket} to history...")
        cursor.execute("SELECT * FROM open_orders WHERE ticket=?", (ticket,))
        closed_order_data = cursor.fetchone()
        if closed_order_data:
            logger.debug(f"[DB-MOVE] Found ticket {ticket} in open_orders. Preparing to move to historic_orders.")
            closed_order_dict = dict(closed_order_data)
            historic_params = {
                'ticket': ticket,
                'symbol': closed_order_dict.get('symbol'),
                'type': closed_order_dict.get('type'),
                'lots': closed_order_dict.get('lots'),
                'open_price': closed_order_dict.get('open_price'),
                'open_time': closed_order_dict.get('open_time'),
                'close_price': closed_order_dict.get('open_price'),
                'close_time': datetime.now().isoformat(),
                'sl': closed_order_dict.get('sl'),
                'tp': closed_order_dict.get('tp'),
                'profit': closed_order_dict.get('profit', 0.0),
                'commission': closed_order_dict.get('commission', 0.0),
                'swap': closed_order_dict.get('swap', 0.0),
                'comment': closed_order_dict.get('comment'),
                'magic': closed_order_dict.get('magic'),
                'comment_ai': closed_order_dict.get('comment_ai'),
                'signal_tf': closed_order_dict.get('signal_tf')
            }
            for i in range(1, 9):
                historic_params[f'tp{i}_price'] = closed_order_dict.get(f'tp{i}_price')
            historic_trade = raw_historic_trades.get(str(ticket))
            if historic_trade:
                logger.debug(f"[DB-MOVE] Found official historic data for ticket {ticket} from MT4. Updating with final values.")
                historic_params.update({
                    'close_price': historic_trade.get('close_price'),
                    'close_time': historic_trade.get('close_time'),
                    'profit': historic_trade.get('pnl'),
                    'commission': historic_trade.get('commission'),
                    'swap': historic_trade.get('swap'),
                })
            else:
                logger.debug(f"[DB-MOVE] No official historic data for ticket {ticket}. Using data from open_orders and current time as fallback.")
            columns = ', '.join(historic_params.keys())
            placeholders = ', '.join(['?'] * len(historic_params))
            cursor.execute(f"INSERT OR REPLACE INTO historic_orders ({columns}) VALUES ({placeholders})", tuple(historic_params.values()))
            cursor.execute("DELETE FROM open_orders WHERE ticket=?", (ticket,))
            logger.debug(f"[DB_SYNC] SUCCESS: Ticket {ticket} deleted from 'open_orders' and moved to 'historic_orders'.")
        else:
            logger.debug(f"[DB_SYNC] FAILED: Ticket {ticket} not found in 'open_orders', cannot move to history.")
    def _confirm_pre_registered_order_internal(self, cursor: sqlite3.Cursor, temp_id: int, final_ticket: int, mt4_order_data: dict):
        cursor.execute("SELECT * FROM open_orders WHERE ticket = ?", (temp_id,))
        row = cursor.fetchone()
        if row:
            row_dict = dict(row)
            cursor.execute("DELETE FROM open_orders WHERE ticket = ?", (temp_id,))
            row_dict['ticket'] = final_ticket
            row_dict['last_updated'] = datetime.now().isoformat()
            row_dict['profit'] = mt4_order_data.get('pnl')
            row_dict['commission'] = mt4_order_data.get('commission')
            row_dict['swap'] = mt4_order_data.get('swap')
            row_dict['open_time'] = mt4_order_data.get('open_time')
            columns = ', '.join(row_dict.keys())
            placeholders = ', '.join(['?'] * len(row_dict))
            cursor.execute(f"INSERT OR REPLACE INTO open_orders ({columns}) VALUES ({placeholders})", tuple(row_dict.values()))
            logger.info(f"Confirmed pre-registered order. Updated temp ID '{temp_id}' to final ticket {final_ticket}.")
        else:
            logger.warning(f"Could not find pre-registered order with temp_id={temp_id} to confirm.")
    async def perform_comment_inheritance(self, old_ticket: int, new_ticket: int, cursor: sqlite3.Cursor = None):
        if self._db_conn is None: return
        if cursor is None:
            async with self._db_lock:
                internal_cursor = self._conn.cursor()
                try:
                    await self._perform_comment_inheritance_logic(internal_cursor, old_ticket, new_ticket)
                    self._conn.commit()
                except sqlite3.Error as e:
                    logger.error(f"INHERITANCE: DB error for {new_ticket} from {old_ticket}: {e}", exc_info=True)
                    self._conn.rollback()
                finally:
                    internal_cursor.close()
        else:
            await self._perform_comment_inheritance_logic(cursor, old_ticket, new_ticket)
    async def _perform_comment_inheritance_logic(self, cursor: sqlite3.Cursor, old_ticket: int, new_ticket: int):
        cursor.execute("SELECT * FROM open_orders WHERE ticket = ?", (new_ticket,))
        new_order_row = cursor.fetchone()
        if new_order_row:
             pretty_child_before = json.dumps(dict(new_order_row), indent=4)
             logger.debug(f"[DB_COMPARE_INHERIT_CHILD_BEFORE] State of new ticket {new_ticket} before inheritance:\n{pretty_child_before}")
        if new_order_row and new_order_row['comment_ai'] and new_order_row['extends']:
            logger.debug(f"INHERITANCE: Already completed for new_ticket={new_ticket}. Skipping.")
            return
        logger.info(f"INHERITANCE: Initiating for new_ticket={new_ticket} from old_ticket={old_ticket}.")
        tp_columns_str = ", ".join([f"tp{i}_price" for i in range(1, 9)])
        required_columns = f"comment_ai, signal_tf, {tp_columns_str}"
        query = f"""
            SELECT {required_columns} FROM (
                SELECT {required_columns}, 1 as source_order FROM historic_orders WHERE ticket = ?
                UNION ALL
                SELECT {required_columns}, 2 as source_order FROM open_orders WHERE ticket = ?
            )
            ORDER BY source_order
            LIMIT 1
        """
        cursor.execute(query, (old_ticket, old_ticket))
        parent_row = cursor.fetchone()
        if parent_row:
            parent_dict = dict(parent_row)
            pretty_parent = json.dumps(parent_dict, indent=4)
            logger.debug(f"[DB_COMPARE_INHERIT_PARENT] State of parent ticket {old_ticket} providing the data:\n{pretty_parent}")
            parent_comment_ai = parent_dict.get('comment_ai')
            if parent_comment_ai:
                update_fields = {
                    'comment_ai': parent_comment_ai,
                    'extends': old_ticket,
                    'signal_tf': parent_dict.get('signal_tf')
                }
                for i in range(1, 9):
                    update_fields[f'tp{i}_price'] = parent_dict.get(f'tp{i}_price')
                set_clause = ', '.join([f"{key} = ?" for key in update_fields.keys()])
                values = list(update_fields.values()) + [new_ticket]
                cursor.execute(f"UPDATE open_orders SET {set_clause} WHERE ticket = ?", tuple(values))
                if cursor.rowcount > 0:
                    logger.info(f"INHERITANCE: Success! Inherited data for new order {new_ticket}.")
                else:
                    logger.warning(f"INHERITANCE: Update for {new_ticket} affected 0 rows. It might not be in the DB yet. The main sync loop will retry.")
            else:
                logger.error(f"INHERITANCE: FAILED for new_ticket={new_ticket}. Parent 'comment_ai' is empty.")
        else:
            logger.error(f"INHERITANCE: FAILED for new_ticket={new_ticket}. Parent order {old_ticket} not found in open or historic tables.")
    def _get_id_from_comment(self, comment: str) -> str | None:
        if not comment: return None
        match = re.search(r'ID=([a-f0-9]{8})', comment)
        return match.group(1) if match else None
    async def add_new_order_with_calculations(self, order_data: dict, signal_tf: int) -> Union[int, str]:
        if self._db_conn is None: return "DB not connected"
        async with self._db_lock:
            cursor = self._conn.cursor()
            temp_id = -int(time.time() * 1000000)
            try:
                ai_comment = order_data.get('comment')
                if ai_comment and 'M=' not in ai_comment:
                    ai_comment += ';M=N'
                params = {
                    'ticket': temp_id, 'symbol': order_data.get('symbol'), 'type': order_data.get('type'),
                    'lots': float(order_data.get('lots', 0.0)), 'open_price': float(order_data.get('open_price', 0.0)),
                    'sl': float(order_data.get('sl_price', 0.0)), 'comment': order_data.get('comment'), 'comment_ai': ai_comment,
                    'magic': int(order_data.get('magic')) if order_data.get('magic') else None,
                    'last_updated': datetime.now().isoformat(), '_creation_timestamp': time.time(),
                    'signal_tf': signal_tf
                }
                ladder_prices = order_data.get('ladder_prices', {})
                if ladder_prices:
                    for i in range(1, 9):
                        val = ladder_prices.get(f'tp{i}', {}).get('price')
                        params[f'tp{i}_price'] = float(val) if val is not None else None
                columns = ', '.join(params.keys())
                placeholders = ', '.join(['?'] * len(params))
                cursor.execute(f"INSERT INTO open_orders ({columns}) VALUES ({placeholders})", tuple(params.values()))
                self._conn.commit()
                try:
                    newly_inserted_order = self.get_order_details(temp_id)
                    if newly_inserted_order:
                        pretty_data = json.dumps(newly_inserted_order, indent=4, ensure_ascii=False)
                        logger.debug(f"[DB_SNAPSHOT_PRE_REG] Data after pre-registration for temp_id {temp_id}:\n{pretty_data}")
                    else:
                        logger.warning(f"[DB_SNAPSHOT_PRE_REG] Failed to fetch pre-registered order {temp_id} immediately after insertion.")
                except Exception as log_e:
                    logger.error(f"[DB_SNAPSHOT_PRE_REG] Error during logging: {log_e}")
                logger.info(f"Pre-registered order with full data under temporary ID: {temp_id}")
                return temp_id
            except (sqlite3.Error, ValueError, TypeError) as e:
                logger.error(f"Failed to pre-register order with calculations: {e}", exc_info=True)
                self._conn.rollback()
                return ""
            finally:
                cursor.close()
    async def remove_pre_registered_order(self, temp_id: int):
        if self._db_conn is None: return
        if temp_id >= 0: return
        async with self._db_lock:
            cursor = self._conn.cursor()
            try:
                cursor.execute("DELETE FROM open_orders WHERE ticket = ?", (temp_id,))
                if cursor.rowcount > 0:
                    self._conn.commit()
                    logger.info(f"Successfully removed failed pre-registered order with temporary ID: {temp_id}")
            except sqlite3.Error as e:
                logger.error(f"DB error while removing pre-registered order {temp_id}: {e}", exc_info=True)
                self._conn.rollback()
            finally:
                cursor.close()
    async def clean_temporary_orders(self):
        if self._db_conn is None: return
        async with self._db_lock:
            cursor = self._conn.cursor()
            try:
                cursor.execute("DELETE FROM open_orders WHERE ticket < 0")
                if cursor.rowcount > 0:
                    self._conn.commit()
                    logger.info(f"Successfully cleaned {cursor.rowcount} temporary orders from the database.")
            except sqlite3.Error as e:
                logger.error(f"DB error while cleaning temporary orders: {e}", exc_info=True)
                self._conn.rollback()
            finally:
                cursor.close()
    def get_enhanced_portfolio(self) -> dict:
        if self._db_conn is None: return {}
        portfolio = {}
        try:
            with self._conn:
                cursor = self._conn.cursor()
                cursor.execute("SELECT * FROM open_orders")
                rows = cursor.fetchall()
                for row in rows:
                    order_dict = dict(row)
                    if row['comment_ai']:
                        order_dict['comment'] = row['comment_ai']
                    portfolio[row['ticket']] = order_dict
        except sqlite3.Error as e:
            logger.error("Failed to get enhanced portfolio from DB: %s", e, exc_info=True)
        return portfolio
    def get_order_details(self, ticket: int) -> Union[dict, None]:
        logger.debug(f"[DB-GET] get_order_details called for ticket: {ticket}")
        if self._db_conn is None:
            logger.debug(f"[DB-GET] DB connection is None. Cannot get details for ticket {ticket}.")
            return None
        try:
            with self._conn:
                cursor = self._conn.cursor()
                logger.debug(f"[DB_DEBUG] get_order_details: Searching for ticket {ticket} in 'open_orders'...")
                cursor.execute("SELECT * FROM open_orders WHERE ticket = ?", (ticket,))
                row = cursor.fetchone()
                if row:
                    logger.debug(f"[DB_DEBUG] get_order_details: FOUND ticket {ticket} in 'open_orders'.")
                else:
                    logger.debug(f"[DB_DEBUG] get_order_details: NOT FOUND in 'open_orders'. Searching 'historic_orders'...")
                    cursor.execute("SELECT * FROM historic_orders WHERE ticket = ?", (ticket,))
                    row = cursor.fetchone()
                    if row:
                        logger.debug(f"[DB_DEBUG] get_order_details: FOUND ticket {ticket} in 'historic_orders'.")
                    else:
                        logger.debug(f"[DB_DEBUG] get_order_details: Ticket {ticket} NOT FOUND in either table.")
                if row:
                    order_dict = dict(row)
                    if 'comment_ai' in order_dict and order_dict['comment_ai']:
                        order_dict['comment'] = order_dict['comment_ai']
                    return order_dict
        except sqlite3.Error as e:
            logger.error("Failed to get order details for ticket %d from DB: %s", ticket, e, exc_info=True)
        return None
    async def update_order_tp_level(self, ticket: int, new_level: int):
        if self._db_conn is None: return
        async with self._db_lock:
            cursor = self._conn.cursor()
            try:
                cursor.execute("SELECT comment_ai FROM open_orders WHERE ticket = ?", (ticket,))
                row = cursor.fetchone()
                if not row or not row['comment_ai']:
                    return
                current_comment = row['comment_ai']
                logger.debug(f"[TP_UPDATE_BEFORE] Ticket {ticket}: Current comment_ai is '{current_comment}'. Attempting to set L={new_level}.")
                new_comment = re.sub(r'L=\d+', f'L={new_level}', current_comment)
                if new_comment != current_comment:
                    cursor.execute("UPDATE open_orders SET comment_ai = ? WHERE ticket = ?", (new_comment, ticket))
                    self._conn.commit()
                    updated_order_details = self.get_order_details(ticket)
                    if updated_order_details:
                        pretty_data = json.dumps(updated_order_details, indent=4, ensure_ascii=False)
                        logger.debug(f"[TP_UPDATE_AFTER] Ticket {ticket}: DB state after commit:\n{pretty_data}")
                    else:
                        logger.warning(f"[TP_UPDATE_AFTER] Failed to fetch details for ticket {ticket} post-update.")
                    logger.info("Successfully updated TP level for ticket %d to 'L=%d'.", ticket, new_level)
            except sqlite3.Error as e:
                logger.error("DB error while updating TP level for ticket %d: %s", ticket, e, exc_info=True)
                self._conn.rollback()
            finally:
                cursor.close()
    async def proactive_update_tp_levels(self, current_prices: dict):
        logger.debug(f"[PROACTIVE_UPDATE] Running with {len(current_prices)} prices. Sample: {dict(list(current_prices.items())[:1])}")
        if self._db_conn is None: return
        orders_to_update = []
        try:
            with self._conn:
                cursor = self._conn.cursor()
                cursor.execute("SELECT * FROM open_orders WHERE ticket > 0 AND type IN ('buy', 'sell')")
                orders = cursor.fetchall()
                for order in orders:
                    comment_ai = order['comment_ai']
                    if not comment_ai or "L=" not in comment_ai: continue
                    match = re.search(r'L=(\d+)', comment_ai)
                    if not match: continue
                    current_level = int(match.group(1))
                    if current_level >= 8: continue
                    symbol = order['symbol']
                    price_data = current_prices.get(symbol)
                    if not price_data: continue
                    market_price = price_data.get('bid') if order['type'] == 'buy' else price_data.get('ask')
                    if market_price is None: continue
                    highest_triggered_level = -1
                    for i in range(8, current_level, -1):
                        tp_price = order[f'tp{i}_price']
                        if tp_price is None: continue
                        is_hit = (order['type'] == 'buy' and market_price >= tp_price) or \
                                 (order['type'] == 'sell' and market_price <= tp_price)
                        logger.debug(
                            f"[TP_CHECK] Ticket {order['ticket']} (L={current_level}): "
                            f"Comparing Market Price {market_price} against TP{i} Price {tp_price}. "
                            f"Result: {'HIT!' if is_hit else 'Not hit.'}"
                        )
                        if is_hit:
                            highest_triggered_level = i
                            break
                    if highest_triggered_level > current_level:
                        logger.info(
                            f"[TP_TRIGGER] Ticket {order['ticket']}: Price crossed TP{highest_triggered_level}. "
                            f"Queueing update from L={current_level} to L={highest_triggered_level}."
                        )
                        orders_to_update.append((order['ticket'], highest_triggered_level))
        except (sqlite3.Error, IndexError) as e:
            logger.error(f"Error reading orders for proactive TP update: {e}", exc_info=True)
        for ticket, new_level in orders_to_update:
            await self.update_order_tp_level(ticket, new_level)
    def get_historic_trades_from_db(self, limit=100) -> Dict:
        if self._db_conn is None: return {}
        trades = {}
        try:
            with self._conn:
                cursor = self._conn.cursor()
                cursor.execute("SELECT * FROM historic_orders ORDER BY close_time DESC LIMIT ?", (limit,))
                rows = cursor.fetchall()
                for row in rows:
                    trades[str(row['ticket'])] = dict(row)
        except sqlite3.Error as e:
            logger.error(f"Failed to get historic trades from DB: {e}", exc_info=True)
        return trades
    def update_order(self, ticket: int, status: str, close_time: str = None):
        if self._db_conn is None: return
        if status == 'closed':
            try:
                with self._conn:
                    cursor = self._conn.cursor()
                    cursor.execute("SELECT ticket FROM open_orders WHERE ticket = ?", (ticket,))
                    row = cursor.fetchone()
                    if row:
                        cursor.execute("DELETE FROM open_orders WHERE ticket = ?", (ticket,))
                        logger.info(f"Eager Sync: Immediately removed order {ticket} from open_orders (Closed).")
                    else:
                        logger.debug(f"Eager Sync: Order {ticket} not found in open_orders (maybe already synced).")
            except sqlite3.Error as e:
                logger.error(f"Failed to eager-update order {ticket}: {e}", exc_info=True)
    async def update_management_status(self, ticket: int, new_status_code: str):
        if self._db_conn is None: return
        async with self._db_lock:
            cursor = self._conn.cursor()
            try:
                cursor.execute("SELECT comment_ai FROM open_orders WHERE ticket = ?", (ticket,))
                row = cursor.fetchone()
                if not row or not row['comment_ai']:
                    logger.warning(f"Cannot update management status for ticket {ticket}: comment_ai not found.")
                    return
                current_comment = row['comment_ai']
                if f'M={new_status_code}' in current_comment:
                    logger.debug(f"Management status for ticket {ticket} is already '{new_status_code}'. No update needed.")
                    return
                if 'M=' in current_comment:
                    new_comment = re.sub(r'M=[A-Z0-9]+', f'M={new_status_code}', current_comment)
                else:
                    new_comment = f"{current_comment};M={new_status_code}"
                cursor.execute("UPDATE open_orders SET comment_ai = ? WHERE ticket = ?", (new_comment, ticket))
                self._conn.commit()
                logger.info(f"Successfully updated management status for ticket {ticket} to '{new_status_code}'.")
            except sqlite3.Error as e:
                logger.error(f"DB error while updating management status for ticket {ticket}: {e}", exc_info=True)
                self._conn.rollback()
            finally:
                cursor.close()
    def close(self):
        if self._db_conn:
            self._db_conn.close()
            self._db_conn = None
            logger.debug("OrderDB connection closed.")
    def reinitialize(self):
        self.close()
        self.init_timestamp = time.time()
        self._connect()
        self._create_tables_if_needed()
        logger.debug("OrderDBManager re-initialized.")
order_db_manager = OrderDBManager()