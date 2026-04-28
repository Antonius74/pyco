import json
import logging
import os
import select
import sys
import termios
import threading
import time
import tty
from queue import Queue, Empty
from typing import Any, Callable

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.text import Text
from rich.style import Style as RStyle
from rich.table import Table
from rich import box

from ollama_client import OllamaClient
from plugins import all_plugins, list_plugins
from config import load_config

logging.getLogger().setLevel(logging.CRITICAL)
logger = logging.getLogger("pyagent.tui")

TOOL_MAX = 4000

C = {
    "user":     "bold #58a6ff",
    "agent":    "#c9d1d9",
    "agent_m":  "italic #484f58",
    "tool":     "bold #d29922",
    "args":     "italic #6e7681",
    "out":      "#7ee787",
    "err":      "bold #f85149",
    "div":      "#21262d",
    "prompt":   "bold #58a6ff",
    "badge":    "bold #f778ba on #21262d",
    "success":  "bold #7ee787",
    "border":   "#30363d",
    "input_bg": "#161b22",
    "tool_bg":  "#161b22",
    "spin":     "bold #d29922",
}

LOGO_RAW = r"""
 ██████╗ ██╗   ██╗ ██████╗ ██████╗ 
 ██╔══██╗╚██╗ ██╔╝██╔════╝██╔═══██╗
 ██████╔╝ ╚████╔╝ ██║     ██║   ██║
 ██╔═══╝   ╚██╔╝  ██║     ██║   ██║
 ██║        ██║   ╚██████╗╚██████╔╝
 ╚═╝        ╚═╝    ╚═════╝ ╚═════╝ 
"""


class _Msg:
    __slots__ = ("role", "text", "name", "args", "tool_out", "tool_ok")
    def __init__(self, role="", text="", name="", args="", tool_out="", tool_ok=True):
        self.role = role; self.text = text
        self.name = name; self.args = args
        self.tool_out = tool_out; self.tool_ok = tool_ok


