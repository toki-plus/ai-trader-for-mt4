import os
import re
import json
import logging
from dotenv import load_dotenv, find_dotenv
logger = logging.getLogger(__name__)
class ConfigManager:
    def __init__(self, config_path, profiles_path):
        self.config_path = config_path
        self.profiles_path = profiles_path
        self.config = {}
        self.profiles = []
        self.models_data = []
        self.model_credentials = {}
        load_dotenv()
        self.load_configuration()
    def load_configuration(self):
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                self.config = json.load(f)
            with open(self.profiles_path, 'r', encoding='utf-8') as f:
                self.profiles = json.load(f)
            self.models_data = self.config.get("models", [])
            for model in self.models_data:
                model_id = model.get("model_id")
                api_key_env = model.get("api_key_env")
                api_base_url_env = model.get("api_base_url_env")
                self.model_credentials[model_id] = {
                    "api_key": os.getenv(api_key_env, ""),
                    "base_url": os.getenv(api_base_url_env, "")
                }
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.error("Error loading configuration: %s", e)
            self.config = {"agent_config": {}}
            self.profiles = []
    def get_agent_config(self):
        return self.config.get("agent_config", {})
    def save_agent_config(self, agent_config_dict):
        self.config['agent_config'] = agent_config_dict
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error("Could not save agent config to %s: %s", self.config_path, e)
    def save_env_and_credentials(self, env_updates, model_credentials):
        self.model_credentials = model_credentials
        for model_spec in self.models_data:
            model_id = model_spec.get('model_id')
            api_key_env = model_spec.get('api_key_env')
            base_url_env = model_spec.get('api_base_url_env')
            if model_id in self.model_credentials:
                if api_key_env:
                    env_updates[api_key_env] = self.model_credentials[model_id].get('api_key', '')
                if base_url_env:
                    env_updates[base_url_env] = self.model_credentials[model_id].get('base_url', '')
        self._update_env_file(env_updates)
    def _update_env_file(self, updates: dict):
        env_file = find_dotenv()
        if not env_file: env_file = ".env"
        try:
            lines = []
            if os.path.exists(env_file):
                with open(env_file, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
            updated_keys = set()
            for i, line in enumerate(lines):
                match = re.match(r'^\s*([a-zA-Z0-9_]+)\s*=', line)
                if match:
                    key = match.group(1)
                    if key in updates:
                        lines[i] = f'{key}="{updates[key]}"\n'
                        updated_keys.add(key)
            for key, value in updates.items():
                if key not in updated_keys:
                    lines.append(f'{key}="{value}"\n')
            with open(env_file, 'w', encoding='utf-8') as f:
                f.writelines(lines)
        except Exception as e:
            logger.error("Error updating .env file: %s", e)