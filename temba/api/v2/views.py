import itertools
import json
from enum import Enum

from rest_framework import generics, status, views
from rest_framework.pagination import CursorPagination
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.reverse import reverse
from smartmin.views import SmartFormView, SmartTemplateView
from weni_datalake_sdk.clients.redshift.events import get_events

from django import forms
from django.contrib.auth import authenticate, login
from django.contrib.auth.models import User
from django.db import connection
from django.db.models import Count, Prefetch, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils.translation import ugettext_lazy as _
from django.views.decorators.csrf import csrf_exempt

from temba.api.models import APIToken, Resthook, ResthookSubscriber, WebHookEvent
from temba.api.v2.elasticsearch.views import ContactsElasticSearchEndpoint
from temba.api.v2.views_base import (
    BaseAPIView,
    BulkWriteAPIMixin,
    ContactsCursorPagination,
    ContactsTemplateCursorPagination,
    CreatedOnCursorPagination,
    DateJoinedCursorPagination,
    DeleteAPIMixin,
    ListAPIMixin,
    ModifiedOnCursorPagination,
    NameCursorPagination,
    WriteAPIMixin,
)
from temba.archives.models import Archive
from temba.campaigns.models import Campaign, CampaignEvent
from temba.channels.models import Channel, ChannelEvent
from temba.classifiers.models import Classifier
from temba.contacts.models import URN, Contact, ContactField, ContactGroup, ContactGroupCount, ContactURN
from temba.externals.models import ExternalService
from temba.flows.models import Flow, FlowLabel, FlowRun, FlowStart
from temba.globals.models import Global
from temba.locations.models import AdminBoundary, BoundaryAlias
from temba.msgs.models import Broadcast, Label, LabelCount, Msg, SystemLabel
from temba.orgs.models import OrgRole
from temba.templates.models import Template, TemplateTranslation
from temba.tickets.models import Ticket, Ticketer, Topic
from temba.utils import splitting_getlist, str_to_bool
from temba.wpp_flows.models import WhatsappFlow
from temba.wpp_products.models import Product

from ..models import SSLPermission
from ..support import InvalidQueryError
from .serializers import (
    AdminBoundaryReadSerializer,
    ArchiveReadSerializer,
    BroadcastReadSerializer,
    BroadcastWriteSerializer,
    CampaignEventReadSerializer,
    CampaignEventWriteSerializer,
    CampaignReadSerializer,
    CampaignWriteSerializer,
    ChannelEventReadSerializer,
    ChannelReadSerializer,
    ClassifierReadSerializer,
    ContactBulkActionSerializer,
    ContactFieldReadSerializer,
    ContactFieldWriteSerializer,
    ContactGroupReadSerializer,
    ContactGroupWriteSerializer,
    ContactLeanReadSerializer,
    ContactReadSerializer,
    ContactTemplateSerializer,
    ContactTemplateSerializerNew,
    ContactWriteSerializer,
    EventFilterSerializer,
    ExternalServicesReadSerializer,
    FilterTemplateSerializer,
    FilterTemplateSerializerNew,
    FlowReadSerializer,
    FlowRunReadSerializer,
    FlowsLabelsReadSerializer,
    FlowStartReadSerializer,
    FlowStartWriteSerializer,
    GlobalReadSerializer,
    GlobalWriteSerializer,
    LabelReadSerializer,
    LabelWriteSerializer,
    MsgBulkActionSerializer,
    MsgReadSerializer,
    ProductReadSerializer,
    ResthookReadSerializer,
    ResthookSubscriberReadSerializer,
    ResthookSubscriberWriteSerializer,
    TemplateReadSerializer,
    TicketBulkActionSerializer,
    TicketerReadSerializer,
    TicketReadSerializer,
    ToggleChannelWriteSerializer,
    TopicReadSerializer,
    TopicWriteSerializer,
    UserReadSerializer,
    WebHookEventReadSerializer,
    WhatsappBroadcastReadSerializer,
    WhatsappBroadcastWriteSerializer,
    WhatsappFlowReadSerializer,
    WorkspaceReadSerializer,
)
from .wenibrain.views import BrainInfoEndpoint
from .wenigpt.views import IntelligencesEndpoint


class RootView(views.APIView):
    """
    We provide a RESTful JSON API for you to interact with your data from outside applications. The following endpoints
    are available:

     * [/api/v2/archives](/api/v2/archives) - to list archives of messages and runs
     * [/api/v2/boundaries](/api/v2/boundaries) - to list administrative boundaries
     * [/api/v2/broadcasts](/api/v2/broadcasts) - to list and send message broadcasts
     * [/api/v2/campaigns](/api/v2/campaigns) - to list, create, or update campaigns
     * [/api/v2/campaign_events](/api/v2/campaign_events) - to list, create, update or delete campaign events
     * [/api/v2/channels](/api/v2/channels) - to list channels
     * [/api/v2/channel_events](/api/v2/channel_events) - to list channel events
     * [/api/v2/classifiers](/api/v2/classifiers) - to list classifiers
     * [/api/v2/contacts](/api/v2/contacts) - to list, create, update or delete contacts
     * [/api/v2/contact_actions](/api/v2/contact_actions) - to perform bulk contact actions
     * [/api/v2/contact_templates](/api/v2/contact_templates) - to list contact data with templates messages
     * [/api/v2/definitions](/api/v2/definitions) - to export flow definitions, campaigns, and triggers
     * [/api/v2/fields](/api/v2/fields) - to list, create or update contact fields
     * [/api/v2/flow_starts](/api/v2/flow_starts) - to list flow starts and start contacts in flows
     * [/api/v2/flows](/api/v2/flows) - to list flows
     * [/api/v2/globals](/api/v2/globals) - to list globals
     * [/api/v2/groups](/api/v2/groups) - to list, create, update or delete contact groups
     * [/api/v2/labels](/api/v2/labels) - to list, create, update or delete message labels
     * [/api/v2/messages](/api/v2/messages) - to list messages
     * [/api/v2/message_actions](/api/v2/message_actions) - to perform bulk message actions
     * [/api/v2/runs](/api/v2/runs) - to list flow runs
     * [/api/v2/products](/api/v2/products) - to list current WhatsApp products on your account
     * [/api/v2/resthooks](/api/v2/resthooks) - to list resthooks
     * [/api/v2/resthook_events](/api/v2/resthook_events) - to list resthook events
     * [/api/v2/resthook_subscribers](/api/v2/resthook_subscribers) - to list, create or delete subscribers on your resthooks
     * [/api/v2/templates](/api/v2/templates) - to list current WhatsApp templates on your account
     * [/api/v2/ticketers](/api/v2/ticketers) - to list ticketing services
     * [/api/v2/tickets](/api/v2/tickets) - to list tickets
     * [/api/v2/ticket_actions](/api/v2/ticket_actions) - to perform bulk ticket actions
     * [/api/v2/topics](/api/v2/topics) - to list and create topics
     * [/api/v2/users](/api/v2/users) - to list user logins
     * [/api/v2/workspace](/api/v2/workspace) - to view your workspace
     * [/api/v2/intelligences](/api/v2/intelligences) - to view your intelligences

    To use the endpoint simply append _.json_ to the URL. For example [/api/v2/flows](/api/v2/flows) will return the
    documentation for that endpoint but a request to [/api/v2/flows.json](/api/v2/flows.json) will return a JSON list of
    flow resources.

    You may wish to use the [API Explorer](/api/v2/explorer) to interactively experiment with the API.

    ## Verbs

    All endpoints follow standard REST conventions. You can list a set of resources by making a `GET` request to the
    endpoint, create or update resources by making a `POST` request, or delete a resource with a `DELETE` request.

    ## Status Codes

    The success or failure of requests is represented by status codes as well as a message in the response body:

     * **200**: A list or update request was successful.
     * **201**: A resource was successfully created (only returned for `POST` requests).
     * **204**: An empty response - used for both successful `DELETE` requests and `POST` requests that update multiple
                resources.
     * **400**: The request failed due to invalid parameters. Do not retry with the same values, and the body of the
                response will contain details.
     * **403**: You do not have permission to access this resource.
     * **404**: The resource was not found (returned by `POST` and `DELETE` methods).
     * **429**: You have exceeded the rate limit for this endpoint (see below).

    ## Rate Limiting

    All endpoints are subject to rate limiting. If you exceed the number of allowed requests in a given time window, you
    will get a response with status code 429. The response will also include a header called 'Retry-After' which will
    specify the number of seconds that you should wait for before making further requests.

    The rate limit for all endpoints is 2,500 requests per hour. It is important to honor the Retry-After header when
    encountering 429 responses as the limit is subject to change without notice.

    ## Date Values

    Many endpoints either return datetime values or can take datatime parameters. The values returned will always be in
    UTC, in the following format: `YYYY-MM-DDThh:mm:ss.ssssssZ`, where `ssssss` is the number of microseconds and
    `Z` denotes the UTC timezone.

    When passing datetime values as parameters, you should use this same format, e.g. `2016-10-13T11:54:32.525277Z`.

    ## URN Values

    We use URNs (Uniform Resource Names) to describe the different ways of communicating with a contact. These can be
    phone numbers, Twitter handles etc. For example a contact might have URNs like:

     * **tel:+250788123123**
     * **twitter:jack**
     * **mailto:jack@example.com**

    Phone numbers should always be given in full [E164 format](http://en.wikipedia.org/wiki/E.164).

    ## Translatable Values

    Some endpoints return or accept text fields that may be translated into different languages. These should be objects
    with ISO-639-3 language codes as keys, e.g. `{"eng": "Hello", "fra": "Bonjour"}`

    ## Authentication

    You must authenticate all calls by including an `Authorization` header with your API token. If you are logged in,
    your token will be visible at the top of this page. The Authorization header should look like:

        Authorization: Token YOUR_API_TOKEN

    For security reasons, all calls must be made using HTTPS.

    ## Clients

    There is an official [Python client library](https://github.com/rapidpro/rapidpro-python) which we recommend for all
    Python users of the API.
    """

    permission_classes = (SSLPermission, IsAuthenticated)

    def get(self, request, *args, **kwargs):
        return Response(
            {
                "archives": reverse("api.v2.archives", request=request),
                "boundaries": reverse("api.v2.boundaries", request=request),
                "broadcasts": reverse("api.v2.broadcasts", request=request),
                "whastapp_broadcasts": reverse("api.v2.whatsapp_broadcasts", request=request),
                "campaigns": reverse("api.v2.campaigns", request=request),
                "campaign_events": reverse("api.v2.campaign_events", request=request),
                "channels": reverse("api.v2.channels", request=request),
                "channel_events": reverse("api.v2.channel_events", request=request),
                "classifiers": reverse("api.v2.classifiers", request=request),
                "contacts": reverse("api.v2.contacts", request=request),
                "contacts_lean": reverse("api.v2.contacts_lean", request=request),
                "contact_actions": reverse("api.v2.contact_actions", request=request),
                "contact_templates": reverse("api.v2.contact_templates", request=request),
                "filter_templates": reverse("api.v2.filter_templates", request=request),
                "definitions": reverse("api.v2.definitions", request=request),
                "fields": reverse("api.v2.fields", request=request),
                "flow_starts": reverse("api.v2.flow_starts", request=request),
                "flows": reverse("api.v2.flows", request=request),
                "globals": reverse("api.v2.globals", request=request),
                "groups": reverse("api.v2.groups", request=request),
                "labels": reverse("api.v2.labels", request=request),
                "messages": reverse("api.v2.messages", request=request),
                "message_actions": reverse("api.v2.message_actions", request=request),
                "products": reverse("api.v2.products", request=request),
                "resthooks": reverse("api.v2.resthooks", request=request),
                "resthook_events": reverse("api.v2.resthook_events", request=request),
                "resthook_subscribers": reverse("api.v2.resthook_subscribers", request=request),
                "runs": reverse("api.v2.runs", request=request),
                "templates": reverse("api.v2.templates", request=request),
                "ticketers": reverse("api.v2.ticketers", request=request),
                "tickets": reverse("api.v2.tickets", request=request),
                "ticket_actions": reverse("api.v2.ticket_actions", request=request),
                "topics": reverse("api.v2.topics", request=request),
                "users": reverse("api.v2.users", request=request),
                "workspace": reverse("api.v2.workspace", request=request),
            }
        )


class ExplorerView(SmartTemplateView):
    """
    Explorer view which lets users experiment with endpoints against their own data
    """

    template_name = "api/v2/api_explorer.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["endpoints"] = [
            ArchivesEndpoint.get_read_explorer(),
            BoundariesEndpoint.get_read_explorer(),
            BroadcastsEndpoint.get_read_explorer(),
            BroadcastsEndpoint.get_write_explorer(),
            WhatsappBroadcastsEndpoint.get_read_explorer(),
            WhatsappBroadcastsEndpoint.get_write_explorer(),
            CampaignsEndpoint.get_read_explorer(),
            CampaignsEndpoint.get_write_explorer(),
            CampaignEventsEndpoint.get_read_explorer(),
            CampaignEventsEndpoint.get_write_explorer(),
            CampaignEventsEndpoint.get_delete_explorer(),
            ChannelsEndpoint.get_read_explorer(),
            ChannelEventsEndpoint.get_read_explorer(),
            ClassifiersEndpoint.get_read_explorer(),
            ContactsEndpoint.get_read_explorer(),
            ContactsEndpoint.get_write_explorer(),
            ContactsEndpoint.get_delete_explorer(),
            ContactsLeanEndpoint.get_read_explorer(),
            ContactActionsEndpoint.get_write_explorer(),
            ContactsTemplatesEndpoint.get_read_explorer(),
            ContactsElasticSearchEndpoint.get_read_explorer(),
            FilterTemplatesEndpoint.get_read_explorer(),
            DefinitionsEndpoint.get_read_explorer(),
            FieldsEndpoint.get_read_explorer(),
            FieldsEndpoint.get_write_explorer(),
            FlowsEndpoint.get_read_explorer(),
            FlowsLabelsEndpoint.get_read_explorer(),
            FlowStartsEndpoint.get_read_explorer(),
            FlowStartsEndpoint.get_write_explorer(),
            GlobalsEndpoint.get_read_explorer(),
            GlobalsEndpoint.get_write_explorer(),
            GroupsEndpoint.get_read_explorer(),
            GroupsEndpoint.get_write_explorer(),
            GroupsEndpoint.get_delete_explorer(),
            LabelsEndpoint.get_read_explorer(),
            LabelsEndpoint.get_write_explorer(),
            LabelsEndpoint.get_delete_explorer(),
            MessagesEndpoint.get_read_explorer(),
            MessageActionsEndpoint.get_write_explorer(),
            ProductsEndpoint.get_read_explorer(),
            ResthooksEndpoint.get_read_explorer(),
            ResthookEventsEndpoint.get_read_explorer(),
            ResthookSubscribersEndpoint.get_read_explorer(),
            ResthookSubscribersEndpoint.get_write_explorer(),
            ResthookSubscribersEndpoint.get_delete_explorer(),
            RunsEndpoint.get_read_explorer(),
            TemplatesEndpoint.get_read_explorer(),
            TicketersEndpoint.get_read_explorer(),
            TicketsEndpoint.get_read_explorer(),
            TicketActionsEndpoint.get_write_explorer(),
            TopicsEndpoint.get_read_explorer(),
            TopicsEndpoint.get_write_explorer(),
            UsersEndpoint.get_read_explorer(),
            WorkspaceEndpoint.get_read_explorer(),
            IntelligencesEndpoint.get_read_explorer(),
            ExternalServicesEndpoint.get_read_explorer(),
            BrainInfoEndpoint.get_read_explorer(),
            WhatsappFlowsEndpoint.get_read_explorer(),
            EventsEndpoint.get_read_explorer(),
        ]
        return context


class AuthenticateView(SmartFormView):
    """
    Provides a login form view for app users to generate and access their API tokens
    """

    class LoginForm(forms.Form):
        ROLE_CHOICES = (("A", _("Administrator")), ("E", _("Editor")), ("S", _("Surveyor")))

        username = forms.CharField()
        password = forms.CharField(widget=forms.PasswordInput)
        role = forms.ChoiceField(choices=ROLE_CHOICES)

    title = "API Authentication"
    form_class = LoginForm

    @csrf_exempt
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)

    def form_valid(self, form, *args, **kwargs):
        username = form.cleaned_data.get("username")
        password = form.cleaned_data.get("password")
        role_code = form.cleaned_data.get("role")

        user = authenticate(username=username, password=password)
        if user and user.is_active:
            login(self.request, user)

            role = APIToken.get_role_from_code(role_code)
            tokens = []

            if role:
                valid_orgs = APIToken.get_orgs_for_role(user, role)
                for org in valid_orgs:
                    token = APIToken.get_or_create(org, user, role)
                    serialized = {"uuid": str(org.uuid), "name": org.name, "id": org.id}  # for backward compatibility
                    tokens.append({"org": serialized, "token": token.key})
            else:  # pragma: needs cover
                return HttpResponse(status=404)

            return JsonResponse({"tokens": tokens})
        else:
            return HttpResponse(status=403)


# ============================================================
# Endpoints (A-Z)
# ============================================================


class ArchivesEndpoint(ListAPIMixin, BaseAPIView):
    """
    This endpoint allows you to list the data archives associated with your account.

    ## Listing Archives

    A `GET` returns the archives for your organization with the following fields.

      * **archive_type** - the type of the archive: *message*, *run* (string) (filterable as `archive_type`)
      * **start_date** - the UTC date of the archive (string) (filterable as `before` and `after`)
      * **period** - *daily* for daily archives, *monthly* for monthly archives (string) (filterable as `period`)
      * **record_count** - number of records in the archive (int)
      * **size** - size of the gziped archive content (int)
      * **hash** - MD5 hash of the gziped archive (string)
      * **download_url** - temporary download URL of the archive (string)

    Example:

        GET /api/v2/archives.json?archive_type=message&before=2017-05-15&period=daily

    Response is a list of the archives on your account

        {
            "next": null,
            "previous": null,
            "count": 248,
            "results": [
            {
                "archive_type":"message",
                "start_date":"2017-02-20",
                "period":"daily",
                "record_count":1432,
                "size":2304,
                "hash":"feca9988b7772c003204a28bd741d0d0",
                "download_url":"<redacted>"
            },
            ...
        }

    """

    permission = "archives.archive_api"
    model = Archive
    serializer_class = ArchiveReadSerializer

    def get_queryset(self):
        queryset = super().get_queryset()

        return queryset.order_by("-start_date").exclude(period=Archive.PERIOD_DAILY, rollup_id__isnull=False)

    def filter_queryset(self, queryset):
        # filter by `archive_type`
        archive_type = self.request.query_params.get("archive_type")
        if archive_type:
            queryset = queryset.filter(archive_type=archive_type)

        # filter by `period`
        period = self.request.query_params.get("period")

        if period == "daily":
            queryset = queryset.filter(period="D")
        elif period == "monthly":
            queryset = queryset.filter(period="M")

        # setup filter by before/after on start_date
        return self.filter_before_after(queryset, "start_date")

    @classmethod
    def get_read_explorer(cls):
        return {
            "method": "GET",
            "title": "List Archives",
            "url": reverse("api.v2.archives"),
            "slug": "archive-list",
            "params": [
                {
                    "name": "archive_type",
                    "required": False,
                    "help": "An archive_type to filter by, like: run, message",
                },
                {"name": "period", "required": False, "help": "A period to filter by: daily, monthly"},
            ],
        }


class BoundariesEndpoint(ListAPIMixin, BaseAPIView):
    """
    This endpoint allows you to list the administrative boundaries for the country associated with your account,
    along with the simplified GPS geometry for those boundaries in GEOJSON format.

    ## Listing Boundaries

    A `GET` returns the boundaries for your organization with the following fields. To include geometry,
    specify `geometry=true`.

      * **osm_id** - the OSM ID for this boundary prefixed with the element type (string)
      * **name** - the name of the administrative boundary (string)
      * **parent** - the id of the containing parent of this boundary or null if this boundary is a country (string)
      * **level** - the level: 0 for country, 1 for state, 2 for district (int)
      * **geometry** - the geometry for this boundary, which will usually be a MultiPolygon (GEOJSON)

    **Note that including geometry may produce a very large result so it is recommended to cache the results on the
    client side.**

    Example:

        GET /api/v2/boundaries.json?geometry=true

    Response is a list of the boundaries on your account

        {
            "next": null,
            "previous": null,
            "results": [
            {
                "osm_id": "1708283",
                "name": "Kigali City",
                "parent": {"osm_id": "171496", "name": "Rwanda"},
                "level": 1,
                "aliases": ["Kigari"],
                "geometry": {
                    "type": "MultiPolygon",
                    "coordinates": [
                        [
                            [
                                [7.5251021, 5.0504713],
                                [7.5330272, 5.0423498]
                            ]
                        ]
                    ]
                }
            },
            ...
        }

    """

    class Pagination(CursorPagination):
        ordering = ("osm_id",)

    permission = "locations.adminboundary_api"
    model = AdminBoundary
    serializer_class = AdminBoundaryReadSerializer
    pagination_class = Pagination

    def derive_queryset(self):
        org = self.request.user.get_org()
        if not org.country:
            return AdminBoundary.objects.none()

        queryset = org.country.get_descendants(include_self=True)

        queryset = queryset.prefetch_related(
            Prefetch("aliases", queryset=BoundaryAlias.objects.filter(org=org).order_by("name"))
        )

        return queryset.defer(None).select_related("parent")

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["include_geometry"] = str_to_bool(self.request.query_params.get("geometry", "false"))
        return context

    @classmethod
    def get_read_explorer(cls):
        return {
            "method": "GET",
            "title": "List Administrative Boundaries",
            "url": reverse("api.v2.boundaries"),
            "slug": "boundary-list",
            "params": [],
        }


