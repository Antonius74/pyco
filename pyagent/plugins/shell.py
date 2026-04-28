import subprocess

from plugins.base import BasePlugin, ToolParameter


class ShellPlugin(BasePlugin):
    tool_name = "shell"
    description = "Esegue un comando shell nel terminale. Restituisce stdout e stderr."
    parameters = [
        ToolParameter(name="command", type="string", description="Comando shell da eseguire")
    ]

    def execute(self, command: str) -> str:
        try:
            r = subprocess.run(
                command, shell=True, capture_output=True, text=True, timeout=30
            )
            out = r.stdout.strip() or "(nessun output)"
            err = r.stderr.strip()
            if err:
                out += f"\n[stderr]: {err}"
            return out
        except subprocess.TimeoutExpired:
            return "Errore: timeout (30s) superato."
        except Exception as e:
            return f"Errore: {e}"
