from rest_framework.urlpatterns import format_suffix_patterns

from django.conf.urls import url
from django.urls import include, path

from temba.api.v2.elasticsearch.views import ContactsElasticSearchEndpoint

from .flows.urls import urlpatterns as flows_urlpatterns
from .internals.urls import urlpatterns as internals_urlpatterns
from .views import (
    ArchivesEndpoint,
    AuthenticateView,
    BoundariesEndpoint,
    BroadcastsEndpoint,
    CampaignEventsEndpoint,
    CampaignsEndpoint,
    ChannelEventsEndpoint,
    ChannelsEndpoint,
    ClassifiersEndpoint,
    ContactActionsEndpoint,
    ContactsEndpoint,
    ContactsLeanEndpoint,
    ContactsTemplatesEndpoint,
    ContactsTemplatesEndpointNew,
    DefinitionsEndpoint,
    ExplorerView,
    ExternalServicesEndpoint,
    FieldsEndpoint,
    FilterTemplatesEndpoint,
    FilterTemplatesEndpointNew,
    FlowsEndpoint,
    FlowsLabelsEndpoint,
    FlowStartsEndpoint,
    GlobalsEndpoint,
    GroupsEndpoint,
    LabelsEndpoint,
    MediaEndpoint,
    MessageActionsEndpoint,
    MessagesEndpoint,
    ProductsEndpoint,
    ResthookEventsEndpoint,
    ResthooksEndpoint,
    ResthookSubscribersEndpoint,
    RootView,
    RunsEndpoint,
    TemplatesEndpoint,
    TicketActionsEndpoint,
    TicketersEndpoint,
    TicketsEndpoint,
    ToggleChannelsEndpoint,
    TopicsEndpoint,
    UsersEndpoint,
    WhatsappBroadcastsEndpoint,
    WhatsappFlowsEndpoint,
    WorkspaceEndpoint,
)
from .wenibrain.views import BrainInfoEndpoint
from .wenigpt.views import IntelligencesEndpoint

urlpatterns = [
    url(r"^$", RootView.as_view(), name="api.v2"),
    url(r"^explorer/$", ExplorerView.as_view(), name="api.v2.explorer"),
    url(r"^authenticate$", AuthenticateView.as_view(), name="api.v2.authenticate"),
    # ========== endpoints A-Z ===========
    url(r"^archives$", ArchivesEndpoint.as_view(), name="api.v2.archives"),
    url(r"^boundaries$", BoundariesEndpoint.as_view(), name="api.v2.boundaries"),
    url(r"^broadcasts$", BroadcastsEndpoint.as_view(), name="api.v2.broadcasts"),
    url(r"^whatsapp_broadcasts$", WhatsappBroadcastsEndpoint.as_view(), name="api.v2.whatsapp_broadcasts"),
    url(r"^campaigns$", CampaignsEndpoint.as_view(), name="api.v2.campaigns"),
    url(r"^campaign_events$", CampaignEventsEndpoint.as_view(), name="api.v2.campaign_events"),
    url(r"^channels$", ChannelsEndpoint.as_view(), name="api.v2.channels"),
    url(r"^channel_events$", ChannelEventsEndpoint.as_view(), name="api.v2.channel_events"),
    url(r"^toggle_channels$", ToggleChannelsEndpoint.as_view(), name="api.v2.toggle_channels"),
    url(r"^classifiers$", ClassifiersEndpoint.as_view(), name="api.v2.classifiers"),
    url(r"^contacts$", ContactsEndpoint.as_view(), name="api.v2.contacts"),
    url(r"^contacts_lean$", ContactsLeanEndpoint.as_view(), name="api.v2.contacts_lean"),
    url(r"^contact_actions$", ContactActionsEndpoint.as_view(), name="api.v2.contact_actions"),
    url(r"^contact_templates$", ContactsTemplatesEndpoint.as_view(), name="api.v2.contact_templates"),
    url(r"^contact_templates_new$", ContactsTemplatesEndpointNew.as_view(), name="api.v2.contact_templates_new"),
    url(r"^contacts_elastic$", ContactsElasticSearchEndpoint.as_view(), name="api.v2.contacts_elastic"),
    url(r"^filter_templates$", FilterTemplatesEndpoint.as_view(), name="api.v2.filter_templates"),
    url(r"^filter_templates_new$", FilterTemplatesEndpointNew.as_view(), name="api.v2.filter_templates_new"),
    url(r"^definitions$", DefinitionsEndpoint.as_view(), name="api.v2.definitions"),
    url(r"^fields$", FieldsEndpoint.as_view(), name="api.v2.fields"),
    url(r"^flow_starts$", FlowStartsEndpoint.as_view(), name="api.v2.flow_starts"),
    url(r"^flows$", FlowsEndpoint.as_view(), name="api.v2.flows"),
    url(r"^flows_labels$", FlowsLabelsEndpoint.as_view(), name="api.v2.flows_labels"),
    url(r"^globals$", GlobalsEndpoint.as_view(), name="api.v2.globals"),
    url(r"^groups$", GroupsEndpoint.as_view(), name="api.v2.groups"),
    url(r"^labels$", LabelsEndpoint.as_view(), name="api.v2.labels"),
    url(r"^media$", MediaEndpoint.as_view(), name="api.v2.media"),
    url(r"^messages$", MessagesEndpoint.as_view(), name="api.v2.messages"),
    url(r"^message_actions$", MessageActionsEndpoint.as_view(), name="api.v2.message_actions"),
    url(r"^org$", WorkspaceEndpoint.as_view(), name="api.v2.org"),  # deprecated
    url(r"^products$", ProductsEndpoint.as_view(), name="api.v2.products"),
    url(r"^resthooks$", ResthooksEndpoint.as_view(), name="api.v2.resthooks"),
    url(r"^resthook_events$", ResthookEventsEndpoint.as_view(), name="api.v2.resthook_events"),
    url(r"^resthook_subscribers$", ResthookSubscribersEndpoint.as_view(), name="api.v2.resthook_subscribers"),
    url(r"^runs$", RunsEndpoint.as_view(), name="api.v2.runs"),
    url(r"^templates$", TemplatesEndpoint.as_view(), name="api.v2.templates"),
    url(r"^ticketers$", TicketersEndpoint.as_view(), name="api.v2.ticketers"),
    url(r"^external_services$", ExternalServicesEndpoint.as_view(), name="api.v2.external_services"),
    url(r"^tickets$", TicketsEndpoint.as_view(), name="api.v2.tickets"),
    url(r"^ticket_actions$", TicketActionsEndpoint.as_view(), name="api.v2.ticket_actions"),
    url(r"^topics$", TopicsEndpoint.as_view(), name="api.v2.topics"),
    url(r"^users$", UsersEndpoint.as_view(), name="api.v2.users"),
    url(r"^workspace$", WorkspaceEndpoint.as_view(), name="api.v2.workspace"),
    url(r"^intelligences$", IntelligencesEndpoint.as_view(), name="api.v2.intelligences"),
    url(r"^brain_info$", BrainInfoEndpoint.as_view(), name="api.v2.brain_info"),
    url(r"^whatsapp_flows$", WhatsappFlowsEndpoint.as_view(), name="api.v2.whatsapp_flows"),
]

urlpatterns = format_suffix_patterns(urlpatterns, allowed=["json", "api"])

urlpatterns += [path("internals/", include(internals_urlpatterns))]
urlpatterns += flows_urlpatterns