class BroadcastsEndpoint(ListAPIMixin, WriteAPIMixin, BaseAPIView):
    """
    This endpoint allows you to send new message broadcasts and list existing broadcasts in your account.

    ## Listing Broadcasts

    A `GET` returns the outgoing message activity for your organization, listing the most recent messages first.

     * **id** - the id of the broadcast (int), filterable as `id`.
     * **urns** - the URNs that received the broadcast (array of strings)
     * **contacts** - the contacts that received the broadcast (array of objects)
     * **groups** - the groups that received the broadcast (array of objects)
     * **text** - the message text (string or translations object)
     * **status** - the status of the message (one of "queued", "sent", "failed").
     * **created_on** - when this broadcast was either created (datetime) (filterable as `before` and `after`).

    Example:

        GET /api/v2/broadcasts.json

    Response is a list of recent broadcasts:

        {
            "next": null,
            "previous": null,
            "results": [
                {
                    "id": 123456,
                    "urns": ["tel:+250788123123", "tel:+250788123124"],
                    "contacts": [{"uuid": "09d23a05-47fe-11e4-bfe9-b8f6b119e9ab", "name": "Joe"}]
                    "groups": [],
                    "text": "hello world",
                    "created_on": "2013-03-02T17:28:12.123456Z"
                },
                ...

    ## Sending Broadcasts

    A `POST` allows you to create and send new broadcasts, with the following JSON data:

      * **text** - the text of the message to send (string, limited to 640 characters)
      * **urns** - the URNs of contacts to send to (array of up to 100 strings, optional)
      * **contacts** - the UUIDs of contacts to send to (array of up to 100 strings, optional)
      * **groups** - the UUIDs of contact groups to send to (array of up to 100 strings, optional)

    Example:

        POST /api/v2/broadcasts.json
        {
            "urns": ["tel:+250788123123", "tel:+250788123124"],
            "contacts": ["09d23a05-47fe-11e4-bfe9-b8f6b119e9ab"],
            "text": "hello @contact.name"
        }

    You will receive a response containing the message broadcast created:

        {
            "id": 1234,
            "urns": ["tel:+250788123123", "tel:+250788123124"],
            "contacts": [{"uuid": "09d23a05-47fe-11e4-bfe9-b8f6b119e9ab", "name": "Joe"}]
            "groups": [],
            "text": "hello world",
            "created_on": "2013-03-02T17:28:12.123456Z"
        }
    """

    permission = "msgs.broadcast_api"
    model = Broadcast
    serializer_class = BroadcastReadSerializer
    write_serializer_class = BroadcastWriteSerializer
    pagination_class = CreatedOnCursorPagination
    throttle_scope = "v2.broadcasts"

    def filter_queryset(self, queryset):
        org = self.request.user.get_org()

        queryset = queryset.filter(broadcast_type=Broadcast.BROADCAST_TYPE_DEFAULT)

        # filter by id (optional)
        broadcast_id = self.get_int_param("id")
        if broadcast_id:
            queryset = queryset.filter(id=broadcast_id)

        queryset = queryset.prefetch_related(
            Prefetch("contacts", queryset=Contact.objects.only("uuid", "name").order_by("pk")),
            Prefetch("groups", queryset=ContactGroup.user_groups.only("uuid", "name").order_by("pk")),
        )

        if not org.is_anon:
            queryset = queryset.prefetch_related(
                Prefetch("urns", queryset=ContactURN.objects.only("scheme", "path", "display").order_by("pk"))
            )

        return self.filter_before_after(queryset, "created_on")

    @classmethod
    def get_read_explorer(cls):
        return {
            "method": "GET",
            "title": "List Broadcasts",
            "url": reverse("api.v2.broadcasts"),
            "slug": "broadcast-list",
            "params": [
                {"name": "id", "required": False, "help": "A broadcast ID to filter by, ex: 123456"},
                {
                    "name": "before",
                    "required": False,
                    "help": "Only return broadcasts created before this date, ex: 2015-01-28T18:00:00.000",
                },
                {
                    "name": "after",
                    "required": False,
                    "help": "Only return broadcasts created after this date, ex: 2015-01-28T18:00:00.000",
                },
            ],
        }

    @classmethod
    def get_write_explorer(cls):
        return {
            "method": "POST",
            "title": "Send Broadcasts",
            "url": reverse("api.v2.broadcasts"),
            "slug": "broadcast-write",
            "fields": [
                {"name": "text", "required": True, "help": "The text of the message you want to send"},
                {"name": "urns", "required": False, "help": "The URNs of contacts you want to send to"},
                {"name": "contacts", "required": False, "help": "The UUIDs of contacts you want to send to"},
                {"name": "groups", "required": False, "help": "The UUIDs of contact groups you want to send to"},
            ],
        }


class WhatsappBroadcastsEndpoint(ListAPIMixin, WriteAPIMixin, BaseAPIView):
    """
    This endpoint allows you to send new whatsapp message broadcasts and list existing broadcasts in your account.

    ## Listing Whatsapp Broadcasts

    A `GET` returns the outgoing message activity for your organization, listing the most recent messages first.

     * **id** - the id of the broadcast (int), filterable as `id`.
     * **urns** - the URNs that received the broadcast (array of strings)
     * **contacts** - the contacts that received the broadcast (array of objects)
     * **groups** - the groups that received the broadcast (array of objects)
     * **status** - the status of the message (one of "queued", "sent", "failed").
     * **created_on** - when this broadcast was either created (datetime) (filterable as `before` and `after`).
     * **metadata** - the message that was send to microservice

    Example:

        GET /api/v2/whatsapp_broadcasts.json

    Response is a list of recent broadcasts:

        {
            "next": null,
            "previous": null,
            "results": [
                {
                    "id": 123456,
                    "urns": ["tel:+250788123123", "tel:+250788123124"],
                    "contacts": [{"uuid": "09d23a05-47fe-11e4-bfe9-b8f6b119e9ab", "name": "Joe"}]
                    "groups": [],
                    "created_on": "2013-03-02T17:28:12.123456Z".
                    "metadata": {
                        "text": "Essa é uma mensagem de teste para @contact.name",
                        "header": {
                            "type": "text",
                            "text": "Oi @contact.name"
                        }
                    },
                },
                ...

    ## Sending Whatsapp Broadcasts

    A `POST` allows you to create and send new broadcasts, with the following JSON data:

      * **urns** - the URNs of contacts to send to (array of up to 100 strings, optional)
      * **contacts** - the UUIDs of contacts to send to (array of up to 100 strings, optional)
      * **groups** - the UUIDs of contact groups to send to (array of up to 100 strings, optional)
      * **msg** - the template, text and attachments that will be send to contacts


    Example:

    **Not all fields below are required, it depends on the type and format of message you want to send.**

        POST /api/v2/whatsapp_broadcasts.json
        {
            "urns": ["tel:+250788123123", "tel:+250788123124"],
            "contacts": ["09d23a05-47fe-11e4-bfe9-b8f6b119e9ab"],
            "msg": {
                "text": "This is a test message for @contact.name",
                "template":{
                    "uuid":"c3e129a2-5802-4248-a5f0-620566ef4345",
                    "variables": ["@contact.name"]
                }
                "attachments": ["image/png:https://example.com/image.png"]
                "header": {
                    "type": "text",
                    "text": "Hello @contact.name"
                },
                "footer": "Test message",
                "quick_replies": ["Yes", "No", "@contact.name"],
                "buttons": [
                    {
                        "sub_type": "url",
                        "parameters": [
                            {
                                "type": "text",
                                "text": "url button parameter text"
                            }
                        ]
                    }
                ],
                "interaction_type": "flow_msg | cta_url | location | order_details",
                "flow_message": {
                    "flow_id": "1234567890",
                    "flow_data": {
                        "foo": "bar"
                    },
                    "flow_screen": "WELCOME_SCREEN",
                    "flow_cta": "Click here",
                    "flow_mode": "draft | published"
                },
                "list_message": {
                    "button_text": "See more",
                    "list_items": [
                        {
                            "title": "Item 1",
                            "description": "Description 1",
                            "uuid": "1"
                        },
                        {
                            "title": "Item 2",
                            "description": "You can add up to 10 list items",
                            "uuid": "2"
                        },
                    ]
                },
                "cta_message": {
                    "url": "https://weni.ai",
                    "display_text": "Go to Weni"
                },
                "order_details": {
                    "reference_id": "unique-reference-id-123",
                    "payment_settings": {
                        "type": "digital-goods",
                        "payment_link": "https://weni.ai",
                        "pix_config": {
                            "key": "1234567890",
                            "key_type": "CPF",
                            "merchant_name": "John Doe",
                            "code": "00020126330014BR.GOV.BCB.PIX01111...."
                        }
                    },
                    "total_amount": 92188,
                    "order": {
                        "items": [
                            {
                                "retailer_id": "123#sellerid",
                                "name": "Product Item 1",
                                "amount": {
                                    "value": 64899,
                                    "offset": 100
                                },
                                "quantity": 1
                            },
                            {
                                "retailer_id": "456#sellerid",
                                "name": "Product Item 2",
                                "amount": {
                                    "value": 29990,
                                    "offset": 100
                                },
                                "quantity": 1,
                                "sale_amount": {
                                    "value": 25990,
                                    "offset": 100
                                }
                            }
                        ],
                        "subtotal": 90889,
                        "tax": {
                            "description": "Tax description",
                            "offset": 100,
                            "value": 999
                        },
                        "discount": {
                            "description": "Discount description",
                            "offset": 100,
                            "value": 200
                        },
                        "shipping": {
                            "description": "Shipping description",
                            "offset": 100,
                            "value": 500
                        }
                    }
                }
            }
        }

    You will receive a response containing the message broadcast created:

        {
            "id": 1234,
            "urns": ["tel:+250788123123", "tel:+250788123124"],
            "contacts": [{"uuid": "09d23a05-47fe-11e4-bfe9-b8f6b119e9ab", "name": "Joe"}]
            "groups": [],
            "created_on": "2013-03-02T17:28:12.123456Z",
            "metadata": {
                "text": "This is a test message for @contact.name",
                "template":{
                    "uuid":"c3e129a2-5802-4248-a5f0-620566ef4345",
                    "variables": ["@contact.name"]
                }
                "attachments": ["image/png:https://example.com/image.png"]
                "header": {
                    "type": "text",
                    "text": "Hello @contact.name"
                },
                "footer": "Test message",
                "quick_replies": ["Yes", "No", "@contact.name"],
                "buttons": [
                    {
                        "sub_type": "url",
                        "parameters": [
                            {
                                "type": "text",
                                "text": "url button parameter text"
                            }
                        ]
                    }
                ],
                "interaction_type": "flow_msg | cta_url | location | order_details",
                "flow_message": {
                    "flow_id": "1234567890",
                    "flow_data": {
                        "foo": "bar"
                    },
                    "flow_screen": "WELCOME_SCREEN",
                    "flow_cta": "Click here",
                    "flow_mode": "draft | published"
                },
                "list_message": {
                    "button_text": "See more",
                    "list_items": [
                        {
                            "title": "Item 1",
                            "description": "Description 1",
                            "uuid": "1"
                        },
                        {
                            "title": "Item 2",
                            "description": "You can add up to 10 list items",
                            "uuid": "2"
                        },
                    ]
                },
                "cta_message": {
                    "url": "https://weni.ai",
                    "display_text": "Go to Weni"
                },
                "order_details": {
                    "reference_id": "unique-reference-id-123",
                    "payment_settings": {
                        "type": "digital-goods",
                        "payment_link": "https://weni.ai",
                        "pix_config": {
                            "key": "1234567890",
                            "key_type": "CPF",
                            "merchant_name": "John Doe",
                            "code": "00020126330014BR.GOV.BCB.PIX01111...."
                        }
                    },
                    "total_amount": 92188,
                    "order": {
                        "items": [
                            {
                                "retailer_id": "123#sellerid",
                                "name": "Product Item 1",
                                "amount": {
                                    "value": 64899,
                                    "offset": 100
                                },
                                "quantity": 1
                            },
                            {
                                "retailer_id": "456#sellerid",
                                "name": "Product Item 2",
                                "amount": {
                                    "value": 29990,
                                    "offset": 100
                                },
                                "quantity": 1,
                                "sale_amount": {
                                    "value": 25990,
                                    "offset": 100
                                }
                            }
                        ],
                        "subtotal": 90889,
                        "tax": {
                            "description": "Tax description",
                            "offset": 100,
                            "value": 999
                        },
                        "discount": {
                            "description": "Discount description",
                            "offset": 100,
                            "value": 200
                        },
                        "shipping": {
                            "description": "Shipping description",
                            "offset": 100,
                            "value": 500
                        }
                    }
                }
            }
        }
    """

    permission = "msgs.broadcast_api"
    model = Broadcast
    serializer_class = WhatsappBroadcastReadSerializer
    write_serializer_class = WhatsappBroadcastWriteSerializer
    pagination_class = CreatedOnCursorPagination
    throttle_scope = "v2.broadcasts"

    def filter_queryset(self, queryset):
        org = self.request.user.get_org()

        queryset = queryset.filter(broadcast_type=Broadcast.BROADCAST_TYPE_WHATSAPP)

        # filter by id (optional)
        broadcast_id = self.get_int_param("id")
        if broadcast_id:
            queryset = queryset.filter(id=broadcast_id)

        queryset = queryset.prefetch_related(
            Prefetch("contacts", queryset=Contact.objects.only("uuid", "name").order_by("pk")),
            Prefetch("groups", queryset=ContactGroup.user_groups.only("uuid", "name").order_by("pk")),
        )

        if not org.is_anon:
            queryset = queryset.prefetch_related(
                Prefetch("urns", queryset=ContactURN.objects.only("scheme", "path", "display").order_by("pk"))
            )

        return self.filter_before_after(queryset, "created_on")

    @classmethod
    def get_read_explorer(cls):
        return {
            "method": "GET",
            "title": "List Broadcasts",
            "url": reverse("api.v2.whatsapp_broadcasts"),
            "slug": "whatsapp_broadcast-list",
            "params": [
                {
                    "name": "id",
                    "required": False,
                    "help": "A broadcast ID to filter by, ex: 123456",
                },
                {
                    "name": "before",
                    "required": False,
                    "help": "Only return broadcasts created before this date, ex: 2015-01-28T18:00:00.000",
                },
                {
                    "name": "after",
                    "required": False,
                    "help": "Only return broadcasts created after this date, ex: 2015-01-28T18:00:00.000",
                },
            ],
        }

    @classmethod
    def get_write_explorer(cls):
        return {
            "method": "POST",
            "title": "Send Broadcasts",
            "url": reverse("api.v2.whatsapp_broadcasts"),
            "slug": "whatsapp_broadcast-write",
            "fields": [
                {"name": "urns", "required": False, "help": "The URNs of contacts you want to send to"},
                {"name": "contacts", "required": False, "help": "The UUIDs of contacts you want to send to"},
                {"name": "groups", "required": False, "help": "The UUIDs of contact groups you want to send to"},
                {
                    "name": "msg",
                    "required": True,
                    "help": "The template, text and attachments that will be sent to contact",
                    "fields": [
                        {
                            "name": "template",
                            "required": False,
                            "help": "The template to be used",
                            "fields": [
                                {
                                    "name": "uuid",
                                    "required": True,
                                    "help": "The UUID of the template",
                                },
                                {
                                    "name": "variables",
                                    "required": False,
                                    "help": "The variables to be used in the template body",
                                },
                            ],
                        },
                        {
                            "name": "attachments",
                            "required": False,
                            "help": 'The attachments to be sent. Ex: ["image/png:https://example.com/image.png"]',
                        },
                    ],
                },
            ],
        }


class CampaignsEndpoint(ListAPIMixin, WriteAPIMixin, BaseAPIView):
    """
    This endpoint allows you to list campaigns in your account.

    ## Listing Campaigns

    A `GET` returns the campaigns, listing the most recently created campaigns first.

     * **uuid** - the UUID of the campaign (string), filterable as `uuid`.
     * **name** - the name of the campaign (string).
     * **archived** - whether this campaign is archived (boolean)
     * **group** - the group this campaign operates on (object).
     * **created_on** - when the campaign was created (datetime), filterable as `before` and `after`.

    Example:

        GET /api/v2/campaigns.json

    Response is a list of the campaigns on your account

        {
            "next": null,
            "previous": null,
            "results": [
            {
                "uuid": "f14e4ff0-724d-43fe-a953-1d16aefd1c00",
                "name": "Reminders",
                "archived": false,
                "group": {"uuid": "7ae473e8-f1b5-4998-bd9c-eb8e28c92fa9", "name": "Reporters"},
                "created_on": "2013-08-19T19:11:21.088Z"
            },
            ...
        }

    ## Adding Campaigns

    A **POST** can be used to create a new campaign, by sending the following data. Don't specify a UUID as this will be
    generated for you.

    * **name** - the name of the campaign (string, required)
    * **group** - the UUID of the contact group this campaign will be run against (string, required)

    Example:

        POST /api/v2/campaigns.json
        {
            "name": "Reminders",
            "group": "7ae473e8-f1b5-4998-bd9c-eb8e28c92fa9"
        }

    You will receive a campaign object as a response if successful:

        {
            "uuid": "f14e4ff0-724d-43fe-a953-1d16aefd1c00",
            "name": "Reminders",
            "archived": false,
            "group": {"uuid": "7ae473e8-f1b5-4998-bd9c-eb8e28c92fa9", "name": "Reporters"},
            "created_on": "2013-08-19T19:11:21.088Z"
        }

    ## Updating Campaigns

    A **POST** can also be used to update an existing campaign if you specify its UUID in the URL.

    Example:

        POST /api/v2/campaigns.json?uuid=f14e4ff0-724d-43fe-a953-1d16aefd1c00
        {
            "name": "Reminders II",
            "group": "7ae473e8-f1b5-4998-bd9c-eb8e28c92fa9"
        }

    """

    permission = "campaigns.campaign_api"
    model = Campaign
    serializer_class = CampaignReadSerializer
    write_serializer_class = CampaignWriteSerializer
    pagination_class = CreatedOnCursorPagination

    def get_queryset(self):
        queryset = super().get_queryset()

        return queryset.filter(is_active=True, is_archived=False)

    def filter_queryset(self, queryset):
        params = self.request.query_params

        # filter by UUID (optional)
        uuid = params.get("uuid")
        if uuid:
            queryset = queryset.filter(uuid=uuid)

        queryset = queryset.prefetch_related(Prefetch("group", queryset=ContactGroup.user_groups.only("uuid", "name")))

        return queryset

    @classmethod
    def get_read_explorer(cls):
        return {
            "method": "GET",
            "title": "List Campaigns",
            "url": reverse("api.v2.campaigns"),
            "slug": "campaign-list",
            "params": [{"name": "uuid", "required": False, "help": "A campaign UUID to filter by"}],
        }

    @classmethod
    def get_write_explorer(cls):
        return {
            "method": "POST",
            "title": "Add or Update Campaigns",
            "url": reverse("api.v2.campaigns"),
            "slug": "campaign-write",
            "params": [{"name": "uuid", "required": False, "help": "UUID of the campaign to be updated"}],
            "fields": [
                {"name": "name", "required": True, "help": "The name of the campaign"},
                {
                    "name": "group",
                    "required": True,
                    "help": "The UUID of the contact group operated on by the campaign",
                },
            ],
        }


