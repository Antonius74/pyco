import json
import os
from pathlib import Path
from dataclasses import dataclass, field

CONFIG_DIR = Path.home() / ".pyagent"
CONFIG_FILE = CONFIG_DIR / "config.json"
PLUGINS_DIR = CONFIG_DIR / "plugins"


@dataclass
class Config:
    model: str = "llama3.2"
    ollama_host: str = "http://localhost:11434"
    max_tokens: int = 4096
    temperature: float = 0.7
    system_prompt: str = "Sei un coding agent. Rispondi in italiano. Usa gli strumenti disponibili quando necessario."
    plugins_dir: str = str(PLUGINS_DIR)
    max_tool_iterations: int = 10


def load_config() -> Config:
    cfg = Config()
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            data = json.load(f)
            for k, v in data.items():
                if hasattr(cfg, k):
                    setattr(cfg, k, v)
    return cfg


def save_config(cfg: Config) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump({k: v for k, v in cfg.__dict__.items()}, f, indent=2, ensure_ascii=False)


def ensure_dirs() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
    init_file = PLUGINS_DIR / "__init__.py"
    if not init_file.exists():
        init_file.touch()


def get_plugin_dir() -> Path:
    return Path(load_config().plugins_dir)
