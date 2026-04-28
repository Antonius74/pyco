from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolParameter:
    name: str
    type: str
    description: str
    required: bool = True


class BasePlugin(ABC):
    tool_name: str = ""
    description: str = ""
    parameters: list[ToolParameter] = field(default_factory=list)

    @abstractmethod
    def execute(self, **kwargs) -> str: ...

    def get_tool_schema(self) -> dict[str, Any]:
        props = {}
        required = []
        for p in self.parameters:
            props[p.name] = {"type": p.type, "description": p.description}
            if p.required:
                required.append(p.name)
        return {
            "type": "function",
            "function": {
                "name": self.tool_name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": props,
                    "required": required,
                },
            },
        }
