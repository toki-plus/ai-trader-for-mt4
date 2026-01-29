import os
import re
import sys
import json
import shutil
import logging
import asyncio
import markdown
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QGroupBox, QLabel, QLineEdit, QPushButton, QTextBrowser,
    QComboBox, QMessageBox, QFileDialog,
    QStatusBar, QTableWidget, QTableWidgetItem, QHeaderView, QMenuBar
)
from PyQt5.QtCore import pyqtSlot, Qt, QTimer
from PyQt5.QtGui import QIcon, QColor, QTextCursor
from .style import STYLESHEET
from .chart_viewer import ChartWindow
from ..app.trading_engine import TradingEngine
from ..services.config_manager import ConfigManager
import resources.resources_rc
logger = logging.getLogger(__name__)
class MainWindow(QMainWindow):
    def __init__(self, engine: TradingEngine, config_manager: ConfigManager, loop: asyncio.AbstractEventLoop):
        super().__init__()
        self.engine = engine
        self.config_manager = config_manager
        self.loop = loop
        self.trading_task = None
        if not os.path.exists('.cache'):
            try:
                os.makedirs('.cache')
            except Exception as e:
                sys.exit(f"Failed to create '.cache' directory: {e}")
        self.setWindowTitle("AI Trader for MT4")
        self.setGeometry(100, 100, 1500, 900)
        self.setWindowIcon(QIcon(":/icons/logo.png"))
        self.setStyleSheet(STYLESHEET)
        self.open_charts = {}
        self.chart_tasks = {}
        self.models_data = self.config_manager.models_data
        self.strategy_profiles = self.config_manager.profiles
        self.model_credentials = self.config_manager.model_credentials
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        main_layout = QVBoxLayout(self.central_widget)
        top_layout = QHBoxLayout()
        config_pane_widget = QWidget()
        config_pane = QVBoxLayout(config_pane_widget)
        self.create_connection_group(config_pane)
        self.create_api_group(config_pane)
        self.create_agent_group(config_pane)
        self.create_control_group(config_pane)
        config_pane.addStretch(1)
        log_group = QGroupBox("Logs")
        log_layout = QVBoxLayout()
        self.log_browser = QTextBrowser()
        self.log_browser.setOpenExternalLinks(True)
        log_layout.addWidget(self.log_browser)
        log_group.setLayout(log_layout)
        top_layout.addWidget(config_pane_widget, stretch=2)
        top_layout.addWidget(log_group, stretch=1)
        self.positions_group = self.create_positions_group()
        main_layout.addLayout(top_layout, stretch=1)
        main_layout.addWidget(self.positions_group, stretch=1)
        self.create_status_bar()
        self.load_configuration_into_ui()
        self.engine.status_update.connect(self.update_status_label)
        self.engine.positions_update.connect(self.update_positions_table)
        self.engine.connection_status.connect(self.update_connection_status)
        self.engine.finished.connect(self.on_engine_finished)
        self.model_combo.currentIndexChanged.connect(self.on_model_changed)
        self.profile_combo.currentIndexChanged.connect(self.on_profile_changed)
        self.llm_api_key_input.textChanged.connect(self._update_credentials_in_memory)
        self.llm_base_url_input.textChanged.connect(self._update_credentials_in_memory)
    def create_connection_group(self, parent_layout):
        group = QGroupBox("MT4 Connection Settings")
        layout = QGridLayout()
        self.mt4_path_input = QLineEdit()
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self.browse_mt4_path)
        self.connection_status_indicator = QLabel("🔴 Disconnected")
        self.connection_status_indicator.setObjectName("status_label_stopped")
        layout.addWidget(QLabel("MT4 Data Path:"), 0, 0)
        layout.addWidget(self.mt4_path_input, 0, 1)
        layout.addWidget(browse_btn, 0, 2)
        layout.addWidget(QLabel("Connection:"), 1, 0)
        layout.addWidget(self.connection_status_indicator, 1, 1)
        group.setLayout(layout)
        parent_layout.addWidget(group)
    def create_api_group(self, parent_layout):
        group = QGroupBox("API Settings")
        layout = QGridLayout()
        self.llm_api_key_input = QLineEdit()
        self.llm_api_key_input.setEchoMode(QLineEdit.Password)
        self.llm_base_url_input = QLineEdit()
        self.jina_api_key_input = QLineEdit()
        self.jina_api_key_input.setEchoMode(QLineEdit.Password)
        layout.addWidget(QLabel("LLM API Key:"), 0, 0)
        layout.addWidget(self.llm_api_key_input, 0, 1)
        layout.addWidget(QLabel("LLM API Base URL:"), 1, 0)
        layout.addWidget(self.llm_base_url_input, 1, 1)
        layout.addWidget(QLabel("Jina API Key:"), 2, 0)
        layout.addWidget(self.jina_api_key_input, 2, 1)
        group.setLayout(layout)
        parent_layout.addWidget(group)
    def create_agent_group(self, parent_layout):
        group = QGroupBox("AI Agent Configuration")
        layout = QGridLayout()
        self.model_combo = QComboBox()
        self.profile_combo = QComboBox()
        self.profile_description_label = QLabel("Description: -")
        self.profile_description_label.setWordWrap(True)
        self.symbols_input = QLineEdit()
        self.symbols_input.setToolTip("Comma-separated list of symbols to trade (e.g., EURUSD,GBPUSD,XAUUSD).")
        layout.addWidget(QLabel("Enabled Model:"), 0, 0)
        layout.addWidget(self.model_combo, 0, 1)
        layout.addWidget(QLabel("Strategy Profile:"), 1, 0)
        layout.addWidget(self.profile_combo, 1, 1)
        layout.addWidget(self.profile_description_label, 2, 1)
        layout.addWidget(QLabel("Trading Symbols:"), 3, 0)
        layout.addWidget(self.symbols_input, 3, 1)
        group.setLayout(layout)
        parent_layout.addWidget(group)
    def create_control_group(self, parent_layout):
        group = QGroupBox("Run Control")
        layout = QHBoxLayout()
        self.run_button = QPushButton("RUN")
        self.run_button.setObjectName("PrimaryButton")
        self.run_button.clicked.connect(self.start_trading)
        self.stop_button = QPushButton("STOP")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_trading)
        self.status_label = QLabel("Idle")
        self.status_label.setObjectName("status_label_stopped")
        clear_cache_button = QPushButton("Clear Cache")
        clear_cache_button.clicked.connect(self.clear_cache)
        layout.addWidget(self.run_button)
        layout.addWidget(self.stop_button)
        layout.addStretch()
        layout.addWidget(clear_cache_button)
        layout.addStretch()
        layout.addWidget(QLabel("Status:"))
        layout.addWidget(self.status_label)
        group.setLayout(layout)
        parent_layout.addWidget(group)
    def create_status_bar(self):
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")
    def create_positions_group(self):
        group = QGroupBox("MT4 Open Positions")
        layout = QVBoxLayout()
        self.positions_table = QTableWidget()
        self.positions_table.setColumnCount(18)
        headers = [
            "Ticket", "Symbol", "Side", "Lots", "Entry", "Market", "PNL", "SL", "Target", "Comment",
            "TP1", "TP2", "TP3", "TP4", "TP5", "TP6", "TP7", "TP8"
        ]
        self.positions_table.setHorizontalHeaderLabels(headers)
        self.positions_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.positions_table.setAlternatingRowColors(True)
        header = self.positions_table.horizontalHeader()
        header.setSectionResizeMode(9, QHeaderView.Stretch)
        for i in range(self.positions_table.columnCount()):
            if i != 9:
                header.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        self.positions_table.setSortingEnabled(True)
        layout.addWidget(self.positions_table)
        group.setLayout(layout)
        self.positions_table.itemDoubleClicked.connect(self.on_position_double_clicked)
        return group
    def clear_cache(self):
        cache_dir = '.cache'
        if os.path.exists(cache_dir):
            reply = QMessageBox.question(self, 'Confirm Clear Cache', "Are you sure you want to clear all data in the '.cache' directory?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.Yes:
                try:
                    shutil.rmtree(cache_dir)
                    os.makedirs(cache_dir)
                    logger.info("Cache directory '.cache' has been successfully cleared and reset.")
                except Exception as e:
                    logger.error(f"Error clearing cache directory: {e}")
        else:
            try:
                os.makedirs(cache_dir)
                logger.info(f"Cache directory '{cache_dir}' did not exist and has now been created.")
            except Exception as e:
                logger.error(f"Error creating non-existent cache directory: {e}")
    def browse_mt4_path(self):
        path = QFileDialog.getExistingDirectory(self, "Select MT4 MQL4/Files Directory")
        if path:
            self.mt4_path_input.setText(path)
    def on_model_changed(self, index):
        if not self.models_data or index < 0 or index >= len(self.models_data):
            return
        model_data = self.model_combo.itemData(index)
        creds = self.model_credentials.get(model_data.get('model_id'), {})
        self.llm_api_key_input.blockSignals(True)
        self.llm_base_url_input.blockSignals(True)
        self.llm_api_key_input.setText(creds.get('api_key', ''))
        self.llm_base_url_input.setText(creds.get('base_url', ''))
        self.llm_api_key_input.blockSignals(False)
        self.llm_base_url_input.blockSignals(False)
    def on_profile_changed(self, index):
        if self.strategy_profiles and 0 <= index < len(self.strategy_profiles):
            profile = self.profile_combo.itemData(index)
            desc = f"Desc: {profile.get('description', 'N/A')}"
            self.profile_description_label.setText(desc)
            self.profile_description_label.setToolTip(desc)
    def _update_credentials_in_memory(self):
        if (index := self.model_combo.currentIndex()) >= 0:
            model_id = self.model_combo.itemData(index).get('model_id')
            if model_id in self.model_credentials:
                self.model_credentials[model_id]['api_key'] = self.llm_api_key_input.text()
                self.model_credentials[model_id]['base_url'] = self.llm_base_url_input.text()
    def load_configuration_into_ui(self):
        try:
            agent_config = self.config_manager.get_agent_config()
            self.model_combo.clear()
            for model in self.models_data:
                self.model_combo.addItem(model.get("display_name"), model)
            self.profile_combo.clear()
            for profile in self.strategy_profiles:
                self.profile_combo.addItem(profile.get("name"), profile)
            self.symbols_input.setText(", ".join(agent_config.get("trading_symbols", [])))
            self.mt4_path_input.setText(os.getenv("MT4_DATA_PATH", ""))
            self.jina_api_key_input.setText(os.getenv("JINA_API_KEY", ""))
            if (last_model_id := agent_config.get("last_selected_model_id")):
                for i in range(self.model_combo.count()):
                    if self.model_combo.itemData(i).get('model_id') == last_model_id:
                        self.model_combo.setCurrentIndex(i)
                        break
            if (last_profile_name := agent_config.get("last_selected_profile_name")):
                for i in range(self.profile_combo.count()):
                    if self.profile_combo.itemData(i).get('name') == last_profile_name:
                        self.profile_combo.setCurrentIndex(i)
                        break
            if self.model_combo.count() > 0:
                self.on_model_changed(self.model_combo.currentIndex())
            if self.profile_combo.count() > 0:
                self.on_profile_changed(self.profile_combo.currentIndex())
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load configuration into UI: {e}")
    def save_configuration(self):
        try:
            model_index = self.model_combo.currentIndex()
            profile_index = self.profile_combo.currentIndex()
            agent_config = {
                "last_selected_model_id": self.model_combo.itemData(model_index).get('model_id') if model_index >= 0 else None,
                "last_selected_profile_name": self.profile_combo.itemData(profile_index).get('name') if profile_index >= 0 else None,
                "trading_symbols": [s for s in re.split(r'\s*,\s*', self.symbols_input.text().strip()) if s]
            }
            self.config_manager.save_agent_config(agent_config)
            env_updates = {
                "MT4_DATA_PATH": self.mt4_path_input.text(),
                "JINA_API_KEY": self.jina_api_key_input.text()
            }
            self.config_manager.save_env_and_credentials(env_updates, self.model_credentials)
            self.status_bar.showMessage("Configuration saved.", 3000)
        except Exception as e:
            QMessageBox.warning(self, "Save Error", f"Could not save configuration: {e}")
    @pyqtSlot(str, str)
    def update_status_label(self, text, style_id):
        self.status_label.setText(text)
        self.status_label.setObjectName(style_id)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
        self.status_bar.showMessage(text)
    @pyqtSlot(bool)
    def update_connection_status(self, is_connected):
        if is_connected:
            self.connection_status_indicator.setText("🟢 Connected")
            self.connection_status_indicator.setObjectName("status_label_ok")
        else:
            self.connection_status_indicator.setText("🔴 Disconnected")
            self.connection_status_indicator.setObjectName("status_label_error")
        self.connection_status_indicator.style().unpolish(self.connection_status_indicator)
        self.connection_status_indicator.style().polish(self.connection_status_indicator)
    def _format_prepare_flow_result(self, parsed_result: dict) -> str:
        data = parsed_result.get('data', {})
        snapshot = data.get('portfolio_snapshot', {})
        positions = snapshot.get('positions', {})
        proposals = data.get('management_proposals', [])
        stale_orders = data.get('stale_pending_orders_to_delete', [])
        risk = data.get('portfolio_risk', {})
        return (
            f"<b>Portfolio:</b> {len(positions)} open, "
            f"<b>Proposals:</b> {len(proposals)}, "
            f"<b>Stale:</b> {len(stale_orders)}, "
            f"<b>Risk:</b> {risk.get('risk_percentage', 0)}%"
        )
    def _format_scan_flow_result(self, parsed_result: dict) -> str:
        data = parsed_result.get('data', {})
        total = len(data)
        active = sum(1 for v in data.values() if v.get('status') == 'success')
        inactive = total - active
        return f"Scanned {total} symbols. <b>Active:</b> {active}, <b>Inactive:</b> {inactive}."
    @pyqtSlot(list)
    def append_log_message(self, log_data_list: list):
        for log_data in log_data_list:
            log_type = log_data.get("type", "unknown")
            content = log_data.get("content", {})
            message = log_data.get("message", "")
            html = ""
            if log_type == "cycle_start":
                time_str = content.get("time", "")
                html = f"""
                <div style="margin: 10px 0 5px 0; border-top: 1px solid #3B3F51; padding-top: 5px;">
                    <p style="color:#888; margin: 0;"><b>New Cycle Started at {time_str}</b></p>
                </div>
                """
            elif log_type == "news_summary":
                html = f"<div style='margin-bottom: 8px;'>📰 <font color='#F8D800'><b>News:</b></font> {message}</div>"
            elif log_type == "thought":
                thought = content.get('thought', '')
                tool_calls = content.get('tool_calls', [])
                thought_html = ""
                if thought:
                    md_html = markdown.markdown(thought, extensions=['fenced_code', 'tables'])
                    thought_html = f"<div>🤔 <font color='#97FEFA'><b>AI Thought:</b></font> {md_html}</div>"
                tool_calls_html = ""
                if tool_calls:
                    calls_list = []
                    for tc in tool_calls:
                        tool_name = tc.get('name')
                        args = tc.get('args', {})
                        params_str = json.dumps(args).replace('"', '&quot;')
                        if len(params_str) > 150: params_str = params_str[:150] + '...)'
                        summary = ""
                        if parsed_result := content.get('parsed_tool_result', {}):
                            if parsed_result.get('status') == 'error':
                                summary = f"<font color='#FE2C55'>Error: {parsed_result.get('message', 'Unknown error')}</font>"
                            elif tool_name == 'execute_prepare_flow':
                                summary = self._format_prepare_flow_result(parsed_result)
                            elif tool_name == 'execute_scan_flow':
                                summary = self._format_scan_flow_result(parsed_result)
                            else:
                                result_str = json.dumps(parsed_result)
                                summary = result_str[:250] + "..." if len(result_str) > 250 else result_str
                        calls_list.append(f"""
                        <div style="background-color:#24283B; border-left: 3px solid #F8D800; padding: 8px 12px; margin: 8px 0; border-radius: 4px;">
                            <div>🛠️ <font color='#F8D800'><b>{tool_name}</b></font><code style="color:#D0D0D0;">({params_str})</code></div>
                        </div>
                        """)
                    tool_calls_html = "".join(calls_list)
                html = thought_html + tool_calls_html
            elif log_type == "observation":
                tool_name = content.get('tool_name', 'Unknown Tool')
                parsed_result = content.get('parsed_tool_result', {})
                summary = ""
                if parsed_result.get('status') == 'error':
                    summary = f"<font color='#FE2C55'>Error: {parsed_result.get('message', 'Unknown error')}</font>"
                elif tool_name == 'execute_prepare_flow':
                    summary = self._format_prepare_flow_result(parsed_result)
                elif tool_name == 'execute_scan_flow':
                    summary = self._format_scan_flow_result(parsed_result)
                else:
                    result_str = json.dumps(parsed_result)
                    summary = result_str[:250] + "..." if len(result_str) > 250 else result_str
                html = f"""
                <div style="background-color:#24283B; border-left: 3px solid #25F4EE; padding: 8px 12px; margin-top: -8px; margin-bottom: 8px; margin-left: 20px; border-radius: 4px;">
                    📬 <font color='#25F4EE'><b>Result:</b></font> {summary}
                </div>
                """
            elif log_type == "final_answer":
                text = content.get('text', '')
                md_html = markdown.markdown(text, extensions=['fenced_code', 'tables'])
                html = f"""
                <div style="background-color:#24283B; border: 1px solid #4A4E60; padding: 12px; margin-top: 10px; border-radius: 6px;">
                    <div style="margin-bottom: 8px; border-bottom: 1px solid #4A4E60; padding-bottom: 8px;">
                        ✅ <font color='#47C97D'><b>Final Summary & Decision</b></font>
                    </div>
                    <div style="font-size: 9.5pt; line-height: 1.5;">
                        {md_html}
                    </div>
                </div>
                """
            elif log_type == "trade_action":
                action = content.get('action', 'N/A')
                ticket = content.get('ticket', 'N/A')
                symbol = content.get('tool_args', {}).get('symbol', 'N/A')
                lots = content.get('tool_args', {}).get('lots', 'N/A')
                color = '#47C97D' if 'buy' in action.lower() else '#FE2C55' if 'sell' in action.lower() else '#F8D800'
                html = f"<div style='margin-top:5px;'>📈 <font color='{color}'><b>Trade Action: {action.upper()}</b></font> on {symbol} | Lots: {lots}, Ticket: {ticket}</div>"
            else:
                level = log_data.get("level", "INFO").upper()
                if level not in ["WARNING", "ERROR", "CRITICAL"]:
                    continue
                color_map = {"WARNING": "#F8D800", "ERROR": "#FE2C55", "CRITICAL": "#FE2C55"}
                color = color_map.get(level, "#E0E0E0")
                icon = "⚠️" if level == "WARNING" else "🔴"
                html = f"<font color='{color}'>{icon} {message}</font>"
            if html:
                self.log_browser.append(html)
        self.log_browser.moveCursor(QTextCursor.End)
    def start_trading(self):
        logger.info("MainWindow: 'RUN' button clicked.")
        if self.trading_task and not self.trading_task.done():
            logger.warning("MainWindow: Trading task is already running.")
            return
        config = self.get_current_config_from_ui()
        if not config:
            logger.error("MainWindow: Configuration validation failed. Aborting start.")
            return
        self.set_controls_enabled(False)
        self.log_browser.clear()
        logger.info("MainWindow: Creating and starting TradingEngine task...")
        self.trading_task = self.loop.create_task(self.engine.start_with_loop(config, self.loop))
    @pyqtSlot()
    def on_engine_finished(self):
        logger.info("MainWindow: Received 'finished' signal from engine.")
        self.set_controls_enabled(True)
        self.trading_task = None
    def stop_trading(self):
        logger.info("MainWindow: 'STOP' button clicked.")
        if self.trading_task and not self.trading_task.done():
            logger.info("MainWindow: Requesting engine to stop...")
            self.engine.stop()
            self.update_status_label("Stopping...", "status_label_pending")
            self.stop_button.setEnabled(False)
        else:
            logger.warning("MainWindow: No running trading task to stop.")
    def set_controls_enabled(self, enabled):
        self.run_button.setEnabled(enabled)
        self.stop_button.setEnabled(not enabled)
        for groupbox in self.findChildren(QGroupBox):
            if groupbox.title() not in ["Run Control", "Logs", "MT4 Open Positions"]:
                groupbox.setEnabled(enabled)
        if enabled:
            self.update_status_label("Stopped", "status_label_stopped")
            if hasattr(self, 'positions_table'):
                self.update_positions_table({})
            self.update_connection_status(False)
    def get_current_config_from_ui(self):
        if not os.path.isdir(self.mt4_path_input.text()):
            QMessageBox.warning(self, "Validation Error", "MT4 Data Path is not a valid directory.")
            return None
        if not (llm_api_key := self.llm_api_key_input.text()):
            QMessageBox.warning(self, "Validation Error", "LLM API Key cannot be empty.")
            return None
        os.environ['TEMP_LLM_API_KEY'] = llm_api_key
        os.environ['TEMP_LLM_API_BASE'] = self.llm_base_url_input.text() or ""
        os.environ['JINA_API_KEY'] = self.jina_api_key_input.text() or ""
        if (model_index := self.model_combo.currentIndex()) < 0:
            QMessageBox.warning(self, "Validation Error", "Please select an AI model.")
            return None
        if (profile_index := self.profile_combo.currentIndex()) < 0:
            QMessageBox.warning(self, "Validation Error", "Please select a Strategy Profile.")
            return None
        return {
            "mt4_data_path": self.mt4_path_input.text(),
            "enabled_model": self.model_combo.itemData(model_index),
            "strategy_profile": self.profile_combo.itemData(profile_index),
            "trading_symbols": [s for s in re.split(r'\s*,\s*', self.symbols_input.text().strip()) if s]
        }
    def closeEvent(self, event):
        self.save_configuration()
        if self.trading_task and not self.trading_task.done():
            reply = QMessageBox.question(
                self, 'Confirm Exit',
                "The trading agent is still running. Are you sure you want to exit?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                logger.info("User confirmed exit. Initiating shutdown sequence...")
                self.stop_trading()
                logger.warning("Worker thread did not stop gracefully within 5 seconds. Forcing quit.")
                self.thread.quit()
                self.thread.wait(1000)
                logger.info("Shutdown sequence complete. Closing application.")
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()
    @pyqtSlot(int)
    def on_chart_closed(self, ticket_id: int):
        logger.debug(f"Chart window for ticket {ticket_id} is being closed. Cleaning up resources.")
        task = self.chart_tasks.pop(ticket_id, None)
        if task and not task.done():
            if self.loop and self.loop.is_running():
                task.cancel()
                logger.info(f"Requested cancellation for chart task (ticket: {ticket_id}).")
            else:
                logger.warning(f"Engine loop not running, cannot cancel task for ticket {ticket_id}.")
        if ticket_id in self.open_charts:
            del self.open_charts[ticket_id]
            logger.debug(f"Removed chart window for ticket {ticket_id} from tracking dictionary.")
    @pyqtSlot(QTableWidgetItem)
    def on_position_double_clicked(self, item):
        if not item:
            return
        if not self.loop or not self.loop.is_running():
            QMessageBox.warning(self, "Engine Not Running", "Please start the trading engine before opening a chart.")
            return
        row = item.row()
        ticket_item = self.positions_table.item(row, 0)
        if not ticket_item:
            return
        try:
            ticket_id = int(ticket_item.text())

            if ticket_id in self.open_charts:
                chart_window = self.open_charts[ticket_id]
                chart_window.activateWindow()
                chart_window.raise_()
                logger.info(f"Chart for ticket {ticket_id} is already open. Activating it.")
                return
            logger.info(f"Launching chart for ticket {ticket_id} ...")
            chart_window = ChartWindow(ticket_id=ticket_id)
            self.open_charts[ticket_id] = chart_window
            chart_window.destroyed.connect(lambda _, tid=ticket_id: self.on_chart_closed(tid))
            chart_window.show()
            coro = chart_window.load_data()
            task = self.loop.create_task(coro)
            self.chart_tasks[ticket_id] = task
        except (ValueError, TypeError) as e:
            logger.error(f"Could not parse ticket ID or create chart window: {e}", exc_info=True)
            QMessageBox.critical(self, "Error", f"Failed to open chart for ticket '{ticket_item.text()}':\n\n{e}")
    @pyqtSlot(dict)
    def update_positions_table(self, positions):
        self.positions_table.setSortingEnabled(False)
        self.positions_table.setRowCount(0)
        if not positions:
            self.positions_table.setSortingEnabled(True)
            return
        def create_item(text, color=QColor("white")):
            item = QTableWidgetItem()
            item.setData(Qt.DisplayRole, str(text))
            item.setData(Qt.ForegroundRole, color)
            item.setData(Qt.TextAlignmentRole, Qt.AlignCenter)
            return item
        for ticket in sorted(positions.keys(), key=lambda x: int(x)):
            pos = positions[ticket]
            row = self.positions_table.rowCount()
            self.positions_table.insertRow(row)
            profit = pos.get('profit') or 0.0
            pnl_color = QColor("white")
            if profit > 0:
                pnl_color = QColor("#47C97D")
            elif profit < 0:
                pnl_color = QColor("#FE2C55")
            self.positions_table.setItem(row, 0, create_item(ticket))
            self.positions_table.setItem(row, 1, create_item(pos.get('symbol', '')))
            self.positions_table.setItem(row, 2, create_item(pos.get('type', '')))
            self.positions_table.setItem(row, 3, create_item(f"{pos.get('lots', 0.0):.2f}"))
            self.positions_table.setItem(row, 4, create_item(f"{pos.get('open_price', 0.0):.5f}"))
            self.positions_table.setItem(row, 5, create_item(f"{pos.get('current_price', 0.0):.5f}", QColor("#97FEFA")))
            self.positions_table.setItem(row, 6, create_item(f"{profit:.2f}", pnl_color))
            self.positions_table.setItem(row, 7, create_item(f"{(pos.get('sl') or 0.0):.5f}"))
            next_tp_profit = pos.get('next_tp_profit')
            next_tp_text = f"{next_tp_profit:.2f}" if next_tp_profit is not None else "-"
            next_tp_color = QColor("#47C97D") if next_tp_profit is not None else QColor("white")
            self.positions_table.setItem(row, 8, create_item(next_tp_text, next_tp_color))
            self.positions_table.setItem(row, 9, create_item(pos.get('comment', '')))
            for i in range(1, 9):
                tp_price = pos.get(f'tp{i}_price')
                tp_text = f"{tp_price:.5f}" if tp_price is not None and tp_price > 0 else "-"
                self.positions_table.setItem(row, 9 + i, create_item(tp_text))
        self.positions_table.setSortingEnabled(True)