class CampaignEventsEndpoint(ListAPIMixin, WriteAPIMixin, DeleteAPIMixin, BaseAPIView):
    """
    This endpoint allows you to list campaign events in your account.

    ## Listing Campaign Events

    A `GET` returns the campaign events, listing the most recently created events first.

     * **uuid** - the UUID of the campaign (string), filterable as `uuid`.
     * **campaign** - the UUID and name of the campaign (object), filterable as `campaign` with UUID.
     * **relative_to** - the key and label of the date field this event is based on (object).
     * **offset** - the offset from our contact field (positive or negative integer).
     * **unit** - the unit for our offset (one of "minutes, "hours", "days", "weeks").
     * **delivery_hour** - the hour of the day to deliver the message (integer 0-24, -1 indicates send at the same hour as the contact field).
     * **message** - the message to send to the contact if this is a message event (string or translations object)
     * **flow** - the UUID and name of the flow if this is a flow event (object).
     * **created_on** - when the event was created (datetime).

    Example:

        GET /api/v2/campaign_events.json

    Response is a list of the campaign events on your account

        {
            "next": null,
            "previous": null,
            "results": [
            {
                "uuid": "f14e4ff0-724d-43fe-a953-1d16aefd1c00",
                "campaign": {"uuid": "f14e4ff0-724d-43fe-a953-1d16aefd1c00", "name": "Reminders"},
                "relative_to": {"key": "registration", "label": "Registration Date"},
                "offset": 7,
                "unit": "days",
                "delivery_hour": 9,
                "flow": {"uuid": "09d23a05-47fe-11e4-bfe9-b8f6b119e9ab", "name": "Survey"},
                "message": null,
                "created_on": "2013-08-19T19:11:21.088Z"
            },
            ...
        }

    ## Adding Campaign Events

    A **POST** can be used to create a new campaign event, by sending the following data. Don't specify a UUID as this
    will be generated for you.

    * **campaign** - the UUID of the campaign this event should be part of (string, can't be changed for existing events)
    * **relative_to** - the field key that this event will be relative to (string)
    * **offset** - the offset from our contact field (positive or negative integer)
    * **unit** - the unit for our offset (one of "minutes", "hours", "days" or "weeks")
    * **delivery_hour** - the hour of the day to deliver the message (integer 0-24, -1 indicates send at the same hour as the field)
    * **message** - the message to send to the contact (string, required if flow is not specified)
    * **flow** - the UUID of the flow to start the contact down (string, required if message is not specified)

    Example:

        POST /api/v2/campaign_events.json
        {
            "campaign": "f14e4ff0-724d-43fe-a953-1d16aefd1c00",
            "relative_to": "last_hit",
            "offset": 160,
            "unit": "weeks",
            "delivery_hour": -1,
            "message": "Feeling sick and helpless, lost the compass where self is."
        }

    You will receive an event object as a response if successful:

        {
            "uuid": "6a6d7531-6b44-4c45-8c33-957ddd8dfabc",
            "campaign": {"uuid": "f14e4ff0-724d-43fe-a953-1d16aefd1c00", "name": "Hits"},
            "relative_to": "last_hit",
            "offset": 160,
            "unit": "W",
            "delivery_hour": -1,
            "message": {"eng": "Feeling sick and helpless, lost the compass where self is."},
            "flow": null,
            "created_on": "2013-08-19T19:11:21.088453Z"
        }

    ## Updating Campaign Events

    A **POST** can also be used to update an existing campaign event if you specify its UUID in the URL.

    Example:

        POST /api/v2/campaign_events.json?uuid=6a6d7531-6b44-4c45-8c33-957ddd8dfabc
        {
            "relative_to": "last_hit",
            "offset": 100,
            "unit": "weeks",
            "delivery_hour": -1,
            "message": "Feeling sick and helpless, lost the compass where self is."
        }

    ## Deleting Campaign Events

    A **DELETE** can be used to delete a campaign event if you specify its UUID in the URL.

    Example:

        DELETE /api/v2/campaign_events.json?uuid=6a6d7531-6b44-4c45-8c33-957ddd8dfabc

    You will receive either a 204 response if an event was deleted, or a 404 response if no matching event was found.

    """

    permission = "campaigns.campaignevent_api"
    model = CampaignEvent
    serializer_class = CampaignEventReadSerializer
    write_serializer_class = CampaignEventWriteSerializer
    pagination_class = CreatedOnCursorPagination

    def derive_queryset(self):
        return self.model.objects.filter(campaign__org=self.request.user.get_org(), is_active=True)

    def filter_queryset(self, queryset):
        params = self.request.query_params
        queryset = queryset.filter(is_active=True)
        org = self.request.user.get_org()

        # filter by UUID (optional)
        uuid = params.get("uuid")
        if uuid:
            queryset = queryset.filter(uuid=uuid)

        # filter by campaign name/uuid (optional)
        campaign_ref = params.get("campaign")
        if campaign_ref:
            campaign = Campaign.objects.filter(org=org).filter(Q(uuid=campaign_ref) | Q(name=campaign_ref)).first()
            if campaign:
                queryset = queryset.filter(campaign=campaign)
            else:
                queryset = queryset.filter(pk=-1)

        queryset = queryset.prefetch_related(
            Prefetch("campaign", queryset=Campaign.objects.only("uuid", "name")),
            Prefetch("flow", queryset=Flow.objects.only("uuid", "name")),
            Prefetch("relative_to", queryset=ContactField.all_fields.filter(is_active=True).only("key", "label")),
        )

        return queryset

    @classmethod
    def get_read_explorer(cls):
        return {
            "method": "GET",
            "title": "List Campaign Events",
            "url": reverse("api.v2.campaign_events"),
            "slug": "campaign-event-list",
            "params": [
                {"name": "uuid", "required": False, "help": "A campaign event UUID to filter by"},
                {"name": "campaign", "required": False, "help": "A campaign UUID or name to filter"},
            ],
        }

    @classmethod
    def get_write_explorer(cls):
        return {
            "method": "POST",
            "title": "Add or Update Campaign Events",
            "url": reverse("api.v2.campaign_events"),
            "slug": "campaign-event-write",
            "params": [{"name": "uuid", "required": False, "help": "The UUID of the campaign event to update"}],
            "fields": [
                {"name": "campaign", "required": False, "help": "The UUID of the campaign this event belongs to"},
                {
                    "name": "relative_to",
                    "required": True,
                    "help": "The key of the contact field this event is relative to. (string)",
                },
                {
                    "name": "offset",
                    "required": True,
                    "help": "The offset from the relative_to field value (integer, positive or negative)",
                },
                {
                    "name": "unit",
                    "required": True,
                    "help": 'The unit of the offset (one of "minutes, "hours", "days", "weeks")',
                },
                {
                    "name": "delivery_hour",
                    "required": True,
                    "help": "The hour this event should be triggered, or -1 if the event should be sent at the same hour as our date (integer, -1 or 0-23)",
                },
                {
                    "name": "message",
                    "required": False,
                    "help": "The message that should be sent to the contact when this event is triggered (string)",
                },
                {
                    "name": "flow",
                    "required": False,
                    "help": "The UUID of the flow that the contact should start when this event is triggered (string)",
                },
            ],
        }

    @classmethod
    def get_delete_explorer(cls):
        return {
            "method": "DELETE",
            "title": "Delete Campaign Events",
            "url": reverse("api.v2.campaign_events"),
            "slug": "campaign-event-delete",
            "request": "",
            "params": [{"name": "uuid", "required": False, "help": "The UUID of the campaign event to delete"}],
        }


class ChannelsEndpoint(ListAPIMixin, BaseAPIView):
    """
    This endpoint allows you to list channels in your account.

    ## Listing Channels

    A **GET** returns the list of channels for your organization, in the order of last created.  Note that for
    Android devices, all status information is as of the last time it was seen and can be null before the first sync.

     * **uuid** - the UUID of the channel (string), filterable as `uuid`.
     * **name** - the name of the channel (string).
     * **address** - the address (e.g. phone number, Twitter handle) of the channel (string), filterable as `address`.
     * **country** - which country the sim card for this channel is registered for (string, two letter country code).
     * **device** - information about the device if this is an Android channel:
        * **name** - the name of the device (string).
        * **power_level** - the power level of the device (int).
        * **power_status** - the power status, either ```CHA``` (charging) or ```DIS``` (discharging) (string).
        * **power_source** - the source of power as reported by Android (string).
        * **network_type** - the type of network the device is connected to as reported by Android (string).
     * **last_seen** - the datetime when this channel was last seen (datetime).
     * **created_on** - the datetime when this channel was created (datetime).

    Example:

        GET /api/v2/channels.json

    Response containing the channels for your organization:

        {
            "next": null,
            "previous": null,
            "results": [
            {
                "uuid": "09d23a05-47fe-11e4-bfe9-b8f6b119e9ab",
                "name": "Android Phone",
                "address": "+250788123123",
                "country": "RW",
                "device": {
                    "name": "Nexus 5X",
                    "power_level": 99,
                    "power_status": "STATUS_DISCHARGING",
                    "power_source": "BATTERY",
                    "network_type": "WIFI",
                },
                "last_seen": "2016-03-01T05:31:27.456",
                "created_on": "2014-06-23T09:34:12.866",
            }]
        }

    """

    permission = "channels.channel_api"
    model = Channel
    serializer_class = ChannelReadSerializer
    pagination_class = CreatedOnCursorPagination

    def filter_queryset(self, queryset):
        params = self.request.query_params
        queryset = queryset.filter(is_active=True)

        # filter by UUID (optional)
        uuid = params.get("uuid")
        if uuid:
            queryset = queryset.filter(uuid=uuid)

        # filter by address (optional)
        address = params.get("address")
        if address:
            queryset = queryset.filter(address=address)

        return queryset

    @classmethod
    def get_read_explorer(cls):
        return {
            "method": "GET",
            "title": "List Channels",
            "url": reverse("api.v2.channels"),
            "slug": "channel-list",
            "params": [
                {
                    "name": "uuid",
                    "required": False,
                    "help": "A channel UUID to filter by. ex: 09d23a05-47fe-11e4-bfe9-b8f6b119e9ab",
                },
                {"name": "address", "required": False, "help": "A channel address to filter by. ex: +250783530001"},
            ],
        }


class ChannelEventsEndpoint(ListAPIMixin, BaseAPIView):
    """
    This endpoint allows you to list channel events in your account.

    ## Listing Channel Events

    A **GET** returns the channel events for your organization, most recent first.

     * **id** - the ID of the event (int), filterable as `id`.
     * **channel** - the UUID and name of the channel that handled this call (object).
     * **type** - the type of event (one of "call-in", "call-in-missed", "call-out", "call-out-missed").
     * **contact** - the UUID and name of the contact (object), filterable as `contact` with UUID.
     * **extra** - any extra attributes collected for this event
     * **occurred_on** - when this event happened on the channel (datetime).
     * **created_on** - when this event was created (datetime), filterable as `before` and `after`.

    Example:

        GET /api/v2/channel_events.json

    Response:

        {
            "next": null,
            "previous": null,
            "results": [
            {
                "id": 4,
                "channel": {"uuid": "9a8b001e-a913-486c-80f4-1356e23f582e", "name": "Vonage"},
                "type": "call-in"
                "contact": {"uuid": "d33e9ad5-5c35-414c-abd4-e7451c69ff1d", "name": "Bob McFlow"},
                "extra": { "duration": 606 },
                "occurred_on": "2013-02-27T09:06:12.123"
                "created_on": "2013-02-27T09:06:15.456"
            },
            ...

    """

    permission = "channels.channelevent_api"
    model = ChannelEvent
    serializer_class = ChannelEventReadSerializer
    pagination_class = CreatedOnCursorPagination

    def filter_queryset(self, queryset):
        params = self.request.query_params
        org = self.request.user.get_org()

        # filter by id (optional)
        call_id = self.get_int_param("id")
        if call_id:
            queryset = queryset.filter(id=call_id)

        # filter by contact (optional)
        contact_uuid = params.get("contact")
        if contact_uuid:
            contact = Contact.objects.filter(org=org, is_active=True, uuid=contact_uuid).first()
            if contact:
                queryset = queryset.filter(contact=contact)
            else:
                queryset = queryset.filter(pk=-1)

        queryset = queryset.prefetch_related(
            Prefetch("contact", queryset=Contact.objects.only("uuid", "name")),
            Prefetch("channel", queryset=Channel.objects.only("uuid", "name")),
        )

        return self.filter_before_after(queryset, "created_on")

    @classmethod
    def get_read_explorer(cls):
        return {
            "method": "GET",
            "title": "List Channel Events",
            "url": reverse("api.v2.channel_events"),
            "slug": "channel-event-list",
            "params": [
                {"name": "id", "required": False, "help": "An event ID to filter by. ex: 12345"},
                {
                    "name": "contact",
                    "required": False,
                    "help": "A contact UUID to filter by. ex: 09d23a05-47fe-11e4-bfe9-b8f6b119e9ab",
                },
                {
                    "name": "before",
                    "required": False,
                    "help": "Only return events created before this date, ex: 2015-01-28T18:00:00.000",
                },
                {
                    "name": "after",
                    "required": False,
                    "help": "Only return events created after this date, ex: 2015-01-28T18:00:00.000",
                },
            ],
        }


class ToggleChannelsEndpoint(ListAPIMixin, WriteAPIMixin, BaseAPIView):
    """
    This endpoint allows you to enable/disable channels in your account.

    ## Toggle Channels

    A **POST** will recieve a channel uuid and a action parameter to enable or disable the channel.

    Example:

        POST /api/v2/toggle_channels.json

        body: action=enable

    Response containing the channels for your organization:

        {
            "next": null,
            "previous": null,
            "results": [
            {
                "uuid": "09d23a05-47fe-11e4-bfe9-b8f6b119e9ab",
                "name": "Android Phone",
                "address": "+250788123123",
                "country": "RW",
                "device": {
                    "name": "Nexus 5X",
                    "power_level": 99,
                    "power_status": "STATUS_DISCHARGING",
                    "power_source": "BATTERY",
                    "network_type": "WIFI",
                },
                "last_seen": "2016-03-01T05:31:27.456",
                "created_on": "2014-06-23T09:34:12.866",
                "is_active": true
            }]
        }

    To disable a channel, the action parameter should be set to disable.

    Example:

        POST /api/v2/toggle_channels.json

        body: action=disable

    """

    permission = "channels.channel_api"
    model = Channel
    serializer_class = ChannelReadSerializer
    write_serializer_class = ToggleChannelWriteSerializer
    pagination_class = CreatedOnCursorPagination

    def filter_queryset(self, queryset):
        params = self.request.query_params
        queryset = queryset.filter(is_active=True)

        # filter by UUID (optional)
        uuid = params.get("uuid")
        if uuid:
            queryset = queryset.filter(uuid=uuid)

        # filter by address (optional)
        address = params.get("address")
        if address:
            queryset = queryset.filter(address=address)

        return queryset

    @classmethod
    def get_write_explorer(cls):  # pragma: no cover
        return {
            "method": "POST",
            "title": "Update is_active channels",
            "url": reverse("api.v2.toggle_channels"),
            "slug": "channels-toggle",
            "fields": [
                {"name": "uuid", "required": True, "help": "The UUIDs of the contacts to update"},
                {"action": "enable/disable", "required": True, "help": "The action to be performed on the channel"},
            ],
        }


class ClassifiersEndpoint(ListAPIMixin, BaseAPIView):
    """
    This endpoint allows you to list the active natural language understanding classifiers on your account.

    ## Listing Classifiers

    A **GET** returns the classifiers for your organization, most recent first.

     * **uuid** - the UUID of the classifier, filterable as `uuid`.
     * **name** - the name of the classifier
     * **intents** - the list of intents this classifier exposes (list of strings)
     * **type** - the type of the classifier, one of 'wit' or 'luis'
     * **created_on** - when this classifier was created

    Example:

        GET /api/v2/classifiers.json

    Response:

        {
            "next": null,
            "previous": null,
            "results": [
            {
                "uuid": "9a8b001e-a913-486c-80f4-1356e23f582e",
                "name": "Temba Classifier",
                "intents": ["book_flight", "book_car"],
                "type": "wit",
                "created_on": "2013-02-27T09:06:15.456"
            },
            ...

    """

    permission = "classifiers.classifier_api"
    model = Classifier
    serializer_class = ClassifierReadSerializer
    pagination_class = CreatedOnCursorPagination

    def filter_queryset(self, queryset):
        params = self.request.query_params
        org = self.request.user.get_org()

        queryset = queryset.filter(org=org, is_active=True)

        # filter by uuid (optional)
        uuid = params.get("uuid")
        if uuid:
            queryset = queryset.filter(uuid=uuid)

        return self.filter_before_after(queryset, "created_on")

    @classmethod
    def get_read_explorer(cls):
        return {
            "method": "GET",
            "title": "List Classifiers",
            "url": reverse("api.v2.classifiers"),
            "slug": "classifier-list",
            "params": [
                {
                    "name": "uuid",
                    "required": False,
                    "help": "A classifier UUID to filter by. ex: 09d23a05-47fe-11e4-bfe9-b8f6b119e9ab",
                },
                {
                    "name": "before",
                    "required": False,
                    "help": "Only return classifiers created before this date, ex: 2015-01-28T18:00:00.000",
                },
                {
                    "name": "after",
                    "required": False,
                    "help": "Only return classifiers created after this date, ex: 2015-01-28T18:00:00.000",
                },
            ],
        }


