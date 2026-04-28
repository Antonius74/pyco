# PyCo

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10+-blue?style=flat-square&logo=python" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/license-MIT-green?style=flat-square" alt="MIT License">
  <img src="https://img.shields.io/badge/Ollama-native-orange?style=flat-square" alt="Ollama">
  <img src="https://img.shields.io/badge/pip_install-requests_only-lightgrey?style=flat-square" alt="Lightweight">
</p>

**The open source coding agent in Python.**  
100% locale, plugin nativi, interfaccia TUI stile terminale — tutto in Python.

<p align="center">
  <img src="https://img.shields.io/badge/model-llama3.2-default?style=flat-square&logo=ollama">
  <img src="https://img.shields.io/badge/streaming-true-success?style=flat-square">
  <img src="https://img.shields.io/badge/tool_calls-native-blue?style=flat-square">
  <img src="https://img.shields.io/badge/plugins-auto_discovery-ff69b4?style=flat-square">
</p>

---

## What is PyCo?

PyCo è un **coding agent open source** che gira nel terminale. Scritto in Python, pensato per essere minimale e veloce.
Collegato nativamente a **Ollama** con streaming real-time e tool calling OpenAI-compatibile.

```
⠋ Generating · · ───────────────────────────────────────────╮
╰────────────────────────────────────────────────────────────╯
⬢ spiega come funziona la ricorsione in Python
```

---

## Why PyCo?

- **100% Python** — nessun Node, nessun Rust toolchain, nessun runtime esotico
- **Una sola dipendenza** — `requests`. Più `prompt_toolkit` per la TUI
- **Ollama nativo** — nessun wrapper, chiamate dirette a `/api/chat` con streaming
- **Plugin system** — aggiungi strumenti in 5 righe di codice, auto-scoperti al boot
- **Tool calling reale** — il modello decide cosa chiamare, PyCo esegue e risponde
- **Leggerissimo** — gira su un Raspberry Pi senza problemi
- **TUI moderna** — prompt in basso, streaming in tempo reale, comandi `/slash`, Ctrl+C per interrompere

---

## Installation

```bash
# Clona il repo
git clone https://github.com/Antonius74/pyco.git
cd pyco/pyagent

# Virtual environment (consigliato)
python3 -m venv venv
source venv/bin/activate

# Installa
pip install -r requirements.txt

# Avvia Ollama (assicurati che sia in esecuzione)
ollama serve

# Scarica un modello (se non lo hai già)
ollama pull llama3.2
```

