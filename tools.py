import inspect
import json
import subprocess
from pathlib import Path
from typing import get_type_hints


_TYPE_MAP = {str: "string", int: "integer", float: "number", bool: "boolean"}


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, dict] = {}

    def tool(self, description: str):
        def decorator(func):
            hints = get_type_hints(func)
            hints.pop("return", None)
            properties = {
                name: {"type": _TYPE_MAP.get(t, "string"), "description": ""}
                for name, t in hints.items()
            }
            sig = inspect.signature(func)
            required = [
                name for name, param in sig.parameters.items()
                if param.default is inspect.Parameter.empty
            ]
            self._tools[func.__name__] = {
                "func": func,
                "schema": {
                    "name": func.__name__,
                    "description": description,
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                    },
                },
            }
            return func
        return decorator

    def get_schemas(self) -> list[dict]:
        return [{"type": "function", "function": t["schema"]} for t in self._tools.values()]

    def execute(self, tool_call) -> str:
        name = tool_call.function.name
        try:
            args = json.loads(tool_call.function.arguments)
        except json.JSONDecodeError:
            return "参数解析失败"
        if name not in self._tools:
            return f"未知工具：{name}"
        if name == "run_terminal_command":
            confirm = input(f"\n⚠️  即将执行：{args.get('command', '')}\n是否继续？（Y/N）")
            if confirm.strip().lower() != "y":
                return "操作已取消"
        try:
            return str(self._tools[name]["func"](**args))
        except Exception as e:
            return f"工具执行错误：{e}"
