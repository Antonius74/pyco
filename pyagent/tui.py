import json
import logging
import time
import threading
import re
from typing import Any

from prompt_toolkit import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, VSplit, Window, Layout
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.dimension import D
from prompt_toolkit.styles import Style
from prompt_toolkit.formatted_text import FormattedText as PTFormattedText

from ollama_client import OllamaClient
from plugins import all_plugins, list_plugins
from config import load_config

logger = logging.getLogger("pyagent.tui")

THEME = Style.from_dict({
    "bg": "bg:#0b0e14 #cdd6f4",
    "header": "bg:#0b0e14 #89b4fa bold",
    "user-bubble": "bg:#1e1e2e #89b4fa bold",
    "agent": "#cdd6f4",
    "agent-dim": "#6c7086 italic",
    "tool-name": "bg:#1e1e2e #f9e2af bold",
    "tool-args": "#585b70 italic",
    "tool-out": "bg:#111118 #a6e3a1",
    "tool-err-label": "#f38ba8 bold",
    "error": "#f38ba8 bold",
    "success": "#a6e3a1",
    "thinking": "#6c7086 italic",
    "divider": "#313244",
    "input-area": "bg:#0b0e14",
    "input-prompt": "#89dceb bold",
    "input-model-badge": "bg:#1e1e2e #f5c2e7 bold",
    "status-bar": "bg:#1e1e2e #585b70",
    "status-spinner": "#f9e2af",
    "status-model": "#89b4fa bold",
    "status-count": "#a6e3a1",
})
TOOL_RESULT_MAX = 6000
DIV_WIDTH = 50


def _fmt_token(tok: dict) -> str:
    fn = tok.get("function", {})
    name = fn.get("name", "")
    args = fn.get("arguments", {})
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            pass
    if isinstance(args, dict):
        bits = ", ".join(f"{k}={v!r}" for k, v in args.items())
    else:
        bits = str(args)
    return f"{name}({bits})"


class _ChatLine:
    __slots__ = ("style", "text")

    def __init__(self, style: str, text: str):
        self.style = style
        self.text = text


