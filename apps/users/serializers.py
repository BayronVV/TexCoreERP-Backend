from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth import get_user_model

User = get_user_model()

class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        # Add custom claims
        token['role'] = user.role
        return token

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'role']

class RoleUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['role']

import re
from rest_framework.exceptions import ValidationError

class UserRegistrationSerializer(serializers.ModelSerializer):
    password_confirm = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email', 'password', 'password_confirm', 'requested_area', 'document_id']
        extra_kwargs = {
            'password': {'write_only': True},
            'first_name': {'required': True},
            'last_name': {'required': True},
            'email': {'required': True},
        }

    def validate(self, attrs):
        if attrs['password'] != attrs['password_confirm']:
            raise ValidationError({"password_confirm": "Las contraseñas no coinciden."})
        
        # Validate password strength
        password = attrs['password']
        if len(password) < 8:
            raise ValidationError({"password": "La contraseña debe tener al menos 8 caracteres."})
        if not re.search(r"[A-Z]", password):
            raise ValidationError({"password": "La contraseña debe contener al menos una letra mayúscula."})
        if not re.search(r"[a-z]", password):
            raise ValidationError({"password": "La contraseña debe contener al menos una letra minúscula."})
        if not re.search(r"[0-9]", password):
            raise ValidationError({"password": "La contraseña debe contener al menos un número."})
        if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
            raise ValidationError({"password": "La contraseña debe contener al menos un símbolo especial."})

        return attrs

    def create(self, validated_data):
        validated_data.pop('password_confirm')
        # Use email as username
        user = User.objects.create_user(
            username=validated_data['email'],
            email=validated_data['email'],
            first_name=validated_data['first_name'],
            last_name=validated_data['last_name'],
            password=validated_data['password'],
            requested_area=validated_data.get('requested_area', ''),
            document_id=validated_data.get('document_id', ''),
            role='PENDING'
        )
        return user
