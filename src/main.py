import argparse
import sys
import threading

from rich.console import Console
from rich.markdown import Markdown

from agent.factory import build_orchestrator, create_progress_notifier
from config.settings import settings


def validate_settings() -> None:
    missing = [
        name for name, val in [
            ("LLM_BASE_URL", settings.llm_base_url),
            ("LLM_API_KEY", settings.llm_api_key),
            ("LLM_MODEL", settings.llm_model),
            ("PROGRESS_LLM_BASE_URL", settings.progress_llm_base_url),
            ("PROGRESS_LLM_API_KEY", settings.progress_llm_api_key),
            ("PROGRESS_LLM_MODEL", settings.progress_llm_model),
        ] if not val
    ]
    if missing:
        print(f"Error: missing required env vars: {', '.join(missing)}", file=sys.stderr)
        print("Copy .env.example to .env and fill in the values.", file=sys.stderr)
        sys.exit(1)
    if not settings.serpapi_api_key:
        print("Warning: SERPAPI_API_KEY not set — flight search unavailable.", file=sys.stderr)
    if not settings.tavily_api_key:
        print("Warning: TAVILY_API_KEY not set — web search unavailable.", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description="TravelAgent CLI")
    parser.add_argument("--debug", action="store_true", help="Print tool calls and results to stderr")
    args = parser.parse_args()
    validate_settings()

    console = Console()
    progress = create_progress_notifier()
    progress_events = progress.subscribe()

    def print_progress() -> None:
        for event in progress.events(progress_events):
            parent = f" parent={event.parent_id}" if event.parent_id else ""
            marker = "○" if event.status == "pending" else "✓"
            style = "dim" if event.status == "pending" else "green"
            console.print(f"[{style}]{marker} {event.entry_id}{parent} L{event.level}: {event.label}[/{style}]")

    threading.Thread(target=print_progress, daemon=True).start()
    orchestrator = build_orchestrator(progress=progress, debug=args.debug)
    console.print("[bold]TravelAgent[/bold] — type your message, Ctrl-C to quit.\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\nGoodbye.")
            break
        if not user_input:
            continue

        try:
            with console.status("[dim]Thinking…[/dim]"):
                response = orchestrator.turn(user_input)
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            continue

        console.print()
        console.print(Markdown(response))
        console.print()


if __name__ == "__main__":
    main()
