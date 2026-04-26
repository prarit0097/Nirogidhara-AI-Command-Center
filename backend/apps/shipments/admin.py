from django.contrib import admin

from .models import Shipment, WorkflowStep

admin.site.register(Shipment)
admin.site.register(WorkflowStep)
