from django import forms

from .models import Project, Ticket


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
		]
		widgets = {
			"description": forms.Textarea(attrs={"rows": 4}),
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

