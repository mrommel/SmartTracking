from django import forms

from .models import Attachment, Comment, Component, Label, Project, Ticket


class ProjectForm(forms.ModelForm):
	"""Create / edit a project."""

	class Meta:
		model = Project
		fields = [
			"key",
			"name",
			"description",
		]
		widgets = {
			"description": forms.Textarea(attrs={"rows": 4}),
		}

	def clean_key(self):
		# Project keys are stored/compared uppercase (used as ticket-ID prefix).
		return self.cleaned_data["key"].upper()


class TicketForm(forms.ModelForm):
	"""Create / edit a ticket. State is managed via transitions, not here."""

	class Meta:
		model = Ticket
		fields = [
			"project",
			"title",
			"description",
			"type",
			"priority",
			"assignee",
			"components",
			"labels",
		]
		widgets = {
			"description": forms.Textarea(attrs={"rows": 4}),
			"components": forms.SelectMultiple(attrs={"class": "form-select"}),
			"labels": forms.SelectMultiple(attrs={"class": "form-select"}),
		}


class TicketTransitionForm(forms.Form):
	"""Move a ticket to one of its currently-allowed next states."""

	state = forms.ChoiceField(label="Move to")

	def __init__(self, *args, ticket=None, **kwargs):
		super().__init__(*args, **kwargs)
		self.ticket = ticket
		if ticket is not None:
			self.fields["state"].choices = [
				(s.value, s.label) for s in ticket.allowed_transitions()
			]

	def clean_state(self):
		state = self.cleaned_data["state"]
		if self.ticket is not None and not self.ticket.can_transition_to(state):
			raise forms.ValidationError("That state transition is not allowed.")
		return state


class CommentForm(forms.ModelForm):
	"""Create a comment on a ticket."""

	class Meta:
		model = Comment
		fields = [
			"body",
		]
		widgets = {
			"body": forms.Textarea(attrs={"rows": 3}),
		}

class LabelForm(forms.ModelForm):
	"""Create / edit a label."""

	color = forms.ChoiceField(
		choices=[
			("secondary", "Secondary"),
			("primary", "Primary"),
			("success", "Success"),
			("danger", "Danger"),
			("warning", "Warning"),
			("info", "Info"),
			("light", "Light"),
			("dark", "Dark"),
		],
		widget=forms.Select(attrs={"class": "form-select"}),
	)

	class Meta:
		model = Label
		fields = [
			"name",
			"color",
			"description",
		]
		widgets = {
			"description": forms.Textarea(attrs={"rows": 3}),
		}

	def __init__(self, *args, project=None, **kwargs):
		super().__init__(*args, **kwargs)
		self.project = project
		if project is not None:
			self.fields["name"].widget.attrs["placeholder"] = f"e.g. blocked, in-review"

	def clean_name(self):
		name = self.cleaned_data["name"]
		if self.instance.pk is None and self.project is not None:
			if Label.objects.filter(project=self.project, name=name).exists():
				raise forms.ValidationError(f"A label named '{name}' already exists.")
		return name


class LabelDeleteForm(forms.Form):
	"""Delete a label."""

	label = forms.ModelChoiceField(queryset=Label.objects.none(), label="Label")

	def __init__(self, *args, project=None, **kwargs):
		super().__init__(*args, **kwargs)
		if project is not None:
			self.fields["label"].queryset = project.labels.all()


class ComponentForm(forms.ModelForm):
	"""Create / edit a component."""

	class Meta:
		model = Component
		fields = [
			"name",
			"description",
		]
		widgets = {
			"description": forms.Textarea(attrs={"rows": 3}),
		}

	def __init__(self, *args, project=None, **kwargs):
		super().__init__(*args, **kwargs)
		self.project = project
		if project is not None:
			self.fields["name"].widget.attrs["placeholder"] = f"e.g. frontend, api"

	def clean_name(self):
		name = self.cleaned_data["name"]
		if self.instance.pk is None and self.project is not None:
			if Component.objects.filter(project=self.project, name=name).exists():
				raise forms.ValidationError(f"A component named '{name}' already exists.")
		return name


class ComponentDeleteForm(forms.Form):
	"""Delete a component."""

	component = forms.ModelChoiceField(queryset=Component.objects.none(), label="Component")

	def __init__(self, *args, project=None, **kwargs):
		super().__init__(*args, **kwargs)
		if project is not None:
			self.fields["component"].queryset = project.components.all()


class AttachmentForm(forms.ModelForm):
	"""Upload an attachment to a ticket."""

	name = forms.CharField(required=False, widget=forms.HiddenInput())

	def clean(self):
		cleaned = super().clean()
		file = self.files.get("file")
		name = cleaned.get("name")
		if file and not name:
			cleaned["name"] = file.name
		return cleaned

	class Meta:
		model = Attachment
		fields = ["file", "name"]
		widgets = {"file": forms.ClearableFileInput(attrs={"class": "form-control"})}
