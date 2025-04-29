// DOM Elements
const privateChatsList = document.getElementById('privateChats');
const groupChatsList = document.getElementById('groupChats');
const chatBox = document.getElementById('chatBox');
const messageInput = document.getElementById('messageInput');
const sendMessageBtn = document.getElementById('sendMessageBtn');
const searchInput = document.getElementById('searchInput');
const activeChatTitle = document.getElementById('activeChatTitle');
const activeChatStatus = document.getElementById('activeChatStatus');
const newGroupBtn = document.getElementById('newGroupBtn');
const groupModal = document.getElementById('groupModal');
const closeModal = document.querySelector('.close-modal');
const groupForm = document.getElementById('groupForm');
const memberSelection = document.getElementById('memberSelection');

// State variables
let currentUser = null;
let selectedChat = null;
let chatSocket = null;
let activeTab = 'private';
let currentModalView = 'details';
let unreadCounts = {
    private: {},
    groups: {}
};

// Initialize chat
document.addEventListener('DOMContentLoaded', () => {
    const userMeta = document.querySelector('meta[name="current-user"]');
    if (!userMeta) {
        console.error('Current user meta tag missing!');
        return;
    }
    console.log('Current user:', userMeta.content, userMeta.getAttribute('data-user-id'));

    currentUser = {
        id: userMeta.getAttribute('data-user-id'),
        username: userMeta.content
    };

    // Load initial data
    loadPrivateChats();
    loadGroups();

    // Event listeners
    document.querySelectorAll('.chat-tabs button').forEach(button => {
        button.addEventListener('click', switchTab);
    });

    searchInput.addEventListener('input', handleSearch);
    messageInput.addEventListener('keypress', handleKeyPress);
    sendMessageBtn.addEventListener('click', sendMessage);
    newGroupBtn.addEventListener('click', openGroupModal);
    closeModal.addEventListener('click', closeGroupModal);
    groupForm.addEventListener('submit', createGroup);

    // Click outside modal to close
    window.addEventListener('click', (e) => {
        if (e.target === groupModal) {
            closeGroupModal();
        }
    });
});

// Load private chats
async function loadPrivateChats() {
    try {
        console.log('Fetching users...');
        const response = await fetch('/chat/get_users/');

        if (!response.ok) {
            throw new Error('HTTP error! status: ${response.status}');
        }

        const data = await response.json();
        console.log('Users data:', data);

        if (!data.users) {
            throw new Error('Invalid response format - missing users array');
        }

        // Initialize unread counts from server if available
        if (data.unread_counts) {
            unreadCounts.private = data.unread_counts;
        }

        privateChatsList.innerHTML = '';

        if (data.users.length === 0) {
            privateChatsList.innerHTML = `
                <div class="empty-state">
                    <i class="fas fa-comment-alt"></i>
                    <p>No private chats yet</p>
                </div>
            `;
            return;
        }

        data.users.forEach(user => {
            const chatItem = document.createElement('div');
            chatItem.className = 'chat-item';
            chatItem.dataset.userId = user.id;

            // Get unread count for this user (default to 0 if not found)
            const unreadCount = unreadCounts.private[user.id] || 0;

            // Create avatar HTML
            const avatarHTML = (user.profile_picture && user.profile_picture.trim() !== "")
                ? `<img src="${user.profile_picture}" class="avatar-image">`
                : '<i class="fas fa-user avatar-icon"></i>';


            chatItem.innerHTML = `
                <div class="avatar">
                    ${avatarHTML}
                    ${user.is_online ? '<span class="online-dot"></span>' : ''}
                </div>
                <div class="chat-info">
                    <h4>${user.username}</h4>
                </div>
                <div class="unread-badge">${unreadCount > 0 ? unreadCount : ''}</div>
            `;

            // Only show badge if count > 0
            const badge = chatItem.querySelector('.unread-badge');
            badge.style.display = unreadCount > 0 ? 'flex' : 'none';

            chatItem.addEventListener('click', () => selectPrivateChat(user.id, user.username, user.is_online, user.profile_picture));
            privateChatsList.appendChild(chatItem);
        });
    } catch (error) {
        console.error('Error loading private chats:', error);
    }
}

