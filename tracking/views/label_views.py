from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from tracking.models import Label, Project
from tracking.forms import LabelForm

@login_required
def label_list(request, pk=None):
	if pk:
		project = get_object_or_404(Project, pk=pk)
		queryset = project.labels.all()
		return render(request, 'tracking/label_list.html', {'labels': queryset, 'project': project})
	else:
		queryset = Label.objects.all()
		projects = Project.objects.all()
		return render(request, 'tracking/label_list.html', {'labels': queryset, 'projects': projects})

@login_required
def label_create(request, pk):
	project = get_object_or_404(Project, pk=pk)
	if request.method == 'POST':
		form = LabelForm(request.POST, project=project)
		if form.is_valid():
			label = form.save(commit=False)
			label.project = project
			label.save()
			messages.success(request, "Label created")
			return redirect('label_list', pk=pk)
	else:
		form = LabelForm(project=project)
	return render(request, 'tracking/label_create.html', {'form': form, 'project': project})

@login_required
def label_update(request, pk):
	label = get_object_or_404(Label, pk=pk)
	if request.method == 'POST':
		form = LabelForm(request.POST, instance=label)
		if form.is_valid():
			form.save()
			return redirect('label_list', pk=label.project.pk)
	else:
		form = LabelForm(instance=label)
	return render(request, 'tracking/label_edit.html', {
		'form': form, 'label': label, 'project': label.project
	})

@login_required
def label_delete(request, pk):
	label = get_object_or_404(Label, pk=pk)
	project = label.project
	if request.method == 'POST':
		label.delete()
		messages.success(request, "Label deleted")
		return redirect('label_list', pk=project.pk)
	return render(request, 'tracking/label_delete.html', {'label': label, 'project': project})
