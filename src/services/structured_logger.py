import os
import json
from datetime import datetime
class StructuredLogger:
    def __init__(self, base_log_dir="logs"):
        self.base_log_dir = base_log_dir
        self.current_log_file = None
        self.current_trade_log_file = None
        self.current_portfolio_log_file = None
        self._ui_callback = None
    def register_ui_callback(self, callback):
        self._ui_callback = callback
    def _ensure_dir(self, file_path):
        directory = os.path.dirname(file_path)
        if not os.path.exists(directory):
            os.makedirs(directory)
    def start_cycle(self, agent_signature: str, current_time: datetime):
        date_str = current_time.strftime("%Y-%m-%d")
        time_str = current_time.strftime("%H-%M-%S")
        log_filename = f"{time_str}.jsonl"
        self.current_log_file = os.path.join(self.base_log_dir, "thinking", agent_signature, date_str, log_filename)
        self._ensure_dir(self.current_log_file)
        trade_log_filename = "trades.jsonl"
        self.current_trade_log_file = os.path.join(self.base_log_dir, "trades", agent_signature, trade_log_filename)
        self._ensure_dir(self.current_trade_log_file)
        portfolio_log_filename = "portfolio_snapshots.jsonl"
        self.current_portfolio_log_file = os.path.join(self.base_log_dir, "portfolio", agent_signature, portfolio_log_filename)
        self._ensure_dir(self.current_portfolio_log_file)
    def _append_log(self, file_path: str, log_data: dict):
        if not file_path:
            return
        log_data['log_timestamp_utc'] = datetime.utcnow().isoformat()
        try:
            with open(file_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(log_data, ensure_ascii=False) + '\n')
        except Exception as e:
            print(f"Failed to write to log file {file_path}: {e}")
        if self._ui_callback:
            try:
                self._ui_callback(log_data)
            except Exception as e:
                print(f"Error in logger UI callback: {e}")
    def log_thought(self, thought_process: dict):
        self._append_log(self.current_log_file, {"type": "thought", "content": thought_process})
    def log_observation(self, observation: dict):
        self._append_log(self.current_log_file, {"type": "observation", "content": observation})
    def log_final_answer(self, final_answer: str):
        self._append_log(self.current_log_file, {"type": "final_answer", "content": {"text": final_answer}})
    def log_trade_action(self, trade_payload: dict):
        self._append_log(self.current_trade_log_file, {"type": "trade_action", "content": trade_payload})
    def log_portfolio_snapshot(self, portfolio_data: dict):
        self._append_log(self.current_portfolio_log_file, {"type": "portfolio_snapshot", "content": portfolio_data})
logger = StructuredLogger()