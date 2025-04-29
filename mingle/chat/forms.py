from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from .models import Profile


class RegistrationForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = ['username', 'email', 'password1', 'password2']

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("This email is already registered.")
        return email


class LoginForm(AuthenticationForm):
    def clean(self):
        username = self.cleaned_data.get('username')
        password = self.cleaned_data.get('password')

        if username and password:
            self.user_cache = authenticate(self.request, username=username, password=password)
            if self.user_cache is None:
                raise forms.ValidationError(
                    "Invalid username or password.",
                    code='invalid_login',
                )
            elif not self.user_cache.is_active:
                raise forms.ValidationError(
                    "This account is inactive.",
                    code='inactive',
                )
        return self.cleaned_data

class ProfileForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ['profile_picture', 'bio', 'phone_number']
        widgets = {
            'bio': forms.Textarea(attrs={'rows': 4, 'class': 'form-control'}),
            'phone_number': forms.TextInput(attrs={'placeholder': '+1234567890'})
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['profile_picture'].required = False
        # Add User model fields
        self.fields['username'] = forms.CharField(
            initial=self.instance.user.username,
            max_length=150
        )
        self.fields['email'] = forms.EmailField(
            initial=self.instance.user.email
        )

    def save(self, commit=True):
        profile = super().save(commit=False)
        user = profile.user
        user.username = self.cleaned_data['username']
        user.email = self.cleaned_data['email']

        if commit:
            user.save()
            profile.save()
        return profile