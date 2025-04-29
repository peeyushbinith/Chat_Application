from django.db import models, IntegrityError
from django.contrib.auth.models import User
from django.utils import timezone
from django.utils.text import slugify
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db.models.signals import pre_save


class Message(models.Model):
    sender = models.ForeignKey(User, related_name='sent_messages', on_delete=models.CASCADE)
    receiver = models.ForeignKey(User, related_name='received_messages', on_delete=models.CASCADE)
    content = models.TextField()
    read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['sender', 'receiver']),
            models.Index(fields=['receiver', 'sender']),
            models.Index(fields=['timestamp']),
            models.Index(fields=['read']),
        ]

    def mark_as_read(self):
        if not self.read:
            self.read = True
            self.read_at = timezone.now()
            self.save()

    def __str__(self):
        return f"{self.sender.username} -> {self.receiver.username}: {self.content[:50]}"


class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    profile_picture = models.ImageField(upload_to='profile_pics/', default='default.jpg', null=True, blank=True)
    bio = models.TextField(blank=True)
    phone_number = models.CharField(max_length=15, blank=True, null=True)
    last_seen = models.DateTimeField(auto_now=True)

    def is_online(self):
        """User is online if last_seen is None (actively connected)
        or was seen less than 5 minutes ago"""
        if self.last_seen is None:
            return True
        return (timezone.now() - self.last_seen).total_seconds() < 300  # 5 minute threshold


class Group(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    avatar = models.ImageField(upload_to='group_avatars/', null=True, blank=True)
    slug = models.SlugField(unique=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
            # Ensure slug uniqueness
            while Group.objects.filter(slug=self.slug).exists():
                self.slug = f"{self.slug}-{Group.objects.filter(slug__startswith=self.slug).count()}"
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class GroupMember(models.Model):
    group = models.ForeignKey(Group, related_name='members', on_delete=models.CASCADE)
    user = models.ForeignKey(User, related_name='group_memberships', on_delete=models.CASCADE)
    is_admin = models.BooleanField(default=False)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('group', 'user')


class GroupMessage(models.Model):
    group = models.ForeignKey(Group, related_name='messages', on_delete=models.CASCADE)
    sender = models.ForeignKey(User, on_delete=models.CASCADE)
    content = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['group', 'timestamp']),
            models.Index(fields=['timestamp']),
        ]

    def __str__(self):
        return f"{self.sender.username} in {self.group.name}: {self.content[:50]}"


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        try:
            Profile.objects.get_or_create(user=instance)
        except IntegrityError:
            # Handle rare race condition
            pass


@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    try:
        instance.profile.save()
    except Profile.DoesNotExist:
        # If profile doesn't exist, create it
        Profile.objects.create(user=instance)


@receiver(pre_save, sender=Profile)
def delete_old_profile_picture(sender, instance, **kwargs):
    if instance.pk:  # Only for existing instances
        try:
            old_instance = Profile.objects.get(pk=instance.pk)
            if (old_instance.profile_picture and
                old_instance.profile_picture != instance.profile_picture and
                not old_instance.profile_picture.name.endswith('profile_pics/default.png')):
                old_instance.profile_picture.delete(save=False)
        except Profile.DoesNotExist:
            pass