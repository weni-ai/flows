import logging
import time

from django.http import HttpResponseRedirect
from django.urls import resolve
from django.utils.translation import ugettext_lazy as _

from temba.orgs.context_processors import user_group_perms_processor

logger = logging.getLogger(__name__)


class FormaxMixin:
    def derive_formax_sections(self, formax, context):  # pragma: needs cover
        pass

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)

        formax = Formax(self.request)
        self.derive_formax_sections(formax, context)

        if len(formax.sections) > 0:
            context["formax"] = formax
        return context


class Formax:
    def __init__(self, request):
        self.sections = []
        self.request = request
        context = user_group_perms_processor(self.request)
        self.org = context["user_org"]

    def add_section(
        self, name, url, icon, action="formax", button=_("Save"), nobutton=False, dependents=None, wide=False
    ):
        resolver = resolve(url)
        self.request.META["HTTP_X_FORMAX"] = 1
        self.request.META["HTTP_X_PJAX"] = 1
        self.request.META["HTTP_X_FORMAX_ACTION"] = action

        start = time.time()

        open = self.request.GET.get("open", None)
        if open == name:  # pragma: needs cover
            action = "open"

        response = resolver.func(self.request, *resolver.args, **resolver.kwargs)

        # redirects don't do us any good
        if not isinstance(response, HttpResponseRedirect):
            self.sections.append(
                dict(
                    name=name,
                    url=url,
                    response=response.rendered_content,
                    icon=icon,
                    action=action,
                    button=button,
                    nobutton=nobutton,
                    dependents=dependents,
                    wide=wide,
                )
            )

        logger.debug(f"{url} {response.status_code} {int((time.time() - start)*1000)}ms")
