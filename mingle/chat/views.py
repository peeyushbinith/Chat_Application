from datetime import timezone
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods, require_POST
from django.db import models
from django.utils.text import slugify
import json
from .models import Message, Profile, Group, GroupMember, GroupMessage
from .forms import RegistrationForm, ProfileForm, LoginForm
from django.db.models import Count
from django.contrib.auth import get_user_model
from django.contrib import messages
from django.db import IntegrityError, transaction

User = get_user_model()


# Authentication Views
def register(request):
    if request.method == 'POST':
        form = RegistrationForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    user = form.save()  # This will trigger the profile creation signal
                    login(request, user)
                    return redirect('chat:chat_home')
            except IntegrityError as e:
                # Remove any partially created user
                User.objects.filter(username=form.cleaned_data['username']).delete()
                messages.error(request, 'Registration error. Please try different credentials.')
                return render(request, 'chat/login_signup.html', {
                    'login_form': AuthenticationForm(),
                    'signup_form': form
                })
        else:
            return render(request, 'chat/login_signup.html', {
                'login_form': AuthenticationForm(),
                'signup_form': form
            })

    return render(request, 'chat/login_signup.html', {
        'login_form': AuthenticationForm(),
        'signup_form': RegistrationForm()
    })


def login_view(request):
    if request.method == 'POST':
        form = LoginForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            return redirect('chat:chat_home')
        # If form is invalid, return with errors
        return render(request, 'chat/login_signup.html', {
            'login_form': form,
            'signup_form': RegistrationForm()
        })
    else:
        return render(request, 'chat/login_signup.html', {
            'login_form': LoginForm(request),
            'signup_form': RegistrationForm()
        })


def logout_view(request):
    logout(request)
    return redirect('chat:login')


# Chat Views
@login_required
def chat_home(request):
    return render(request, 'chat/chat_home.html', {
        'current_user': {
            'id': request.user.id,
            'username': request.user.username
        }
    })


@login_required
@require_http_methods(["GET"])
def get_users(request):
    """Get users with existing conversations and unread counts"""
    try:
        # Get distinct user IDs from messages
        sent_users = Message.objects.filter(
            sender=request.user
        ).values_list('receiver', flat=True).distinct()

        received_users = Message.objects.filter(
            receiver=request.user
        ).values_list('sender', flat=True).distinct()

        user_ids = set(sent_users) | set(received_users)

        # Get users with their profiles
        users = User.objects.filter(
            id__in=user_ids
        ).exclude(
            id=request.user.id
        ).select_related('profile')

        # Get unread counts
        unread_counts = Message.objects.filter(
            receiver=request.user,
            read=False,
            sender__in=user_ids
        ).values('sender').annotate(count=Count('id'))

        # Convert to dictionary {user_id: count}
        unread_counts_dict = {
            item['sender']: item['count']
            for item in unread_counts
        }

        # Prepare response data
        data = {
            'users': [],
            'unread_counts': unread_counts_dict
        }

        for user in users:
            # Default values
            is_online = False
            last_seen_str = "Online"
            profile_picture_url = None  # Initialize as None

            # Safely handle profile
            try:
                if hasattr(user, 'profile'):
                    profile = user.profile
                    is_online = profile.is_online()
                    if profile.last_seen:
                        last_seen_str = profile.last_seen.strftime("%Y-%m-%d %H:%M")

                    # Only set URL if profile_picture exists and has valid URL
                    if profile.profile_picture:
                        try:
                            if profile.profile_picture.url:  # Check if URL exists
                                profile_picture_url = request.build_absolute_uri(profile.profile_picture.url)
                                # Additional validation for empty URLs
                                if not profile_picture_url.strip():
                                    profile_picture_url = None
                        except:
                            profile_picture_url = None  # Fallback to None if any error occurs
            except Exception as e:
                print(f"Error processing profile for user {user.id}: {str(e)}")
                profile_picture_url = None  # Explicitly set to None on error

            user_data = {
                'id': user.id,
                'username': user.username,
                'is_online': is_online,
                'last_seen': last_seen_str,
                'profile_picture': profile_picture_url  # Will be None if no valid picture
            }
            data['users'].append(user_data)

        return JsonResponse(data)

    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error in get_users: {str(e)}", exc_info=True)
        return JsonResponse(
            {'error': 'Internal server error', 'details': str(e)},
            status=500
        )

