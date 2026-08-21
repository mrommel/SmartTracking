---
description: Testing agent for SmartTracking Django project — use when writing unit tests, integration tests, regression tests, or verifying code coverage for features
mode: subagent
---

# Testing Agent

You are the testing agent for the SmartTracking Django project. Write comprehensive tests that cover success paths, error paths, auth guards, and validation boundaries.

## Environment

- Use `./.venv/bin/python3.12 manage.py` for all test runs. The Makefile pins python3.12.
- Tests live in the `tracking/tests/` package. Current test files: `test_models.py`, `test_views.py`, `test_api.py`, `test_ui.py`, `test_components.py`, `test_mcp_server.py`.
- Run all tests: `./.venv/bin/python3.12 manage.py test tracking`
- Run a specific test module: `./.venv/bin/python3.12 manage.py test tracking.tests.test_<module>`
- Run a specific test class: `./.venv/bin/python3.12 manage.py test tracking.tests.test_<module>.TestSomeClass`

## Auth testing patterns

HTML views use `@login_required` (`tracking/views.py`). API views use `@require_api_auth` (`tracking/api.py`).

### Session-based auth (HTML views)

When a view accesses `request.user` or needs Django session login:

```python
from django.contrib.auth.models import User
from django.test import TestCase, override_settings

class TicketViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="tester", password="pass123")
        self.client = Client()

    def test_login_required(self):
        response = self.client.get("/tracking/dashboard/")
        self.assertEqual(response.status_code, 302)  # redirects to login

    def test_view_accessible_after_login(self):
        self.client.force_login(self.user)
        response = self.client.get("/tracking/dashboard/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Some Expected Content")
```

Key points:
- `force_login(user)` logs a user in via the session backend — no password needed.
- Always test both unauthenticated (302 redirect) and authenticated (200) paths.
- Use `assertContains(response, text)` and `assertNotContains(response, text)` for content checks.
- Use `assertRedirects(response, expected_url, status_code=302)` for redirect assertions.

### Token-based auth (API views)

API views accept either session auth OR bearer token. For token auth:

```python
from django.test import TestCase, override_settings
from django.conf import settings

class TicketAPITests(TestCase):
    @override_settings(TRACKING_API_TOKEN="my-secret-token")
    def test_api_requires_auth(self):
        response = self.client.get("/tracking/api/tickets/")
        self.assertEqual(response.status_code, 401)

    @override_settings(TRACKING_API_TOKEN="my-secret-token")
    def test_api_with_valid_token(self):
        response = self.client.get(
            "/tracking/api/tickets/",
            HTTP_AUTHORIZATION="Bearer my-secret-token"
        )
        self.assertEqual(response.status_code, 200)
```

- Use `@override_settings(TRACKING_API_TOKEN=...)` in every API test that requires auth.
- Without a token setting, `require_api_auth` falls through to session auth.
- Remember: if `TRACKING_API_TOKEN` is empty/not set, token auth is disabled and session-only.

## API response testing

API list endpoints return a paginated envelope:

```json
{
    "count": 42,
    "pagination": {"next": "http://...?page=2", "previous": null},
    "results": [...]
}
```

```python
from django.test import TestCase

class TicketAPITests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(name="Test", key="TST")

    def test_ticket_list_returns_paginated_envelope(self):
        # create some tickets...
        response = self.client.get("/tracking/api/tickets/")
        data = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertIn("count", data)
        self.assertIn("pagination", data)
        self.assertIn("results", data)
        self.assertIsInstance(data["results"], list)
        self.assertEqual(data["count"], expected_count)

    def test_ticket_list_filter_by_project(self):
        project = Project.objects.create(name="Filtered", key="FLT")
        Ticket.objects.create(title="Open", project=project, state=...)
        response = self.client.get("/tracking/api/tickets/?project=FLT")
        data = response.json()
        self.assertEqual(len(data["results"]), 1)
```

## GET / POST / PUT / PATCH / DELETE testing

### Singleton endpoints (GET, PATCH, DELETE)

```python
def test_ticket_detail(self):
    ticket = Ticket.objects.create(title="My Ticket", project=self.project, state=...)
    self.client.force_login(self.user)
    response = self.client.get(f"/tracking/api/tickets/{ticket.pk}/")
    data = response.json()
    self.assertIn("id", data)
    self.assertIn("title", data)
    self.assertEqual(data["title"], "My Ticket")

def test_ticket_patch_state_from_model(self):
    ticket = Ticket.objects.create(title="Test", project=self.project, state=...)
    self.client.force_login(self.user)
    response = self.client.patch(
        f"/tracking/api/tickets/{ticket.pk}/",
        content_type="application/json",
        data={"state": "in_progress"}
    )
    # API rejected PATCH state — it only goes through /transition/
    self.assertEqual(response.status_code, 400)
```

### Transition endpoint

State changes MUST go through `/transition/`:

