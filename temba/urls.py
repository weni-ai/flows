from django.conf import settings
from django.conf.urls import include, url
from django.conf.urls.static import static
from django.contrib.auth.models import AnonymousUser, User
from django.views.generic import RedirectView
from django.views.i18n import JavaScriptCatalog
from django.views.static import serve

from celery.signals import worker_process_init

from temba.api.prometheus.metrics import metrics_view
from temba.channels.views import register, sync
from temba.utils.analytics import init_analytics

from .views import WeniRedirect

urlpatterns = [
    url(r"^", include("temba.airtime.urls")),
    url(r"^", include("temba.api.urls")),
    url(r"^", include("temba.apks.urls")),
    url(r"^", include("temba.archives.urls")),
    url(r"^", include("temba.campaigns.urls")),
    url(r"^", include("temba.channels.urls")),
    url(r"^", include("temba.classifiers.urls")),
    url(r"^", include("temba.contacts.urls")),
    url(r"^", include("temba.dashboard.urls")),
    url(r"^", include("temba.flows.urls")),
    url(r"^", include("temba.globals.urls")),
    url(r"^", include("temba.ivr.urls")),
    url(r"^", include("temba.locations.urls")),
    url(r"^", include("temba.msgs.urls")),
    url(r"^", include("temba.notifications.urls")),
    url(r"^", include("temba.policies.urls")),
    url(r"^", include("temba.public.urls")),
    url(r"^", include("temba.request_logs.urls")),
    url(r"^", include("temba.schedules.urls")),
    url(r"^", include("temba.tickets.urls")),
    url(r"^", include("temba.triggers.urls")),
    url(r"^", include("temba.orgs.urls")),
    url(r"^", include("temba.externals.urls")),
    url(r"^", include("temba.wpp_products.urls")),
    url(r"^", include("temba.wpp_flows.urls")),
    url(r"^", include("temba.templates.urls")),
    url(r"^", include("temba.conversion_events.urls")),
    url(r"^relayers/relayer/sync/(\d+)/$", sync, {}, "sync"),
    url(r"^relayers/relayer/register/$", register, {}, "register"),
    url(r"users/user/forget/", RedirectView.as_view(pattern_name="orgs.user_forget", permanent=True)),
    url(r"^users/", include("smartmin.users.urls")),
    url(r"^imports/", include("smartmin.csv_imports.urls")),
    url(r"^assets/", include("temba.assets.urls")),
    url(r"^jsi18n/$", JavaScriptCatalog.as_view(domain="django"), name="django.views.i18n.javascript_catalog"),
    url(r"^redirect/", WeniRedirect.as_view(), {}, "weni.redirect"),
    url(r"^api/prometheus/metrics$", metrics_view, name="metrics_view"),
]


if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
else:
    urlpatterns.append(url(r"^sitestatic/(?P<path>.*)$", serve, {"document_root": settings.STATIC_ROOT}))

# import any additional urls
for app in settings.APP_URLS:  # pragma: needs cover
    urlpatterns.append(url(r"^", include(app)))

# initialize our analytics (the signal below will initialize each worker)
init_analytics()


@worker_process_init.connect
def configure_workers(sender=None, **kwargs):
    init_analytics()  # pragma: needs cover


def track_user(self):  # pragma: no cover
    """
    Should the current user be tracked
    """

    # nothing to report if they haven't logged in
    if not self.is_authenticated:
        return False

    return True


User.track_user = track_user
AnonymousUser.track_user = track_user


def handler500(request):
    """
    500 error handler which includes ``request`` in the context.

    Templates: `500.html`
    Context: None
    """
    from django.template import loader
    from django.http import HttpResponseServerError

    from .settings import BRANDING, DEFAULT_BRAND
    from .context_processors_weni import use_weni_layout

    weni_layout = use_weni_layout(request)

    t = loader.get_template("500.html")
    return HttpResponseServerError(
        t.render(
            {"request": request, "brand": BRANDING[DEFAULT_BRAND], "use_weni_layout": weni_layout["use_weni_layout"]}
        )
    )
