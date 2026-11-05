from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("books", views.BookViewSet, basename="api-book")
router.register("entries", views.EntryViewSet, basename="api-entry")

urlpatterns = [
    path("auth/register/", views.register, name="api-register"),
    path("auth/login/", views.login, name="api-login"),
    path("auth/logout/", views.logout, name="api-logout"),
    path("auth/me/", views.me, name="api-me"),
    path("schema/", SpectacularAPIView.as_view(), name="api-schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="api-schema"), name="api-docs"),
    path("", include(router.urls)),
]
