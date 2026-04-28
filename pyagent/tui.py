import json
import logging
import re
import threading
import time
from typing import Any

from prompt_toolkit import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, VSplit, Window, Layout
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.dimension import D
from prompt_toolkit.styles import Style

from ollama_client import OllamaClient
from plugins import all_plugins, list_plugins
from config import load_config

logging.getLogger("prompt_toolkit").setLevel(logging.CRITICAL)
logger = logging.getLogger("pyagent.tui")

STYLE = Style.from_dict({
    "root":            "bg:#0a0c10 #c6cdd4",
    "logo":            "bg:#0a0c10 #89b4fa bold",
    "user":            "bg:#0a0c10 #aac4ff",
    "agent":           "bg:#0a0c10 #c6cdd4",
    "agent-dim":       "bg:#0a0c10 #5c6370 italic",
    "thinking":        "bg:#0a0c10 #5c6370 italic",
    "tool-tag":        "bg:#11131a #f2cd7f bold",
    "tool-args":       "bg:#0a0c10 #6c7086 italic",
    "tool-out":        "bg:#0a0c10 #a6e3a1",
    "tool-err":        "bg:#0a0c10 #f38ba8",
    "error":           "bg:#0a0c10 #f38ba8 bold",
    "success":         "bg:#0a0c10 #a6e3a1 bold",
    "divider":         "bg:#0a0c10 #2a2e3a",
    "input-area":      "bg:#11131a",
    "input-prompt":    "bg:#11131a #89b4fa bold",
    "input-model-badge": "bg:#1e2230 #f2cde7 bold",
    "status-bar":      "bg:#11131a #5c6370",
    "status-spin":     "bg:#11131a #f2cd7f",
    "status-model":    "bg:#11131a #89b4fa bold",
    "status-hint":     "bg:#11131a #45475a italic",
})

TOOL_MAX = 6000
DIV = "─" * 60
SPIN = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
WELCOME = """\
  █████╗  █████╗   █████╗
  ██╔══╝  ██╔══╝   ██╔══╝
  █████╗  ██║      ██║
  ╚═══██╗ ██║      ██║
  █████╔╝ ███████╗ ███████╗
  ╚════╝  ╚══════╝ ╚══════╝
"""


class _Msg:
    __slots__ = ("style", "text")
    def __init__(self, s: str, t: str): self.style = s; self.text = t


