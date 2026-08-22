from django import forms
from .models import WhatsAppAccount
from django.contrib.auth.models import User
from django import forms
from django.contrib.auth.forms import UserCreationForm

class SignUpForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = ['username', 'email', 'password1', 'password2']
class WhatsAppAccountForm(forms.ModelForm):
    class Meta:
        model = WhatsAppAccount
        fields = ['name', 'number', 'country_code', 'is_default', 'notes']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. MarketingBot 1'}),
            'number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '+91XXXXXXXXXX'}),
            'country_code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. 91'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Purpose of this account'}),
            'is_default': forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'setDefault'}),
        }


