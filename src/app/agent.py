import json
import logging
from datetime import datetime
from openai import AsyncOpenAI
from typing import Any, Dict, List, Optional
from inspect import signature, Parameter
from src.tools import get_all_tools
from .prompts import get_agent_system_prompt_mt4, STOP_SIGNAL
logger = logging.getLogger(__name__)
def _parse_tool_result(tool_output: Any) -> Dict:
    if isinstance(tool_output, dict):
        return tool_output
    try:
        return {"status": "success", "data": str(tool_output)}
    except Exception as e:
        return {"status": "error", "message": f"Failed to parse tool output: {e}. Original output: {str(tool_output)}"}
class BaseAgentMT4:
    _is_running = True
    def __init__(self, signature: str, basemodel: str, trading_symbols: List[str], openai_api_key: str, openai_base_url: Optional[str] = None, strategy_profile: Optional[Dict] = None, **kwargs):
        self.signature = signature
        self.basemodel = basemodel
        self.trading_symbols = trading_symbols
        self.openai_api_key = openai_api_key
        self.openai_base_url = openai_base_url
        self.strategy_profile = strategy_profile
        self.max_steps = kwargs.get("max_steps")
        self.tools: List[Any] = []
        self.tool_map: Dict[str, Any] = {}
        self.client: Optional[AsyncOpenAI] = None
        self.system_prompt: Optional[str] = None
        self.openai_tools: List[Dict] = []
    def _create_tool_schemas(self, tool_functions: List[callable]) -> List[Dict]:
        schemas = []
        for func in tool_functions:
            try:
                sig = signature(func)
                properties = {}
                required = []
                for name, param in sig.parameters.items():
                    param_type = 'string'
                    type_hint = param.annotation
                    if type_hint == int:
                        param_type = 'integer'
                    elif type_hint == float:
                        param_type = 'number'
                    elif type_hint == bool:
                        param_type = 'boolean'
                    elif hasattr(type_hint, '__origin__') and type_hint.__origin__ in (list, List):
                        param_type = 'array'
                    elif hasattr(type_hint, '__origin__') and type_hint.__origin__ in (dict, Dict):
                        param_type = 'object'
                    properties[name] = {"type": param_type, "description": ""}
                    if param.default == Parameter.empty:
                        required.append(name)
                schema = {
                    "type": "function",
                    "function": {
                        "name": func.__name__,
                        "description": func.__doc__ or f"Executes the {func.__name__} tool.",
                        "parameters": {
                            "type": "object",
                            "properties": properties,
                            "required": required,
                        },
                    },
                }
                schemas.append(schema)
            except Exception as e:
                logger.error(f"Could not generate schema for tool {func.__name__}: {e}")
        return schemas
    async def initialize(self) -> None:
        logger.debug(f"Initializing agent: {self.signature}")
        if not self.openai_api_key:
            raise ValueError("OpenAI API key not set.")
        if not self.strategy_profile:
            raise ValueError("No strategy profile provided to the agent.")
        self.tools = get_all_tools()
        logger.info(f"Registering {len(self.tools)} tools...")
        if not self.tools:
            raise ValueError("No tools found or provided to the agent.")
        self.system_prompt = get_agent_system_prompt_mt4(self.strategy_profile)
        try:
            self.client = AsyncOpenAI(
                api_key=self.openai_api_key,
                base_url=self.openai_base_url,
                max_retries=3,
                timeout=120,
            )
            self.openai_tools = self._create_tool_schemas(self.tools)
            self.tool_map = {func.__name__: func for func in self.tools}
            logger.debug(f"Built tool map with {len(self.tool_map)} tools for {self.signature}")
        except Exception as e:
            raise RuntimeError(f"Failed to initialize AI model or tools for {self.signature}: {e}")
        logger.info(f"Agent {self.signature} initialization completed.")
    async def run_trading_session(self, current_time_dt: datetime, news_summary: str = "") -> None:
        current_time_str = current_time_dt.strftime("%Y-%m-%d %H:%M:%S")
        logger.info(f"Starting trading session: {current_time_str}")
        symbols_to_scan_str = ', '.join(self.trading_symbols)
        system_prompt_content = self.system_prompt.replace('__SIGNATURE__', self.signature)
        symbols_json_str = json.dumps(self.trading_symbols)
        system_prompt_content = system_prompt_content.replace('__TRADING_SYMBOLS__', symbols_json_str)
        user_query_content = f"""It's a new trading cycle. The current time is {current_time_str}.

**[IMPORTANT] Market Context from recent news:**
{news_summary if news_summary else 'No significant news in this cycle.'}

Please analyze the market and manage my portfolio according to your directives.

**Your mandatory list of symbols to scan for this cycle is:** {symbols_to_scan_str}.
You must scan every symbol in this list.
"""
        message_history = [
            {"role": "system", "content": system_prompt_content},
            {"role": "user", "content": user_query_content}
        ]
        current_step = 0
        while current_step < self.max_steps:
            if not self._is_running:
                logger.warning("Agent stopping mid-cycle due to external signal.")
                break
            current_step += 1
            logger.info(f"Step {current_step}/{self.max_steps} for {self.signature}")
            try:
                response = await self.client.chat.completions.create(
                    model=self.basemodel,
                    messages=message_history,
                    tools=self.openai_tools,
                    tool_choice="auto",
                    max_tokens=4096
                )
                ai_response_message = response.choices[0].message
                message_history.append(ai_response_message.model_dump(exclude_unset=True))
                is_final_step = (ai_response_message.content and STOP_SIGNAL in ai_response_message.content) or not ai_response_message.tool_calls
                if is_final_step:
                    final_msg = f"{self.signature} concluded the session. Final message: {ai_response_message.content}"
                    logger.info(final_msg, extra={"type": "final_answer", "content": {"text": ai_response_message.content}})
                    break
                formatted_tool_calls = []
                if ai_response_message.tool_calls:
                    for tc in ai_response_message.tool_calls:
                        try:
                            args_parsed = json.loads(tc.function.arguments)
                        except:
                            args_parsed = tc.function.arguments
                        formatted_tool_calls.append({
                            "name": tc.function.name,
                            "args": args_parsed,
                            "id": tc.id
                        })
                thought_log = {
                    "step": current_step,
                    "thought": ai_response_message.content,
                    "tool_calls": formatted_tool_calls if formatted_tool_calls else None,
                }
                logger.info("Agent is thinking and calling tools", extra={"type": "thought", "content": thought_log})
                tool_results = []
                for tool_call in ai_response_message.tool_calls:
                    tool_name = tool_call.function.name
                    try:
                        tool_args = json.loads(tool_call.function.arguments)
                    except json.JSONDecodeError:
                        logger.error(f"Failed to decode tool arguments: {tool_call.function.arguments}")
                        parsed_result = {"status": "error", "message": "Invalid JSON in tool arguments."}
                        tool_results.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_name,
                            "content": json.dumps(parsed_result, indent=2)
                        })
                        continue
                    tool_call_id = tool_call.id
                    if tool_name in self.tool_map:
                        tool_to_call = self.tool_map[tool_name]
                        if tool_name == 'execute_trade_flow' and 'signal_tf' not in tool_args:
                            if self.strategy_profile and 'signal_tf' in self.strategy_profile:
                                tool_args['signal_tf'] = self.strategy_profile['signal_tf']
                                logger.debug(f"Auto-injected signal_tf={tool_args['signal_tf']} into execute_trade_flow call.")
                        raw_result = await tool_to_call(**tool_args)
                        parsed_result = _parse_tool_result(raw_result)
                        obs_log = {
                            "tool_name": tool_name, "tool_args": tool_args,
                            "raw_tool_result": raw_result, "parsed_tool_result": parsed_result
                        }
                        logger.info(f"Observation from tool '{tool_name}'", extra={"type": "observation", "content": obs_log})
                        if parsed_result.get("status") == "success" and "action" in parsed_result:
                            trade_log = {**parsed_result, "tool_args": tool_args}
                            logger.info(f"Trade action executed: {parsed_result['action']}", extra={"type": "trade_action", "content": trade_log})
                        tool_results.append({
                            "role": "tool",
                            "tool_call_id": tool_call_id,
                            "name": tool_name,
                            "content": json.dumps(parsed_result, indent=2)
                        })
                    else:
                        tool_not_found_msg = f"Tool Not Found: {tool_name}"
                        logger.error(tool_not_found_msg)
                        tool_results.append({
                            "role": "tool",
                            "tool_call_id": tool_call_id,
                            "name": tool_name,
                            "content": json.dumps({"status": "error", "message": f"Tool '{tool_name}' not found."})
                        })
                message_history.extend(tool_results)
            except Exception as e:
                error_msg = f"An error occurred during the trading session for {self.signature}: {e}"
                logger.critical(error_msg, exc_info=True)
                logger.info(f"FATAL ERROR in agent loop: {e}", extra={"type": "final_answer", "content": {"text": f"FATAL ERROR: {e}"}})
                break