class ContactsEndpoint(ListAPIMixin, WriteAPIMixin, DeleteAPIMixin, BaseAPIView):
    """
    This endpoint allows you to list, create, update and delete contacts in your account.

    ## Listing Contacts

    A **GET** returns the list of contacts for your organization, in the order of last activity date. You can return
    only deleted contacts by passing the "deleted=true" parameter to your call.

     * **uuid** - the UUID of the contact (string), filterable as `uuid`.
     * **name** - the name of the contact (string), filterable as `name`.
     * **language** - the preferred language of the contact (string).
     * **urns** - the URNs associated with the contact (string array), filterable as `urn`.
     * **groups** - the UUIDs of any groups the contact is part of (array of objects), filterable as `group` with group name or UUID.
     * **fields** - any contact fields on this contact (dictionary).
     * **blocked** - whether the contact is blocked (boolean).
     * **stopped** - whether the contact is stopped, i.e. has opted out (boolean).
     * **created_on** - when this contact was created (datetime).
     * **modified_on** - when this contact was last modified (datetime), filterable as `before` and `after`.
     * **last_seen_on** - when this contact last communicated with us (datetime).

    Example:

        GET /api/v2/contacts.json

    Response containing the contacts for your organization:

        {
            "next": null,
            "previous": null,
            "results": [
            {
                "uuid": "09d23a05-47fe-11e4-bfe9-b8f6b119e9ab",
                "name": "Ben Haggerty",
                "language": null,
                "urns": ["tel:+250788123123"],
                "groups": [{"name": "Customers", "uuid": "5a4eb79e-1b1f-4ae3-8700-09384cca385f"}],
                "fields": {
                  "nickname": "Macklemore",
                  "side_kick": "Ryan Lewis"
                }
                "blocked": false,
                "stopped": false,
                "created_on": "2015-11-11T13:05:57.457742Z",
                "modified_on": "2020-08-11T13:05:57.576056Z",
                "last_seen_on": "2020-07-11T13:05:57.576056Z"
            }]
        }

    ## Adding Contacts

    You can add a new contact to your account by sending a **POST** request to this URL with the following JSON data:

    * **name** - the full name of the contact (string, optional)
    * **language** - the preferred language for the contact (3 letter iso code, optional)
    * **urns** - a list of URNs you want associated with the contact (array of up to 100 strings, optional)
    * **groups** - a list of the UUIDs of any groups this contact is part of (array of up to 100 strings, optional)
    * **fields** - the contact fields you want to set or update on this contact (dictionary of up to 100 items, optional)

    Example:

        POST /api/v2/contacts.json
        {
            "name": "Ben Haggerty",
            "language": "eng",
            "urns": ["tel:+250788123123", "twitter:ben"],
            "groups": ["6685e933-26e1-4363-a468-8f7268ab63a9"],
            "fields": {
              "nickname": "Macklemore",
              "side_kick": "Ryan Lewis"
            }
        }

    You will receive a contact object as a response if successful:

        {
            "uuid": "09d23a05-47fe-11e4-bfe9-b8f6b119e9ab",
            "name": "Ben Haggerty",
            "language": "eng",
            "urns": ["tel:+250788123123", "twitter:ben"],
            "groups": [{"name": "Devs", "uuid": "6685e933-26e1-4363-a468-8f7268ab63a9"}],
            "fields": {
              "nickname": "Macklemore",
              "side_kick": "Ryan Lewis"
            }
            "blocked": false,
            "stopped": false,
            "created_on": "2015-11-11T13:05:57.457742Z",
            "modified_on": "2015-11-11T13:05:57.576056Z",
            "last_seen_on": null
        }

    ## Updating Contacts

    A **POST** can also be used to update an existing contact if you specify either its UUID or one of its URNs in the
    URL. Only those fields included in the body will be changed on the contact.

    If providing a URN in the URL then don't include URNs in the body. Also note that we will create a new contact if
    there is no contact with that URN. You will receive a 201 response if this occurs.

    Examples:

        POST /api/v2/contacts.json?uuid=09d23a05-47fe-11e4-bfe9-b8f6b119e9ab
        {
            "name": "Ben Haggerty",
            "language": "eng",
            "urns": ["tel:+250788123123", "twitter:ben"],
            "groups": [{"name": "Devs", "uuid": "6685e933-26e1-4363-a468-8f7268ab63a9"}],
            "fields": {}
        }

        POST /api/v2/contacts.json?urn=tel%3A%2B250783835665
        {
            "fields": {"nickname": "Ben"}
        }

    ## Deleting Contacts

    A **DELETE** can also be used to delete an existing contact if you specify either its UUID or one of its URNs in the
    URL.

    Examples:

        DELETE /api/v2/contacts.json?uuid=27fb583b-3087-4778-a2b3-8af489bf4a93

        DELETE /api/v2/contacts.json?urn=tel%3A%2B250783835665

    You will receive either a 204 response if a contact was deleted, or a 404 response if no matching contact was found.
    """

    permission = "contacts.contact_api"
    model = Contact
    serializer_class = ContactReadSerializer
    write_serializer_class = ContactWriteSerializer
    write_with_transaction = False
    pagination_class = ContactsCursorPagination
    throttle_scope = "v2.contacts"
    lookup_params = {"uuid": "uuid", "urn": "urns__identity", "name": "name"}

    def filter_queryset(self, queryset):
        params = self.request.query_params
        org = self.request.user.get_org()

        deleted_only = str_to_bool(params.get("deleted"))
        queryset = queryset.filter(is_active=(not deleted_only))

        # filter by UUID (optional)
        uuid = params.get("uuid")
        if uuid:
            queryset = queryset.filter(uuid=uuid)

        # filter by URN (optional)
        urn = params.get("urn")
        if urn:
            queryset = queryset.filter(urns__identity=self.normalize_urn(urn))

        # filter by search (optional)
        search = params.get("search")
        if search:
            try:
                urn_search = Q(urns__identity=self.normalize_urn(search))
            except InvalidQueryError:
                urn_search = Q()
            queryset = queryset.filter(urn_search | Q(name=search))

        # filter by contact name (optional)
        name = params.get("name")
        if name:
            queryset = queryset.filter(name__icontains=name)

        # filter by group name/uuid (optional)
        group_ref = params.get("group")
        if group_ref:
            group = ContactGroup.user_groups.filter(org=org).filter(Q(uuid=group_ref) | Q(name=group_ref)).first()
            if group:
                queryset = queryset.filter(all_groups=group)
            else:
                queryset = queryset.filter(pk=-1)

        # use prefetch rather than select_related for foreign keys to avoid joins
        queryset = queryset.prefetch_related(
            Prefetch("org"),
            Prefetch(
                "all_groups",
                queryset=ContactGroup.user_groups.only("uuid", "name").order_by("pk"),
                to_attr="prefetched_user_groups",
            ),
        )

        return self.filter_before_after(queryset, "modified_on")

    def prepare_for_serialization(self, object_list, using: str):
        Contact.bulk_urn_cache_initialize(object_list, using=using)

    def get_serializer_context(self):
        """
        So that we only fetch active contact fields once for all contacts
        """
        context = super().get_serializer_context()
        context["contact_fields"] = ContactField.user_fields.active_for_org(org=self.request.user.get_org())
        return context

    def get_object(self):
        queryset = self.get_queryset().filter(**self.lookup_values)

        # don't blow up if posted a URN that doesn't exist - we'll let the serializer create a new contact
        if self.request.method == "POST" and "urns__identity" in self.lookup_values:
            org = self.request.user.get_org()
            urn = self.lookup_values.get("urns__identity")

            contact = queryset.first()

            if not contact and org.config.get("verify_ninth_digit", False):
                scheme, path, _, _ = URN.to_parts(urn)
                if scheme == "whatsapp" and path.startswith("55"):
                    if len(path) == 13 and path[4] == "9":
                        # Generate without digit 9
                        number = path[:4] + path[5:]
                        self.lookup_values["urns__identity"] = scheme + ":" + number
                        contact = self.get_queryset().filter(**self.lookup_values).first()

                    else:
                        # Generate with digit 9
                        number = path[:4] + "9" + path[4:]

                        self.lookup_values["urns__identity"] = scheme + ":" + number
                        contact = self.get_queryset().filter(**self.lookup_values).first()

            return contact
        else:
            return generics.get_object_or_404(queryset)

    @classmethod
    def get_read_explorer(cls):
        return {
            "method": "GET",
            "title": "List Contacts",
            "url": reverse("api.v2.contacts"),
            "slug": "contact-list",
            "params": [
                {
                    "name": "uuid",
                    "required": False,
                    "help": "A contact UUID to filter by. ex: 09d23a05-47fe-11e4-bfe9-b8f6b119e9ab",
                },
                {"name": "urn", "required": False, "help": "A contact URN to filter by. ex: tel:+250788123123"},
                {
                    "name": "search",
                    "required": False,
                    "help": "A contact URN to filter by. ex: tel:+250788123123 or by a contact name",
                },
                {"name": "group", "required": False, "help": "A group name or UUID to filter by. ex: Customers"},
                {"name": "deleted", "required": False, "help": "Whether to return only deleted contacts. ex: false"},
                {
                    "name": "before",
                    "required": False,
                    "help": "Only return contacts modified before this date, ex: 2015-01-28T18:00:00.000",
                },
                {
                    "name": "after",
                    "required": False,
                    "help": "Only return contacts modified after this date, ex: 2015-01-28T18:00:00.000",
                },
                {
                    "name": "order_by",
                    "required": False,
                    "help": "Expect a date field (created_on or modified_on) to filter, ex: order_by=created_on",
                },
                {
                    "name": "limit",
                    "required": False,
                    "help": "Return objects numbers according to limit, ex: limit=50",
                },
            ],
            "example": {"query": "urn=tel%3A%2B250788123123"},
        }

    @classmethod
    def get_write_explorer(cls):
        return {
            "method": "POST",
            "title": "Add or Update Contacts",
            "url": reverse("api.v2.contacts"),
            "slug": "contact-write",
            "params": [
                {"name": "uuid", "required": False, "help": "UUID of the contact to be updated"},
                {"name": "urn", "required": False, "help": "URN of the contact to be updated. ex: tel:+250788123123"},
            ],
            "fields": [
                {"name": "name", "required": False, "help": "List of UUIDs of this contact's groups."},
                {
                    "name": "language",
                    "required": False,
                    "help": "Preferred language of the contact (3-letter ISO code). ex: fre, eng",
                },
                {"name": "urns", "required": False, "help": "List of URNs belonging to the contact."},
                {"name": "groups", "required": False, "help": "List of UUIDs of groups that the contact belongs to."},
                {"name": "fields", "required": False, "help": "Custom fields as a JSON dictionary."},
            ],
            "example": {"body": '{"name": "Ben Haggerty", "groups": [], "urns": ["tel:+250788123123"]}'},
        }

    @classmethod
    def get_delete_explorer(cls):
        return {
            "method": "DELETE",
            "title": "Delete Contacts",
            "url": reverse("api.v2.contacts"),
            "slug": "contact-delete",
            "params": [
                {"name": "uuid", "required": False, "help": "UUID of the contact to be deleted"},
                {"name": "urn", "required": False, "help": "URN of the contact to be deleted. ex: tel:+250788123123"},
            ],
        }


class ContactsLeanEndpoint(ListAPIMixin, BaseAPIView):
    """
    This endpoint allows you to list contacts in your account, with basics informations.

    ## Listing Contacts

    A **GET** returns the list of contacts for your organization, in the order of last activity date. You can return
    only deleted contacts by passing the "deleted=true" parameter to your call.

     * **uuid** - the UUID of the contact (string), filterable as `uuid`.
     * **name** - the name of the contact (string), filterable as `name`.
     * **language** - the preferred language of the contact (string).
     * **blocked** - whether the contact is blocked (boolean).
     * **stopped** - whether the contact is stopped, i.e. has opted out (boolean).
     * **created_on** - when this contact was created (datetime).
     * **modified_on** - when this contact was last modified (datetime), filterable as `before` and `after`.
     * **last_seen_on** - when this contact last communicated with us (datetime).

    Example:

        GET /api/v2/contacts_lean.json

    Response containing the contacts for your organization:

        {
            "next": null,
            "previous": null,
            "results": [
            {
                "uuid": "09d23a05-47fe-11e4-bfe9-b8f6b119e9ab",
                "name": "Ben Haggerty",
                "language": null,
                "blocked": false,
                "stopped": false,
                "created_on": "2015-11-11T13:05:57.457742Z",
                "modified_on": "2020-08-11T13:05:57.576056Z",
                "last_seen_on": "2020-07-11T13:05:57.576056Z"
            }]
        }
    """

    permission = "contacts.contact_api"
    model = Contact
    serializer_class = ContactLeanReadSerializer
    pagination_class = ContactsCursorPagination
    throttle_scope = "v2.contacts"
    lookup_params = {"uuid": "uuid", "name": "name"}

    def filter_queryset(self, queryset):
        params = self.request.query_params
        org = self.request.user.get_org()

        deleted_only = str_to_bool(params.get("deleted"))
        queryset = queryset.filter(is_active=(not deleted_only))

        # filter by UUID (optional)
        uuid = params.get("uuid")
        if uuid:
            queryset = queryset.filter(uuid=uuid)

        # filter by search (optional)
        search = params.get("search")
        if search:
            try:
                urn_search = Q(urns__identity=self.normalize_urn(search))
            except InvalidQueryError:
                urn_search = Q()
            queryset = queryset.filter(urn_search | Q(name=search))

        # filter by contact name (optional)
        name = params.get("name")
        if name:
            queryset = queryset.filter(name__icontains=name)

        # filter by group name/uuid (optional)
        group_ref = params.get("group")
        if group_ref:
            group = ContactGroup.user_groups.filter(org=org).filter(Q(uuid=group_ref) | Q(name=group_ref)).first()
            if group:
                queryset = queryset.filter(all_groups=group)
            else:
                queryset = queryset.filter(pk=-1)

        # use prefetch rather than select_related for foreign keys to avoid joins
        queryset = queryset.prefetch_related(
            Prefetch("org"),
            Prefetch(
                "all_groups",
                queryset=ContactGroup.user_groups.only("uuid", "name").order_by("pk"),
                to_attr="prefetched_user_groups",
            ),
        )

        return self.filter_before_after(queryset, "modified_on")

    @classmethod
    def get_read_explorer(cls):
        return {
            "method": "GET",
            "title": "List Contacts(lean)",
            "url": reverse("api.v2.contacts_lean"),
            "slug": "contact-lean",
            "params": [
                {
                    "name": "uuid",
                    "required": False,
                    "help": "A contact UUID to filter by. ex: 09d23a05-47fe-11e4-bfe9-b8f6b119e9ab",
                },
                {
                    "name": "search",
                    "required": False,
                    "help": "A contact URN to filter by. ex: tel:+250788123123 or by a contact name",
                },
                {"name": "group", "required": False, "help": "A group name or UUID to filter by. ex: Customers"},
                {"name": "deleted", "required": False, "help": "Whether to return only deleted contacts. ex: false"},
                {
                    "name": "before",
                    "required": False,
                    "help": "Only return contacts modified before this date, ex: 2015-01-28T18:00:00.000",
                },
                {
                    "name": "after",
                    "required": False,
                    "help": "Only return contacts modified after this date, ex: 2015-01-28T18:00:00.000",
                },
                {
                    "name": "order_by",
                    "required": False,
                    "help": "Expect a date field (created_on or modified_on) to filter, ex: order_by=created_on",
                },
                {
                    "name": "limit",
                    "required": False,
                    "help": "Return objects numbers according to limit, ex: limit=50",
                },
            ],
        }


class ContactActionsEndpoint(BulkWriteAPIMixin, BaseAPIView):
    """
    ## Bulk Contact Updating

    A **POST** can be used to perform an action on a set of contacts in bulk.

    * **contacts** - the contact UUIDs or URNs (array of up to 100 strings)
    * **action** - the action to perform, a string one of:

        * _add_ - Add the contacts to the given group
        * _remove_ - Remove the contacts from the given group
        * _block_ - Block the contacts
        * _unblock_ - Un-block the contacts
        * _interrupt_ - Interrupt and end any of the contacts' active flow runs
        * _archive_messages_ - Archive all of the contacts' messages
        * _delete_ - Permanently delete the contacts

    * **group** - the UUID or name of a contact group (string, optional)

    Example:

        POST /api/v2/contact_actions.json
        {
            "contacts": ["7acfa6d5-be4a-4bcc-8011-d1bd9dfasff3", "tel:+250783835665"],
            "action": "add",
            "group": "Testers"
        }

    You will receive an empty response with status code 204 if successful.
    """

    permission = "contacts.contact_api"
    serializer_class = ContactBulkActionSerializer

    @classmethod
    def get_write_explorer(cls):
        actions = cls.serializer_class.ACTIONS

        return {
            "method": "POST",
            "title": "Update Multiple Contacts",
            "url": reverse("api.v2.contact_actions"),
            "slug": "contact-actions",
            "fields": [
                {"name": "contacts", "required": True, "help": "The UUIDs of the contacts to update"},
                {"name": "action", "required": True, "help": "One of the following strings: " + ", ".join(actions)},
                {"name": "group", "required": False, "help": "The UUID or name of a contact group"},
            ],
        }


class ContactsTemplatesEndpoint(ListAPIMixin, BaseAPIView):
    """
    This endpoint allows you to list contacts with templates in your account.

    ## Listing Contacts

    A **GET** returns the list of contacts whti templates for your organization, in the order of last activity date. The endpoin
    will return only with the contact that has template called in Msg.

     * **uuid** - the UUID of the contact (string), filterable as `uuid`.
     * **name** - the name of the contact (string), filterable as `name`.
     * **urns** - the URNs associated with the contact (string array), filterable as `urn`.
     * **groups** - the UUIDs of any groups the contact is part of (array of objects), filterable as `group` with group name or UUID.
     * **templates** - the templates the contact messages receive
     * **created_on** - when this contact was created (datetime).
     * **modified_on** - when this contact was last modified (datetime).
     * **last_seen_on** - when this contact last communicated with us (datetime).



    Example:

        GET /api/v2/contact_templates.json

    Response containing the contacts for your organization:

        {
            "next": null,
            "previous": null,
            "results": [
            {
            "uuid": "0fcbfa94-abbe-436a-867a-d8b3e6da6b83",
            "id": 123546,
            "name": "Jimmy",
            "urns": [
                "whatsapp:5555555555"
            ],
            "templates": [
                {
                    "uuid": "44019537-9afe-4898-9626-a5c724d169ef",
                    "name": "template_test",
                    "text": "Hello teste! I'm Doris, Weni's virtual assistant.",
                    "created_on": "2023-11-01T18:35:52.690932Z",
                    "sent_on": "2023-11-01T18:36:02.590312Z",
                    "direction": "Incoming",
                    "status": "wired"
                }
            ],
            "created_on": "2023-02-24T14:23:11.058607Z",
            "modified_on": "2024-02-08T14:05:51.711344Z",
            "last_seen_on": "2023-12-08T14:10:48.490004Z"
        }
                ]
        }

    """

    permission = "contacts.contact_api"
    model = Contact
    serializer_class = ContactTemplateSerializer
    pagination_class = ContactsTemplateCursorPagination

    def get_queryset(self):
        return self.model.objects.filter(org=self.request.user.get_org(), is_active=True)

    def filter_queryset(self, queryset):
        params = self.request.query_params
        org = self.request.user.get_org()

        contact = params.get("contact")
        if contact:
            queryset = queryset.filter(uuid=contact)

        group_ref = params.get("group")
        if group_ref:
            group = ContactGroup.user_groups.filter(org=org).filter(Q(uuid=group_ref) | Q(name=group_ref)).first()

            if group:
                queryset = queryset.filter(all_groups=group)

        queryset = queryset.annotate(
            num_non_empty_templates=Count(
                "msgs", filter=Q(msgs__metadata__contains="templating", msgs__text__isnull=False)
            )
        )
        queryset = queryset.filter(num_non_empty_templates__gt=0)

        return self.filter_before_after(queryset, "msgs__sent_on")

    @classmethod
    def get_read_explorer(cls):
        return {
            "method": "GET",
            "title": "List Templates for contacts",
            "url": reverse("api.v2.contact_templates"),
            "slug": "contacts-templates-list",
            "params": [
                {
                    "name": "contact",
                    "required": False,
                    "help": "A Contact UUID to filter by. ex: 09d23a05-47fe-11e4-bfe9-b8f6b119e9ab",
                },
                {
                    "name": "group",
                    "required": False,
                    "help": "A Group UUID to filter by. ex: 09d23a05-47fe-11e4-bfe9-b8f6b119e9ab",
                },
                {
                    "name": "before",
                    "required": False,
                    "help": "Only return contacts modified before this date, ex: 2015-01-28T18:00:00.000",
                },
                {
                    "name": "after",
                    "required": False,
                    "help": "Only return contacts modified after this date, ex: 2015-01-28T18:00:00.000",
                },
            ],
        }


class ContactsTemplatesEndpointNew(ListAPIMixin, BaseAPIView):
    """
    This endpoint allows you to list contacts with templates in your account.

    ## Listing Contacts

    A **GET** returns the list of contacts whti templates for your organization, in the order of last activity date. The endpoin
    will return only with the contact that has template called in Msg.

     * **uuid** - the UUID of the contact (string), filterable as `uuid`.
     * **name** - the name of the contact (string), filterable as `name`.
     * **urns** - the URNs associated with the contact (string array), filterable as `urn`.
     * **groups** - the UUIDs of any groups the contact is part of (array of objects), filterable as `group` with group name or UUID.
     * **templates** - the templates the contact messages receive
     * **created_on** - when this contact was created (datetime).
     * **modified_on** - when this contact was last modified (datetime).
     * **last_seen_on** - when this contact last communicated with us (datetime).



    Example:

        GET /api/v2/contact_templates.json

    Response containing the contacts for your organization:

        {
            "next": null,
            "previous": null,
            "results": [
            {
            "uuid": "0fcbfa94-abbe-436a-867a-d8b3e6da6b83",
            "id": 123546,
            "name": "Jimmy",
            "urns": [
                "whatsapp:5555555555"
            ],
            "templates": [
                {
                    "uuid": "44019537-9afe-4898-9626-a5c724d169ef",
                    "name": "template_test",
                    "text": "Hello teste! I'm Doris, Weni's virtual assistant.",
                    "created_on": "2023-11-01T18:35:52.690932Z",
                    "sent_on": "2023-11-01T18:36:02.590312Z",
                    "direction": "Incoming",
                    "status": "wired"
                }
            ],
            "created_on": "2023-02-24T14:23:11.058607Z",
            "modified_on": "2024-02-08T14:05:51.711344Z",
            "last_seen_on": "2023-12-08T14:10:48.490004Z"
        }
                ]
        }

    """

    permission = "contacts.contact_api"
    model = Contact
    serializer_class = ContactTemplateSerializerNew
    pagination_class = ContactsTemplateCursorPagination

    def get_queryset(self):
        return self.model.objects.filter(org=self.request.user.get_org(), is_active=True)

    def filter_queryset(self, queryset):
        params = self.request.query_params
        org = self.request.user.get_org()

        contact = params.get("contact")
        if contact:
            queryset = queryset.filter(uuid=contact)

        group_ref = params.get("group")
        if group_ref:
            group = ContactGroup.user_groups.filter(org=org).filter(Q(uuid=group_ref) | Q(name=group_ref)).first()

            if group:
                queryset = queryset.filter(all_groups=group)

        template = params.get("template")
        if template:  # pragma: no cover
            template_object = get_object_or_404(Template, org=org, name=template)
            queryset = queryset.filter(msgs__template=template_object.name)

        queryset = queryset.annotate(
            num_non_empty_templates=Count(
                "msgs", filter=Q(msgs__text__isnull=False, msgs__template__isnull=False) & ~Q(msgs__template="")
            )
        )

        queryset = queryset.filter(num_non_empty_templates__gt=0)

        return self.filter_before_after(queryset, "msgs__sent_on")

    @classmethod
    def get_read_explorer(cls):
        return {
            "method": "GET",
            "title": "List Templates for contacts",
            "url": reverse("api.v2.contact_templates_new"),
            "slug": "contacts-templates-list",
            "params": [
                {
                    "name": "contact",
                    "required": False,
                    "help": "A Contact UUID to filter by. ex: 09d23a05-47fe-11e4-bfe9-b8f6b119e9ab",
                },
                {
                    "name": "group",
                    "required": False,
                    "help": "A Group UUID to filter by. ex: 09d23a05-47fe-11e4-bfe9-b8f6b119e9ab",
                },
                {
                    "name": "before",
                    "required": False,
                    "help": "Only return contacts modified before this date, ex: 2015-01-28T18:00:00.000",
                },
                {
                    "name": "after",
                    "required": False,
                    "help": "Only return contacts modified after this date, ex: 2015-01-28T18:00:00.000",
                },
            ],
        }


