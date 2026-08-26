from services.chatgpt import ChatGPT


class Ali(ChatGPT):
    """Ali provider compatibility entry point."""

    def __init__(self, usage_report_path=None):
        super().__init__(provider="ali", usage_report_path=usage_report_path)
