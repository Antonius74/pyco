import json
import logging
import threading
from typing import Any

from prompt_toolkit import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, VSplit, Window, Layout
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.dimension import D
from prompt_toolkit.styles import Style

from ollama_client import OllamaClient
from plugins import all_plugins, list_plugins
from config import load_config

logger = logging.getLogger("pyagent.tui")

STYLE = Style.from_dict({
    "header": "#00d7ff bold",
    "tool-label": "#ff9d00 bold",
    "tool-args": "#666666 italic",
    "tool-result": "#00ff88",
    "prompt-bar": "bg:#0d0d1a",
    "prompt": "#00d7ff bold",
    "thinking": "#888888 italic",
    "user-msg": "#aaccff",
    "agent-msg": "#ffffff",
    "status-bar": "bg:#1a1a2e #888888",
    "divider": "#333333",
    "error": "#ff3333 bold",
    "success": "#00ff88",
})

TOOL_RESULT_MAX_LEN = 4000


class PyAgentTUI:
    def __init__(self, model: str | None = None):
        cfg = load_config()
        self.client = OllamaClient(model=model)
        self.client.model = model or cfg.model
        self.system_prompt = cfg.system_prompt
        self.max_iterations = cfg.max_tool_iterations

        self._lock = threading.Lock()
        self.output_lines: list[tuple[str, str]] = []
        self.streaming = False
        self.interrupted = False
        self.status_text = f" Modello: {self.client.model}  |  Ctrl+D per uscire  |  /help per comandi"

        self.output_control = FormattedTextControl(
            text=self._render_output,
            focusable=False,
        )

        self.input_buffer = Buffer(
            multiline=True,
            completer=WordCompleter(
                ["/help", "/clear", "/models", "/plugins", "/model ", "/exit"],
                ignore_case=True,
            ),
            complete_while_typing=True,
        )

        self.kb = self._make_keybindings()
        self.app = self._build_app()

    # ── key bindings ────────────────────────────────────────────────

    def _make_keybindings(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add("escape", "enter")
        def _(event):
            self.input_buffer.insert_text("\n")

        @kb.add("enter")
        def _(event):
            text = self.input_buffer.text.strip()
            if not text:
                return
            self.input_buffer.reset()
            self._dispatch(text)

        @kb.add("c-c")
        def _(event):
            if self.streaming:
                self.interrupted = True
                self._emit("error", "\n[INTERROTTO]")
            else:
                event.app.exit()

        @kb.add("c-d")
        def _(event):
            if not self.input_buffer.text:
                event.app.exit()

        return kb

    # ── layout ──────────────────────────────────────────────────────

    def _build_app(self) -> Application:
        header = Window(
            content=FormattedTextControl([
                ("class:header", "  █████╗  ██████╗ ███████╗███╗   ██╗████████╗"),
            ]),
            height=1,
        )

        output_area = Window(
            content=self.output_control,
            wrap_lines=True,
            always_hide_cursor=True,
        )

        divider = Window(height=1, char="─", style="class:divider")

        prompt_label = Window(
            content=FormattedTextControl(" ⬢ "),
            width=3,
            style="class:prompt",
        )

        input_area = VSplit([
            prompt_label,
            Window(
                content=BufferControl(buffer=self.input_buffer),
                wrap_lines=True,
            ),
        ], style="class:prompt-bar", height=D(min=1, max=20))

        status = Window(
            content=FormattedTextControl(
                lambda: [("class:status-bar", " " + self.status_text)]
            ),
            height=1,
            style="class:status-bar",
        )

        root = HSplit([header, output_area, divider, input_area, status])

        return Application(
            layout=Layout(root, focused_element=input_area),
            key_bindings=self.kb,
            style=STYLE,
            full_screen=True,
            mouse_support=True,
            refresh_interval=0.1,
        )

    # ── output helpers ──────────────────────────────────────────────

    def _emit(self, style: str, text: str):
        with self._lock:
            self.output_lines.append((style, text))
        self.app.invalidate()

    def _emit_append(self, style: str, text: str):
        with self._lock:
            if self.output_lines and self.output_lines[-1][0] == style:
                prev = self.output_lines[-1]
                self.output_lines[-1] = (style, prev[1] + text)
            else:
                self.output_lines.append((style, text))
        self.app.invalidate()

    def _render_output(self):
        parts = []
        with self._lock:
            for style, text in self.output_lines:
                parts.append(("class:" + style, text))
                parts.append(("", "\n"))
        return parts

    # ── dispatch ────────────────────────────────────────────────────

    def _dispatch(self, text: str):
        if text.startswith("/"):
            parts = text.split(maxsplit=1)
            cmd = parts[0].lower()
            arg = parts[1] if len(parts) > 1 else ""
            self._run_command(cmd, arg)
        else:
            self._run_agent(text)

    # ── commands ────────────────────────────────────────────────────

    def _run_command(self, cmd: str, arg: str):
        if cmd == "/exit":
            self.app.exit()
        elif cmd == "/clear":
            self.output_lines.clear()
            self._emit("success", "\n[SCHERMO PULITO]")
        elif cmd == "/models":
            self._emit("agent-msg", "\n🔍 Caricamento modelli...")
            models = self.client.list_models()
            if not models:
                self._emit("error", "  Nessun modello trovato.")
            else:
                self._emit("agent-msg", "  Modelli disponibili:")
                for m in models:
                    mark = " ●" if m == self.client.model else ""
                    self._emit("agent-msg", f"    - {m}{mark}")
        elif cmd == "/plugins":
            plugins = list_plugins()
            self._emit("agent-msg", "\n🔌 Plugin:")
            for p in plugins:
                self._emit("agent-msg", f"  {p.tool_name}: {p.description}")
        elif cmd.startswith("/model"):
            if arg:
                self.client.model = arg
                self.status_text = f" Modello: {self.client.model}  |  Ctrl+D per uscire  |  /help per comandi"
                self._emit("success", f"\n✅ Modello cambiato: {arg}")
            else:
                self._emit("agent-msg", f"\n  Modello attuale: {self.client.model}")
        elif cmd == "/help":
            self._emit("agent-msg", """\n
  /exit            Esci
  /clear           Pulisci la conversazione
  /models          Lista modelli Ollama
  /model <nome>    Cambia modello
  /plugins         Lista plugin disponibili
  /help            Questo messaggio
  ESC+Enter        Nuova riga
  Ctrl+C           Interrompi generazione
  Ctrl+D           Esci""")
        else:
            self._emit("error", f"\n  Comando sconosciuto: {cmd}")

    # ── agent loop ──────────────────────────────────────────────────

    def _run_agent(self, text: str):
        if self.streaming:
            return

        self.streaming = True
        self.interrupted = False
        self.status_text = " ⏳ Generando..."
        self._emit("user-msg", f"\n⬢ {text}")

        tools = [p.get_tool_schema() for p in all_plugins()]
        messages: list[dict] = [{"role": "user", "content": text}]
        tool_calls_total = 0

        try:
            for _ in range(self.max_iterations):
                if self.interrupted:
                    self._emit("error", "\n[Interrotto dall'utente]")
                    break

                response_text, tool_calls = self._stream_one(
                    messages, tools, self.system_prompt
                )

                if self.interrupted:
                    break

                if not tool_calls:
                    if response_text.strip():
                        self._emit("agent-msg", response_text)
                    elif tool_calls_total > 0:
                        self._emit("agent-msg", "\n✅ Operazione completata.")
                    break

                if response_text.strip():
                    self._emit("thinking", response_text)

                assistant_msg: dict = {
                    "role": "assistant",
                    "content": response_text,
                    "tool_calls": [],
                }

                for tc in tool_calls:
                    fn = tc.get("function", {})
                    name = fn.get("name", "")
                    args = fn.get("arguments", {})

                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {}

                    args_display = ", ".join(
                        f"{k}={v!r}" for k, v in args.items()
                    )
                    self._emit("tool-label", f"\n  ▸ {name}")
                    self._emit("tool-args", f"     {args_display}")

                    from plugins import get_plugin
                    plugin = get_plugin(name)
                    if plugin:
                        try:
                            result = str(plugin.execute(**args))
                            tool_calls_total += 1
                        except Exception as e:
                            result = f"Errore: {e}"

                        assistant_msg["tool_calls"].append(tc)
                        messages.append(assistant_msg)
                        messages.append({
                            "role": "tool",
                            "content": result[:TOOL_RESULT_MAX_LEN],
                        })

                        preview = result[:300]
                        if len(result) > 300:
                            preview += " [...]"
                        self._emit("tool-result", f"     ↳ {preview}")
                    else:
                        self._emit("error", f"  Tool '{name}' non trovato")
                        assistant_msg["tool_calls"].append(tc)
                        messages.append(assistant_msg)
                        messages.append({
                            "role": "tool",
                            "content": f"Tool '{name}' non disponibile.",
                        })

            self._emit("divider", f"\n{'─' * 40}")

        except Exception as e:
            self._emit("error", f"\n  Errore: {e}")

        self.streaming = False
        self.interrupted = False
        self.status_text = f" Modello: {self.client.model}  |  Ctrl+D per uscire  |  /help per comandi"

    # ── streaming ───────────────────────────────────────────────────

    def _stream_one(
        self, messages: list[dict], tools: list[dict], system: str
    ) -> tuple[str, list[dict]]:
        full_content = ""
        tool_calls_map: dict[int, dict] = {}

        try:
            for chunk in self.client.chat_stream(messages, tools, system):
                if self.interrupted:
                    break

                msg = chunk.get("message", {})
                delta = msg.get("content", "")
                if delta:
                    full_content += delta
                    self._emit_append("agent-msg", delta)

                for tc in msg.get("tool_calls") or []:
                    idx = tc.get("index", 0)
                    if idx not in tool_calls_map:
                        tool_calls_map[idx] = {
                            "function": {"name": "", "arguments": ""}
                        }
                    fn = tc.get("function", {})
                    if "name" in fn:
                        tool_calls_map[idx]["function"]["name"] += fn["name"]
                    if "arguments" in fn:
                        val = fn["arguments"]
                        tool_calls_map[idx]["function"]["arguments"] += (
                            val if isinstance(val, str) else json.dumps(val)
                        )

                if chunk.get("done"):
                    break
        except Exception as e:
            raise Exception(f"Connessione Ollama fallita: {e}")

        tool_calls = []
        for idx in sorted(tool_calls_map.keys()):
            tc = tool_calls_map[idx]
            args = tc["function"].get("arguments", "")
            try:
                tc["function"]["arguments"] = json.loads(args) if args.strip() else {}
            except json.JSONDecodeError:
                tc["function"]["arguments"] = {}
            tool_calls.append(tc)

        return full_content.strip(), tool_calls

    # ── entry ───────────────────────────────────────────────────────

    def run(self):
        self._emit("header", "  PyAgent v0.2 — coding agent con plugin")
        self._emit("agent-msg", "  Digita un prompt o /help per i comandi")
        self.app.run()


def main():
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--model", "-m", help="Modello Ollama")
    p.add_argument("prompt", nargs="*")
    p.add_argument("--no-tools", action="store_true")
    args = p.parse_args()

    from config import ensure_dirs
    from plugins import discover_plugins
    import plugins as _plugins

    ensure_dirs()
    discover_plugins(_plugins)

    if args.prompt:
        from agent import Agent

        agent = Agent(OllamaClient(model=args.model) if args.model else None)
        result = agent.run(" ".join(args.prompt), tools_enabled=not args.no_tools)
        print(result.answer)
        return

    PyAgentTUI(model=args.model).run()


if __name__ == "__main__":
    main()
