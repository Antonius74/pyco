import os
from pathlib import Path

from plugins.base import BasePlugin, ToolParameter


class ReadFilePlugin(BasePlugin):
    tool_name = "read_file"
    description = "Legge il contenuto di un file e lo restituisce."
    parameters = [
        ToolParameter(name="path", type="string", description="Percorso del file da leggere")
    ]

    def execute(self, path: str) -> str:
        path = os.path.expanduser(path)
        if not Path(path).exists():
            return f"Errore: file '{path}' non trovato."
        try:
            with open(path) as f:
                content = f.read(10000)
            return content if content else "(file vuoto)"
        except Exception as e:
            return f"Errore nella lettura: {e}"


class WriteFilePlugin(BasePlugin):
    tool_name = "write_file"
    description = "Scrive contenuto in un file. Crea o sovrascrive il file."
    parameters = [
        ToolParameter(name="path", type="string", description="Percorso del file"),
        ToolParameter(name="content", type="string", description="Contenuto da scrivere"),
    ]

    def execute(self, path: str, content: str) -> str:
        path = os.path.expanduser(path)
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w") as f:
                f.write(content)
            return f"File scritto: {path} ({len(content)} byte)"
        except Exception as e:
            return f"Errore nella scrittura: {e}"


class ListDirPlugin(BasePlugin):
    tool_name = "list_dir"
    description = "Elenca file e cartelle in una directory."
    parameters = [
        ToolParameter(name="path", type="string", description="Percorso della directory", required=False)
    ]

    def execute(self, path: str = ".") -> str:
        path = os.path.expanduser(path)
        if not os.path.isdir(path):
            return f"Errore: '{path}' non è una directory."
        try:
            entries = os.listdir(path)
            if not entries:
                return "(directory vuota)"
            return "\n".join(sorted(entries))
        except Exception as e:
            return f"Errore: {e}"