// Load groups
async function loadGroups() {
    try {
        const response = await fetch('/chat/get-groups/');
        const data = await response.json();

        groupChatsList.innerHTML = '';

        if (data.groups.length === 0) {
            groupChatsList.innerHTML = `
                <div class="empty-state">
                    <i class="fas fa-users"></i>
                    <p>No group chats yet</p>
                </div>
            `;
            return;
        }

        data.groups.forEach(group => {
            const groupItem = document.createElement('div');
            groupItem.className = 'chat-item';
            groupItem.dataset.groupSlug = group.slug;
            groupItem.innerHTML = `
                <div class="avatar group-avatar">
                    <i class="fas fa-users"></i>
                </div>
                <div class="chat-info">
                    <h4>${group.name}</h4>
                </div>
            `;
            groupItem.addEventListener('click', () => selectGroupChat(group.slug, group.name));
            groupChatsList.appendChild(groupItem);
        });
    } catch (error) {
        console.error('Error loading groups:', error);
    }
}

// Select private chat
async function selectPrivateChat(userId, username, isOnline) {
    // 1. Optimistic UI update
    unreadCounts.private[userId] = 0;
    updateChatItemBadge(userId, 0);
    localStorage.setItem(`unread_${userId}`, '0');

    // 2. Server update (with retry)
    let retries = 3;
    while (retries > 0) {
        if (await markMessagesAsRead(userId)) break;
        retries--;
        await new Promise(resolve => setTimeout(resolve, 1000));
    }

    // 3. Proceed with chat opening
    const container = document.querySelector('#chatBox .message-container');
    if (container) container.innerHTML = '<div class="message-spacer"></div>';

    selectedChat = { type: 'private', id: userId };
    updateActiveChatUI(username, isOnline ? 'Online' : 'Offline', isOnline);

    if (chatSocket) {
        chatSocket.onclose = null;
        chatSocket.close();
    }

    await loadChatMessages();
    connectWebSocket();
}

// Select group chat
async function selectGroupChat(groupSlug, groupName) {
    // Clear existing state
    unreadCounts.groups[groupSlug] = 0;
    updateChatItemBadge(groupSlug, 0);

    // Reset the message container
    const container = document.querySelector('#chatBox .message-container');
    if (container) {
        container.innerHTML = '<div class="message-spacer"></div>';
    }

    selectedChat = { type: 'group', slug: groupSlug };
    updateActiveChatUI(groupName, 'Group', false);

    // Make group name clickable
    activeChatTitle.style.cursor = 'pointer';
    activeChatTitle.onclick = () => {
        openGroupDetailsModal(groupSlug, groupName);
    };

    // Close existing socket
    if (chatSocket) {
        chatSocket.onclose = null;
        chatSocket.close();
    }

    // Load messages and connect socket
    await loadChatMessages();
    connectWebSocket();
}

// Update active chat UI
function updateActiveChatUI(title, status, isOnline, profilePicture = null) {
    activeChatTitle.textContent = title;
    activeChatStatus.textContent = status;
    activeChatStatus.style.display = 'block';
    activeChatStatus.className = isOnline ? 'online' : '';

    // Get avatar element
    const avatar = document.querySelector('.chat-header .avatar');

    // Reset avatar classes and content
    avatar.className = 'avatar';
    avatar.innerHTML = '';

    // Set appropriate avatar based on chat type
    if (selectedChat) {
        avatar.style.display = 'flex';
        if (selectedChat.type === 'private') {
            avatar.classList.add('user-avatar');
            if (profilePicture) {
                avatar.innerHTML = `<img src="${profilePicture}" alt="${title}" class="avatar-image">`;
            } else {
                avatar.innerHTML = '<i class="fas fa-user avatar-icon"></i>';
            }
            activeChatTitle.style.cursor = 'default';
            activeChatTitle.onclick = null;
        } else {
            avatar.classList.add('group-avatar');
            avatar.innerHTML = '<i class="fas fa-users avatar-icon"></i>';
            activeChatTitle.style.cursor = 'pointer';
            activeChatTitle.onclick = () => {
                openGroupDetailsModal(selectedChat.slug, activeChatTitle.textContent);
            };
        }
    } else {
        avatar.style.display = 'none';
    }

    // Update active state in list
    document.querySelectorAll('.chat-item').forEach(item => {
        item.classList.remove('active');
    });

    if (selectedChat?.type === 'private') {
        document.querySelector(`.chat-item[data-user-id="${selectedChat.id}"]`)?.classList.add('active');
    } else if (selectedChat?.type === 'group') {
        document.querySelector(`.chat-item[data-group-slug="${selectedChat.slug}"]`)?.classList.add('active');
    }
}

