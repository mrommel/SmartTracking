import json
from django.shortcuts import get_object_or_404
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from tracking.api._common import require_api_auth
from tracking.models import WorkLog
from tracking.forms import WorkLogForm


@csrf_exempt
@require_api_auth
@require_http_methods(["DELETE"])
def api_worklog_delete(request, pk):
	entry = get_object_or_404(WorkLog, pk=pk)
	if request.user.is_superuser or entry.author == request.user:
		ticket_pk = entry.ticket.pk
		entry.delete()
		return JsonResponse({"id": pk, "ticket": ticket_pk})
	return JsonResponse({"error": "Forbidden"}, status=403)