class FilterTemplatesEndpoint(ListAPIMixin, BaseAPIView):
    """
    This endpoint allows you to list contacts with templates in your account.

    ## Filter contacts by templates

    A **GET** returns the list of contacts with templates for your organization, in the order of last activity date. The endpoint
    will return only with the contact that has template called in Msg.

     * **uuid** - the UUID of the contact (string), filterable as `uuid`.
     * **name** - the name of the contact (string), filterable as `name`.
     * **template** - the template the contact messages receive
     * **created_on** - when this contact was created (datetime).
     * **modified_on** - when this contact was last modified (datetime).
     * **last_seen_on** - when this contact last communicated with us (datetime).

    Example:

        GET /api/v2/filter_templates.json

    Response containing the contacts for your organization:

        {
            "results": [
            {
            "id": 123546,
            "uuid": "0fcbfa94-abbe-436a-867a-d8b3e6da6b83",
            "name": "Jimmy",
            "template":
                {
                    "uuid": "44019537-9afe-4898-9626-a5c724d169ef",
                    "name": "template_test",
                    "text": "Hello teste! I'm Doris, Weni's virtual assistant.",
                    "created_on": "2023-11-01T18:35:52.690932Z",
                    "sent_on": "2023-11-01T18:36:02.590312Z",
                    "direction": "I",
                    "status": "wired"
                },
            "created_on": "2023-02-24T14:23:11.058607Z",
            "modified_on": "2024-02-08T14:05:51.711344Z",
            "last_seen_on": "2023-12-08T14:10:48.490004Z"
        }
                ]
        }

    """

    permission = "contacts.contact_api"
    model = Msg
    serializer_class = FilterTemplateSerializer
    pagination_class = ContactsTemplateCursorPagination

    def get(self, request, *args, **kwargs):
        params = self.request.query_params
        org = self.request.user.get_org()

        serializer = FilterTemplateSerializer(data=params)
        serializer.is_valid(raise_exception=True)

        template = serializer.validated_data["template"]
        page_size = serializer.validated_data["page_size"]
        offset = serializer.validated_data["offset"]

        before = None
        if params.get("before"):
            before = serializer.validated_data["before"]

            filter_before = f"""
                    AND msg.created_on <= '{before}'"""

        after = None
        if params.get("after"):
            after = serializer.validated_data["after"]
            filter_after = f"""
                    AND msg.created_on >= '{after}'"""

        sql = """SELECT
                    contact.id,
                    contact.uuid,
                    contact.name,
                    msg.metadata::json->'templating'->'template'->>'uuid',
                    msg.metadata::json->'templating'->'template'->>'name',
                    msg.text,
                    msg.created_on,
                    msg.sent_on,
                    msg.direction,
                    msg.status
                FROM public.msgs_msg as msg
                JOIN public.contacts_contact as contact
                    on msg.contact_id = contact.id
                WHERE
                    msg.metadata::json->'templating'->'template'->>'name' = %s
                    AND msg.org_id = %s"""

        final_sql = """
                ORDER BY contact.id
                LIMIT %s
                OFFSET %s
                """

        messages = None
        with connection.cursor() as cursor:
            if before:
                sql = sql + filter_before

            if after:
                sql = sql + filter_after

            sql = sql + final_sql
            cursor.execute(sql, [template, org.id, int(page_size), int(offset)])

            results = cursor.fetchall()
            messages = list(
                map(
                    lambda message: {
                        "id": message[0],
                        "uuid": message[1],
                        "name": message[2],
                        "template": {
                            "uuid": message[3],
                            "name": message[4],
                            "text": message[5],
                            "created_on": message[6],
                            "sent_on": message[7],
                            "direction": message[8],
                            "status": message[9],
                        },
                    },
                    results,
                )
            )

        response_data = {
            "results": messages,
        }

        return Response(response_data)

    @classmethod
    def get_read_explorer(cls):
        return {
            "method": "GET",
            "title": "Filter Templates for contacts context",
            "url": reverse("api.v2.filter_templates"),
            "slug": "contacts-templates-list",
            "params": [
                {
                    "name": "template",
                    "required": False,
                    "help": "Only return contacts for this template, ex: template=template_test",
                },
                {
                    "name": "before",
                    "required": False,
                    "help": "Only return contacts for this template before the date, ex: before=2024-01-01",
                },
                {
                    "name": "after",
                    "required": False,
                    "help": "Only return contacts for this template after the data, ex: after=2023-01-01",
                },
            ],
        }


class FilterTemplatesEndpointNew(ListAPIMixin, BaseAPIView):
    """
    This endpoint allows you to list contacts with templates in your account.

    ## Filter contacts by templates

    A **GET** returns the list of contacts with templates for your organization, in the order of last activity date. The endpoint
    will return only with the contact that has template called in Msg.

     * **uuid** - the UUID of the contact (string), filterable as `uuid`.
     * **name** - the name of the contact (string), filterable as `name`.
     * **template** - the template the contact messages receive
     * **created_on** - when this contact was created (datetime).
     * **modified_on** - when this contact was last modified (datetime).
     * **last_seen_on** - when this contact last communicated with us (datetime).

    Example:

        GET /api/v2/filter_templates.json

    Response containing the contacts for your organization:

        {
            "results": [
            {
            "id": 123546,
            "uuid": "0fcbfa94-abbe-436a-867a-d8b3e6da6b83",
            "name": "Jimmy",
            "template":
                {
                    "uuid": "44019537-9afe-4898-9626-a5c724d169ef",
                    "name": "template_test",
                    "text": "Hello teste! I'm Doris, Weni's virtual assistant.",
                    "created_on": "2023-11-01T18:35:52.690932Z",
                    "sent_on": "2023-11-01T18:36:02.590312Z",
                    "direction": "I",
                    "status": "wired"
                },
            "created_on": "2023-02-24T14:23:11.058607Z",
            "modified_on": "2024-02-08T14:05:51.711344Z",
            "last_seen_on": "2023-12-08T14:10:48.490004Z"
        }
                ]
        }

    """

    permission = "contacts.contact_api"
    model = Msg
    serializer_class = FilterTemplateSerializerNew
    pagination_class = ContactsTemplateCursorPagination

    def filter_queryset(self, queryset):
        params = self.request.query_params

        template = params.get("template")
        if template:
            queryset = queryset.filter(template=template)

        return self.filter_before_after(queryset, "created_on")

    @classmethod
    def get_read_explorer(cls):
        return {
            "method": "GET",
            "title": "Filter Templates for contacts context",
            "url": reverse("api.v2.filter_templates_new"),
            "slug": "contacts-templates-list",
            "params": [
                {
                    "name": "template",
                    "required": False,
                    "help": "Only return contacts for this template, ex: template=template_test",
                },
                {
                    "name": "before",
                    "required": False,
                    "help": "Only return contacts for this template before the date, ex: before=2024-01-01",
                },
                {
                    "name": "after",
                    "required": False,
                    "help": "Only return contacts for this template after the data, ex: after=2023-01-01",
                },
            ],
        }


class DefinitionsEndpoint(BaseAPIView):
    """
    This endpoint allows you to export definitions of flows, campaigns and triggers in your account. Note that the
    schema of flow definitions may change over time.

    ## Exporting Definitions

    A **GET** exports a set of flows and campaigns, and can automatically include dependencies for the requested items,
    such as groups, triggers and other flows.

      * **flow** - the UUIDs of flows to include (string, repeatable)
      * **campaign** - the UUIDs of campaigns to include (string, repeatable)
      * **dependencies** - whether to include dependencies (all, flows, none, default: all)

    Example:

        GET /api/v2/definitions.json?flow=f14e4ff0-724d-43fe-a953-1d16aefd1c0b&flow=09d23a05-47fe-11e4-bfe9-b8f6b119e9ab

    Response is a collection of definitions:

        {
            "version": "13",
            "site": "https://app.rapidpro.io",
            "flows": [
                {
                    "uuid": "7adbf194-a05c-4fe0-bd22-a178e24bee5e",
                    "name": "My Flow",
                    "spec_version": "13.1.0",
                    "language": "eng",
                    "type": "messaging",
                    "nodes": [
                        {
                            "uuid": "d2240abf-8c70-4cb4-96e9-c7e67ccb0e2a",
                            "actions": [
                                {
                                    "attachments": [],
                                    "text": "Hi @contact! Which state do you live in?",
                                    "type": "send_msg",
                                    "quick_replies": [],
                                    "uuid": "9012e709-76c8-4f2f-aea9-c1f7a31e7bb0"
                                }
                            ],
                            "exits": [
                                {
                                    "uuid": "81683d94-9623-4706-8878-e314beb9325c"
                                }
                            ]
                        }
                    ]
                }
            ],
            ...
        }
    """

    permission = "orgs.org_api"

    class Depends(Enum):
        none = 0
        flows = 1
        all = 2

    def get(self, request, *args, **kwargs):
        org = request.user.get_org()
        params = request.query_params

        if "flow_uuid" in params or "campaign_uuid" in params:  # deprecated
            flow_uuids = splitting_getlist(self.request, "flow_uuid")
            campaign_uuids = splitting_getlist(self.request, "campaign_uuid")
        else:
            flow_uuids = params.getlist("flow")
            campaign_uuids = params.getlist("campaign")

        include = params.get("dependencies", "all")
        if include not in DefinitionsEndpoint.Depends.__members__:
            raise InvalidQueryError(
                "dependencies must be one of %s" % ", ".join(DefinitionsEndpoint.Depends.__members__)
            )

        include = DefinitionsEndpoint.Depends[include]

        if flow_uuids:
            flows = set(Flow.objects.filter(uuid__in=flow_uuids, org=org, is_active=True))
        else:
            flows = set()

        if campaign_uuids:
            campaigns = set(Campaign.objects.filter(uuid__in=campaign_uuids, org=org, is_active=True))
        else:
            campaigns = set()

        include_fields_and_groups = False

        if include == DefinitionsEndpoint.Depends.none:
            components = set(itertools.chain(flows, campaigns))
        elif include == DefinitionsEndpoint.Depends.flows:
            components = org.resolve_dependencies(flows, campaigns, include_campaigns=False, include_triggers=True)
        else:
            components = org.resolve_dependencies(flows, campaigns, include_campaigns=True, include_triggers=True)
            include_fields_and_groups = True

        export = org.export_definitions(
            self.request.branding["link"],
            components,
            include_fields=include_fields_and_groups,
            include_groups=include_fields_and_groups,
        )

        return Response(export, status=status.HTTP_200_OK)

    @classmethod
    def get_read_explorer(cls):
        return {
            "method": "GET",
            "title": "Export Definitions",
            "url": reverse("api.v2.definitions"),
            "slug": "definition-list",
            "params": [
                {"name": "flow", "required": False, "help": "One or more flow UUIDs to include"},
                {"name": "campaign", "required": False, "help": "One or more campaign UUIDs to include"},
                {
                    "name": "dependencies",
                    "required": False,
                    "help": "Whether to include dependencies of the requested items. ex: false",
                },
            ],
        }


class FieldsEndpoint(ListAPIMixin, WriteAPIMixin, BaseAPIView):
    """
    This endpoint allows you to list custom contact fields in your account.

    ## Listing Fields

    A **GET** returns the list of custom contact fields for your organization, in the order of last created.

     * **key** - the unique key of this field (string), filterable as `key`
     * **label** - the display label of this field (string)
     * **value_type** - the data type of values associated with this field (string)

    Example:

        GET /api/v2/fields.json

    Response containing the fields for your organization:

         {
            "next": null,
            "previous": null,
            "results": [
                {
                    "key": "nick_name",
                    "label": "Nick name",
                    "value_type": "text"
                },
                ...
            ]
        }

    ## Adding Fields

    A **POST** can be used to create a new contact field. Don't specify a key as this will be generated for you.

    * **label** - the display label (string)
    * **value_type** - one of the value type codes (string)

    Example:

        POST /api/v2/fields.json
        {
            "label": "Nick name",
            "value_type": "text"
        }

    You will receive a field object (with the new field key) as a response if successful:

        {
            "key": "nick_name",
            "label": "Nick name",
            "value_type": "text"
        }

    ## Updating Fields

    A **POST** can also be used to update an existing field if you include it's key in the URL.

    Example:

        POST /api/v2/fields.json?key=nick_name
        {
            "label": "New label",
            "value_type": "text"
        }

    You will receive the updated field object as a response if successful:

        {
            "key": "nick_name",
            "label": "New label",
            "value_type": "text"
        }
    """

    permission = "contacts.contactfield_api"
    model = ContactField
    serializer_class = ContactFieldReadSerializer
    write_serializer_class = ContactFieldWriteSerializer
    pagination_class = CreatedOnCursorPagination
    lookup_params = {"key": "key"}

    def derive_queryset(self):
        org = self.request.user.get_org()
        return self.model.user_fields.filter(org=org, is_active=True)

    def filter_queryset(self, queryset):
        params = self.request.query_params

        # filter by key (optional)
        key = params.get("key")
        if key:
            queryset = queryset.filter(key=key)

        return queryset.filter(is_active=True)

    @classmethod
    def get_read_explorer(cls):
        return {
            "method": "GET",
            "title": "List Fields",
            "url": reverse("api.v2.fields"),
            "slug": "field-list",
            "params": [{"name": "key", "required": False, "help": "A field key to filter by. ex: nick_name"}],
            "example": {"query": "key=nick_name"},
        }

    @classmethod
    def get_write_explorer(cls):
        return {
            "method": "POST",
            "title": "Add or Update Fields",
            "url": reverse("api.v2.fields"),
            "slug": "field-write",
            "params": [{"name": "key", "required": False, "help": "Key of an existing field to update"}],
            "fields": [
                {"name": "label", "required": True, "help": "The label of the field"},
                {"name": "value_type", "required": True, "help": "The value type of the field"},
            ],
            "example": {"query": "key=nick_name"},
        }


class FlowsEndpoint(ListAPIMixin, BaseAPIView):
    """
    This endpoint allows you to list flows in your account.

    ## Listing Flows

    A **GET** returns the list of flows for your organization, in the order of last created.

     * **uuid** - the UUID of the flow (string), filterable as `uuid`
     * **name** - the name of the flow (string)
     * **type** - the type of the flow (one of "message", "voice", "survey"), filterable as `type`
     * **archived** - whether this flow is archived (boolean), filterable as `archived`
     * **labels** - the labels for this flow (array of objects), filterable as `labels`
     * **expires** - the time (in minutes) when this flow's inactive contacts will expire (integer)
     * **runs** - the counts of completed, interrupted and expired runs (object)
     * **results** - the results that this flow may create (array)
     * **parent_refs** - the keys of the parent flow results referenced in this flow (array)
     * **created_on** - when this flow was created (datetime)
     * **modified_on** - when this flow was last modified (datetime), filterable as `before` and `after`.

    Example:

        GET /api/v2/flows.json

    Response containing the flows for your organization:

        {
            "next": null,
            "previous": null,
            "results": [
                {
                    "uuid": "5f05311e-8f81-4a67-a5b5-1501b6d6496a",
                    "name": "Survey",
                    "type": "message",
                    "archived": false,
                    "labels": [{"name": "Important", "uuid": "5a4eb79e-1b1f-4ae3-8700-09384cca385f"}],
                    "expires": 600,
                    "runs": {
                        "active": 47,
                        "completed": 123,
                        "interrupted": 2,
                        "expired": 34
                    },
                    "results": [
                        {
                            "key": "has_water",
                            "name": "Has Water",
                            "categories": ["Yes", "No", "Other"],
                            "node_uuids": ["99afcda7-f928-4d4a-ae83-c90c96deb76d"]
                        }
                    ],
                    "parent_refs": [],
                    "created_on": "2016-01-06T15:33:00.813162Z",
                    "modified_on": "2017-01-07T13:14:00.453567Z"
                },
                ...
            ]
        }
    """

    permission = "flows.flow_api"
    model = Flow
    serializer_class = FlowReadSerializer
    pagination_class = CreatedOnCursorPagination

    FLOW_TYPES = {v: k for k, v in FlowReadSerializer.FLOW_TYPES.items()}

    def filter_queryset(self, queryset):
        params = self.request.query_params

        queryset = queryset.exclude(is_active=False).exclude(is_system=True)

        # filter by UUID (optional)
        uuid = params.get("uuid")
        if uuid:
            queryset = queryset.filter(uuid=uuid)

        # filter by type (optional)
        flow_type = params.get("type")
        if flow_type:
            queryset = queryset.filter(flow_type=self.FLOW_TYPES.get(flow_type))

        # filter by archived (optional)
        archived = params.get("archived")
        if archived:
            queryset = queryset.filter(is_archived=str_to_bool(archived))

        labels = params.getlist("labels")
        if labels:
            queryset = queryset.filter(labels__name__in=labels)

        queryset = queryset.prefetch_related("labels")

        return self.filter_before_after(queryset, "modified_on")

    @classmethod
    def get_read_explorer(cls):
        return {
            "method": "GET",
            "title": "List Flows",
            "url": reverse("api.v2.flows"),
            "slug": "flow-list",
            "params": [
                {
                    "name": "uuid",
                    "required": False,
                    "help": "A flow UUID filter by. ex: 5f05311e-8f81-4a67-a5b5-1501b6d6496a",
                },
                {
                    "name": "before",
                    "required": False,
                    "help": "Only return flows modified before this date, ex: 2017-01-28T18:00:00.000",
                },
                {
                    "name": "after",
                    "required": False,
                    "help": "Only return flows modified after this date, ex: 2017-01-28T18:00:00.000",
                },
            ],
        }


class FlowsLabelsEndpoint(ListAPIMixin, BaseAPIView):
    """
    This endpoint allows you to list labels of the flows in your account.

    ## Listing Labels Flows

    A **GET** returns the list of labels of the flows for your organization, in the order of last created.

     * **uuid** - the UUID of the label (string)
     * **name** - the name of the label (string)
     * **parents** - the parent label of the label, if exists


    Example:

        GET /api/v2/flows_labels.json

    Response containing the labels for your organization:

        {
            "next": null,
            "previous": null,
            "results": [
                {
                    "uuid": "5f05311e-8f81-4a67-a5b5-1501b6d6496a",
                    "name": "Survey",
                    "parent": null,
                },
                ...
            ]
        }
    """

    permission = "flows.flow_api"
    model = FlowLabel
    serializer_class = FlowsLabelsReadSerializer
    pagination_class = NameCursorPagination

    def filter_queryset(self, queryset):
        org = self.request.user.get_org()
        return org.flow_labels.all()

    @classmethod
    def get_read_explorer(cls):
        return {
            "method": "GET",
            "title": "List Flows Labels",
            "url": reverse("api.v2.flows_labels"),
            "slug": "flow-label-list",
            "params": [],
        }


class GlobalsEndpoint(ListAPIMixin, WriteAPIMixin, BaseAPIView):
    """
    This endpoint allows you to list, create, and update active globals on your account.

    ## Listing Globals

    A **GET** returns the globals for your organization, most recently modified first.

     * **key** - the key of the global
     * **name** - the name of the global
     * **value** - the value of the global
     * **modified_on** - when this global was modified

    Example:

        GET /api/v2/globals.json

    Response:

        {
            "next": null,
            "previous": null,
            "results": [
                {
                    "key": "org_name",
                    "name": "Org Name",
                    "value": "Acme Ltd",
                    "modified_on": "2013-02-27T09:06:15.456"
                },
                ...
            ]
        }

    ## Adding a Global

    A **POST** can be used to create a new Global. Don't specify a key as this will be generated for you.

     * **name** - the name of the global
     * **value** - the value of the global

    Example:

        POST /api/v2/global.json
        {
            "name": "Org Name",
            "value": "Acme Ltd"
        }

    You will receive a global object as a response if successful:

        {
            "key": "org_name",
            "name": "Org Name",
            "value": "Acme Ltd",
            "modified_on": "2013-02-27T09:06:15.456"
        }

    ## Updating a Global

    A **POST** can also be used to update an existing global if you specify its key in the URL.

    Example:

        POST /api/v2/globals.json?key=org_name
        {
            "value": "Acme Ltd"
        }

    You will receive the updated global object as a response if successful:

        {
            "key": "org_name",
            "name": "Org Name",
            "value": "Acme Ltd",
            "modified_on": "2013-02-27T09:06:15.456"
        }
    """

    permission = "globals.global_api"
    model = Global
    serializer_class = GlobalReadSerializer
    write_serializer_class = GlobalWriteSerializer
    pagination_class = ModifiedOnCursorPagination
    lookup_params = {"key": "key"}

    def filter_queryset(self, queryset):
        params = self.request.query_params
        # filter by key (optional)
        key = params.get("key")
        if key:
            queryset = queryset.filter(key=key)

        # filter by modified (optional)
        before = params.get("before")
        after = params.get("after")
        if before or after:
            return self.filter_before_after(queryset, "modified_on")

        return queryset.filter(is_active=True)

    @classmethod
    def get_read_explorer(cls):
        return {
            "method": "GET",
            "title": "List Globals",
            "url": reverse("api.v2.globals"),
            "slug": "globals-list",
            "params": [
                {
                    "name": "before",
                    "required": False,
                    "help": "Only return globals modified before this date, ex: 2015-01-28T18:00:00.000",
                },
                {
                    "name": "after",
                    "required": False,
                    "help": "Only return globals modified after this date, ex: 2015-01-28T18:00:00.000",
                },
                {"name": "key", "required": False, "help": "A global key filter by"},
            ],
        }

    @classmethod
    def get_write_explorer(cls):
        return {
            "method": "POST",
            "title": "Add or Update Globals ",
            "url": reverse("api.v2.globals"),
            "slug": "globals-write",
            "params": [{"name": "key", "required": False, "help": "Key of an existing global to update"}],
            "fields": [
                {"name": "name", "required": False, "help": "the Name value of the global"},
                {"name": "value", "required": True, "help": "the new value of the global"},
            ],
        }