@login_required
@require_http_methods(["GET"])
def get_messages(request, user_id):
    """Get messages between current user and another user"""
    try:
        other_user = get_object_or_404(User, id=user_id)
        messages = Message.objects.filter(
            models.Q(sender=request.user, receiver=other_user) |
            models.Q(sender=other_user, receiver=request.user)
        ).order_by('timestamp')

        data = [{
            'sender': msg.sender.username,
            'sender_id': msg.sender.id,
            'receiver_id': msg.receiver.id,
            'content': msg.content,
            'timestamp': msg.timestamp.isoformat()
        } for msg in messages]

        return JsonResponse({'messages': data})

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


# Group Chat Views
@login_required
@require_http_methods(["GET"])
def get_groups(request):
    """Get all groups the user belongs to"""
    try:
        groups = Group.objects.filter(members__user=request.user).annotate(
            member_count=models.Count('members__user', distinct=True),
            last_message=models.Subquery(
                GroupMessage.objects.filter(
                    group=models.OuterRef('pk')
                ).order_by('-timestamp').values('content')[:1]
            ),
            last_message_time=models.Subquery(
                GroupMessage.objects.filter(
                    group=models.OuterRef('pk')
                ).order_by('-timestamp').values('timestamp')[:1]
            ),
            last_message_sender=models.Subquery(
                GroupMessage.objects.filter(
                    group=models.OuterRef('pk')
                ).order_by('-timestamp').values('sender__username')[:1]
            )
        )

        data = [{
            'id': g.id,
            'name': g.name,
            'slug': g.slug,
            'member_count': g.member_count,
            'last_message': {
                'content': g.last_message,
                'sender': g.last_message_sender,
                'timestamp': g.last_message_time.strftime("%Y-%m-%d %H:%M") if g.last_message_time else None
            }
        } for g in groups]

        return JsonResponse({'groups': data})

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_http_methods(["GET"])
def get_group_messages(request, group_slug):
    """Get messages for a specific group"""
    try:
        group = get_object_or_404(Group, slug=group_slug)
        if not GroupMember.objects.filter(group=group, user=request.user).exists():
            return JsonResponse({'error': 'Not a group member'}, status=403)

        messages = GroupMessage.objects.filter(group=group) \
            .select_related('sender', 'group')\
            .order_by('timestamp')

        data = [{
            'sender': msg.sender.username,
            'sender_id': msg.sender.id,
            'group_slug': group.slug,
            'group_id': group.id,
            'content': msg.content,
            'timestamp': msg.timestamp.isoformat()
        } for msg in messages]

        return JsonResponse({'messages': data})

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_http_methods(["POST"])
@transaction.atomic
def create_group(request):
    """Create a new group with transaction safety"""
    try:
        data = json.loads(request.body)

        # Validate required fields
        if not data.get('name'):
            return JsonResponse({'error': 'Group name is required'}, status=400)

        # Create slug from name
        slug = slugify(data['name'])
        if not slug:
            return JsonResponse({'error': 'Invalid group name'}, status=400)

        # Ensure slug is unique
        counter = 1
        original_slug = slug
        while Group.objects.filter(slug=slug).exists():
            slug = f"{original_slug}-{counter}"
            counter += 1

        # Create group
        group = Group.objects.create(
            name=data['name'],
            description=data.get('description', ''),
            created_by=request.user,
            slug=slug
        )

        # Add creator as admin member
        GroupMember.objects.create(
            group=group,
            user=request.user,
            is_admin=True
        )

        # Add other members if provided
        if 'members' in data and isinstance(data['members'], list):
            # Remove duplicates and exclude creator
            member_ids = list(set(data['members']))
            if str(request.user.id) in member_ids:
                member_ids.remove(str(request.user.id))

            # Add members in bulk for efficiency
            GroupMember.objects.bulk_create([
                GroupMember(group=group, user_id=user_id)
                for user_id in member_ids
                if User.objects.filter(id=user_id).exists()
            ])

        return JsonResponse({
            'status': 'success',
            'group': {
                'id': group.id,
                'name': group.name,
                'slug': group.slug
            }
        })

    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON data'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


