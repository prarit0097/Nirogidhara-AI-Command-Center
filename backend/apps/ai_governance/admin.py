from django.contrib import admin

from .models import CaioAudit, CeoBriefing, CeoRecommendation

admin.site.register(CeoBriefing)
admin.site.register(CeoRecommendation)
admin.site.register(CaioAudit)
