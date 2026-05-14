from config.settings import settings
from clients.llm_client import LLMClient, LLMError
from agent.session import ConversationHistory


def main() -> None:
    client = LLMClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        extra_headers=settings.llm_extra_headers,
    )
    history = ConversationHistory("You are a helpful travel planning assistant.")

    print("TravelAgent — type your message, Ctrl-C to quit.")
    while True:
        try:
            user_input = input("\nYou: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye.")
            break
        if not user_input:
            continue

        history.add_user(user_input)
        try:
            msg = client.chat(history.messages)
        except LLMError as e:
            print(f"Error: {e}")
            continue

        history.add_assistant(msg)
        print(f"\nAgent: {msg.get('content', '')}")


if __name__ == "__main__":
    main()
