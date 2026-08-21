from services.chatgpt import ChatGPT


class Ali(ChatGPT):
    """Ali provider compatibility entry point."""

    def __init__(self):
        super().__init__(provider="ali")
