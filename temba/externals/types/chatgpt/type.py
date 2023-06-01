from temba.externals.models import ExternalServiceType
from .serializers import ChatGPTSerializer


class ChatGPTType(ExternalServiceType):
    """
    Type for using chatgpt as a external service
    """

    CONFIG_API_KEY = "api_key"
    CONFIG_AI_MODEL = "ai_model"
    CONFIG_RULES = "rules"
    CONFIG_KNOWLEDGE_BASE = "knowledge_base"

    AI_MODELS = [
        ("gpt-3.5-turbo", "gpt-3.5-turbo"),
        ("gpt-4", "gpt-4"),
    ]

    serializer_class = ChatGPTSerializer

    name = "ChatGPT"
    slug = "chatgpt"
    icon = "icon-power-cord"

    def is_available_to(self, user):
        return True