# Utility Views
@login_required
def search_users(request):
    """Search users by username"""
    query = request.GET.get("query", "").strip()
    users = User.objects.filter(
        username__icontains=query
    ).exclude(
        id=request.user.id
    ).select_related('profile')

    data = [{
        'id': u.id,
        'username': u.username,
        'is_online': u.profile.is_online(),
        'last_seen': u.profile.last_seen.strftime("%Y-%m-%d %H:%M") if u.profile.last_seen else "Online"
    } for u in users]

    return JsonResponse({'users': data})


@login_required
def edit_profile(request):
    try:
        profile = request.user.profile
    except Profile.DoesNotExist:
        profile = Profile.objects.create(user=request.user)

    if request.method == 'POST':
        form = ProfileForm(request.POST, request.FILES, instance=profile)
        if form.is_valid():
            # First handle non-file fields
            new_username = form.cleaned_data['username']
            if new_username != request.user.username:
                if User.objects.filter(username=new_username).exists():
                    messages.error(request, 'Username already exists')
                    return render(request, 'chat/edit_profile.html', {'form': form})

            # Handle profile picture separately with file content caching
            if 'profile_picture' in request.FILES:
                try:
                    # Read the file content into memory first
                    uploaded_file = request.FILES['profile_picture']
                    file_content = uploaded_file.read()

                    # Delete old image if it exists (except default)
                    if (profile.profile_picture and
                            not profile.profile_picture.name.endswith('profile_pics/default.png')):
                        profile.profile_picture.delete(save=False)

                    # Create a ContentFile from the cached content
                    from django.core.files.base import ContentFile
                    profile.profile_picture.save(
                        uploaded_file.name,
                        ContentFile(file_content),
                        save=False
                    )
                except Exception as e:
                    messages.error(request, f"Error processing image: {str(e)}")
                    return redirect('chat:edit_profile')

            # Save all changes
            profile.save()
            user = profile.user
            user.username = form.cleaned_data['username']
            user.email = form.cleaned_data['email']
            user.save()

            return redirect('chat:chat_home')
    else:
        form = ProfileForm(instance=profile)

    return render(request, 'chat/edit_profile.html', {'form': form, 'profile': profile})


@login_required
@require_http_methods(["GET"])
def get_non_members(request, group_slug):
    """Get users not in group"""
    try:
        group = get_object_or_404(Group, slug=group_slug)
        current_members = group.members.values_list('user_id', flat=True)

        users = User.objects.exclude(id__in=current_members) \
            .exclude(id=request.user.id) \
            .select_related('profile')

        data = [{
            'id': u.id,
            'username': u.username
        } for u in users]

        return JsonResponse({'users': data})

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


@login_required
@require_http_methods(["POST"])
@transaction.atomic
def add_members(request, group_slug):
    """Add members to existing group"""
    try:
        data = json.loads(request.body)
        group = get_object_or_404(Group, slug=group_slug)

        # Verify request.user is group admin
        if not group.members.filter(user=request.user, is_admin=True).exists():
            return JsonResponse({'error': 'Only admins can add members'}, status=403)

        # Add new members
        if 'members' in data and isinstance(data['members'], list):
            GroupMember.objects.bulk_create([
                GroupMember(group=group, user_id=user_id)
                for user_id in data['members']
                if User.objects.filter(id=user_id).exists()
            ])

        return JsonResponse({'status': 'success'})

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


