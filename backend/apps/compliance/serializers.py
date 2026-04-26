from __future__ import annotations

from rest_framework import serializers

from .models import Claim


class ClaimSerializer(serializers.ModelSerializer):
    class Meta:
        model = Claim
        fields = ("product", "approved", "disallowed", "doctor", "compliance", "version")