class PyAgentTUI:
    def __init__(self, model: str | None = None):
        cfg = load_config()
        self.client = OllamaClient(model=model)
        self.client.model = model or cfg.model
        self.system = cfg.system_prompt
        self.max_it = cfg.max_tool_iterations

        self.console = Console(color_system="truecolor", highlight=False)
        self._msgs: list[_Msg] = []
        self._streaming = False
        self._interrupt = False
        self._tc = 0
        self._running = True

        self._init_msgs(model)

    def _init_msgs(self, model: str | None = None):
        m = model or self.client.model
        self._msgs.append(_Msg("agent", LOGO_RAW))
        self._msgs.append(_Msg("agent_m", "  coding agent · ollama native · plugin"))
        self._msgs.append(_Msg("agent_m", f"  modello {m}  |  /help per comandi"))
        self._msgs.append(_Msg("agent_m", ""))

    def run(self):
        old = termios.tcgetattr(sys.stdin)
        tty.setraw(sys.stdin.fileno())
        try:
            # start input thread
            def input_loop():
                buf = ""
                while self._running:
                    if not select.select([sys.stdin], [], [], 0.05)[0]:
                        continue
                    try:
                        ch = os.read(sys.stdin.fileno(), 1).decode() if hasattr(os, 'read') else sys.stdin.read(1)
                    except Exception:
                        ch = ""
                    if ch == "\x03":  # ctrl+c
                        if self._streaming:
                            self._interrupt = True
                        else:
                            self._running = False
                    elif ch == "\x04":  # ctrl+d
                        if not buf.strip():
                            self._running = False
                    elif ch in ("\r", "\n"):
                        t = buf.strip()
                        buf = ""
                        if t:
                            self._on_input(t)
                    elif ch == "\x7f":  # backspace
                        buf = buf[:-1]
                    elif ord(ch) >= 32:
                        buf += ch

            threading.Thread(target=input_loop, daemon=True).start()

            renderable = self._build()
            with Live(renderable, console=self.console, screen=True,
                       refresh_per_second=10, transient=False) as live:
                self._live = live
                while self._running:
                    live.update(self._build())
                    time.sleep(0.06)

        finally:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old)

    def _build(self):
        t = Table.grid(padding=(0, 2))
        t.add_column(ratio=1)

        for m in self._msgs:
            if m.role == "tool":
                t.add_row(self._render_tool(m))
            elif m.role in C:
                t.add_row(Text(m.text, style=C[m.role]))
            else:
                t.add_row(Text(m.text))

        divider = Text("▔" * 60, style=C["div"])

        # input bar
        badge = Text(f" {self.client.model} ", style=C["badge"])
        input_panel = Panel(
            Text("", style=f"on {C['input_bg']}"),
            border_style=C["border"],
            box=box.SQUARE,
        )
        input_panel.title = Text("⬢", style=C["prompt"])
        input_panel.title_align = "left"
        # right-aligned badge as subtitle
        input_panel.subtitle = badge
        input_panel.subtitle_align = "right"

        # status
        if self._streaming:
            status = Text(" ●  Generating...  esc per interrompere", style=C["spin"])
        else:
            status = Text(" enter invia · ctrl+d esci · /help comandi", style=C["agent_m"])

        final = Table.grid(padding=0)
        final.add_column(ratio=1)
        final.add_row(t)
        final.add_row(divider)
        final.add_row(input_panel)
        final.add_row(status)
        return final

    def _render_tool(self, m: _Msg):
        style = C["out"] if m.tool_ok else C["err"]
        panel = Panel(
            Text(m.tool_out, style=style),
            title=f"▸ {m.name}",
            title_align="left",
            border_style=C["tool"],
            style=f"on {C['tool_bg']}",
            box=box.SQUARE,
        )
        items = [Text(m.args, style=C["args"])] if m.args else []
        items.append(panel)
        return Text.assemble(*items, "\n") if len(items) > 1 else panel

    def _on_input(self, text: str):
        if text.startswith("/"):
            p = text.split(maxsplit=1)
            self._cmd(p[0].lower(), p[1] if len(p) > 1 else "")
        else:
            if not self._streaming:
                threading.Thread(target=self._agent, args=(text,), daemon=True).start()

    def _cmd(self, cmd: str, arg: str):
        if cmd == "/exit":
            self._running = False
        elif cmd == "/clear":
            self._msgs.clear()
            self._init_msgs()
            self._tc = 0
        elif cmd == "/models":
            items = "\n".join(f"  {m} {'●' if m == self.client.model else ''}" for m in self.client.list_models())
            self._msgs.append(_Msg("tool", name="models", tool_out=items, tool_ok=True))
        elif cmd == "/plugins":
            items = "\n".join(f"  {p.tool_name}  {C['agent_m']}{p.description}" for p in list_plugins())
            self._msgs.append(_Msg("tool", name="plugins", tool_out=items, tool_ok=True))
        elif cmd.startswith("/model"):
            if arg:
                self.client.model = arg
                self._msgs.append(_Msg("success", f"\n  ✓ modello: {arg}"))
            else:
                self._msgs.append(_Msg("agent_m", f"\n  modello: {self.client.model}"))
        elif cmd == "/help":
            self._msgs.append(_Msg("agent", """\n
comandi                         tasti
────────────────────────────────────────────
/exit   uscire                  enter      inviare
/clear  pulire conversazione    ctrl+c     interrompere/uscire
/models modelli ollama          ctrl+d     uscire
/model  cambiare modello
/plugins plugin disponibili
/help   questo aiuto"""))
        else:
            self._msgs.append(_Msg("err", f"\n  comando: {cmd}"))

    def _agent(self, text: str):
        self._streaming = True
        self._interrupt = False
        self._tc = 0

        self._msgs.append(_Msg("user", f"\n  ▌ {text}"))

        tools = [p.get_tool_schema() for p in all_plugins()]
        msgs: list[dict] = [{"role": "user", "content": text}]
        agent_msg_idx = None

        try:
            for _ in range(self.max_it):
                if self._interrupt:
                    break
                resp, tcs = self._stream_one(msgs, tools, agent_msg_idx)
                agent_msg_idx = None
                if self._interrupt:
                    break
                if not tcs:
                    break

                for tc in tcs:
                    fn = tc.get("function", {})
                    name = fn.get("name", "")
                    args = fn.get("arguments", {})
                    if isinstance(args, str):
                        try: args = json.loads(args)
                        except json.JSONDecodeError: args = {}

                    arg_str = ", ".join(f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in args.items())

                    from plugins import get_plugin
                    pl = get_plugin(name)
                    if pl:
                        try:
                            out = str(pl.execute(**args))
                            self._tc += 1
                            ok = True
                        except Exception as e:
                            out = str(e); ok = False

                        self._msgs.append(_Msg("tool", name=name, args=arg_str, tool_out=out[:TOOL_MAX], tool_ok=ok))
                        msgs.append({"role": "assistant", "content": resp, "tool_calls": [dict(tc)]})
                        msgs.append({"role": "tool", "content": out[:TOOL_MAX]})
                    else:
                        self._msgs.append(_Msg("tool", name=name, args=arg_str, tool_out=f"tool non trovato", tool_ok=False))

            self._msgs.append(_Msg("div", "─" * 60))

        except Exception as e:
            self._msgs.append(_Msg("err", f"\n  ✗ {e}"))
        finally:
            self._streaming = False
            self._interrupt = False

    def _stream_one(self, msgs: list, tools: list, mut_idx: int | None):
        full = ""
        tmap: dict[int, dict] = {}
        started = False

        try:
            for ch in self.client.chat_stream(msgs, tools, self.system):
                if self._interrupt:
                    break
                msg = ch.get("message", {})
                d = msg.get("content", "")
                if d:
                    full += d
                    if not started:
                        self._msgs.append(_Msg("agent", d))
                        started = True
                    else:
                        last = self._msgs[-1]
                        if last.role == "agent":
                            last.text += d
                        else:
                            self._msgs.append(_Msg("agent", d))

                for tc in msg.get("tool_calls") or []:
                    idx = tc.get("index", 0)
                    if idx not in tmap:
                        tmap[idx] = {"function": {"name": "", "arguments": ""}}
                    fn = tc.get("function", {})
                    if fn.get("name"):
                        tmap[idx]["function"]["name"] += fn["name"]
                    if "arguments" in fn:
                        v = fn["arguments"]
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


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", "-m")
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
