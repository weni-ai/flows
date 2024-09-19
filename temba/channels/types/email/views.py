from smartmin.views import SmartFormView

from temba.channels.views import ClaimViewMixin


class ClaimView(ClaimViewMixin, SmartFormView):
    class ClaimForm(ClaimViewMixin.Form):
        pass
