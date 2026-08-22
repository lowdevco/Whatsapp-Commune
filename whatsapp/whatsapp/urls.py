from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.contrib.staticfiles.views import serve as static_serve
from django.views.static import serve as media_serve

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('bulk.urls')),
    
    # Force the desktop app to "hunt" for static files across all your app folders
    re_path(r'^static/(?P<path>.*)$', static_serve, {'insecure': True}),
    
    # Serve user uploads (like attachments) from the media folder
    re_path(r'^media/(?P<path>.*)$', media_serve, {'document_root': settings.MEDIA_ROOT}),
]