import argparse
import logging
import os
import sys

from config import load_config, ensure_dirs
from ollama_client import OllamaClient
from agent import Agent
from plugins import all_plugins, list_plugins

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
logger = logging.getLogger("pyagent")


def setup():
    ensure_dirs()
    import plugins as _plugins
    from plugins import discover_plugins
    discover_plugins(_plugins)


def cmd_list_models(client: OllamaClient):
    models = client.list_models()
    if not models:
        print("Nessun modello trovato. Avvia Ollama e scarica un modello: ollama pull llama3.2")
        return
    print("Modelli disponibili:")
    for m in models:
        marker = " (attivo)" if m == client.model else ""
        print(f"  - {m}{marker}")


def cmd_list_plugins():
    plugins = list_plugins()
    if not plugins:
        print("Nessun plugin caricato.")
        return
    for p in plugins:
        print(f"  {p.tool_name}: {p.description}")


def cmd_version():
    print("PyAgent v0.2.0")
    cfg = load_config()
    print(f"  Modello: {cfg.model}")
    print(f"  Ollama:  {cfg.ollama_host}")
    print(f"  Plugin:  {cfg.plugins_dir}")


def parse_args():
    p = argparse.ArgumentParser(description="PyAgent - Coding Agent con plugin")
    p.add_argument("prompt", nargs="*", help="Prompt da inviare all'agent")
    p.add_argument("--model", "-m", help="Modello Ollama da usare")
    p.add_argument("--config", "-c", action="store_true", help="Mostra configurazione")
    p.add_argument("--models", action="store_true", help="Lista modelli disponibili")
    p.add_argument("--plugins", action="store_true", help="Lista plugin disponibili")
    p.add_argument("--no-tools", action="store_true", help="Disabilita i tool")
    p.add_argument("--debug", action="store_true", help="Log di debug")
    p.add_argument("--simple", "-s", action="store_true", help="Interfaccia testuale semplice (no TUI)")
    p.add_argument("--version", "-v", action="store_true", help="Versione")
    return p.parse_args()


def simple_repl(agent: Agent):
    while True:
        try:
            user = input("\033[92mpyagent>\033[0m ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nCiao!")
            break
        if not user:
            continue
        if user == "/exit":
            break
        if user.startswith("/"):
            print("Comandi: /exit | Usa la TUI (senza --simple) per tutti i comandi.")
            continue
        try:
            result = agent.run(user)
            print(result.answer)
            print()
        except Exception as e:
            print(f"\033[91mErrore: {e}\033[0m")


def main():
    args = parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        logging.getLogger("pyagent").setLevel(logging.DEBUG)

    setup()

    if args.config:
        cfg = load_config()
        for k, v in sorted(cfg.__dict__.items()):
            print(f"  {k}: {v}")
        return

    if args.version:
        cmd_version()
        return

    if args.models:
        client = OllamaClient(model=args.model) if args.model else OllamaClient()
        cmd_list_models(client)
        return

    if args.plugins:
        cmd_list_plugins()
        return

    if args.prompt:
        client = OllamaClient(model=args.model) if args.model else OllamaClient()
        agent = Agent(client)
        prompt = " ".join(args.prompt)
        result = agent.run(prompt, tools_enabled=not args.no_tools)
        print(result.answer)
        return

    if args.simple:
        client = OllamaClient(model=args.model) if args.model else OllamaClient()
        agent = Agent(client)
        simple_repl(agent)
    else:
        from tui import PyAgentTUI
        PyAgentTUI(model=args.model).run()


if __name__ == "__main__":
    main()