class GroupsEndpoint(ListAPIMixin, WriteAPIMixin, DeleteAPIMixin, BaseAPIView):
    """
    This endpoint allows you to list, create, update and delete contact groups in your account.

    ## Listing Groups

    A **GET** returns the list of contact groups for your organization, in the order of last created.

     * **uuid** - the UUID of the group (string), filterable as `uuid`
     * **name** - the name of the group (string), filterable as `name`
     * **count** - the number of contacts in the group (int)

    Example:

        GET /api/v2/groups.json

    Response containing the groups for your organization:

        {
            "next": null,
            "previous": null,
            "results": [
                {
                    "uuid": "5f05311e-8f81-4a67-a5b5-1501b6d6496a",
                    "name": "Reporters",
                    "count": 315,
                    "query": null
                },
                ...
            ]
        }

    ## Adding a Group

    A **POST** can be used to create a new contact group. Don't specify a UUID as this will be generated for you.

    * **name** - the group name (string)

    Example:

        POST /api/v2/groups.json
        {
            "name": "Reporters"
        }

    You will receive a group object as a response if successful:

        {
            "uuid": "5f05311e-8f81-4a67-a5b5-1501b6d6496a",
            "name": "Reporters",
            "count": 0,
            "query": null
        }

    ## Updating a Group

    A **POST** can also be used to update an existing contact group if you specify its UUID in the URL.

    Example:

        POST /api/v2/groups.json?uuid=5f05311e-8f81-4a67-a5b5-1501b6d6496a
        {
            "name": "Checked"
        }

    You will receive the updated group object as a response if successful:

        {
            "uuid": "5f05311e-8f81-4a67-a5b5-1501b6d6496a",
            "name": "Checked",
            "count": 0,
            "query": null
        }

    ## Deleting a Group

    A **DELETE** can be used to delete a contact group if you specify its UUID in the URL.

    Notes:
        - cannot delete groups with associated active campaigns, flows or triggers. You first need to delete related
          objects through the web interface

    Example:

        DELETE /api/v2/groups.json?uuid=5f05311e-8f81-4a67-a5b5-1501b6d6496a

    You will receive either a 204 response if a group was deleted, or a 404 response if no matching group was found.
    """

    permission = "contacts.contactgroup_api"
    model = ContactGroup
    model_manager = "user_groups"
    serializer_class = ContactGroupReadSerializer
    write_serializer_class = ContactGroupWriteSerializer
    pagination_class = CreatedOnCursorPagination
    exclusive_params = ("uuid", "name")

    def filter_queryset(self, queryset):
        params = self.request.query_params

        # filter by UUID (optional)
        uuid = params.get("uuid")
        if uuid:
            queryset = queryset.filter(uuid=uuid)

        # filter by name (optional)
        name = params.get("name")
        if name:
            queryset = queryset.filter(name__iexact=name)

        return queryset.filter(is_active=True).exclude(status=ContactGroup.STATUS_INITIALIZING)

    def prepare_for_serialization(self, object_list, using: str):
        group_counts = ContactGroupCount.get_totals(object_list)
        for group in object_list:
            group.count = group_counts[group]

    def delete(self, request, *args, **kwargs):
        self.lookup_values = self.get_lookup_values()
        if not self.lookup_values:
            raise InvalidQueryError(
                "URL must contain one of the following parameters: " + ", ".join(sorted(self.lookup_params.keys()))
            )

        instance = self.get_object()

        # if there are still dependencies, give up
        triggers = instance.triggers.filter(is_archived=False)
        if triggers:
            deps = ", ".join([str(t.id) for t in triggers])
            raise InvalidQueryError(
                f"Group is being used by the following triggers which must be archived first: {deps}"
            )

        flows = Flow.objects.filter(org=instance.org, group_dependencies__in=[instance])
        if flows:
            deps = ", ".join([f.uuid for f in flows])
            raise InvalidQueryError(f"Group is being used by the following flows which must be archived first: {deps}")

        campaigns = instance.campaigns.filter(is_archived=False)
        if campaigns:
            deps = ", ".join([c.uuid for c in campaigns])
            raise InvalidQueryError(
                f"Group is being used by the following campaigns which must be archived first: {deps}"
            )

        self.perform_destroy(instance)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @classmethod
    def get_read_explorer(cls):
        return {
            "method": "GET",
            "title": "List Contact Groups",
            "url": reverse("api.v2.groups"),
            "slug": "group-list",
            "params": [
                {"name": "uuid", "required": False, "help": "A contact group UUID to filter by"},
                {"name": "name", "required": False, "help": "A contact group name to filter by"},
            ],
        }

    @classmethod
    def get_write_explorer(cls):
        return {
            "method": "POST",
            "title": "Add or Update Contact Groups",
            "url": reverse("api.v2.groups"),
            "slug": "group-write",
            "params": [{"name": "uuid", "required": False, "help": "The UUID of the contact group to update"}],
            "fields": [{"name": "name", "required": True, "help": "The name of the contact group"}],
        }

    @classmethod
    def get_delete_explorer(cls):
        return {
            "method": "DELETE",
            "title": "Delete Contact Groups",
            "url": reverse("api.v2.groups"),
            "slug": "group-delete",
            "params": [{"name": "uuid", "required": True, "help": "The UUID of the contact group to delete"}],
        }


class LabelsEndpoint(ListAPIMixin, WriteAPIMixin, DeleteAPIMixin, BaseAPIView):
    """
    This endpoint allows you to list, create, update and delete message labels in your account.

    ## Listing Labels

    A **GET** returns the list of message labels for your organization, in the order of last created.

     * **uuid** - the UUID of the label (string), filterable as `uuid`
     * **name** - the name of the label (string), filterable as `name`
     * **count** - the number of messages with this label (int)

    Example:

        GET /api/v2/labels.json

    Response containing the labels for your organization:

        {
            "next": null,
            "previous": null,
            "results": [
                {
                    "uuid": "5f05311e-8f81-4a67-a5b5-1501b6d6496a",
                    "name": "Screened",
                    "count": 315
                },
                ...
            ]
        }

    ## Adding a Label

    A **POST** can be used to create a new message label. Don't specify a UUID as this will be generated for you.

    * **name** - the label name (string)

    Example:

        POST /api/v2/labels.json
        {
            "name": "Screened"
        }

    You will receive a label object as a response if successful:

        {
            "uuid": "fdd156ca-233a-48c1-896d-a9d594d59b95",
            "name": "Screened",
            "count": 0
        }

    ## Updating a Label

    A **POST** can also be used to update an existing message label if you specify its UUID in the URL.

    Example:

        POST /api/v2/labels.json?uuid=fdd156ca-233a-48c1-896d-a9d594d59b95
        {
            "name": "Checked"
        }

    You will receive the updated label object as a response if successful:

        {
            "uuid": "fdd156ca-233a-48c1-896d-a9d594d59b95",
            "name": "Checked",
            "count": 0
        }

    ## Deleting a Label

    A **DELETE** can be used to delete a message label if you specify its UUID in the URL.

    Example:

        DELETE /api/v2/labels.json?uuid=fdd156ca-233a-48c1-896d-a9d594d59b95

    You will receive either a 204 response if a label was deleted, or a 404 response if no matching label was found.
    """

    permission = "contacts.label_api"
    model = Label
    model_manager = "label_objects"
    serializer_class = LabelReadSerializer
    write_serializer_class = LabelWriteSerializer
    pagination_class = CreatedOnCursorPagination
    exclusive_params = ("uuid", "name")

    def filter_queryset(self, queryset):
        params = self.request.query_params

        # filter by UUID (optional)
        uuid = params.get("uuid")
        if uuid:
            queryset = queryset.filter(uuid=uuid)

        # filter by name (optional)
        name = params.get("name")
        if name:
            queryset = queryset.filter(name__iexact=name)

        return queryset.filter(is_active=True)

    def prepare_for_serialization(self, object_list, using: str):
        label_counts = LabelCount.get_totals(object_list)
        for label in object_list:
            label.count = label_counts[label]

    @classmethod
    def get_read_explorer(cls):
        return {
            "method": "GET",
            "title": "List Message Labels",
            "url": reverse("api.v2.labels"),
            "slug": "label-list",
            "params": [
                {"name": "uuid", "required": False, "help": "A message label UUID to filter by"},
                {"name": "name", "required": False, "help": "A message label name to filter by"},
            ],
        }

    @classmethod
    def get_write_explorer(cls):
        return {
            "method": "POST",
            "title": "Add or Update Message Labels",
            "url": reverse("api.v2.labels"),
            "slug": "label-write",
            "params": [{"name": "uuid", "required": False, "help": "The UUID of the message label to update"}],
            "fields": [{"name": "name", "required": True, "help": "The name of the message label"}],
        }

    @classmethod
    def get_delete_explorer(cls):
        return {
            "method": "DELETE",
            "title": "Delete Message Labels",
            "url": reverse("api.v2.labels"),
            "slug": "label-delete",
            "params": [{"name": "uuid", "required": True, "help": "The UUID of the message label to delete"}],
        }


class MediaEndpoint(BaseAPIView):
    """
    This endpoint allows you to submit media which can be embedded in flow steps.

    ## Creating Media

    By making a `POST` request to the endpoint you can add a new media files
    """

    parser_classes = (MultiPartParser, FormParser)
    permission = "msgs.msg_api"

    def post(self, request, format=None, *args, **kwargs):
        org = self.request.user.get_org()
        media_file = request.data.get("media_file", None)
        extension = request.data.get("extension", None)

        if media_file and extension:
            location = org.save_media(media_file, extension)
            return Response(dict(location=location), status=status.HTTP_201_CREATED)

        return Response(dict(), status=status.HTTP_400_BAD_REQUEST)


class MessagesEndpoint(ListAPIMixin, BaseAPIView):
    """
    This endpoint allows you to list messages in your account.

    ## Listing Messages

    A `GET` returns the messages for your organization, filtering them as needed. Each message has the following
    attributes:

     * **id** - the ID of the message (int), filterable as `id`.
     * **broadcast** - the id of the broadcast (int), filterable as `broadcast`.
     * **contact** - the UUID and name of the contact (object), filterable as `contact` with UUID.
     * **urn** - the URN of the sender or receiver, depending on direction (string).
     * **channel** - the UUID and name of the channel that handled this message (object).
     * **direction** - the direction of the message (one of "incoming" or "outgoing").
     * **type** - the type of the message (one of "inbox", "flow", "ivr").
     * **status** - the status of the message (one of "initializing", "queued", "wired", "sent", "delivered", "handled", "errored", "failed", "resent").
     * **visibility** - the visibility of the message (one of "visible", "archived" or "deleted")
     * **text** - the text of the message received (string). Note this is the logical view and the message may have been received as multiple physical messages.
     * **attachments** - the attachments on the message (array of objects).
     * **labels** - any labels set on this message (array of objects), filterable as `label` with label name or UUID.
     * **created_on** - when this message was either received by the channel or created (datetime) (filterable as `before` and `after`).
     * **sent_on** - for outgoing messages, when the channel sent the message (null if not yet sent or an incoming message) (datetime).
     * **modified_on** - when the message was last modified (datetime)

    You can also filter by `folder` where folder is one of `inbox`, `flows`, `archived`, `outbox`, `incoming`, `failed` or `sent`.
    Note that you cannot filter by more than one of `contact`, `folder`, `label` or `broadcast` at the same time.

    Without any parameters this endpoint will return all incoming and outgoing messages ordered by creation date.

    The sort order for all folders save for `incoming` is the message creation date. For the `incoming` folder (which
    includes all incoming messages, regardless of visibility or type) messages are sorted by last modified date. This
    allows clients to poll for updates to message labels and visibility changes.

    Example:

        GET /api/v2/messages.json?folder=inbox

    Response is the list of messages for that contact, most recently created first:

        {
            "next": "http://example.com/api/v2/messages.json?folder=inbox&cursor=cD0yMDE1LTExLTExKzExJTNBM40NjQlMkIwMCUzRv",
            "previous": null,
            "results": [
            {
                "id": 4105426,
                "broadcast": 2690007,
                "contact": {"uuid": "d33e9ad5-5c35-414c-abd4-e7451c69ff1d", "name": "Bob McFlow"},
                "urn": "twitter:textitin",
                "channel": {"uuid": "9a8b001e-a913-486c-80f4-1356e23f582e", "name": "Vonage"},
                "direction": "out",
                "type": "inbox",
                "status": "wired",
                "visibility": "visible",
                "text": "How are you?",
                "attachments": [{"content_type": "audio/wav" "url": "http://domain.com/recording.wav"}],
                "labels": [{"name": "Important", "uuid": "5a4eb79e-1b1f-4ae3-8700-09384cca385f"}],
                "created_on": "2016-01-06T15:33:00.813162Z",
                "sent_on": "2016-01-06T15:35:03.675716Z",
                "modified_on": "2016-01-06T15:35:03.675716Z"
            },
            ...
        }
    """

    class Pagination(CreatedOnCursorPagination):
        """
        Overridden paginator for Msg endpoint that switches from created_on to modified_on when looking
        at all incoming messages.
        """

        def get_ordering(self, request, queryset, view=None):
            if request.query_params.get("folder", "").lower() == "incoming":
                return "-modified_on", "-id"
            else:
                return CreatedOnCursorPagination.ordering

    permission = "msgs.msg_api"
    model = Msg
    serializer_class = MsgReadSerializer
    pagination_class = Pagination
    exclusive_params = ("contact", "folder", "label", "broadcast")
    throttle_scope = "v2.messages"

    FOLDER_FILTERS = {
        "inbox": SystemLabel.TYPE_INBOX,
        "flows": SystemLabel.TYPE_FLOWS,
        "archived": SystemLabel.TYPE_ARCHIVED,
        "outbox": SystemLabel.TYPE_OUTBOX,
        "failed": SystemLabel.TYPE_FAILED,
        "sent": SystemLabel.TYPE_SENT,
    }

    def derive_queryset(self):
        org = self.request.user.get_org()
        folder = self.request.query_params.get("folder")

        if folder:
            sys_label = self.FOLDER_FILTERS.get(folder.lower())
            if sys_label:
                return SystemLabel.get_queryset(org, sys_label)
            elif folder == "incoming":
                return self.model.objects.filter(org=org, direction="I")
            else:
                return self.model.objects.filter(pk=-1)
        else:
            return self.model.objects.filter(org=org).exclude(visibility=Msg.VISIBILITY_DELETED).exclude(msg_type=None)

    def filter_queryset(self, queryset):
        params = self.request.query_params
        org = self.request.user.get_org()

        # filter by id (optional)
        msg_id = self.get_int_param("id")
        if msg_id:
            queryset = queryset.filter(id=msg_id)

        # filter by broadcast (optional)
        broadcast_id = params.get("broadcast")
        if broadcast_id:
            queryset = queryset.filter(broadcast_id=broadcast_id)

        # filter by contact (optional)
        contact_uuid = params.get("contact")
        if contact_uuid:
            contact = Contact.objects.filter(org=org, is_active=True, uuid=contact_uuid).first()
            if contact:
                queryset = queryset.filter(contact=contact)
            else:
                queryset = queryset.filter(pk=-1)

        # filter by label name/uuid (optional)
        label_ref = params.get("label")
        if label_ref:
            label = Label.label_objects.filter(org=org).filter(Q(name=label_ref) | Q(uuid=label_ref)).first()
            if label:
                queryset = queryset.filter(labels=label, visibility=Msg.VISIBILITY_VISIBLE)
            else:
                queryset = queryset.filter(pk=-1)

        # use prefetch rather than select_related for foreign keys to avoid joins
        queryset = queryset.prefetch_related(
            Prefetch("contact", queryset=Contact.objects.only("uuid", "name")),
            Prefetch("contact_urn", queryset=ContactURN.objects.only("scheme", "path", "display")),
            Prefetch("channel", queryset=Channel.objects.only("uuid", "name")),
            Prefetch("labels", queryset=Label.label_objects.only("uuid", "name").order_by("pk")),
        )

        # incoming folder gets sorted by 'modified_on'
        if self.request.query_params.get("folder", "").lower() == "incoming":
            return self.filter_before_after(queryset, "modified_on")

        # everything else by 'created_on'
        else:
            return self.filter_before_after(queryset, "created_on")

    @classmethod
    def get_read_explorer(cls):
        return {
            "method": "GET",
            "title": "List Messages",
            "url": reverse("api.v2.messages"),
            "slug": "msg-list",
            "params": [
                {"name": "id", "required": False, "help": "A message ID to filter by, ex: 123456"},
                {"name": "broadcast", "required": False, "help": "A broadcast ID to filter by, ex: 12345"},
                {
                    "name": "contact",
                    "required": False,
                    "help": "A contact UUID to filter by, ex: 09d23a05-47fe-11e4-bfe9-b8f6b119e9ab",
                },
                {
                    "name": "folder",
                    "required": False,
                    "help": "A folder name to filter by, one of: inbox, flows, archived, outbox, sent, incoming",
                },
                {"name": "label", "required": False, "help": "A label name or UUID to filter by, ex: Spam"},
                {
                    "name": "before",
                    "required": False,
                    "help": "Only return messages created before this date, ex: 2015-01-28T18:00:00.000",
                },
                {
                    "name": "after",
                    "required": False,
                    "help": "Only return messages created after this date, ex: 2015-01-28T18:00:00.000",
                },
            ],
            "example": {"query": "folder=incoming&after=2014-01-01T00:00:00.000"},
        }


class MessageActionsEndpoint(BulkWriteAPIMixin, BaseAPIView):
    """
    ## Bulk Message Updating

    A **POST** can be used to perform an action on a set of messages in bulk.

    * **messages** - the message ids (array of up to 100 integers)
    * **action** - the action to perform, a string one of:

        * _label_ - Apply the given label to the messages
        * _unlabel_ - Remove the given label from the messages
        * _archive_ - Archive the messages
        * _restore_ - Restore the messages if they are archived
        * _delete_ - Permanently delete the messages

    * **label** - the UUID or name of an existing label (string, optional)
    * **label_name** - the name of a label which can be created if it doesn't exist (string, optional)

    If labelling or unlabelling messages using `label` you will get an error response (400) if the label doesn't exist.
    If labelling with `label_name` the label will be created if it doesn't exist, and if unlabelling it is ignored if
    it doesn't exist.

    Example:

        POST /api/v2/message_actions.json
        {
            "messages": [1234, 2345, 3456],
            "action": "label",
            "label": "Testing"
        }

    You will receive an empty response with status code 204 if successful. In the case that some messages couldn't be
    updated because they no longer exist, the status code will be 200 and the body will include the failed message ids:

    Example response:

        {"failures": [2345, 3456]}

    """

    permission = "msgs.msg_api"
    serializer_class = MsgBulkActionSerializer

    @classmethod
    def get_write_explorer(cls):
        actions = cls.serializer_class.ACTIONS

        return {
            "method": "POST",
            "title": "Update Multiple Messages",
            "url": reverse("api.v2.message_actions"),
            "slug": "message-actions",
            "fields": [
                {"name": "messages", "required": True, "help": "The ids of the messages to update"},
                {"name": "action", "required": True, "help": "One of the following strings: " + ", ".join(actions)},
                {"name": "label", "required": False, "help": "The UUID or name of a message label"},
            ],
        }


class ResthooksEndpoint(ListAPIMixin, BaseAPIView):
    """
    This endpoint allows you to list configured resthooks in your account.

    ## Listing Resthooks

    A `GET` returns the resthooks on your organization. Each resthook has the following attributes:

     * **resthook** - the slug for the resthook (string)
     * **created_on** - the datetime when this resthook was created (datetime)
     * **modified_on** - the datetime when this resthook was last modified (datetime)

    Example:

        GET /api/v2/resthooks.json

    Response is the list of resthooks on your organization, most recently modified first:

        {
            "next": "http://example.com/api/v2/resthooks.json?cursor=cD0yMDE1LTExLTExKzExJTNBM40NjQlMkIwMCUzRv",
            "previous": null,
            "results": [
            {
                "resthook": "new-report",
                "created_on": "2015-11-11T13:05:57.457742Z",
                "modified_on": "2015-11-11T13:05:57.457742Z",
            },
            ...
        }
    """

    permission = "api.resthook_api"
    model = Resthook
    serializer_class = ResthookReadSerializer
    pagination_class = ModifiedOnCursorPagination

    def filter_queryset(self, queryset):
        return queryset.filter(is_active=True)

    @classmethod
    def get_read_explorer(cls):
        return {
            "method": "GET",
            "title": "List Resthooks",
            "url": reverse("api.v2.resthooks"),
            "slug": "resthook-list",
            "params": [],
        }


