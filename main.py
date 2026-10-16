#!/usr/bin/env python3
"""Arc Project Two — CLI entrypoint."""
import argparse
from rich.console import Console
from rich.markdown import Markdown
from core.agent import ArcAgent

console = Console()

def main():
    parser = argparse.ArgumentParser(description="Arc — Local AI Assistant")
    parser.add_argument("--model", default="llama3.1:8b", help="Ollama model name")
    args = parser.parse_args()

    console.print("[bold cyan]Arc Project Two[/bold cyan] — Local AI (no API keys)")
    console.print(f"Model: [green]{args.model}[/green]\n")
    console.print("Type 'exit' or 'quit' to leave.\n")

    agent = ArcAgent(model=args.model)

    while True:
        try:
            user_input = console.input("[bold blue]You:[/bold blue] ").strip()
            if user_input.lower() in ("exit", "quit", "q"):
                console.print("Goodbye.")
                break
            if not user_input:
                continue

            console.print("[bold magenta]Arc:[/bold magenta] thinking...")
            response = agent.chat(user_input)
            console.print(Markdown(response))
            console.print()

        except KeyboardInterrupt:
            console.print("\nGoodbye.")
            break
        except Exception as e:
            console.print(f"[red]Error:[/red] {e}")

if __name__ == "__main__":
    main()
