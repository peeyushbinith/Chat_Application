from django.urls import path
from .consumers import ChatConsumer, GroupChatConsumer

websocket_urlpatterns = [
    path("ws/chat/<int:user_id>/", ChatConsumer.as_asgi()),
    path('ws/group/<slug:group_slug>/', GroupChatConsumer.as_asgi()),
]