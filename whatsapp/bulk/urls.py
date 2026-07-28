from django.urls import path
from . import views
from django.conf import settings
from django.conf.urls.static import static


urlpatterns = [
    path('', views.index, name='index'),
    # path("start-messaging/<int:campaign_id>/", views.start_messaging, name="start_messaging"),
    path('signup/', views.signup_view, name='signup'),  # <-- add views.
    path('login/', views.login_view, name='login'),
    path('settings/', views.settings_view, name='settings_view'),
    path('initiate_qr_scan/<int:account_id>/', views.initiate_qr_scan, name='initiate_qr_scan'),
    path('add-account/', views.add_account, name='add_account'),
    path('check-scan-status/', views.check_scan_status, name='check_scan_status'),
    path('delete-account/<int:account_id>/', views.delete_account, name='delete_account'),
    path('save-campaign/', views.save_campaign, name='save_campaign'),
    path('delete-campaign/<int:campaign_id>/', views.delete_campaign, name='delete_campaign'),
    path('deploy/<int:campaign_id>/', views.deploy_campaign, name='deploy_campaign'),
    path('deploy/latest/', views.deploy_latest, name='deploy_latest'),
    
    path('campaign/start/<int:campaign_id>/', views.start_messaging, name='start_messaging'),
    path('campaign/status/<int:campaign_id>/', views.campaign_status, name='campaign_status'),
    path('campaign/pause/<int:campaign_id>/', views.pause_campaign, name='pause_campaign'),
    path('campaign/resume/<int:campaign_id>/', views.resume_campaign, name='resume_campaign'),
    path('campaign/stop/<int:campaign_id>/', views.stop_campaign, name='stop_campaign'),    
]

# Serve media files during development
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

