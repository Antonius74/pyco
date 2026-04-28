import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from ollama_client import OllamaClient
from plugins import all_plugins
from config import load_config

logger = logging.getLogger("pyagent")


@dataclass
class AgentResult:
    answer: str
    tool_calls: int


class Agent:
    def __init__(self, client: OllamaClient | None = None):
        cfg = load_config()
        self.client = client or OllamaClient()
        self.system_prompt = cfg.system_prompt
        self.max_iterations = cfg.max_tool_iterations

    def _build_messages(self, user_prompt: str) -> list[dict]:
        return [{"role": "user", "content": user_prompt}]

    def _get_tools(self) -> list[dict]:
        return [p.get_tool_schema() for p in all_plugins()]

    def _parse_tool_calls(self, message: dict) -> list[dict]:
        calls = message.get("tool_calls") or []
        return calls

    def _parse_tool_call_text(self, text: str) -> list[dict] | None:
        patterns = [
            r'<tool_call>(.*?)</tool_call>',
            r'```tool_call\s*\n(.*?)```',
            r'{"tool"\s*:\s*"(.*?)"\s*,\s*"(.*?)"\s*:\s*(.*?)}',
        ]
        for pattern in patterns:
            m = re.search(pattern, text, re.DOTALL)
            if m:
                try:
                    data = json.loads(m.group(1))
                    if "name" in data:
                        return [{
                            "function": {
                                "name": data["name"],
                                "arguments": data.get("arguments", {}),
                            }
                        }]
                except json.JSONDecodeError:
                    continue
        return None

    def run(self, prompt: str, tools_enabled: bool = True) -> AgentResult:
        from plugins import get_plugin

        messages = self._build_messages(prompt)
        tools = self._get_tools() if tools_enabled else None
        tool_calls_total = 0

        for i in range(self.max_iterations):
            try:
                resp = self.client.chat(messages, tools=tools, system=self.system_prompt)
            except Exception as e:
                return AgentResult(answer=f"Errore di connessione a Ollama: {e}", tool_calls=tool_calls_total)

            content = resp.get("message", resp)
            tool_calls = self._parse_tool_calls(content)

            if not tool_calls:
                text_content = content.get("content", "") if isinstance(content, dict) else str(content)
                parsed = self._parse_tool_call_text(text_content)
                if parsed:
                    tool_calls = parsed
                    messages.append({"role": "assistant", "content": text_content})

            if not tool_calls:
                answer = content.get("content", "") if isinstance(content, dict) else str(content)
                if not answer.strip() and tool_calls_total > 0:
                    answer = "(L'agente ha completato le operazioni ma non ha prodotto una risposta testuale.)"
                return AgentResult(answer=answer, tool_calls=tool_calls_total)

            assistant_msg = {"role": "assistant", "content": content.get("content", "") or ""}
            if tool_calls:
                assistant_msg["tool_calls"] = tool_calls
            messages.append(assistant_msg)

            for tc in tool_calls:
                func = tc.get("function", {})
                name = func.get("name", "")
                args = func.get("arguments", {})

                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}

                plugin = get_plugin(name)
                if plugin:
                    logger.info("Tool: %s(%s)", name, args)
                    try:
                        result = plugin.execute(**args)
                        tool_calls_total += 1
                    except Exception as e:
                        result = f"Errore esecuzione tool '{name}': {e}"
                    messages.append({
                        "role": "tool",
                        "content": str(result),
                    })
                else:
                    messages.append({
                        "role": "tool",
                        "content": f"Tool '{name}' non disponibile.",
                    })

        return AgentResult(
            answer="Raggiunto limite massimo di iterazioni. Interrompo.",
            tool_calls=tool_calls_total,
        )
