from plugins.base import BasePlugin, ToolParameter

try:
    import requests
except ImportError:
    requests = None


class WebFetchPlugin(BasePlugin):
    tool_name = "web_fetch"
    description = "Scarica il contenuto testuale di una pagina web (URL)."
    parameters = [
        ToolParameter(name="url", type="string", description="URL completo della pagina")
    ]

    def execute(self, url: str) -> str:
        if requests is None:
            return "Errore: modulo 'requests' non installato. Esegui: pip install requests"
        try:
            r = requests.get(url, timeout=15, headers={
                "User-Agent": "PyAgent/1.0"
            })
            r.raise_for_status()
            ct = r.headers.get("content-type", "")
            if "text/html" in ct:
                text = r.text[:8000]
            else:
                text = r.text[:8000]
            return text if text else "(contenuto vuoto)"
        except requests.RequestException as e:
            return f"Errore HTTP: {e}"