class PyAgentTUI:
    def __init__(self, model: str | None = None):
        cfg = load_config()
        self.client = OllamaClient(model=model)
        self.client.model = model or cfg.model
        self.system_prompt = cfg.system_prompt
        self.max_iterations = cfg.max_tool_iterations

        self._lock = threading.Lock()
        self._lines: list[_ChatLine] = []
        self.streaming = False
        self.interrupted = False
        self.tool_calls_total = 0
        self.start_time = 0.0

        self._model_str = f" {self.client.model} "
        self._status_str = ""
        self._spinner_idx = 0
        self._spinner_frames = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
        self._last_spinner = 0.0

        self.output_control = FormattedTextControl(
            text=self._render_output, focusable=False
        )

        self.input_buffer = Buffer(multiline=True)
        input_ctrl = BufferControl(buffer=self.input_buffer)

        prompt_lbl = Window(
            content=FormattedTextControl([("class:input-prompt", " ⬢ ")]),
            width=3,
            style="class:bg",
        )

        model_badge = Window(
            content=FormattedTextControl(
                lambda: [("class:input-model-badge", self._model_str)]),
            style="class:bg",
            width=len(self.client.model) + 4,
            height=1,
        )

        input_row = VSplit(
            [
                prompt_lbl,
                Window(content=input_ctrl, wrap_lines=True),
                model_badge,
            ],
            style="class:bg",
            height=D(min=1, max=8),
        )

        self.status_ctrl = FormattedTextControl(
            lambda: self._build_status_line()
        )
        status_bar = Window(
            content=self.status_ctrl, height=1, style="class:status-bar"
        )

        out = Window(
            content=self.output_control, wrap_lines=False, always_hide_cursor=True
        )

        root = HSplit(
            [
                Window(height=1, char=" ", style="class:bg"),
                out,
                Window(height=1, char="▔", style="class:divider"),
                input_row,
                status_bar,
            ]
        )

        self.kb = self._make_kb()
        self.app = Application(
            layout=Layout(root, focused_element=input_row),
            key_bindings=self.kb,
            style=THEME,
            full_screen=True,
            mouse_support=True,
            refresh_interval=0.08,
        )

        self._lines.append(_ChatLine("agent-dim", "\n  PyCo v0.2 — coding agent in Python"))
        self._lines.append(_ChatLine("agent-dim", "  /help per i comandi"))

    def _make_kb(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add("escape", "enter")
        def _(event):
            self.input_buffer.insert_text("\n")

        @kb.add("c-j")
        def _(event):
            text = self.input_buffer.text.rstrip("\n")
            if not text.strip():
                return
            self.input_buffer.reset()
            self._dispatch(text.strip())

        @kb.add("enter")
        def _(event):
            text = self.input_buffer.text.rstrip("\n")
            if not text.strip():
                return
            self.input_buffer.reset()
            self._dispatch(text.strip())

        @kb.add("c-c")
        def _(event):
            if self.streaming:
                self.interrupted = True
                self._push("error", "\n[interrotto]")
            else:
                event.app.exit()

        @kb.add("c-d")
        def _(event):
            if not self.input_buffer.text:
                event.app.exit()

        @kb.add("pageup")
        def _(event):
            pass

        @kb.add("pagedown")
        def _(event):
            pass

        return kb

    def _push(self, style: str, text: str):
        with self._lock:
            self._lines.append(_ChatLine(style, text))
        self.app.invalidate()

    def _push_append(self, style: str, text: str):
        with self._lock:
            if self._lines and self._lines[-1].style == style:
                self._lines[-1].text += text
            else:
                self._lines.append(_ChatLine(style, text))
        self.app.invalidate()

    def _render_output(self):
        parts = []
        with self._lock:
            for line in self._lines:
                parts.append(("class:" + line.style, line.text))
                parts.append(("", "\n"))
        return PTFormattedText(parts)

    def _build_status_line(self):
        now = time.monotonic()
        if self.streaming:
            if now - self._last_spinner > 0.08:
                self._spinner_idx = (self._spinner_idx + 1) % len(self._spinner_frames)
                self._last_spinner = now
            spin = self._spinner_frames[self._spinner_idx]
            elapsed = now - self.start_time if self.start_time else 0
            tc = f"{self.tool_calls_total} tool" if self.tool_calls_total else ""
            return [
                ("class:status-spinner", f" {spin} "),
                ("", "Generando"),
                ("class:status-count", f"  {tc}" if tc else " "),
                ("", f"  {elapsed:.1f}s" if elapsed > 0.5 else ""),
                ("", "  Esc per interrompere"),
            ]
        return [
            ("", " tab agent · ctrl+k comandi · ctrl+d esci"),
            ("class:status-model", f"  {self.client.model}"),
        ]

    def _dispatch(self, text: str):
        if text.startswith("/"):
            parts = text.split(maxsplit=1)
            cmd = parts[0].lower()
            arg = parts[1] if len(parts) > 1 else ""
            self._cmd(cmd, arg)
        else:
            self._run(text)

    def _cmd(self, cmd: str, arg: str):
        if cmd == "/exit":
            self.app.exit()
        elif cmd == "/clear":
            with self._lock:
                self._lines.clear()
            self._push("agent-dim", "\n  PyCo v0.2")
            self._push("agent-dim", "  Conversazione pulita.")
            self.tool_calls_total = 0
            self.start_time = 0
        elif cmd == "/models":
            self._push("agent-dim", "\n  Modelli disponibili:")
            for m in self.client.list_models():
                mark = " ●" if m == self.client.model else ""
                self._push("status-count" if mark.strip() else "agent-dim", f"    {m}{mark}")
        elif cmd == "/plugins":
            self._push("agent-dim", "\n  Plugin:")
            for p in list_plugins():
                self._push("tool-name", f"    ▸ {p.tool_name}")
                self._push("agent-dim", f"      {p.description}")
        elif cmd.startswith("/model"):
            if arg:
                self.client.model = arg
                self._model_str = f" {arg} "
                self._push("success", f"\n  → modello: {arg}")
            else:
                self._push("agent-dim", f"\n  Modello: {self.client.model}")
        elif cmd == "/help":
            self._push("agent-dim", """\n
  ⌨  Comandi
  ──────────
  /exit           Esci
  /clear          Pulisci conversazione
  /models         Modelli Ollama
  /model <nome>   Cambia modello
  /plugins        Plugin disponibili
  /help           Questo aiuto
  Ctrl+Enter      Nuova riga
  Ctrl+C          Interrompi / esci
  Ctrl+D          Esci""")
        else:
            self._push("error", f"\n  Comando sconosciuto: {cmd}")

    def _run(self, text: str):
        if self.streaming:
            return

        self.streaming = True
        self.interrupted = False
        self.tool_calls_total = 0
        self.start_time = time.monotonic()

        self._push("user-bubble", f"\n▌ {text}")

        tools = [p.get_tool_schema() for p in all_plugins()]
        messages: list[dict] = [{"role": "user", "content": text}]
        first_content = True

        try:
            for _ in range(self.max_iterations):
                if self.interrupted:
                    break

                response_text, tool_calls = self._stream_one(
                    messages, tools, self.system_prompt
                )

                if self.interrupted:
                    break

                if not tool_calls:
                    if not response_text.strip() and self.tool_calls_total > 0:
                        self._push("agent", "\n  ✅ fatto")
                    break

                for tc in tool_calls:
                    fn = tc.get("function", {})
                    name = fn.get("name", "")
                    args = fn.get("arguments", {})

                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {}

                    self._push("tool-name", f"\n  ▸ {name}")
                    args_str = ", ".join(
                        f"{k}={json.dumps(v, ensure_ascii=False)}"
                        for k, v in args.items()
                    )
                    self._push("tool-args", f"     {args_str}")

                    from plugins import get_plugin

                    plugin = get_plugin(name)
                    if plugin:
                        try:
                            result = str(plugin.execute(**args))
                            self.tool_calls_total += 1
                        except Exception as e:
                            result = f"ERR: {e}"
                            self._push("tool-err-label", f"     {result[:200]}")
                            continue

                        preview = result.rstrip()[:600]
                        if len(result) > 600:
                            preview += f"\n     (... {len(result)} caratteri totali)"
                        self._push("tool-out", f"     │ {preview.replace(chr(10), chr(10)+'     │ ')}")

                        assistant_msg = {
                            "role": "assistant",
                            "content": response_text,
                            "tool_calls": [dict(tc)],
                        }
                        messages.append(assistant_msg)
                        messages.append({
                            "role": "tool",
                            "content": result[:TOOL_RESULT_MAX],
                        })
                    else:
                        self._push("error", f"     tool '{name}' non trovato")
                        messages.append({
                            "role": "tool",
                            "content": f"Tool '{name}' non disponibile.",
                        })

            self._push("divider", f"\n{'—' * DIV_WIDTH}")

        except Exception as e:
            self._push("error", f"\n  ✗ {e}")

        self.streaming = False
        self.interrupted = False

    def _stream_one(
        self, messages: list[dict], tools: list[dict], system: str
    ) -> tuple[str, list[dict]]:
        full = ""
        tcm: dict[int, dict] = {}
        first = True

        try:
            for chunk in self.client.chat_stream(messages, tools, system):
                if self.interrupted:
                    break

                msg = chunk.get("message", {})
                delta = msg.get("content", "")
                if delta:
                    full += delta
                    if first:
                        self._push("agent", delta)
                        first = False
                    else:
                        self._push_append("agent", delta)

                for tc in msg.get("tool_calls") or []:
                    idx = tc.get("index", 0)
                    if idx not in tcm:
                        tcm[idx] = {"function": {"name": "", "arguments": ""}}
                    f = tc.get("function", {})
                    if f.get("name"):
                        tcm[idx]["function"]["name"] += f["name"]
                    if "arguments" in f:
                        v = f["arguments"]
                        tcm[idx]["function"]["arguments"] += (
                            v if isinstance(v, str) else json.dumps(v)
                        )

                if chunk.get("done"):
                    break
        except Exception as e:
            raise Exception(f"Ollama → {e}")

        out = []
        for idx in sorted(tcm):
            tc = tcm[idx]
            a = tc["function"].get("arguments", "")
            try:
                tc["function"]["arguments"] = json.loads(a) if a.strip() else {}
            except json.JSONDecodeError:
                tc["function"]["arguments"] = {}
            out.append(tc)
        return full, out

    def run(self):
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
