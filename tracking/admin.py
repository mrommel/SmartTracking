from django.contrib import admin

from .models import Project, Ticket


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
	list_display = ("key", "name", "created_at")
	search_fields = ("key", "name")


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
	list_display = ("title", "project", "type", "state", "priority", "assignee", "created_at")
	list_filter = ("project", "type", "state", "priority")
	search_fields = ("title", "description")
	autocomplete_fields = ("project", "reporter", "assignee")
	readonly_fields = ("created_at", "updated_at")