```python
def test_ticket_transition(self):
    ticket = Ticket.objects.create(..., state=Ticket.State.OPEN)
    self.client.force_login(self.user)
    response = self.client.post(
        f"/tracking/api/tickets/{ticket.pk}/transition/",
        content_type="application/json",
        data={"state": "in_progress"}
    )
    self.assertEqual(response.status_code, 200)
    ticket.refresh_from_db()
    self.assertEqual(ticket.state, Ticket.State.IN_PROGRESS)

def test_ticket_transition_forbidden(self):
    ticket = Ticket.objects.create(..., state=Ticket.State.DONE)
    self.client.force_login(self.user)
    response = self.client.post(
        f"/tracking/api/tickets/{ticket.pk}/transition/",
        content_type="application/json",
        data={"state": "OPEN"}
    )
    self.assertEqual(response.status_code, 409)
    data = response.json()
    self.assertIn("allowed_transitions", data)
```

The 409 response on illegal transitions includes `{"detail": "Invalid state transition", "allowed_transitions": ["done"]}`.

## Assert patterns

### Assert returns true / false

```python
ticket = Ticket.objects.create(...)
self.assertTrue(ticket.can_transition_to(Ticket.State.IN_PROGRESS))
self.assertFalse(ticket.can_transition_to(Ticket.State.DONE))
allowed = ticket.allowed_transitions()
self.assertEqual(len(allowed), 1)  # only one target from current state
```

### Assert redirects

```python
response = self.client.post("/tracking/ticket/create/", data={"title": "X"}, follow=False)
self.assertRedirects(response, reverse("ticket_detail", kwargs={"pk": created_ticket.pk}))
```

### Assert contains / assertNotContains

```python
self.assertContains(response, "Expected text")
self.assertContains(response, "link text", status_code=200)
self.assertContains(response, "link text", count=2)  # appears exactly twice
self.assertNotContains(response, "Hidden text")
```

## Error and edge-case testing

- **401:** Unauthenticated access to API and HTML views.
- **404:** Non-existent resources (ticket, project, sprint).
- **409:** Invalid state transitions via `/transition/`.
- **400:** Validation errors (e.g. PATCH state on API ticket, missing required fields).
- **405:** HTTP method not allowed (POST on GET-only endpoint, etc.).

```python
def test_ticket_404(self):
    self.client.force_login(self.user)
    response = self.client.get("/tracking/api/tickets/99999/")
    self.assertEqual(response.status_code, 404)

def test_ticket_transition_invalid(self):
    ticket = Ticket.objects.create(..., state=Ticket.State.OPEN)
    self.client.force_login(self.user)
    response = self.client.post(
        f"/tracking/api/tickets/{ticket.pk}/transition/",
        content_type="application/json",
        data={"state": "unknown_state"}
    )
    self.assertEqual(response.status_code, 400)
```

## Model testing patterns

```python
from django.test import TestCase
from tracking.models import Project, Ticket, Sprint, Comment, Attachment

class ModelTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(name="Test Project", key="TST")
        self.sprint = Sprint.objects.create(name="Sprint 1", project=self.project)

    def test_ticket_creation(self):
        ticket = Ticket.objects.create(
            title="Test Ticket",
            project=self.project,
            state=Ticket.State.OPEN,
            sprint=self.sprint,
        )
        self.assertEqual(ticket.project, self.project)
        self.assertEqual(ticket.state, Ticket.State.OPEN)

    def test_ticket_relations_symmetric(self):
        t1 = Ticket.objects.create(title="T1", project=self.project)
        t2 = Ticket.objects.create(title="T2", project=self.project)
        TicketRelation.objects.create(ticket_a=t1, ticket_b=t2, relation_type="blocked_by")
        self.assertTrue(TicketRelation.objects.filter(ticket_a=t1, ticket_b=t2).exists())
        self.assertTrue(TicketRelation.objects.filter(ticket_a=t2, ticket_b=t1, relation_type="related_to").exists())

    def test_relation_deletion_both_ways(self):
        rel = TicketRelation.objects.create(ticket_a=self.t1, ticket_b=self.t2)
        pk = rel.pk
        TicketRelation.objects.filter(pk=pk).delete()
        self.assertFalse(TicketRelation.objects.filter(pk=pk).exists())
        # Check reverse was also cleaned up
        remaining = TicketRelation.objects.filter(
            Q(ticket_a=self.t2, ticket_b=self.t1) | Q(ticket_a=self.t1, ticket_b=self.t2)
        )
        self.assertEqual(remaining.count(), 0)
```

## What NOT to do

- DO NOT assume which decorators a view has — always read `tracking/views.py` or `tracking/api.py` to confirm.
- DO NOT assume API response structure — check `tracking/api.py` for the exact JSON shape.
- DO NOT skip testing error paths (401, 404, 409, 400). Test both success AND failure.
- DO NOT forget `@override_settings(TRACKING_API_TOKEN=...)` on API tests.
- DO NOT use `self.client.login(username, password)` for session-based tests — use `self.client.force_login(user)` which is simpler and more reliable.
- DO NOT assume state transitions work the way `test_models.py` does — always check the model definition for `TRANSITIONS`.
- DO NOT forget that TicketRelation deletes must remove both directions.
- DO NOT delete or modify the backlog sprint in any test — it must always exist (pk=1).

## Workflow

1. Read AGENTS.md for project conventions.
2. Read the relevant source files (models, views, API) to understand boundaries.
3. Write tests covering: success paths, auth guards, validation errors, edge cases.
4. Run `./.venv/bin/python3.12 manage.py test tracking.tests.test_<module>` first for quick feedback.
5. Run `./.venv/bin/python3.12 manage.py test tracking` for full regressions. Fix any failures.
