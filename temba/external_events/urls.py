from django.urls import path
from . import views

# Main conversion API URLs
urlpatterns = [
    # Main conversion event endpoint
    path('conversion/', views.ConversionEventView.as_view(), name='conversion_event'),
] 