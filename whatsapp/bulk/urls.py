from django.urls import path
from . import views
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth.views import LogoutView

urlpatterns = [
    path('', views.index, name='index'),
    # path("start-messaging/<int:campaign_id>/", views.start_messaging, name="start_messaging"),
    path('signup/', views.signup_view, name='signup'),  # <-- add views.
    path('login/', views.login_view, name='login'),
    path('logout/', LogoutView.as_view(next_page='/login/'), name='logout'),
    path('settings/', views.settings_view, name='settings_view'),
    path('history/', views.campaign_history, name='campaign_history'),
    path('initiate_qr_scan/<int:account_id>/', views.initiate_qr_scan, name='initiate_qr_scan'),
    path('add-account/', views.add_account, name='add_account'),
    path('check-scan-status/', views.check_scan_status, name='check_scan_status'),
    path('delete-account/<int:account_id>/', views.delete_account, name='delete_account'),
    path('save-campaign/', views.save_campaign, name='save_campaign'),
    path('delete-campaign/<int:campaign_id>/', views.delete_campaign, name='delete_campaign'),
    path('campaign/view/<int:campaign_id>/', views.view_campaign, name='view_campaign'),
    path('deploy/<int:campaign_id>/', views.deploy_campaign, name='deploy_campaign'),
    path('deploy/latest/', views.deploy_latest, name='deploy_latest'),
    path('campaign/<int:campaign_id>/download-errors/', views.download_campaign_report, name='download_campaign_report'),
    path('campaign/relaunch/<int:campaign_id>/', views.relaunch_campaign, name='relaunch_campaign'),
    
    path('campaign/start/<int:campaign_id>/', views.start_messaging, name='start_messaging'),
    path('campaign/status/<int:campaign_id>/', views.campaign_status, name='campaign_status'),
    path('campaign/pause/<int:campaign_id>/', views.pause_campaign, name='pause_campaign'),
    path('campaign/resume/<int:campaign_id>/', views.resume_campaign, name='resume_campaign'),
    path('campaign/stop/<int:campaign_id>/', views.stop_campaign, name='stop_campaign'),    
    
    # Friendly Numbers API
    path('api/friendly-numbers/', views.get_friendly_numbers, name='get_friendly_numbers'),
    path('api/friendly-numbers/save/', views.save_friendly_numbers, name='save_friendly_numbers'),
    path('api/friendly-numbers/toggle/<int:number_id>/', views.toggle_friendly_number, name='toggle_friendly_number'),
    path('api/friendly-numbers/delete/<int:number_id>/', views.delete_friendly_number, name='delete_friendly_number'),
]

# Serve media files during development
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