// Load chat messages
async function loadChatMessages() {
    if (!selectedChat) return;

    try {
        let response;
        if (selectedChat.type === 'private') {
            response = await fetch(`/chat/get_messages/${selectedChat.id}/`);
        } else {
            response = await fetch(`/chat/get_group_messages/${selectedChat.slug}/`);
        }

        if (!response.ok) throw new Error('Failed to load messages');

        const data = await response.json();
        if (data.messages && data.messages.length > 0) {
            // Store the current scroll height before rendering
            const container = document.querySelector('.message-container');
            const previousScrollHeight = container ? container.scrollHeight : 0;

            renderMessages(data.messages);

            // Immediately set scroll to bottom without animation
            if (container) {
                // Use a small timeout to ensure DOM is updated
                setTimeout(() => {
                    container.scrollTop = container.scrollHeight;
                }, 10);
            }
        } else {
            showEmptyChatState();
        }
    } catch (error) {
        console.error('Error loading messages:', error);
        showEmptyChatState();
    }
}

function showEmptyChatState() {
    const container = document.querySelector('#chatBox .message-container');
    container.innerHTML = `
        <div class="empty-chat">
            <i class="fas fa-comments"></i>
            <p>No messages yet</p>
        </div>
    `;
}

// Render messages
function renderMessages(messages) {
    const container = document.querySelector('#chatBox .message-container');
    if (!container) return;

    // Store current scroll position before clearing
    const previousScrollTop = container.scrollTop;
    const previousHeight = container.scrollHeight;

    container.innerHTML = '';

    if (messages.length === 0) {
        showEmptyChatState();
        return;
    }

    const fragment = document.createDocumentFragment();
    let currentDate = null;

    // First pass to identify date changes
    const dateChanges = [];
    let prevDate = null;
    messages.forEach((msg, index) => {
        const msgDate = new Date(msg.timestamp).toLocaleDateString('en-IN', {
            timeZone: 'Asia/Kolkata'
        });
        if (msgDate !== prevDate) {
            dateChanges.push({index, date: msgDate});
            prevDate = msgDate;
        }
    });

    // Second pass to render with separators
    let nextDateChange = 0;
    messages.slice().reverse().forEach((message, reversedIndex) => {
        const originalIndex = messages.length - 1 - reversedIndex;


        const isSelf = message.sender === currentUser.username;
        const messageDiv = document.createElement('div');
        messageDiv.className = `message ${isSelf ? 'sent' : 'received'}`;
        messageDiv.innerHTML = `
            ${!isSelf ? `<div class="sender">${message.sender}</div>` : ''}
            <div class="content">${message.content}</div>
            <div class="timestamp">${formatTime(message.timestamp)}</div>
        `;
        fragment.appendChild(messageDiv);
    });

    container.appendChild(fragment);

    // Restore scroll position relative to last date separator
    const heightDifference = container.scrollHeight - previousHeight;
    container.scrollTop = previousScrollTop + heightDifference;
}

function isNearBottom() {
    const container = document.querySelector('.message-container');
    if (!container) return true;

    // Consider "near bottom" if within 300px of bottom
    return container.scrollHeight - container.scrollTop - container.clientHeight < 300;
}

// Scroll to bottom helper
function scrollToBottom() {
    const container = document.querySelector('.message-container');
    if (!container) return;

    // Use the browser's native scroll anchoring
    container.scrollTop = container.scrollHeight;

    // Fallback for smooth scrolling
    setTimeout(() => {
        container.scrollTo({
            top: container.scrollHeight,
            behavior: 'smooth'
        });
    }, 50);
}

