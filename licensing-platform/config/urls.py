from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from licensing.urls import api_urlpatterns

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('accounts.urls')),
    path('api/v1/', include(api_urlpatterns)),
    path('', include('licensing.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
