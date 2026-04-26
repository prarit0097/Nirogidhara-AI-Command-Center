from django.contrib import admin

from .models import Customer, Lead

admin.site.register(Lead)
admin.site.register(Customer)