// Connect WebSocket
function connectWebSocket() {
    if (chatSocket) {
        chatSocket.onclose = null;
        chatSocket.close();
    }

    if (!selectedChat) return;

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    let socketUrl;

    if (selectedChat.type === 'private') {
        socketUrl = `${protocol}//${window.location.host}/ws/chat/${selectedChat.id}/`;
    } else {
        socketUrl = `${protocol}//${window.location.host}/ws/group/${selectedChat.slug}/`;
    }

    chatSocket = new WebSocket(socketUrl);

    chatSocket.onopen = () => {
        console.log('WebSocket connected for', selectedChat.type);
    };

    chatSocket.onmessage = (e) => {
    try {
        const data = JSON.parse(e.data);

        // Debug log to see raw WebSocket data
        console.log("WebSocket data received:", data);

        // Check if this message belongs to the currently active chat
        const isActiveChat = (
            (selectedChat?.type === 'private' &&
            (data.sender_id == selectedChat.id || data.receiver_id == selectedChat.id)) ||
            (selectedChat?.type === 'group' && data.group_slug === selectedChat.slug)
        );

        // Handle unread counts for non-active chats
        if (!isActiveChat && data.sender_id !== currentUser.id) {
            // ... (keep your existing unread count logic)
        }

        // Handle message display
        if (isActiveChat) {
            // Transform data to match what appendNewMessage expects
            const messageData = {
                sender: data.sender || data.username || 'Unknown',
                sender_id: data.sender_id,
                message: data.message || data.content,
                timestamp: data.timestamp || new Date().toISOString(),
                read: data.read || false
            };

            // For group messages, add the slug
            if (selectedChat.type === 'group') {
                messageData.group_slug = data.group_slug;
            }

            console.log("Processed message data:", messageData);
            appendNewMessage(messageData);

            // For group chats, still keep your refresh logic
            if (selectedChat.type === 'group') {
                setTimeout(() => {
                }, 300);
            }
        }
    } catch (error) {
        console.error('Error handling message:', error);
    }
};

    chatSocket.onclose = () => {
        console.log('WebSocket disconnected, reconnecting...');
        setTimeout(connectWebSocket, 3000);
    };

    chatSocket.onerror = (error) => {
        console.error('WebSocket error:', error);
    };
}

// Helper function to update badge on chat items
function updateChatItemBadge(identifier, count) {
    const selector = typeof identifier === 'number'
        ? `[data-user-id="${identifier}"]`
        : `[data-group-slug="${identifier}"]`;

    const chatItem = document.querySelector(selector);
    if (chatItem) {
        updateUnreadBadge(chatItem, count);
    }
}

