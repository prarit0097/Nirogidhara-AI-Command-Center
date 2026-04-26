from __future__ import annotations

from rest_framework import serializers

from .models import User


class UserSerializer(serializers.ModelSerializer):
    displayName = serializers.CharField(source="display_name", required=False, allow_blank=True)

    class Meta:
        model = User
        fields = ("id", "username", "email", "role", "displayName")
        read_only_fields = ("id",)
