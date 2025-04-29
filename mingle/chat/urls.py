from django.urls import path
from . import views
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth import views as auth_views
from .views import delete_account
from .views import get_messages

app_name = 'chat'

urlpatterns = [
    path('', views.chat_home, name='chat_home'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('signup/', views.register, name='signup'),
    path('edit_profile/', views.edit_profile, name='edit_profile'),
    path('search/', views.search_users, name='search_users'),
    path('get_users/', views.get_users, name='get_users'),
    path('get_messages/<int:user_id>/', get_messages, name='get_messages'),
    path('create-group/', views.create_group, name='create_group'),
    path('get-groups/', views.get_groups, name='get_groups'),
    path('get_non_members/<slug:group_slug>/', views.get_non_members, name='get_non_members'),
    path('add_members/<slug:group_slug>/', views.add_members, name='add_members'),
    path('group_details/<slug:group_slug>/', views.group_details, name='group_details'),
    path('update_group/<slug:group_slug>/', views.update_group, name='update_group'),
    path('remove_member/<slug:group_slug>/', views.remove_member, name='remove_member'),
    path('delete_group/<slug:group_slug>/', views.delete_group, name='delete_group'),
    path('get_group_messages/<slug:group_slug>/', views.get_group_messages, name='get_group_messages'),
    path('password-reset/', auth_views.PasswordResetView.as_view(template_name='registration/password_reset.html'), name='password_reset'),
    path('password-reset/done/', auth_views.PasswordResetDoneView.as_view(template_name='registration/password_reset_done.html'), name='password_reset_done'),
    path('reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(template_name='registration/password_reset_confirm.html'), name='password_reset_confirm'),
    path('reset/done/', auth_views.PasswordResetCompleteView.as_view(template_name='registration/password_reset_complete.html'), name='password_reset_complete'),
    path('mark_messages_read/<int:user_id>/', views.mark_messages_read, name='mark_messages_read'),
    path('chat/get_unread_count/<int:user_id>/', views.get_unread_count, name='get_unread_count'),
    path('delete-account/', delete_account, name='delete_account'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
