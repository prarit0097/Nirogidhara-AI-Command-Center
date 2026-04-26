from django.contrib import admin

from .models import ActiveCall, Call, CallTranscriptLine

admin.site.register(Call)
admin.site.register(ActiveCall)
admin.site.register(CallTranscriptLine)
