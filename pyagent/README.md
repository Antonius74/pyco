# PyAgent — Quick Reference

```bash
# TUI interattiva (full-screen, streaming, prompt in basso)
python cli.py

# One-shot
python cli.py "quanto fa 2+2?"

# Plugin disponibili
python cli.py --plugins

# Modelli disponibili
python cli.py --models
```

## 🔌 Plugin

| Plugin | Descrizione |
|--------|-------------|
| `shell` | Esegue comandi bash |
| `read_file` | Legge file |
| `write_file` | Scrive file |
| `list_dir` | Elenca directory |
| `web_fetch` | HTTP GET URL |

## 🎮 TUI

| Tasto | Azione |
|-------|--------|
| `Enter` | Invia |
| `Esc+Enter` | Nuova riga |
| `Ctrl+C` | Interrompi |
| `Ctrl+D` | Esci |

## 🧩 Creare un Plugin

```python
from plugins.base import BasePlugin, ToolParameter

class MyTool(BasePlugin):
    tool_name = "mytool"
    description = "Fa qualcosa"
    parameters = [ToolParameter(name="x", type="string", description="Param")]

    def execute(self, x: str) -> str:
        return f"Risultato: {x}"
```
