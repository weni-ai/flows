from temba.tickets.models import TicketerType


class TwilioFlex2Type(TicketerType):
    """
    Type for using Twilio Flex 2.x as a ticketer
    """

    name = "Twilio Flex 2.x"
    slug = "twilioflex2"
    icon = "icon-twilio_original"
    
    CONFIG_ACCOUNT_SID = "account_sid"
    CONFIG_AUTH_TOKEN = "auth_token"
    CONFIG_FLEX_INSTANCE_SID = "flex_instance_sid"
    CONFIG_FLEX_WORKSPACE_SID = "flex_workspace_sid"
    CONFIG_FLEX_WORKFLOW_SID = "flex_workflow_sid"
    
    connect_view = None
    
    def is_available_to(self, user):
        return True
