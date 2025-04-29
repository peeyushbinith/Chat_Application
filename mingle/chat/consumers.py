import json
from datetime import timezone

from channels.generic.websocket import AsyncWebsocketConsumer
from django.contrib.auth import get_user_model
from asgiref.sync import sync_to_async
from django.utils.timezone import now
from .models import Message, Group, GroupMember, GroupMessage, Profile
from django.utils import timezone
import pytz

User = get_user_model()


class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        try:
            self.user = self.scope["user"]
            if not self.user.is_authenticated:
                await self.close(code=4001)
                return

            print(f"Connection attempt by {self.user.username}")

            self.other_user_id = self.scope['url_route']['kwargs']['user_id']
            self.other_user = await sync_to_async(User.objects.get)(id=self.other_user_id)

            user_ids = sorted([self.user.id, self.other_user.id])
            self.room_group_name = f"chat_{user_ids[0]}_{user_ids[1]}"
            print(f"Creating room: {self.room_group_name}")

            await self.channel_layer.group_add(
                self.room_group_name,
                self.channel_name
            )

            await self.accept()  # Connection accepted without sending a message
            print(f"WebSocket connection established for {self.user.username}")

            await self.set_last_seen(online=True)

        except User.DoesNotExist:
            print(f"User {self.other_user_id} not found")
            await self.close(code=4004)
        except Exception as e:
            print(f"Connection error: {str(e)}")
            await self.close(code=4000)

    async def disconnect(self, close_code):
        try:
            print(f"Disconnecting {self.user.username}, code: {close_code}")
            await self.set_last_seen(online=False)

            if hasattr(self, 'room_group_name'):
                await self.channel_layer.group_discard(
                    self.room_group_name,
                    self.channel_name
                )
        except Exception as e:
            print(f"Disconnection error: {str(e)}")

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)

            # Handle read receipts
            if data.get('type') == 'read_receipt':
                await self.mark_messages_as_read(self.user, self.other_user)
                return

            message = data.get("content", "").strip()
            print(f"Received message from {self.user.username}: {message}")

            if not message:
                return

            if len(message) > 1000:
                return

            if self.user.is_authenticated:
                saved_message = await self.save_message(
                    sender=self.user,
                    receiver=self.other_user,
                    content=message
                )

                # If this is a read receipt
                if data.get('type') == 'read_receipt':
                    await self.mark_messages_as_read(self.user, self.other_user)
                    return

            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "chat_message",
                    "message": message,
                    "sender": self.user.username,
                    "sender_id": self.user.id,
                    "receiver_id": self.other_user.id,
                    "timestamp": saved_message.timestamp.isoformat(),
                    "read": saved_message.read
                }
            )

        except json.JSONDecodeError:
            print("Invalid JSON received")
        except Exception as e:
            print(f"Error in receive: {str(e)}")

    async def chat_message(self, event):
        try:
            # Only send if it's a proper chat message
            if "message" in event and "sender" in event:
                await self.send(text_data=json.dumps({
                    "message": event["message"],
                    "sender": event["sender"],
                    "sender_id": event["sender_id"],
                    "receiver_id": event["receiver_id"],
                    "timestamp": event["timestamp"]
                }))
        except Exception as e:
            print(f"Error sending message: {str(e)}")

    @sync_to_async
    def save_message(self, sender, receiver, content):
        ist = pytz.timezone('Asia/Kolkata')
        now = timezone.now().astimezone(ist)

        return Message.objects.create(
            sender=sender,
            receiver=receiver,
            content=content,
            timestamp=now
        )

    @sync_to_async
    def set_last_seen(self, online):
        profile, created = Profile.objects.get_or_create(user=self.user)
        profile.last_seen = now() if not online else None
        profile.save()

    @sync_to_async
    def mark_messages_as_read(self, sender, receiver):
        """Mark all messages from this sender as read"""
        Message.objects.filter(
            sender=sender,
            receiver=receiver,
            read=False
        ).update(read=True, read_at=now)



class GroupChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        try:
            self.user = self.scope["user"]
            if not self.user.is_authenticated:
                await self.close(code=4001)
                return

            print(f"Group connection attempt by {self.user.username}")

            self.group_slug = self.scope['url_route']['kwargs']['group_slug']
            self.group = await sync_to_async(Group.objects.get)(slug=self.group_slug)

            is_member = await sync_to_async(GroupMember.objects.filter(
                group=self.group,
                user=self.user
            ).exists)()

            if not is_member:
                print(f"User {self.user.username} not in group {self.group_slug}")
                await self.close(code=4003)
                return

            self.room_group_name = f'group_{self.group_slug}'
            print(f"Creating group room: {self.room_group_name}")

            await self.channel_layer.group_add(
                self.room_group_name,
                self.channel_name
            )

            await self.accept()  # No automatic message sent
            print(f"Group WebSocket connection established for {self.user.username}")

        except Group.DoesNotExist:
            print(f"Group {self.group_slug} not found")
            await self.close(code=4004)
        except Exception as e:
            print(f"Group connection error: {str(e)}")
            await self.close(code=4000)

    async def disconnect(self, close_code):
        try:
            print(f"Disconnecting {self.user.username} from group, code: {close_code}")
            if hasattr(self, 'room_group_name'):
                await self.channel_layer.group_discard(
                    self.room_group_name,
                    self.channel_name
                )
        except Exception as e:
            print(f"Group disconnection error: {str(e)}")

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
            message = data.get("content", "").strip()

            if not message or len(message) > 1000:
                return

            # Save message to database
            saved_message = await self.save_group_message(
                group=self.group,
                sender=self.user,
                content=message
            )

            # Prepare the message data for broadcasting
            message_data = {
                "type": "group_message",
                "message": message,
                "content": message,  # Send both for compatibility
                "sender": self.user.username,
                "sender_id": self.user.id,
                "group_slug": self.group_slug,
                "timestamp": saved_message.timestamp.isoformat(),
                # Remove read status since GroupMessage doesn't track it
            }

            await self.channel_layer.group_send(
                self.room_group_name,
                message_data
            )

        except Exception as e:
            print(f"Error in group receive: {str(e)}")

    async def group_message(self, event):
        try:
            await self.send(text_data=json.dumps({
                "message": event["message"],
                "content": event["message"],  # For consistency
                "sender": event["sender"],
                "sender_id": event["sender_id"],
                "group_slug": event["group_slug"],
                "timestamp": event["timestamp"]
            }))
        except Exception as e:
            print(f"Error sending group message: {str(e)}")

    @sync_to_async
    def save_group_message(self, group, sender, content):
        ist = pytz.timezone('Asia/Kolkata')
        now = timezone.now().astimezone(ist)

        return GroupMessage.objects.create(
            group=group,
            sender=sender,
            content=content,
            timestamp=now
        )