@login_required
@require_http_methods(["GET"])
def group_details(request, group_slug):
    """Get group details including members"""
    try:
        group = get_object_or_404(Group, slug=group_slug)
        is_admin = GroupMember.objects.filter(
            group=group,
            user=request.user,
            is_admin=True
        ).exists()

        if not is_admin:
            return JsonResponse({'error': 'Only admins can view details'}, status=403)

        members = GroupMember.objects.filter(group=group).select_related('user')

        data = {
            'name': group.name,
            'description': group.description,
            'members': [{
                'id': m.user.id,
                'username': m.user.username,
                'is_admin': m.is_admin,
                'can_remove': m.user != request.user  # Can't remove yourself
            } for m in members]
        }

        return JsonResponse(data)

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


@login_required
@require_http_methods(["POST"])
@transaction.atomic
def remove_member(request, group_slug):
    """Remove a member from group"""
    try:
        data = json.loads(request.body)
        group = get_object_or_404(Group, slug=group_slug)

        # Verify request.user is group admin
        if not GroupMember.objects.filter(
                group=group,
                user=request.user,
                is_admin=True
        ).exists():
            return JsonResponse({'error': 'Only admins can remove members'}, status=403)

        user_id = data.get('user_id')
        if not user_id:
            return JsonResponse({'error': 'User ID required'}, status=400)

        # Can't remove yourself
        if int(user_id) == request.user.id:
            return JsonResponse({'error': 'Cannot remove yourself'}, status=400)

        GroupMember.objects.filter(
            group=group,
            user_id=user_id
        ).delete()

        return JsonResponse({'status': 'success'})

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


@login_required
@require_http_methods(["POST"])
@transaction.atomic
def update_group(request, group_slug):
    """Update existing group information"""
    try:
        group = get_object_or_404(Group, slug=group_slug)

        # Verify request.user is group admin
        if not GroupMember.objects.filter(
                group=group,
                user=request.user,
                is_admin=True
        ).exists():
            return JsonResponse({'error': 'Only admins can edit group'}, status=403)

        data = json.loads(request.body)
        new_name = data.get('name')
        new_description = data.get('description')

        if new_name and new_name != group.name:
            group.name = new_name
            # Generate new slug while preserving the group's ID
            new_slug = slugify(new_name)
            if new_slug != group.slug:
                base_slug = new_slug
                counter = 1
                while Group.objects.filter(slug=new_slug).exclude(id=group.id).exists():
                    new_slug = f"{base_slug}-{counter}"
                    counter += 1
                group.slug = new_slug

        if new_description:
            group.description = new_description

        group.save()

        return JsonResponse({
            'status': 'success',
            'name': group.name,
            'slug': group.slug,
            'old_slug': group_slug
        })

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


@login_required
@require_http_methods(["POST"])
@transaction.atomic
def delete_group(request, group_slug):
    """Delete an existing group"""
    try:
        group = get_object_or_404(Group, slug=group_slug)

        # Verify request.user is group admin
        if not GroupMember.objects.filter(
                group=group,
                user=request.user,
                is_admin=True
        ).exists():
            return JsonResponse({'error': 'Only admins can delete group'}, status=403)

        group.delete()
        return JsonResponse({'status': 'success'})

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


# views.py
@login_required
def mark_messages_read(request, user_id):
    print(f"Marking messages as read from {user_id}")  # Debug log
    updated = Message.objects.filter(
        sender_id=user_id,
        receiver=request.user,
        read=False
    ).update(read=True)
    print(f"Updated {updated} messages")  # Debug log
    return JsonResponse({'status': 'success'})

@login_required
def get_unread_count(request, user_id):
    """Returns unread message count for specific user"""
    try:
        count = Message.objects.filter(
            sender_id=user_id,
            receiver=request.user,
            read=False
        ).count()
        return JsonResponse({'count': count})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


@login_required
@require_POST
def delete_account(request):
    password = request.POST.get('password')

    if not request.user.check_password(password):
        messages.error(request, "Incorrect password")
        return redirect('chat:edit_profile')

    try:
        # Delete user and related data
        request.user.delete()
        logout(request)
        messages.success(request, "Your account has been permanently deleted")
        return redirect('chat:login')  # Make sure this matches your login URL name
    except Exception as e:
        messages.error(request, f"Error deleting account: {str(e)}")
        return redirect('chat:edit_profile')