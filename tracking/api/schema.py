from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from . import _common as api

@api.require_http_methods(['GET'])
@csrf_exempt
def schema_view(request):
    spec = {
        'openapi': '3.1.0',
        'info': {'title': 'SmartTracking REST API', 'version': '0.1.0'},
        'servers': [{'url': '/'}],
        'paths': {
            '/tracking/api/meta/': {'get': {'summary': 'Enum & transition graph'}},
            '/tracking/api/tickets/': {'get': {'summary': 'List tickets'}, 'post': {'summary': 'Create ticket'}},
            '/tracking/api/tickets/{id}/': {'get': {'summary': 'Ticket detail'}, 'patch': {'summary': 'Update ticket'}},
            '/tracking/api/tickets/{id}/transition/': {'post': {'summary': 'Transition ticket state'}},
            '/tracking/api/tickets/{id}/relations/add/': {'post': {'summary': 'Add relation'}},
            '/tracking/api/tickets/relations/{id}/delete/': {'delete': {'summary': 'Delete relation'}},
            '/tracking/api/comments/': {'get': {'summary': 'List comments'}},
            '/tracking/api/components/': {'get': {'summary': 'List components'}},
            '/tracking/api/labels/': {'get': {'summary': 'List labels'}},
            '/tracking/api/attachments/': {'get': {'summary': 'List attachments'}},
            '/tracking/api/sprints/{key}/': {'get': {'summary': 'Sprint detail'}},
            '/tracking/api/projects/': {'get': {'summary': 'List projects'}},
        },
        'components': {
            'schemas': {
                'Ticket': {'type': 'object'},
                'CreateTicket': {'type': 'object'},
                'UpdateTicket': {'type': 'object'},
                'Comment': {'type': 'object'},
                'Component': {'type': 'object'},
                'Label': {'type': 'object'},
                'Sprint': {'type': 'object'},
                'Attachment': {'type': 'object'},
            },
            'securitySchemes': {
                'Bearer': {'type': 'http', 'scheme': 'bearer'},
                'Cookie': {'type': 'apiKey', 'in': 'header', 'name': 'sessionid'},
            }
        },
        'tags': [
            {'name': 'tickets', 'description': 'Ticket operations'},
            {'name': 'projects', 'description': 'Project operations'},
        ]
    }
    return JsonResponse(spec)
