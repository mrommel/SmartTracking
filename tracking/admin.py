from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from .models import Attachment, Comment, Component, Label, Project, Sprint, Ticket, TicketActivity, TicketRelation


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
	list_display = ("key", "name", "created_at")
	search_fields = ("key", "name")


class TicketRelationInline(admin.TabularInline):
	model = TicketRelation
	extra = 0
	raw_id_fields = ("subject", "target")
	fk_name = "subject"
	can_delete = True


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
	list_display = ("title", "project", "type", "state", "estimation", "priority", "assignee", "due_date", "created_at")
	list_filter = ("project", "type", "state", "priority")
	search_fields = ("title", "description")
	autocomplete_fields = ("project", "reporter", "assignee", "parent_epic")
	readonly_fields = ("created_at", "updated_at")
	inlines = (TicketRelationInline,)


@admin.register(TicketRelation)
class TicketRelationAdmin(admin.ModelAdmin):
	list_display = ("subject", "target", "relation_type")
	list_filter = ("relation_type",)
	search_fields = ("subject__title", "target__title")
	autocomplete_fields = ("subject", "target")


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


@admin.register(Attachment)
class AttachmentAdmin(admin.ModelAdmin):
	list_display = ("name", "ticket", "mime_type", "created_at")
	list_filter = ("ticket", "mime_type", "created_at")
	search_fields = ("name", "ticket__title")
	readonly_fields = ("created_at", "mime_type")
	autocomplete_fields = ("ticket",)


@admin.register(TicketActivity)
class TicketActivityAdmin(admin.ModelAdmin):
	list_display = ("ticket", "actor", "action", "field_name", "created_at")
	list_filter = ("action", "created_at")
	search_fields = ("ticket__title", "actor__username", "action")
	readonly_fields = ("created_at",)
	autocomplete_fields = ("ticket", "actor")