class PyAgentTUI:
    def __init__(self, model: str | None = None):
        cfg = load_config()
        self.client = OllamaClient(model=model)
        self.client.model = model or cfg.model
        self.system = cfg.system_prompt
        self.max_it = cfg.max_tool_iterations

        self._lk = threading.Lock()
        self._msgs: list[_Msg] = []
        self._streaming = False
        self._interrupt = False
        self._tc_total = 0
        self._t0 = 0.0
        self._spin_i = 0
        self._spin_t = 0.0

        self._model_label = f" {self.client.model} "

        self._out_ctrl = FormattedTextControl(self._render, focusable=False)

        self._in_buf = Buffer(multiline=True)
        in_ctrl = BufferControl(buffer=self._in_buf)

        prompt_icon = Window(
            content=FormattedTextControl([("class:input-prompt", " ⬢ ")]),
            width=3,
            style="class:input-area",
        )

        model_badge = Window(
            content=FormattedTextControl(
                lambda: [("class:input-model-badge", self._model_label)]
            ),
            width=len(self.client.model) + 4,
            style="class:input-area",
            height=1,
        )

        input_row = VSplit([
            prompt_icon,
            Window(content=in_ctrl, wrap_lines=True),
            model_badge,
        ], style="class:input-area", height=D(min=1, max=8))

        self._status_ctrl = FormattedTextControl(self._status_line)
        status = Window(content=self._status_ctrl, height=1, style="class:status-bar")

        out = Window(content=self._out_ctrl, wrap_lines=False, always_hide_cursor=True)

        root = HSplit([
            out,
            Window(height=1, char="▔", style="class:divider"),
            input_row,
            status,
        ])

        self.kb = self._bind_keys()
        self.app = Application(
            layout=Layout(root, focused_element=input_row),
            key_bindings=self.kb,
            style=STYLE,
            full_screen=True,
            mouse_support=True,
            refresh_interval=0.08,
        )

        self._put("logo", WELCOME)
        self._put("agent-dim", "  /help per i comandi  |  ctrl+d per uscire")

    # ── keys ────────────────────────────────────────────────────────

    def _bind_keys(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add("escape", "enter")
        def _(event):
            self._in_buf.insert_text("\n")

        @kb.add("c-j")
        @kb.add("enter")
        def _(event):
            t = self._in_buf.text.rstrip("\n")
            if not t.strip():
                return
            self._in_buf.reset()
            self._dispatch(t.strip())

        @kb.add("c-c")
        def _(event):
            if self._streaming:
                self._interrupt = True
                self._put("error", "\n  ⏹ interrotto")
            else:
                event.app.exit()

        @kb.add("c-d")
        def _(event):
            if not self._in_buf.text:
                event.app.exit()

        return kb

    # ── output ──────────────────────────────────────────────────────

    def _put(self, style: str, text: str):
        with self._lk:
            self._msgs.append(_Msg(style, text))
        self.app.invalidate()

    def _append(self, style: str, text: str):
        with self._lk:
            if self._msgs and self._msgs[-1].style == style:
                self._msgs[-1].text += text
            else:
                self._msgs.append(_Msg(style, text))
        self.app.invalidate()

    def _render(self):
        parts = []
        with self._lk:
            for m in self._msgs:
                parts.append(("class:" + m.style, m.text))
                parts.append(("", "\n"))
        return parts

    def _status_line(self):
        now = time.monotonic()
        if self._streaming:
            if now - self._spin_t > 0.08:
                self._spin_i = (self._spin_i + 1) % len(SPIN)
                self._spin_t = now
            elapsed = f" {now - self._t0:.1f}s" if self._t0 else ""
            tc = f" {self._tc_total} tool calls" if self._tc_total else ""
            return [
                ("class:status-spin", f" {SPIN[self._spin_i]} "),
                ("", "Generating"),
                ("", tc),
                ("", elapsed),
                ("", "  "),
                ("class:status-hint", "esc interrompi"),
            ]
        return [
            ("class:status-hint", " ctrl+j invia  esc+enter multilinea  ctrl+c esci"),
            ("", "  "),
            ("class:status-model", self._model_label.strip()),
        ]

    # ── dispatch ────────────────────────────────────────────────────

    def _dispatch(self, text: str):
        if text.startswith("/"):
            p = text.split(maxsplit=1)
            self._cmd(p[0].lower(), p[1] if len(p) > 1 else "")
        else:
            self._agent(text)

    def _cmd(self, cmd: str, arg: str):
        if cmd == "/exit":
            self.app.exit()
        elif cmd == "/clear":
            with self._lk:
                self._msgs.clear()
            self._put("logo", WELCOME)
            self._put("agent-dim", "  conversazione pulita")
            self._tc_total = 0
            self._t0 = 0
        elif cmd == "/models":
            self._put("divider", f"\n{DIV}")
            self._put("tool-tag", "  ▸ /models")
            for m in self.client.list_models():
                cur = " ●" if m == self.client.model else ""
                self._put("tool-out", f"     {m}{cur}")
            self._put("divider", DIV)
        elif cmd == "/plugins":
            self._put("divider", f"\n{DIV}")
            self._put("tool-tag", "  ▸ /plugins")
            for p in list_plugins():
                self._put("tool-out", f"    {p.tool_name}")
                self._put("agent-dim", f"      {p.description}")
            self._put("divider", DIV)
        elif cmd.startswith("/model"):
            if arg:
                self.client.model = arg
                self._model_label = f" {arg} "
                self._put("success", f"\n  → modello: {arg}")
            else:
                self._put("agent-dim", f"\n  modello: {self.client.model}")
        elif cmd == "/help":
            self._put("agent", """\n\
  comandi
  ───────
  /exit           uscire
  /clear          pulire conversazione
  /models         modelli ollama
  /model <nome>   cambiare modello
  /plugins        plugin disponibili
  /help           questo aiuto
  ctrl+enter      nuova riga
  ctrl+c          interrompere / uscire
  ctrl+d          uscire""")
        else:
            self._put("error", f"\n  comando sconosciuto: {cmd}")

    # ── agent loop ──────────────────────────────────────────────────

    def _agent(self, text: str):
        if self._streaming:
            return

        self._streaming = True
        self._interrupt = False
        self._tc_total = 0
        self._t0 = time.monotonic()

        self._put("user", f"\n▌ {text}")

        tools = [p.get_tool_schema() for p in all_plugins()]
        msgs: list[dict] = [{"role": "user", "content": text}]

        try:
            for _ in range(self.max_it):
                if self._interrupt:
                    break

                resp_text, tcs = self._stream_msgs(msgs, tools, self.system)

                if self._interrupt:
                    break

                if not tcs:
                    break

                for tc in tcs:
                    fn = tc.get("function", {})
                    name = fn.get("name", "")
                    args = fn.get("arguments", {})
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {}

                    arg_str = ", ".join(f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in args.items())
                    self._put("tool-tag", f"\n  ▸ {name}")
                    if arg_str:
                        self._put("tool-args", f"     {arg_str}")

                    from plugins import get_plugin
                    pl = get_plugin(name)
                    if pl:
                        try:
                            out = str(pl.execute(**args))
                            self._tc_total += 1
                        except Exception as e:
                            out = f"exception: {e}"
                            self._put("tool-err", f"     ERR: {e}")
                            continue

                        for line in out.rstrip().split("\n")[:40]:
                            self._put("tool-out", f"     │ {line}")

                        am = {
                            "role": "assistant",
                            "content": resp_text,
                            "tool_calls": [dict(tc)],
                        }
                        msgs.append(am)
                        msgs.append({"role": "tool", "content": out[:TOOL_MAX]})
                    else:
                        self._put("tool-err", f"     tool '{name}' non trovato")
                        msgs.append({"role": "tool", "content": f"Tool '{name}' non disponibile."})

            self._put("divider", f"\n{DIV}")

        except Exception as e:
            self._put("error", f"\n  ✗ {e}")

        self._streaming = False
        self._interrupt = False

    # ── stream ──────────────────────────────────────────────────────

    def _stream_msgs(self, msgs: list, tools: list, system: str):
        full = ""
        tmap: dict[int, dict] = {}
        started = False

        try:
            for ch in self.client.chat_stream(msgs, tools, system):
                if self._interrupt:
                    break
                msg = ch.get("message", {})
                delta = msg.get("content", "")
                if delta:
                    full += delta
                    self._append("agent", delta)

                for tc in msg.get("tool_calls") or []:
                    idx = tc.get("index", 0)
                    if idx not in tmap:
                        tmap[idx] = {"function": {"name": "", "arguments": ""}}
                    f = tc.get("function", {})
                    if f.get("name"):
                        tmap[idx]["function"]["name"] += f["name"]
                    if "arguments" in f:
                        v = f["arguments"]
                        tmap[idx]["function"]["arguments"] += (v if isinstance(v, str) else json.dumps(v))
                if ch.get("done"):
                    break
        except Exception as e:
            raise Exception(f"ollama: {e}")

        out = []
        for idx in sorted(tmap):
            tc = tmap[idx]
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
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", "-m", help="modello ollama")
    ap.add_argument("prompt", nargs="*")
    ap.add_argument("--no-tools", action="store_true")
    a = ap.parse_args()

    from config import ensure_dirs
    from plugins import discover_plugins
    import plugins as _plugins
    ensure_dirs()
    discover_plugins(_plugins)

    if a.prompt:
        from agent import Agent
        ag = Agent(OllamaClient(model=a.model) if a.model else None)
        r = ag.run(" ".join(a.prompt), tools_enabled=not a.no_tools)
        print(r.answer)
        return
    PyAgentTUI(model=a.model).run()


if __name__ == "__main__":
    main()