// Append new message
function appendNewMessage(data) {
    const container = document.querySelector('#chatBox .message-container');

    if (container.querySelector('.empty-chat')) {
        container.innerHTML = '';
    }

    const isSelf = data.sender === currentUser.username;
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${isSelf ? 'sent' : 'received'}`;
    messageDiv.innerHTML = `
        ${!isSelf ? `<div class="sender">${data.sender}</div>` : ''}
        <div class="content">${data.message}</div>
        <div class="message-footer">
            <span class="timestamp">${formatTime(data.timestamp)}</span>
        </div>
    `;

    // With column-reverse, we prepend new messages instead of appending
    container.insertBefore(messageDiv, container.firstChild);
}

// Send message
function sendMessage() {
    if (!selectedChat || !messageInput.value.trim()) return;

    const message = {
        type: selectedChat.type,
        content: messageInput.value.trim(),
        timestamp: new Date().toISOString()
    };

    if (chatSocket && chatSocket.readyState === WebSocket.OPEN) {
        chatSocket.send(JSON.stringify(message));
        messageInput.value = '';
    } else {
        console.error('WebSocket not connected');
    }
    scrollToBottom();
}

// Handle key press
function handleKeyPress(e) {
    if (e.key === 'Enter') {
        sendMessage();
    }
}

// Switch tabs
function switchTab(e) {
    const tab = e.target.dataset.tab;
    if (tab === activeTab) return;

    activeTab = tab;
    document.querySelectorAll('.chat-tabs button').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tab === tab);
    });

    document.getElementById('privateChats').classList.toggle('hidden', tab !== 'private');
    document.getElementById('groupChats').classList.toggle('hidden', tab !== 'groups');
}

// Handle search
async function handleSearch() {
    const query = searchInput.value.trim();

    // If search is empty, reload the appropriate list
    if (!query) {
        if (activeTab === 'private') {
            loadPrivateChats();
        } else {
            loadGroups();
        }
        return;
    }

    try {
        const response = await fetch(`/chat/search/?query=${encodeURIComponent(query)}`);
        const data = await response.json();

        // Clear current list
        privateChatsList.innerHTML = '';

        if (data.users.length === 0) {
            privateChatsList.innerHTML = `
                <div class="empty-state">
                    <i class="fas fa-user-times"></i>
                    <p>No users found</p>
                </div>
            `;
            return;
        }

        // Render search results
        data.users.forEach(user => {
            const chatItem = document.createElement('div');
            chatItem.className = 'chat-item search-result';
            chatItem.dataset.userId = user.id;

            chatItem.innerHTML = `
                <div class="avatar">
                    <i class="fas fa-user"></i>
                    ${user.is_online ? '<span class="online-dot"></span>' : ''}
                </div>
                <div class="chat-info">
                    <h4>${user.username}</h4>
                </div>
                <div class="start-chat">
                    <i class="fas fa-comment-medical"></i>
                </div>
            `;

            chatItem.addEventListener('click', () => {
                selectPrivateChat(user.id, user.username, user.is_online);
                // Clear search after selection
                searchInput.value = '';
                loadPrivateChats();
            });

            privateChatsList.appendChild(chatItem);
        });

    } catch (error) {
        console.error('Error searching users:', error);
        privateChatsList.innerHTML = `
            <div class="empty-state">
                <i class="fas fa-exclamation-triangle"></i>
                <p>Error searching users</p>
            </div>
        `;
    }
}

// Group modal functions
function openGroupModal() {
    currentModalView = 'create';
    groupModal.querySelector('h3').textContent = 'Create New Group';
    groupForm.innerHTML = `
        <div class="form-group">
            <label>Group Name</label>
            <input type="text" name="group_name" required>
        </div>
        <div class="form-group">
            <label>Description (Optional)</label>
            <textarea name="group_description"></textarea>
        </div>
        <div class="form-group">
            <label>Add Members</label>
            <div class="member-list" id="memberSelection">
                <!-- Members will be loaded here -->
            </div>
        </div>
        <button type="submit" class="btn-create">Create Group</button>
    `;
    loadMembersForGroup();
    groupModal.classList.add('active');
}

function openGroupDetailsModal(groupSlug, groupName) {
    currentModalView = 'details';
    const modal = document.getElementById('groupModal');
    const form = modal.querySelector('form');

    // Clear any existing event listeners
    form.replaceWith(form.cloneNode(true));
    const newForm = modal.querySelector('form');

    modal.querySelector('h3').textContent = groupName;
    newForm.innerHTML = `
        <div class="form-group">
            <label>Group Name</label>
            <input type="text" name="group_name" value="${groupName}" required>
        </div>
        <div class="form-group">
            <label>Description</label>
            <textarea name="group_description"></textarea>
        </div>
        <div class="form-group">
            <label>Members</label>
            <div class="member-list" id="currentMembers">
                <!-- Current members will load here -->
            </div>
        </div>
        <div class="modal-actions">
            <button type="button" class="btn-back" onclick="switchModalView('details')">
                <i class="fas fa-arrow-left"></i> Back
            </button>
            <button type="button" class="btn-delete" id="deleteGroupBtn">
                <i class="fas fa-trash"></i> Delete Group
            </button>
            <button type="button" class="btn-add" id="addMembersBtn">
                <i class="fas fa-user-plus"></i> Add Members
            </button>
            <button type="submit" class="btn-save">
                <i class="fas fa-save"></i> Save Changes
            </button>
        </div>
    `;

    // Add fresh event listeners
    document.getElementById('deleteGroupBtn').addEventListener('click', () => {
        if (confirm('Are you sure you want to delete this group? This action cannot be undone.')) {
            deleteGroup(groupSlug);
        }
    });

    document.getElementById('addMembersBtn').addEventListener('click', () => {
        switchModalView('add-members');
    });

    newForm.addEventListener('submit', (e) => {
        e.preventDefault();
        updateGroupInfo(groupSlug);
    });

    loadGroupDetails(groupSlug);
    modal.classList.add('active');
}

function switchModalView(view) {
    currentModalView = view;
    const modal = document.getElementById('groupModal');

    if (view === 'add-members') {
        modal.querySelector('h3').textContent = 'Add New Members';
        modal.querySelector('form').innerHTML = `
            <div class="form-group">
                <label>Select Members to Add</label>
                <div class="member-list" id="memberSelection">
                    <!-- Non-members will load here -->
                </div>
            </div>
            <div class="modal-actions">
                <button type="button" class="btn-back" onclick="switchModalView('details')">
                    <i class="fas fa-arrow-left"></i> Back
                </button>
                <button type="button" class="btn-done" onclick="addSelectedMembers()">
                    <i class="fas fa-check"></i> Done
                </button>
            </div>
        `;
        loadNonMembers(selectedChat.slug);
    } else {
        openGroupDetailsModal(selectedChat.slug, activeChatTitle.textContent);
    }
}

async function loadGroupDetails(groupSlug) {
    try {
        const response = await fetch(`/chat/group_details/${groupSlug}/`);
        const data = await response.json();

        const membersContainer = document.getElementById('currentMembers');
        membersContainer.innerHTML = '';

        data.members.forEach(member => {
            const memberItem = document.createElement('div');
            memberItem.className = 'member-item';
            memberItem.innerHTML = `
                <div class="avatar">
                    <i class="fas fa-user"></i>
                </div>
                <span>${member.username}</span>
                ${member.is_admin ? '<span class="badge">Admin</span>' : ''}
                ${member.can_remove ?
                    `<button class="btn-remove" data-user-id="${member.id}">
                        <i class="fas fa-times"></i>
                    </button>` : ''}
            `;
            membersContainer.appendChild(memberItem);
        });

        if (data.description) {
            document.querySelector('textarea[name="group_description"]').value = data.description;
        }

        document.querySelectorAll('.btn-remove').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                removeMember(groupSlug, btn.dataset.userId);
            });
        });

    } catch (error) {
        console.error('Error loading group details:', error);
    }
}

async function addSelectedMembers() {
    const groupSlug = selectedChat.slug;
    const members = Array.from(document.querySelectorAll('input[name="new_members"]:checked'))
                         .map(el => el.value);

    try {
        const response = await fetch(`/chat/add_members/${groupSlug}/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken'),
            },
            body: JSON.stringify({ members })
        });

        if (response.ok) {
            switchModalView('details');
            loadGroupDetails(groupSlug);
        }
    } catch (error) {
        console.error('Error adding members:', error);
    }
}