class ResthookSubscribersEndpoint(ListAPIMixin, WriteAPIMixin, DeleteAPIMixin, BaseAPIView):
    """
    This endpoint allows you to list, add or remove subscribers to resthooks.

    ## Listing Resthook Subscribers

    A `GET` returns the subscribers on your organization. Each resthook subscriber has the following attributes:

     * **id** - the id of the subscriber (integer, filterable)
     * **resthook** - the resthook they are subscribed to (string, filterable)
     * **target_url** - the url that will be notified when this event occurs
     * **created_on** - when this subscriber was added

    Example:

        GET /api/v2/resthook_subscribers.json

    Response is the list of resthook subscribers on your organization, most recently created first:

        {
            "next": "http://example.com/api/v2/resthook_subscribers.json?cursor=cD0yMDE1LTExLTExKzExJTNBM40NjQlMkIwMCUzRv",
            "previous": null,
            "results": [
            {
                "id": "10404016"
                "resthook": "mother-registration",
                "target_url": "https://zapier.com/receive/505019595",
                "created_on": "2013-08-19T19:11:21.082Z"
            },
            {
                "id": "10404055",
                "resthook": "new-birth",
                "target_url": "https://zapier.com/receive/605010501",
                "created_on": "2013-08-19T19:11:21.082Z"
            },
            ...
        }

    ## Subscribing to a Resthook

    By making a `POST` request with the event you want to subscribe to and the target URL, you can subscribe to be
    notified whenever your resthook event is triggered.

     * **resthook** - the slug of the resthook to subscribe to
     * **target_url** - the URL you want called (will be called with a POST)

    Example:

        POST /api/v2/resthook_subscribers.json
        {
            "resthook": "new-report",
            "target_url": "https://zapier.com/receive/505019595"
        }

    Response is the created subscription:

        {
            "id": "10404016",
            "resthook": "new-report",
            "target_url": "https://zapier.com/receive/505019595",
            "created_on": "2013-08-19T19:11:21.082Z"
        }

    ## Deleting a Subscription

    A **DELETE** can be used to delete a subscription if you specify its id in the URL.

    Example:

        DELETE /api/v2/resthook_subscribers.json?id=10404016

    You will receive either a 204 response if a subscriber was deleted, or a 404 response if no matching subscriber was found.

    """

    permission = "api.resthooksubscriber_api"
    model = ResthookSubscriber
    serializer_class = ResthookSubscriberReadSerializer
    write_serializer_class = ResthookSubscriberWriteSerializer
    pagination_class = CreatedOnCursorPagination
    lookup_params = {"id": "id"}

    def get_queryset(self):
        org = self.request.user.get_org()
        return self.model.objects.filter(resthook__org=org, is_active=True)

    def filter_queryset(self, queryset):
        params = self.request.query_params

        # filter by id (optional)
        subscriber_id = self.get_int_param("id")
        if subscriber_id:
            queryset = queryset.filter(id=subscriber_id)

        resthook = params.get("resthook")
        if resthook:
            queryset = queryset.filter(resthook__slug=resthook)

        return queryset.select_related("resthook")

    @classmethod
    def get_read_explorer(cls):
        return {
            "method": "GET",
            "title": "List Resthook Subscribers",
            "url": reverse("api.v2.resthook_subscribers"),
            "slug": "resthooksubscriber-list",
            "params": [],
        }

    @classmethod
    def get_write_explorer(cls):
        return dict(
            method="POST",
            title="Add Resthook Subscriber",
            url=reverse("api.v2.resthook_subscribers"),
            slug="resthooksubscriber-write",
            fields=[
                dict(name="resthook", required=True, help="The slug for the resthook you want to subscribe to"),
                dict(
                    name="target_url",
                    required=True,
                    help="The URL that will be called when the resthook is triggered.",
                ),
            ],
            example=dict(body='{"resthook": "new-report", "target_url": "https://zapier.com/handle/1515155"}'),
        )

    @classmethod
    def get_delete_explorer(cls):
        return dict(
            method="DELETE",
            title="Delete Resthook Subscriber",
            url=reverse("api.v2.resthook_subscribers"),
            slug="resthooksubscriber-delete",
            params=[dict(name="id", required=True, help="The id of the subscriber to delete")],
        )


class ResthookEventsEndpoint(ListAPIMixin, BaseAPIView):
    """
    This endpoint lists recent events for the passed in Resthook.

    ## Listing Resthook Events

    A `GET` returns the recent resthook events on your organization. Each event has the following attributes:

     * **resthook** - the slug for the resthook (filterable)
     * **data** - the data for the resthook
     * **created_on** - the datetime when this resthook was created (datetime)

    Example:

        GET /api/v2/resthook_events.json

    Response is the list of recent resthook events on your organization, most recently created first:

        {
            "next": "http://example.com/api/v2/resthook_events.json?cursor=cD0yMDE1LTExLTExKzExJTNBM40NjQlMkIwMCUzRv",
            "previous": null,
            "results": [
            {
                "resthook": "new-report",
                "data": {
                    "flow": {
                        "name": "Water Survey",
                        "uuid": "13fed2d2-160e-48e5-b52e-6eea3f74f27d"
                    },
                    "contact": {
                        "uuid": "dc2b3709-3261-465f-b39a-fc7312b2ab95",
                        "name": "Ben Haggerty",
                        "urn": "tel:+12065551212"
                    },
                    "channel": {
                        "name": "Twilio +12065552020",
                        "uuid": "f49d3dd6-beef-40ba-b86b-f526c649175c"
                    },
                    "run": {
                        "uuid": "7facea33-9fbc-4bdd-ba63-b2600cd4f69b",
                        "created_on":"2014-06-03T08:20:03.242525+00:00"
                    },
                    "input": {
                        "urn": "tel:+12065551212",
                        "text": "stream",
                        "attachments": []
                    }
                    "path": [
                        {
                            "node_uuid": "40019102-e621-4b88-acd2-1288961dc214",
                            "arrived_on": "2014-06-03T08:21:09.865526+00:00",
                            "exit_uuid": "207d919d-ac4d-451a-9892-3ceca16430ff"
                        },
                        {
                            "node_uuid": "207d919d-ac4d-451a-9892-3ceca16430ff",
                            "arrived_on": "2014-06-03T08:21:09.865526+00:00"
                        }
                    ],
                    "results": {
                        "water_source": {
                            "node_uuid": "40019102-e621-4b88-acd2-1288961dc214",
                            "name": "Water Source",
                            "category": "Stream",
                            "value": "stream",
                            "input": "stream",
                            "created_on": "2017-12-05T16:47:57.875680+00:00"
                        }
                    }
                },
                "created_on": "2017-11-11T13:05:57.457742Z",
            },
            ...
        }
    """

    permission = "api.webhookevent_api"
    model = WebHookEvent
    serializer_class = WebHookEventReadSerializer
    pagination_class = CreatedOnCursorPagination

    def filter_queryset(self, queryset):
        params = self.request.query_params
        queryset = queryset.exclude(resthook=None)

        resthook = params.get("resthook")
        if resthook:  # pragma: needs cover
            queryset = queryset.filter(resthook__slug=resthook)

        return queryset.select_related("resthook")

    @classmethod
    def get_read_explorer(cls):
        return {
            "method": "GET",
            "title": "List Resthook Events",
            "url": reverse("api.v2.resthook_events"),
            "slug": "resthook-event-list",
            "params": [],
        }


class RunsEndpoint(ListAPIMixin, BaseAPIView):
    """
    This endpoint allows you to fetch flow runs. A run represents a single contact's path through a flow and is created
    each time a contact is started in a flow.

    ## Listing Flow Runs

    A `GET` request returns the flow runs for your organization, filtering them as needed. Each
    run has the following attributes:

     * **uuid** - the ID of the run (string), filterable as `uuid`.
     * **flow** - the UUID and name of the flow (object), filterable as `flow` with UUID.
     * **contact** - the UUID and name of the contact (object), filterable as `contact` with UUID.
     * **start** - the UUID of the flow start (object)
     * **responded** - whether the contact responded (boolean), filterable as `responded`.
     * **values** - values generated by rulesets in the flow (array of objects).
     * **created_on** - the datetime when this run was started (datetime).
     * **modified_on** - when this run was last modified (datetime), filterable as `before` and `after`.
     * **exited_on** - the datetime when this run exited or null if it is still active (datetime).
     * **exit_type** - how the run ended (one of "interrupted", "completed", "expired").

    Note that you cannot filter by `flow` and `contact` at the same time.

    Example:

        GET /api/v2/runs.json?flow=f5901b62-ba76-4003-9c62-72fdacc1b7b7

    Response is the list of runs on the flow, most recently modified first:

        {
            "next": "http://example.com/api/v2/runs.json?cursor=cD0yMDE1LTExLTExKzExJTNBM40NjQlMkIwMCUzRv",
            "previous": null,
            "results": [
            {
                "id": 12345678,
                "flow": {"uuid": "f5901b62-ba76-4003-9c62-72fdacc1b7b7", "name": "Favorite Color"},
                "contact": {
                    "uuid": "d33e9ad5-5c35-414c-abd4-e7451c69ff1d",
                    "urn": "tel:+12065551212",
                    "name": "Bob McFlow"
                },
                "responded": true,
                "path": [
                    {"node": "27a86a1b-6cc4-4ae3-b73d-89650966a82f", "time": "2015-11-11T13:05:50.457742Z"},
                    {"node": "fc32aeb0-ac3e-42a8-9ea7-10248fdf52a1", "time": "2015-11-11T13:03:51.635662Z"},
                    {"node": "93a624ad-5440-415e-b49f-17bf42754acb", "time": "2015-11-11T13:03:52.532151Z"},
                    {"node": "4c9cb68d-474f-4b9a-b65e-c2aa593a3466", "time": "2015-11-11T13:05:57.576056Z"}
                ],
                "values": {
                    "color": {
                        "value": "blue",
                        "category": "Blue",
                        "node": "fc32aeb0-ac3e-42a8-9ea7-10248fdf52a1",
                        "time": "2015-11-11T13:03:51.635662Z",
                        "name": "color",
                        "input": "it is blue",
                    },
                    "reason": {
                        "value": "Because it's the color of sky",
                        "category": "All Responses",
                        "node": "4c9cb68d-474f-4b9a-b65e-c2aa593a3466",
                        "time": "2015-11-11T13:05:57.576056Z",
                        "name": "reason",
                        "input" "Because it's the color of sky",
                    }
                },
                "created_on": "2015-11-11T13:05:57.457742Z",
                "modified_on": "2015-11-11T13:05:57.576056Z",
                "exited_on": "2015-11-11T13:05:57.576056Z",
                "exit_type": "completed"
            },
            ...
        }
    """

    permission = "flows.flow_api"
    model = FlowRun
    serializer_class = FlowRunReadSerializer
    pagination_class = ModifiedOnCursorPagination
    exclusive_params = ("contact", "flow")
    throttle_scope = "v2.runs"

    def filter_queryset(self, queryset):
        params = self.request.query_params
        org = self.request.user.get_org()

        # filter by flow (optional)
        flow_uuid = params.get("flow")
        if flow_uuid:
            flow = Flow.objects.filter(org=org, uuid=flow_uuid, is_active=True).first()
            if flow:
                queryset = queryset.filter(flow=flow)
            else:
                queryset = queryset.filter(pk=-1)

        # filter by id (optional)
        run_id = self.get_int_param("id")
        if run_id:
            queryset = queryset.filter(id=run_id)

        # filter by uuid (optional)
        run_uuid = self.get_uuid_param("uuid")
        if run_uuid:
            queryset = queryset.filter(uuid=run_uuid)

        # filter by contact (optional)
        contact_uuid = params.get("contact")
        if contact_uuid:
            contact = Contact.objects.filter(org=org, is_active=True, uuid=contact_uuid).first()
            if contact:
                queryset = queryset.filter(contact=contact)
            else:
                queryset = queryset.filter(pk=-1)

        # limit to responded runs (optional)
        if str_to_bool(params.get("responded")):
            queryset = queryset.filter(responded=True)

        # use prefetch rather than select_related for foreign keys to avoid joins
        queryset = queryset.prefetch_related(
            Prefetch("flow", queryset=Flow.objects.only("uuid", "name", "base_language")),
            Prefetch("contact", queryset=Contact.objects.only("uuid", "name", "language")),
            Prefetch("contact__urns", ContactURN.objects.order_by("-priority", "id")),
            Prefetch("start", queryset=FlowStart.objects.only("uuid")),
        )

        return self.filter_before_after(queryset, "modified_on")

    @classmethod
    def get_read_explorer(cls):
        return {
            "method": "GET",
            "title": "List Flow Runs",
            "url": reverse("api.v2.runs"),
            "slug": "run-list",
            "params": [
                {"name": "id", "required": False, "help": "A run ID to filter by, ex: 123456"},
                {
                    "name": "flow",
                    "required": False,
                    "help": "A flow UUID to filter by, ex: f5901b62-ba76-4003-9c62-72fdacc1b7b7",
                },
                {
                    "name": "contact",
                    "required": False,
                    "help": "A contact UUID to filter by, ex: 09d23a05-47fe-11e4-bfe9-b8f6b119e9ab",
                },
                {"name": "responded", "required": False, "help": "Whether to only return runs with contact responses"},
                {
                    "name": "before",
                    "required": False,
                    "help": "Only return runs modified before this date, ex: 2015-01-28T18:00:00.000",
                },
                {
                    "name": "after",
                    "required": False,
                    "help": "Only return runs modified after this date, ex: 2015-01-28T18:00:00.000",
                },
            ],
            "example": {"query": "after=2016-01-01T00:00:00.000"},
        }


class FlowStartsEndpoint(ListAPIMixin, WriteAPIMixin, BaseAPIView):
    """
    This endpoint allows you to list manual flow starts in your account, and add or start contacts in a flow.

    ## Listing Flow Starts

    By making a `GET` request you can list all the manual flow starts on your organization, in the order of last
    modified. Each flow start has the following attributes:

     * **uuid** - the UUID of this flow start (string)
     * **flow** - the flow which was started (object)
     * **contacts** - the list of contacts that were started in the flow (objects)
     * **groups** - the list of groups that were started in the flow (objects)
     * **restart_participants** - whether the contacts were restarted in this flow (boolean)
     * **exclude_active** - whether the active contacts in other flows were excluded in this flow start (boolean)
     * **status** - the status of this flow start
     * **params** - the dictionary of extra parameters passed to the flow start (object)
     * **created_on** - the datetime when this flow start was created (datetime)
     * **modified_on** - the datetime when this flow start was modified (datetime)

    Example:

        GET /api/v2/flow_starts.json

    Response is the list of flow starts on your organization, most recently modified first:

        {
            "next": "http://example.com/api/v2/flow_starts.json?cursor=cD0yMDE1LTExLTExKzExJTNBM40NjQlMkIwMCUzRv",
            "previous": null,
            "results": [
                {
                    "uuid": "09d23a05-47fe-11e4-bfe9-b8f6b119e9ab",
                    "flow": {"uuid": "f5901b62-ba76-4003-9c62-72fdacc1b7b7", "name": "Thrift Shop"},
                    "groups": [
                         {"uuid": "f5901b62-ba76-4003-9c62-72fdacc1b7b7", "name": "Ryan & Macklemore"}
                    ],
                    "contacts": [
                         {"uuid": "f5901b62-ba76-4003-9c62-fjjajdsi15553", "name": "Wanz"}
                    ],
                    "restart_participants": true,
                    "exclude_active": false,
                    "status": "complete",
                    "params": {
                        "first_name": "Ryan",
                        "last_name": "Lewis"
                    },
                    "created_on": "2013-08-19T19:11:21.082Z",
                    "modified_on": "2013-08-19T19:11:21.082Z"
                },
                ...
            ]
        }

    ## Starting contacts down a flow

    By making a `POST` request with the contacts, groups and URNs you want to start down a flow you can trigger a flow
    start. Note that that contacts will be added to the flow asynchronously, you can use the runs endpoint to monitor the
    runs created by this start.

     * **flow** - the UUID of the flow to start contacts in (required)
     * **groups** - the UUIDs of the groups you want to start in this flow (array of up to 100 strings, optional)
     * **contacts** - the UUIDs of the contacts you want to start in this flow (array of up to 100 strings, optional)
     * **urns** - the URNs you want to start in this flow (array of up to 100 strings, optional)
     * **restart_participants** - whether to restart participants already in this flow (optional, defaults to true)
     * **exclude_active** - whether to exclude contacts currently in other flow (optional, defaults to false)
     * **params** - a dictionary of extra parameters to pass to the flow start (accessible via @trigger.params in your flow)

    Example:

        POST /api/v2/flow_starts.json
        {
            "flow": "f5901b62-ba76-4003-9c62-72fdacc1b7b7",
            "groups": ["f5901b62-ba76-4003-9c62-72fdacc15515"],
            "contacts": ["f5901b62-ba76-4003-9c62-fjjajdsi15553"],
            "urns": ["twitter:sirmixalot", "tel:+12065551212"],
            "params": {"first_name": "Ryan", "last_name": "Lewis"}
        }

    Response is the created flow start:

        {
            "uuid": "09d23a05-47fe-11e4-bfe9-b8f6b119e9ab",
            "flow": {"uuid": "f5901b62-ba76-4003-9c62-72fdacc1b7b7", "name": "Thrift Shop"},
            "groups": [
                 {"uuid": "c24813d2-3bc7-4467-8916-255b6525c6be", "name": "Ryan & Macklemore"}
            ],
            "contacts": [
                 {"uuid": "f1ea776e-c923-4c1a-b3a3-0c466932b2cc", "name": "Wanz"}
            ],
            "restart_participants": true,
            "status": "complete",
            "params": {
                "first_name": "Ryan",
                "last_name": "Lewis"
            },
            "created_on": "2013-08-19T19:11:21.082Z",
            "modified_on": "2013-08-19T19:11:21.082Z"
        }

    """

    permission = "api.flowstart_api"
    model = FlowStart
    serializer_class = FlowStartReadSerializer
    write_serializer_class = FlowStartWriteSerializer
    pagination_class = ModifiedOnCursorPagination
    throttle_scope = "v2.flowstart"

    def get_write_serializer_class(self, instance, data, context):
        query_params = self.request.query_params.dict()
        for key in ["groups", "contacts", "urns"]:
            if key in self.request.query_params:
                query_params[key] = self.request.query_params.getlist(key)
        data = {**data, **query_params}

        return self.write_serializer_class(instance=instance, data=data, context=context)

    def filter_queryset(self, queryset):
        # ignore flow starts created by mailroom
        queryset = queryset.exclude(created_by=None)

        # filter by id (optional and deprecated)
        start_id = self.get_int_param("id")
        if start_id:
            queryset = queryset.filter(id=start_id)

        # filter by UUID (optional)
        uuid = self.get_uuid_param("uuid")
        if uuid:
            queryset = queryset.filter(uuid=uuid)

        # use prefetch rather than select_related for foreign keys to avoid joins
        queryset = queryset.prefetch_related(
            Prefetch("contacts", queryset=Contact.objects.only("uuid", "name").order_by("id")),
            Prefetch("groups", queryset=ContactGroup.user_groups.only("uuid", "name").order_by("id")),
        )

        return self.filter_before_after(queryset, "modified_on")

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["is_zapier"] = "Zapier" in self.request.META.get("HTTP_USER_AGENT", "")
        return context

    def post_save(self, instance):
        # actually start our flow
        instance.async_start()

    @classmethod
    def get_read_explorer(cls):
        return {
            "method": "GET",
            "title": "List Flow Starts",
            "url": reverse("api.v2.flow_starts"),
            "slug": "flow-start-list",
            "params": [
                {"name": "id", "required": False, "help": "Only return the flow start with this id"},
                {"name": "after", "required": False, "help": "Only return flow starts modified after this date"},
                {"name": "before", "required": False, "help": "Only return flow starts modified before this date"},
            ],
            "example": {"query": "after=2016-01-01T00:00:00.000"},
        }

    @classmethod
    def get_write_explorer(cls):
        return dict(
            method="POST",
            title="Start Contacts in a Flow",
            url=reverse("api.v2.flow_starts"),
            slug="flow-start-write",
            fields=[
                dict(name="flow", required=True, help="The UUID of the flow to start"),
                dict(name="groups", required=False, help="The UUIDs of any contact groups you want to start"),
                dict(name="contacts", required=False, help="The UUIDs of any contacts you want to start"),
                dict(name="urns", required=False, help="The URNS of any contacts you want to start"),
                dict(
                    name="restart_participants",
                    required=False,
                    help="Whether to restart any participants already in the flow",
                ),
                dict(name="extra", required=False, help="Any extra parameters to pass to the flow start"),
            ],
            example=dict(body='{"flow":"f5901b62-ba76-4003-9c62-72fdacc1b7b7","urns":["twitter:sirmixalot"]}'),
        )


