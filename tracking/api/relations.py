from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from . import _common as api
from . import _common
from tracking.models import TicketRelation

@api.require_http_methods(['POST'])
def relations_add(request, pk):
	data = _common._parse_json(request)
	relation = TicketRelation.objects.create(
		subject_id=data.get('ticket', 0),
		target_id=data.get('related_ticket', 0),
		relation_type=data.get('type', 'related_to')
	)
	return JsonResponse({'id': relation.pk, 'type': relation.relation_type}, status=201)

@api.require_http_methods(['DELETE'])
def delete_relation(request, pk):
	relation = TicketRelation.objects.filter(pk=pk).first()
	if relation:
		relation.delete()
		return JsonResponse({'deleted': pk})
	return JsonResponse({'error': 'Not found'}, status=404)