from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from .models import Comment, Component, Label, Project, Ticket


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


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
	list_display = ("body_preview", "ticket", "author", "created_at")
	list_filter = ("ticket", "created_at")
	search_fields = ("body", "author__username")
	readonly_fields = ("created_at", "updated_at")
	autocomplete_fields = ("author",)

	def body_preview(self, obj):
		return obj.body[:50] + "..." if len(obj.body) > 50 else obj.body
	body_preview.short_description = _("body")


@admin.register(Component)
class ComponentAdmin(admin.ModelAdmin):
	list_display = ("name", "project", "created_at")
	list_filter = ("project",)
	search_fields = ("name", "description")
	autocomplete_fields = ("project",)


@admin.register(Label)
class LabelAdmin(admin.ModelAdmin):
	list_display = ("name", "project", "color", "created_at")
	list_filter = ("project", "color")
	search_fields = ("name", "description")
	autocomplete_fields = ("project",)