**Prerequisiti:**
- Python 3.10+
- [Ollama](https://ollama.ai) installato e in esecuzione
- Almeno un modello (default: `llama3.2`)

---

## Quick Start

```bash
# Modalità interattiva TUI (full-screen, streaming, prompt in basso)
python cli.py

# Prompt one-shot da linea di comando
python cli.py "quanto fa 2+2?"

# Con un modello specifico
python cli.py -m gemma3:12b "spiega il pattern singleton"

# Lista plugin
python cli.py --plugins

# Lista modelli
python cli.py --models

# Interfaccia semplice (no TUI)
python cli.py --simple
```

### Keyboard Shortcuts (TUI)

| Tasto | Azione |
|-------|--------|
| `Enter` | Invia prompt |
| `Esc` + `Enter` | Nuova riga (multiline) |
| `Ctrl+C` | Interrompi generazione / esci |
| `Ctrl+D` | Esci |
| `PgUp` / `PgDn` | Scroll output |

### Comandi Slash (TUI)

```
/help             Aiuto
/models           Lista modelli Ollama
/model <nome>     Cambia modello al volo
/plugins          Lista plugin disponibili
/clear            Pulisci conversazione
/exit             Esci
```

---

## Architecture

```
pyagent/
├── cli.py              # Entry point CLI + argomenti
├── tui.py              # TUI full-screen con prompt_toolkit
├── agent.py            # Core agent (ReAct loop, tool calling)
├── ollama_client.py    # Client Ollama (chat + streaming)
├── config.py           # Config JSON (~/.pyagent/config.json)
├── pyproject.toml      # Build & metadata
├── requirements.txt    # requests + prompt_toolkit
└── plugins/
    ├── __init__.py     # Auto-discovery registrazione plugin
    ├── base.py         # BasePlugin ABC + schema
    ├── shell.py        # Esecuzione comandi shell
    ├── file_ops.py     # read_file, write_file, list_dir
    └── web_search.py   # web_fetch (HTTP)
```

### Come Funziona

```
User Prompt
    │
    ▼
┌──────────────────────────────────┐
│  TUI / CLI                       │
│  prompt_toolkit full-screen UI   │
└──────────────┬───────────────────┘
               │
               ▼
┌──────────────────────────────────┐
│  Agent                           │
│  • Messaggi + tools al modello   │
│  • Riceve streaming / tool_call  │
│  • Esegue plugin locali          │
│  • Risponde con risultati +      │
│    continua il loop              │
└──────────────┬───────────────────┘
               │
               ▼
┌──────────────────────────────────┐
│  OllamaClient                    │
│  POST /api/chat (streaming)      │
│  + tool definitions              │
└──────────────┬───────────────────┘
               │
               ▼
┌──────────────────────────────────┐
│  Ollama (localhost:11434)        │
│  llama3.2 · gemma3 · deepseek    │
└──────────────────────────────────┘
```

---

## Plugin System

I plugin sono il cuore estendibile di PyCo. Ogni plugin è una classe Python che estende `BasePlugin`.

### Creare un Plugin in 5 Righe

```python
# plugins/my_tool.py
from plugins.base import BasePlugin, ToolParameter

class WeatherPlugin(BasePlugin):
    tool_name = "weather"
    description = "Ottiene il meteo per una città"
    parameters = [
        ToolParameter(name="city", type="string", description="Nome città")
    ]

    def execute(self, city: str) -> str:
        # La tua logica qui
        return f"☀️ Meteo a {city}: 22°C, soleggiato"
```

Salva il file in `plugins/`. PyCo lo scopre automaticamente al boot — **nessuna registrazione manuale, nessun import da toccare**.

### Plugin Built-in

| Plugin | Descrizione |
|--------|-------------|
| `shell` | Esegue comandi bash — `ls`, `cat`, `grep`, qualsiasi cosa |
| `read_file` | Legge file dal filesystem |
| `write_file` | Crea o sovrascrive file |
| `list_dir` | Elenca directory |
| `web_fetch` | Scarica contenuto da URL (HTTP GET) |

---

## Configurazione

La configurazione è in `~/.pyagent/config.json` (creata automaticamente al primo avvio):

```json
{
  "model": "llama3.2",
  "ollama_host": "http://localhost:11434",
  "max_tokens": 4096,
  "temperature": 0.7,
  "system_prompt": "Sei un coding agent. Rispondi in italiano.",
  "max_tool_iterations": 10,
  "plugins_dir": "~/.pyagent/plugins"
}
```

Modifica il file per cambiare modello, temperatura o prompt di sistema.

---

## Esempi

```bash
# Esplorazione filesystem
python cli.py "elenca i file nella cartella corrente e dimmi quale è il più grande"

# Operazioni su file
python cli.py "crea un file requirements.txt con dentro requests e flask"

# Comandi shell complessi
python cli.py "trova tutti i file Python modificati negli ultimi 2 giorni"

# Cambio modello al volo
python cli.py -m deepseek-v4-pro:cloud "riscrivi questa funzione in modo più efficiente"
```

---

## Contributing

Contributi benvenuti! Apri una issue o una pull request.

1. Forka il repo
2. Crea un branch (`git checkout -b feature/amazing`)
3. Committa (`git commit -m 'Add amazing feature'`)
4. Pusha (`git push origin feature/amazing`)
5. Apri una Pull Request

---

## FAQ

**Serve una GPU?**  
No. Ollama può girare anche su CPU, ma una GPU con almeno 8GB di VRAM aiuta per modelli più grandi.

**Quali modelli funzionano?**  
Qualsiasi modello Ollama che supporta tool calling. Testato con: `llama3.2`, `gemma3:12b`, `gemma3:27b`, `deepseek-v4-pro:cloud`, `qwen3-coder`.

**Posso fare multi-turno?**  
Sì, ogni sessione TUI mantiene la conversazione. Usa `/clear` per resettare.

**Posso usare OpenAI invece di Ollama?**  
PyCo è pensato per Ollama, ma `ollama_client.py` usa l'API OpenAI-compatibile — con piccole modifiche puoi puntarlo a qualsiasi endpoint compatibile.

**Devo installare Node.js?**  
No. Solo Python e Ollama.

---

## License

MIT © 2026 PyCo

---

<p align="center">
  <sub>Built with ❤️ by Antonius74</sub>
</p>
