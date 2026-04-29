import json
from datetime import datetime
from pathlib import Path


class MemoryManager:
    def __init__(self, project_dir: str):
        agent_dir = Path(project_dir) / ".agent"
        self._project_path = agent_dir / "memory.json"
        self._history_path = agent_dir / "history.json"
        self._user_path = Path.home() / ".agent" / "preferences.json"

        self._project: dict = self._read(self._project_path)
        self._user: dict = self._read(self._user_path)
        self._history: list = self._read(self._history_path, default=[])

    def set_project(self, key: str, value: str):
        self._project[key] = value
        self._write(self._project_path, self._project)

    def set_user(self, key: str, value: str):
        self._user[key] = value
        self._write(self._user_path, self._user)

    def add_history(self, summary: str):
        self._history.append({
            "date": datetime.now().isoformat(timespec="minutes"),
            "summary": summary,
        })
        self._history = self._history[-10:]
        self._write(self._history_path, self._history)

    def get_context_block(self) -> str:
        parts = []
        if self._user:
            lines = "\n".join(f"- {k}: {v}" for k, v in self._user.items())
            parts.append(f"## 用户偏好\n{lines}")
        if self._project:
            lines = "\n".join(f"- {k}: {v}" for k, v in self._project.items())
            parts.append(f"## 项目上下文\n{lines}")
        if self._history:
            recent = self._history[-3:]
            lines = "\n".join(f"- [{h['date']}] {h['summary']}" for h in recent)
            parts.append(f"## 近期对话历史\n{lines}")
        return "\n\n".join(parts)

    @staticmethod
    def _read(path: Path, default=None) -> dict | list:
        if default is None:
            default = {}
        if not path.exists():
            return default
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _write(path: Path, data: dict | list):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