async function removeMember(groupSlug, userId) {
    try {
        const response = await fetch(`/chat/remove_member/${groupSlug}/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken'),
            },
            body: JSON.stringify({ user_id: userId })
        });

        if (response.ok) {
            loadGroupDetails(groupSlug);
        }
    } catch (error) {
        console.error('Error removing member:', error);
    }
}

async function deleteGroup(groupSlug) {
    try {
        const response = await fetch(`/chat/delete_group/${groupSlug}/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken'),
            }
        });

        if (response.ok) {
            closeGroupModal();

            // Clear if this was the active chat
            if (selectedChat?.type === 'group' && selectedChat.slug === groupSlug) {
                selectedChat = null;
                activeChatTitle.textContent = 'Select a chat';
                document.querySelector('#chatBox .message-container').innerHTML = `
                    <div class="empty-chat">
                        <i class="fas fa-comments"></i>
                        <p>Select a chat to start messaging</p>
                    </div>
                `;
            }

            // Remove from sidebar
            const groupItem = document.querySelector(`.chat-item[data-group-slug="${groupSlug}"]`);
            if (groupItem) {
                groupItem.remove();
            }

            // Show empty state if no groups left
            if (document.querySelectorAll('#groupChats .chat-item').length === 0) {
                groupChatsList.innerHTML = `
                    <div class="empty-state">
                        <i class="fas fa-users"></i>
                        <p>No group chats yet</p>
                    </div>
                `;
            }
        }
    } catch (error) {
        console.error('Error deleting group:', error);
    }
}

