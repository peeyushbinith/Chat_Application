# Generated by Django 5.1.5 on 2025-04-23 11:13

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0009_message_read_message_read_at'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddIndex(
            model_name='message',
            index=models.Index(fields=['read'], name='chat_messag_read_8afd86_idx'),
        ),
    ]