class TemplatesEndpoint(ListAPIMixin, BaseAPIView):
    """
    This endpoint allows you to fetch the WhatsApp templates that have been synced. Each template contains a
    dictionary of the languages it has been translated to along with the content of the template for that
    language and the status of that translation.

    ## Listing Templates

    A `GET` request returns the templates for your organization.

    Each template has the following attributes:

     * **uuid** - filterable as `uuid`.
     * **name** - the name of the template, filterable as `name`
     * **translations** - a dictionary of the translations of the template with the key being an ISO639-3 code

     Each translation contains the following attributes:

     * **language** - the ISO639-3 code for the language of this translation
     * **content** - the content of the translation
     * **variable_count** - the count of variables in this template
     * **status** - the status of this translation, either `approved`, `pending`, `rejected` or `unsupported_language`

     For filter translations by status, you can use **status** attribute as folow:

     * **By default**, the endpoint bring status `approved`
     * `pending` - Use **P** , like status=P.
     * `rejected` - Use **R**, like status=R.
     * `unsupported_language` - Use **U**, like status=U.

    Example:

        GET /api/v2/templates.json

    Response is the list of templates for your organization:

        {
            "next": "http://example.com/api/v2/templates.json?cursor=cD0yMDE1LTExLTExKzExJTNBM40NjQlMkIwMCUzRv",
            "previous": null,
            "results": [
            {
                "name": "welcome_message",
                "uuid": "f5901b62-ba76-4003-9c62-72fdacc1b7b7",
                "translations": [
                    {
                        "language": "eng",
                        "content": "Hi {{1}}, your appointment is coming up on {{2}}",
                        "variable_count": 2,
                        "status": "active",
                    },
                    {
                        "language": "fra",
                        "content": "Bonjour {{1}}, votre rendez-vous est à venir {{2}}",
                        "variable_count": 2,
                        "status": "pending",
                    }
                ],
                "created_on": "2013-08-19T19:11:21.082Z",
                "modified_on": "2013-08-19T19:11:21.082Z"
            },
            ...
        }
    """

    permission = "templates.template_api"
    model = Template
    serializer_class = TemplateReadSerializer
    pagination_class = ModifiedOnCursorPagination

    def filter_queryset(self, queryset):
        params = self.request.query_params
        org = self.request.user.get_org()

        active_translations = Prefetch(
            "translations", queryset=TemplateTranslation.objects.filter(is_active=True), to_attr="active_translations"
        )

        queryset = org.templates.filter(translations__is_active=True).distinct().prefetch_related(active_translations)

        status = params.get("status", "A")
        queryset = queryset.filter(translations__status=status).distinct()

        uuid = params.get("uuid")
        if uuid:
            queryset = queryset.filter(uuid=uuid)

        name = params.get("name")
        if name:
            queryset = queryset.filter(name=name)

        return self.filter_before_after(queryset, "modified_on")

    @classmethod
    def get_read_explorer(cls):
        return {
            "method": "GET",
            "title": "List Templates",
            "url": reverse("api.v2.templates"),
            "slug": "templates-list",
            "params": [
                {"name": "name", "required": False, "help": "A template name to filter by, ex: MyTemplate"},
                {
                    "name": "uuid",
                    "required": False,
                    "help": "Only return template with this UUID",
                },
                {
                    "name": "status",
                    "required": False,
                    "help": "Only return templates with this status, ex: R",
                },
            ],
            "example": {},
        }


class TicketersEndpoint(ListAPIMixin, BaseAPIView):
    """
    This endpoint allows you to list the active ticketing services on your account.

    ## Listing Ticketers

    A **GET** returns the ticketers for your organization, most recent first.

     * **uuid** - the UUID of the ticketer, filterable as `uuid`.
     * **name** - the name of the ticketer.
     * **type** - the type of the ticketer, e.g. 'mailgun' or 'zendesk'.
     * **created_on** - when this ticketer was created.

    Example:

        GET /api/v2/ticketers.json

    Response:

        {
            "next": null,
            "previous": null,
            "results": [
            {
                "uuid": "9a8b001e-a913-486c-80f4-1356e23f582e",
                "name": "Email (bob@acme.com)",
                "type": "mailgun",
                "created_on": "2013-02-27T09:06:15.456"
            },
            ...
    """

    permission = "tickets.ticketer_api"
    model = Ticketer
    serializer_class = TicketerReadSerializer
    pagination_class = CreatedOnCursorPagination

    def filter_queryset(self, queryset):
        params = self.request.query_params
        org = self.request.user.get_org()

        queryset = queryset.filter(org=org, is_active=True)

        # filter by uuid (optional)
        uuid = params.get("uuid")
        if uuid:
            queryset = queryset.filter(uuid=uuid)

        return self.filter_before_after(queryset, "created_on")

    @classmethod
    def get_read_explorer(cls):
        return {
            "method": "GET",
            "title": "List Ticketers",
            "url": reverse("api.v2.ticketers"),
            "slug": "ticketer-list",
            "params": [
                {
                    "name": "uuid",
                    "required": False,
                    "help": "A ticketer UUID to filter by. ex: 09d23a05-47fe-11e4-bfe9-b8f6b119e9ab",
                },
                {
                    "name": "before",
                    "required": False,
                    "help": "Only return ticketers created before this date, ex: 2015-01-28T18:00:00.000",
                },
                {
                    "name": "after",
                    "required": False,
                    "help": "Only return ticketers created after this date, ex: 2015-01-28T18:00:00.000",
                },
            ],
        }


class ExternalServicesEndpoint(ListAPIMixin, BaseAPIView):
    """
    This endpoint allows you to list the active external services on your account.

    ## Listing External Services

    A **GET** returns the external services for your organization, most recent first.

     * **uuid** - the UUID of the service, filterable as `uuid`.
     * **name** - the name of the service.
     * **type** - the type of the service, e.g. 'omie'.
     * **created_on** - when this service was created.

    Example:

        GET /api/v2/external_services.json

    Response:

        {
            "next": null,
            "previous": null,
            "results": [
            {
                "uuid": "9a8b001e-a913-486c-80f4-1356e23f582e",
                "name": "Bob's Omie Project",
                "type": "omie",
                "created_on": "2023-02-27T09:06:15.456"
            },
            ...
    """

    # permission = "externals.external_services_api"
    model = ExternalService
    serializer_class = ExternalServicesReadSerializer
    pagination_class = CreatedOnCursorPagination

    def filter_queryset(self, queryset):
        params = self.request.query_params
        org = self.request.user.get_org()

        queryset = queryset.filter(org=org, is_active=True)
        # filter by uuid (optional)
        uuid = params.get("uuid")
        if uuid:
            queryset = queryset.filter(uuid=uuid)

        return self.filter_before_after(queryset, "created_on")

    @classmethod
    def get_read_explorer(cls):
        return {
            "method": "GET",
            "title": "List External Services",
            "url": reverse("api.v2.external_services"),
            "slug": "external_services-list",
            "params": [
                {
                    "name": "uuid",
                    "required": False,
                    "help": "An external serice UUID to filter by. ex: 09d23a05-47fe-11e4-bfe9-b8f6b119e9ab",
                },
                {
                    "name": "before",
                    "required": False,
                    "help": "Only return external services created before this date, ex: 2023-01-28T18:00:00.000",
                },
                {
                    "name": "after",
                    "required": False,
                    "help": "Only return external services created after this date, ex: 2023-01-28T18:00:00.000",
                },
            ],
        }


class TicketsEndpoint(ListAPIMixin, WriteAPIMixin, BaseAPIView):
    """
    This endpoint allows you to list the tickets opened on your account.

    ## Listing Tickets

    A **GET** returns the tickets for your organization, most recent first.

     * **uuid** - the UUID of the ticket, filterable as `uuid`.
     * **ticketer** - the UUID and name of the ticketer (object).
     * **contact** - the UUID and name of the contact (object), filterable as `contact` with UUID.
     * **status** - the status of the ticket, e.g. 'open' or 'closed'.
     * **topic** - the topic of the ticket (object).
     * **body** - the body of the ticket (string).
     * **opened_on** - when this ticket was opened (datetime).

    Example:

        GET /api/v2/tickets.json

    Response:

        {
            "next": null,
            "previous": null,
            "results": [
            {
                "uuid": "9a8b001e-a913-486c-80f4-1356e23f582e",
                "ticketer": {"uuid": "9a8b001e-a913-486c-80f4-1356e23f582e", "name": "Email (bob@acme.com)"},
                "contact": {"uuid": "f1ea776e-c923-4c1a-b3a3-0c466932b2cc", "name": "Jim"},
                "status": "open",
                "topic": {"uuid": "040edbfe-be55-48f3-864d-a4a7147c447b", "name": "Support"},
                "body": "Where did I leave my shorts?",
                "opened_on": "2013-02-27T09:06:15.456"
            },
            ...
    """

    permission = "tickets.ticket_api"
    model = Ticket
    serializer_class = TicketReadSerializer
    pagination_class = ModifiedOnCursorPagination

    def filter_queryset(self, queryset):
        params = self.request.query_params
        org = self.request.user.get_org()

        queryset = queryset.filter(org=org)

        # filter by contact (optional)
        contact_uuid = params.get("contact")
        if contact_uuid:
            contact = org.contacts.filter(is_active=True, uuid=contact_uuid).first()
            if contact:
                queryset = queryset.filter(contact=contact)
            else:
                queryset = queryset.filter(id=-1)

        uuid = params.get("uuid") or params.get("ticket")
        if uuid:
            queryset = queryset.filter(uuid=uuid)

        # filter by ticketer type if provided, unpublished support for agents
        ticketer_type = params.get("ticketer_type")
        if ticketer_type:
            queryset = queryset.filter(ticketer__ticketer_type=ticketer_type)

        queryset = queryset.prefetch_related(
            Prefetch("ticketer", queryset=Ticketer.objects.only("uuid", "name")),
            Prefetch("topic", queryset=Topic.objects.only("uuid", "name")),
            Prefetch("contact", queryset=Contact.objects.only("uuid", "name")),
            "assignee",
        )

        return queryset

    @classmethod
    def get_read_explorer(cls):
        return {
            "method": "GET",
            "title": "List Tickets",
            "url": reverse("api.v2.tickets"),
            "slug": "ticket-list",
            "params": [
                {
                    "name": "contact",
                    "required": False,
                    "help": "A contact UUID to filter by, ex: 09d23a05-47fe-11e4-bfe9-b8f6b119e9ab",
                },
            ],
        }


class TicketActionsEndpoint(BulkWriteAPIMixin, BaseAPIView):
    """
    ## Bulk Ticket Updating

    A **POST** can be used to perform an action on a set of tickets in bulk.

    * **tickets** - the ticket UUIDs (array of up to 100 strings)
    * **action** - the action to perform, a string one of:

        * _assign_ - Assign the tickets to the given user
        * _note_ - Add the given note to the tickets
        * _close_ - Close the tickets
        * _reopen_ - Re-open the tickets

    * **assignee** - the email of a user (string, optional)
    * **note** - the note to add to the tickets (string, optional)

    Example:

        POST /api/v2/ticket_actions.json
        {
            "tickets": ["55b6606d-9e89-45d1-a3e2-dc11f19f78df", "bef96b71-865d-480a-a660-33db466a210a"],
            "action": "assign",
            "assignee": "jim@nyaruka.com"
        }

    You will receive an empty response with status code 204 if successful.
    """

    permission = "tickets.ticket_api"
    serializer_class = TicketBulkActionSerializer

    @classmethod
    def get_write_explorer(cls):
        actions = cls.serializer_class.ACTION_CHOICES
        return {
            "method": "POST",
            "title": "Update Multiple Tickets",
            "url": reverse("api.v2.ticket_actions"),
            "slug": "ticket-actions",
            "fields": [
                {"name": "tickets", "required": True, "help": "The UUIDs of the tickets to update"},
                {"name": "action", "required": True, "help": "One of the following strings: " + ", ".join(actions)},
                {"name": "assignee", "required": False, "help": "The email address of a user"},
                {"name": "note", "required": False, "help": "The note text"},
            ],
        }


class TopicsEndpoint(ListAPIMixin, WriteAPIMixin, BaseAPIView):
    """
    This endpoint allows you to list the topics in your workspace.

    ## Listing Topics

    A **GET** returns the tickets for your organization, most recent first.

     * **uuid** - the UUID of the topic (string).
     * **name** - the name of the topic (string).
     * **created_on** - when this topic was created (datetime).

    Example:

        GET /api/v2/topics.json

    Response:

        {
            "next": null,
            "previous": null,
            "results": [
            {
                "uuid": "9a8b001e-a913-486c-80f4-1356e23f582e",
                "name": "Support",
                "created_on": "2013-02-27T09:06:15.456"
            },
            ...
    """

    permission = "tickets.topic_api"
    model = Topic
    serializer_class = TopicReadSerializer
    write_serializer_class = TopicWriteSerializer
    pagination_class = CreatedOnCursorPagination

    @classmethod
    def get_read_explorer(cls):
        return {"method": "GET", "title": "List Topics", "url": reverse("api.v2.topics"), "slug": "topic-list"}

    @classmethod
    def get_write_explorer(cls):
        return {
            "method": "POST",
            "title": "Add or Update Topics",
            "url": reverse("api.v2.topics"),
            "slug": "topic-write",
            "params": [{"name": "uuid", "required": False, "help": "The UUID of the topic to update"}],
            "fields": [{"name": "name", "required": True, "help": "The name of the topic"}],
        }


class UsersEndpoint(ListAPIMixin, BaseAPIView):
    """
    This endpoint allows you to list the user logins in your workspace.

    ## Listing Users

    A **GET** returns the users in your workspace, ordered by newest created first.

     * **email** - the email address of the user (string).
     * **first_name** - the first name of the user (string).
     * **last_name** - the last name of the user (string).
     * **role** - the role of the user (string), filterable as `role` which can be repeated.
     * **created_on** - when this user was created (datetime).

    Example:

        GET /api/v2/users.json

    Response:

        {
            "next": null,
            "previous": null,
            "results": [
            {
                "email": "bob@flow.com",
                "first_name": "Bob",
                "last_name": "McFlow",
                "role": "agent",
                "created_on": "2013-03-02T17:28:12.123456Z"
            },
            ...
    """

    permission = "orgs.org_api"
    model = User
    serializer_class = UserReadSerializer
    pagination_class = DateJoinedCursorPagination

    def derive_queryset(self):
        org = self.request.user.get_org()

        # limit to roles if specified
        roles = self.request.query_params.getlist("role")
        if roles:
            role_by_name = {name: role for role, name in UserReadSerializer.ROLES.items()}
            roles = [role_by_name.get(r) for r in roles if r in role_by_name]
        else:
            roles = []

        return org.get_users(roles=roles).filter(is_active=True)

    def get_serializer_context(self):
        context = super().get_serializer_context()

        # build a map of users to roles so that serializing multiple users only uses on query per role
        org = self.request.user.get_org()
        user_roles = {}
        for role in OrgRole:
            for user in role.get_users(org):
                user_roles[user] = role

        context["user_roles"] = user_roles
        return context

    @classmethod
    def get_read_explorer(cls):
        return {
            "method": "GET",
            "title": "List Users",
            "url": reverse("api.v2.users"),
            "slug": "user-list",
            "params": [],
        }


class WorkspaceEndpoint(BaseAPIView):
    """
    This endpoint allows you to view details about your workspace.

    ## Viewing Current Workspace

    A **GET** returns the details of your workspace. There are no parameters.

    Example:

        GET /api/v2/workspace.json

    Response containing your workspace details:

        {
            "uuid": "6a44ca78-a4c2-4862-a7d3-2932f9b3a7c3",
            "name": "Nyaruka",
            "country": "RW",
            "languages": ["eng", "fra"],
            "primary_language": "eng",
            "timezone": "Africa/Kigali",
            "date_style": "day_first",
            "credits": {"used": 121433, "remaining": 3452},
            "anon": false
        }
    """

    permission = "orgs.org_api"

    def get(self, request, *args, **kwargs):
        org = request.user.get_org()
        serializer = WorkspaceReadSerializer(org)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @classmethod
    def get_read_explorer(cls):
        return {
            "method": "GET",
            "title": "View Workspace",
            "url": reverse("api.v2.workspace"),
            "slug": "workspace-read",
        }


class ProductsEndpoint(ListAPIMixin, BaseAPIView):
    """
    This endpoint allows you to fetch the WhatsApp catalogs that have been synced. Each catalog contains a
    dictionary of the products.

    ## Listing Products

    A `GET` request returns the products for your organization.

    Each catalog has the following attributes:

     * **name** - the name of the catalog
     * **products** - a dictionary of the products of the catalog with the key being an ISO639-3 code

     Each product contains the following attributes:

     * **name** - the name of the product
     * **facebook_product_id** - the product id in facebook


    Example:

        GET /api/v2/products.json

    Response is the list of products for your organization:

        {
            "next": "http://example.com/api/v2/products.json?cursor=cD0yMDE1LTExLTExKzExJTNBM40NjQlMkIwMCUzRv",
            "previous": null,
            "results": [
            {
            "uuid": "8d16f730-bc3f-4a11-9e1f-8c460fc0a692",
            "name": "Catalog Test",
            "products": [
                {
                    "title": "Dog Bowl In Blue",
                    "facebook_product_id": "6498684463556034",
                    "product_retailer_id": "DB_1",
                    "channel": {
                        "uuid": "2e925f75-e88a-4fae-a303-6988e30b49cc",
                        "name": "Whatsapp"
                    }
                },
                {
                    "title": "Dog Bowl In Yellow",
                    "facebook_product_id": "7442068949153493",
                    "product_retailer_id": "DB_2",
                    "channel": {
                        "uuid": "2e925f75-e88a-4fae-a303-6988e30b49cc",
                        "name": "Whatsapp"
                    }
                }
            ],
            "created_on": "2023-08-24T21:05:42.876148Z",
            "modified_on": "2023-08-24T23:29:15.161065Z"
        },
            ...
        }
    """

    permission = "templates.template_api"
    model = Product
    serializer_class = ProductReadSerializer
    pagination_class = CreatedOnCursorPagination

    def get_queryset(self):
        org = self.request.user.get_org()
        catalog = org.catalogs.exclude(is_active=False).first()
        return Product.objects.filter(catalog=catalog)

    def filter_queryset(self, queryset):
        params = self.request.query_params

        name = params.get("name")
        if name:
            queryset = queryset.filter(title__icontains=name)

        retailer_id = params.get("retailer_id")
        if retailer_id:
            queryset = queryset.filter(product_retailer_id=retailer_id)

        return queryset

    @classmethod
    def get_read_explorer(cls):
        return {
            "method": "GET",
            "title": "List Products",
            "url": reverse("api.v2.products"),
            "slug": "products-list",
            "params": [],
            "example": {},
        }


class WhatsappFlowsEndpoint(ListAPIMixin, BaseAPIView):
    """
    This endpoint allows you to fetch the WhatsApp flows that have been synced.

    ## Listing Whatsapp Flows

    A `GET` request returns the whatsapp flows for your organization.

    Each whatsapp flows has the following attributes:

     * **id** - the id of meta flow
     * **name** - the name of the whatsapp flow
     * **assets** - a dictionary with screens and variables list

    Example:

        GET /api/v2/whatsapp_flows.json

    Response is the list of whatsapp flows for your organization:

        {
            "next": "http://example.com/api/v2/whatsapp_flows.json?cursor=cD0yMDE1LTExLTExKzExJTNBM40NjQlMkIwMCUzRv",
            "previous": null,
            "results": [
            {
            "id": "1111111111111111111",
            "name": "Flow Test",
            "assets": {
                "screens": [
                    "WELCOME", "MIDDLE"
                ],
                "variables": [
                    "question1Checkbox", "checkbox_source"
                ]
            ],
        }
    """

    model = WhatsappFlow
    serializer_class = WhatsappFlowReadSerializer
    pagination_class = CreatedOnCursorPagination

    def get_queryset(self):
        org = self.request.user.get_org()
        return WhatsappFlow.objects.filter(org=org, is_active=True)

    def filter_queryset(self, queryset):
        params = self.request.query_params

        name = params.get("name")
        if name:
            queryset = queryset.filter(name__icontains=name)

        facebook_flow_id = params.get("id")
        if facebook_flow_id:
            queryset = queryset.filter(facebook_flow_id=facebook_flow_id)

        return self.filter_before_after(queryset, "created_on")

    @classmethod
    def get_read_explorer(cls):
        return {
            "method": "GET",
            "title": "List Whatsapp Flows",
            "url": reverse("api.v2.whatsapp_flows"),
            "slug": "whatsapp_flows-list",
            "params": [],
            "example": {},
        }


class EventsEndpoint(BaseAPIView):
    permission = "orgs.org_api"

    def get(self, request, *args, **kwargs):
        serializer = EventFilterSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        try:
            org = request.user.get_org()
            validated_data = serializer.validated_data.copy()
            validated_data["project"] = str(org.proj_uuid)

            events = get_events(**validated_data)

            processed_events = []
            for event in events:
                processed_event = {}
                for key, value in event.items():
                    if isinstance(value, str):
                        try:
                            processed_event[key] = json.loads(value)
                        except (json.JSONDecodeError, TypeError):
                            processed_event[key] = value
                    else:
                        processed_event[key] = value
                processed_events.append(processed_event)

            return Response(processed_events)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @classmethod
    def get_read_explorer(cls):
        return {
            "method": "GET",
            "title": "List Datalake Events",
            "url": reverse("api.v2.events"),
            "slug": "events-list",
            "params": [
                {
                    "name": "date_start",
                    "required": True,
                    "help": "The start date for the filter, ex: 2025-06-03T00:00:00Z",
                },
                {
                    "name": "date_end",
                    "required": True,
                    "help": "The end date for the filter, ex: 2025-06-20T23:59:59Z",
                },
                {"name": "key", "required": False, "help": "A key to filter by"},
                {"name": "contact_urn", "required": False, "help": "A contact URN to filter by"},
                {"name": "value_type", "required": False, "help": "A value_type to filter by"},
                {"name": "value", "required": False, "help": "A value to filter by"},
                {"name": "metadata", "required": False, "help": "A metadata to filter by"},
                {"name": "event_name", "required": False, "help": "An event_name to filter by"},
            ],
        }