async function updateGroupInfo(groupSlug) {
    const form = document.querySelector('#groupModal form');
    const formData = new FormData(form);
    const saveButton = form.querySelector('.btn-save');

    // Disable button to prevent multiple submissions
    saveButton.disabled = true;
    saveButton.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Saving...';

    try {
        const response = await fetch(`/chat/update_group/${groupSlug}/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken'),
            },
            body: JSON.stringify({
                name: formData.get('group_name'),
                description: formData.get('group_description')
            })
        });

        if (response.ok) {
            const data = await response.json();
            if (selectedChat?.type === 'group' && selectedChat.slug === groupSlug) {
                activeChatTitle.textContent = data.name;
                selectedChat.slug = data.slug;
            }

            const groupItem = document.querySelector(`.chat-item[data-group-slug="${groupSlug}"] h4`);
            if (groupItem) {
                groupItem.parentElement.dataset.groupSlug = data.slug;
                groupItem.textContent = data.name;
            }
            closeGroupModal();
            loadGroups(); // Refresh the group list
        }
    } catch (error) {
        console.error('Error updating group:', error);
    } finally {
        saveButton.disabled = false;
        saveButton.innerHTML = '<i class="fas fa-save"></i> Save Changes';
    }
}

function closeGroupModal() {
    groupModal.classList.remove('active');
}

async function loadMembersForGroup() {
    try {
        const response = await fetch('/chat/get_users/');
        const data = await response.json();

        memberSelection.innerHTML = '';
        data.users.forEach(user => {
            const memberItem = document.createElement('div');
            memberItem.className = 'member-item';
            memberItem.innerHTML = `
                <input type="checkbox" name="members" value="${user.id}" id="member-${user.id}">
                <label for="member-${user.id}">
                    <div class="avatar">
                        <i class="fas fa-user"></i>
                    </div>
                    <span>${user.username}</span>
                </label>
            `;
            memberSelection.appendChild(memberItem);
        });
    } catch (error) {
        console.error('Error loading members:', error);
    }
}

async function createGroup(e) {
    e.preventDefault();
    const formData = new FormData(groupForm);
    const members = Array.from(document.querySelectorAll('input[name="members"]:checked')).map(el => el.value);

    try {
        const response = await fetch('/chat/create-group/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken'),
            },
            body: JSON.stringify({
                name: formData.get('group_name'),
                description: formData.get('group_description'),
                members: members
            })
        });

        if (response.ok) {
            closeGroupModal();
            loadGroups();
            groupForm.reset();
        }
    } catch (error) {
        console.error('Error creating group:', error);
    }
}

async function loadNonMembers(groupSlug) {
    try {
        const response = await fetch(`/chat/get_non_members/${groupSlug}/`);
        const data = await response.json();

        const container = document.getElementById('memberSelection');
        container.innerHTML = '';

        data.users.forEach(user => {
            const memberItem = document.createElement('div');
            memberItem.className = 'member-item';
            memberItem.innerHTML = `
                <input type="checkbox" name="new_members" value="${user.id}" id="new-member-${user.id}">
                <label for="new-member-${user.id}">
                    <div class="avatar">
                        <i class="fas fa-user"></i>
                    </div>
                    <span>${user.username}</span>
                </label>
            `;
            container.appendChild(memberItem);
        });
    } catch (error) {
        console.error('Error loading non-members:', error);
    }
}

// Helper functions
function formatTime(timestamp) {
    const date = new Date(timestamp);

    return date.toLocaleString('en-IN', {
        day: 'numeric',
        month: 'short',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        timeZone: 'Asia/Kolkata'
    });
}

function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

function updateUnreadBadge(chatElement, count) {
    const badge = chatElement.querySelector('.unread-badge');
    if (!badge) return;

    badge.textContent = count;
    badge.style.display = count > 0 ? 'flex' : 'none';

    if (count > 0) {
        chatElement.classList.add('has-unread');
    } else {
        chatElement.classList.remove('has-unread');
    }
}

async function markMessagesAsRead(userId) {
    try {
        const response = await fetch(`/chat/mark_messages_read/${userId}/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken'),
            },
            body: JSON.stringify({}),
            credentials: 'include'  // Ensure cookies are sent
        });

        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Update failed');

        localStorage.setItem(`unread_${userId}`, '0'); // Persist
        return true;
    } catch (error) {
        console.error('Mark-as-read failed:', error);
        return false;
    }
}