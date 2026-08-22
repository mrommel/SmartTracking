from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from tracking.models import Component, Project
from tracking.forms import ComponentForm

@login_required
def component_list(request, pk=None):
	if pk:
		project = get_object_or_404(Project, pk=pk)
		queryset = project.components.all()
		return render(request, 'tracking/component_list.html', {'components': queryset, 'project': project})
	else:
		queryset = Component.objects.all()
		projects = Project.objects.all()
		return render(request, 'tracking/component_list.html', {'components': queryset, 'projects': projects})

@login_required
def component_create(request, pk):
	project = get_object_or_404(Project, pk=pk)
	if request.method == 'POST':
		form = ComponentForm(request.POST, project=project)
		if form.is_valid():
			component = form.save(commit=False)
			component.project = project
			component.save()
			messages.success(request, "Component created")
			return redirect('component_list', pk=pk)
	else:
		form = ComponentForm(project=project)
	return render(request, 'tracking/component_create.html', {'form': form, 'project': project})

@login_required
def component_update(request, pk):
	component = get_object_or_404(Component, pk=pk)
	if request.method == 'POST':
		form = ComponentForm(request.POST, instance=component)
		if form.is_valid():
			form.save()
			return redirect('component_list', pk=component.project.pk)
	else:
		form = ComponentForm(instance=component)
	return render(request, 'tracking/component_edit.html', {
		'form': form, 'component': component, 'project': component.project
	})

@login_required
def component_delete(request, pk):
	component = get_object_or_404(Component, pk=pk)
	project = component.project
	if request.method == 'POST':
		component.delete()
		messages.success(request, "Component deleted")
		return redirect('component_list', pk=project.pk)
	return render(request, 'tracking/component_delete.html', {'component': component, 'project': project})
