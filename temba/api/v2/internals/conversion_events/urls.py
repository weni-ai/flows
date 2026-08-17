from django.urls import path

from .views import CtwaReferralSourceListView

urlpatterns = [
    path(
        "ctwa_referral_sources",
        CtwaReferralSourceListView.as_view(),
        name="internal-ctwa-referral-sources",
    ),
]
