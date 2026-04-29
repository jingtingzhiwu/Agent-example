import os
import subprocess
from pathlib import Path
from string import Template

import click
from dotenv import load_dotenv
from openai import OpenAI

from memory import MemoryManager
from prompt_template import system_prompt_template
from tools import ToolRegistry


class ContextManager:
    def __init__(self, system_prompt: str, max_messages: int = 20):
        self._system_prompt = system_prompt
        self._messages: list[dict] = []
        self._max = max_messages

    def add_user(self, content: str):
        self._messages.append({"role": "user", "content": content})
        self._trim()

    def add_assistant(self, message):
        msg: dict = {"role": "assistant", "content": message.content}
        if message.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in message.tool_calls
            ]
        self._messages.append(msg)

    def add_tool_result(self, tool_call_id: str, name: str, content: str):
        self._messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": name,
            "content": content,
        })

    def get_messages(self) -> list[dict]:
        return [{"role": "system", "content": self._system_prompt}] + self._messages

    def _trim(self):
        if len(self._messages) > self._max:
            self._messages = self._messages[-self._max:]


class ReActAgent:
    def __init__(self, model: str, base_url: str, project_directory: str, max_messages: int):
        self.model = model
        self.project_directory = Path(project_directory)
        self.client = OpenAI(base_url=base_url, api_key=self._get_api_key())

        self.memory = MemoryManager(project_directory)
        self.tools = ToolRegistry()
        self._register_tools()

        self.context = ContextManager(self._build_system_prompt(), max_messages)

    def run(self, user_input: str) -> str:
        self.context.add_user(user_input)

        while True:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=self.context.get_messages(),
                tools=self.tools.get_schemas(),
                tool_choice="auto",
            )
            msg = response.choices[0].message

            if not msg.tool_calls:
                return msg.content or ""

            self.context.add_assistant(msg)
            for tc in msg.tool_calls:
                print(f"\n🔧 {tc.function.name}({tc.function.arguments})")
                result = self.tools.execute(tc)
                print(f"🔍 {result[:300]}")
                self.context.add_tool_result(tc.id, tc.function.name, result)

    def _build_system_prompt(self) -> str:
        file_list = "\n".join(
            f.name + ("/" if f.is_dir() else "")
            for f in sorted(self.project_directory.iterdir())
        )
        memory_context = self.memory.get_context_block()
        return Template(system_prompt_template).substitute(
            project_directory=str(self.project_directory),
            file_list=file_list,
            memory_context=memory_context,
        )

    def _register_tools(self):
        memory = self.memory
        project_dir = self.project_directory

        def _resolve(path: str) -> Path:
            p = Path(path)
            return p if p.is_absolute() else project_dir / p

        @self.tools.tool("读取文件内容，返回完整文本。路径可以是绝对路径或相对于项目目录的相对路径")
        def read_file(file_path: str) -> str:
            with open(_resolve(file_path), encoding="utf-8") as f:
                return f.read()

        @self.tools.tool("将内容写入文件（覆盖写入）。路径可以是绝对路径或相对于项目目录的相对路径")
        def write_to_file(file_path: str, content: str) -> str:
            resolved = _resolve(file_path)
            resolved.parent.mkdir(parents=True, exist_ok=True)
            with open(resolved, "w", encoding="utf-8") as f:
                f.write(content)
            return f"已写入：{resolved}"

        @self.tools.tool("在项目目录执行 shell 命令，需用户确认")
        def run_terminal_command(command: str) -> str:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True, cwd=str(project_dir)
            )
            return result.stdout if result.returncode == 0 else (result.stderr or "命令执行失败（无输出）")

        @self.tools.tool("将键值对保存到项目记忆，下次启动自动加载")
        def save_project_memory(key: str, value: str) -> str:
            memory.set_project(key, value)
            return f"已保存项目记忆：{key}"

        @self.tools.tool("将键值对保存到全局用户偏好，所有项目均可读取")
        def save_user_preference(key: str, value: str) -> str:
            memory.set_user(key, value)
            return f"已保存用户偏好：{key}"

    @staticmethod
    def _get_api_key() -> str:
        api_key = os.getenv("AGENT_API_KEY")
        if not api_key:
            raise ValueError("未找到 AGENT_API_KEY，请在 .env 中设置。")
        return api_key


@click.command()
@click.argument("project_directory", type=click.Path(exists=True, file_okay=False, dir_okay=True))
def main(project_directory: str):
    load_dotenv()
    model = os.getenv("AGENT_MODEL", "openai/gpt-4o")
    base_url = os.getenv("AGENT_BASE_URL", "http://192.168.0.100:8000/v1")
    max_messages = int(os.getenv("AGENT_MAX_MESSAGES", "20"))

    agent = ReActAgent(
        model=model,
        base_url=base_url,
        project_directory=project_directory,
        max_messages=max_messages,
    )

    while True:
        try:
            task = input("\n请输入任务（exit 退出）：").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if task.lower() == "exit":
            break
        if not task:
            continue
        result = agent.run(task)
        print(f"\n✅ {result}")

    _maybe_save_summary(agent)


def _maybe_save_summary(agent: ReActAgent):
    msgs = [m for m in agent.context.get_messages() if m["role"] == "user"]
    if not msgs:
        return
    try:
        confirm = input("\n是否保存本次对话摘要？（Y/N）")
    except (EOFError, KeyboardInterrupt):
        return
    if confirm.strip().lower() != "y":
        return
    summary = "；".join(
        m["content"] for m in msgs[:3] if isinstance(m.get("content"), str)
    )
    if len(msgs) > 3:
        summary += f"（共 {len(msgs)} 轮）"
    agent.memory.add_history(summary)
    print("✅ 摘要已保存。")


if __name__ == "__main__":
    main()
