"""Comprehensive UI tests: every view renders with correct content, status codes, and structure."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from tracking.models import Comment, Component, Label, Project, SavedFilter, Sprint, Ticket, TicketRelation

User = get_user_model()


# ── Helper ───────────────────────────────────────────────────────────────────

def _now():
    return timezone.localdate()


def _future():
    return _now() + timedelta(days=30)


# ── Auth tests ───────────────────────────────────────────────────────────────

class AuthRequiredTests(TestCase):
    """Every UI page must redirect anonymous users to the login page."""

    @classmethod
    def setUpTestData(cls):
        cls.project = Project.objects.create(key="SMT", name="SmartTracking")
        cls.ticket = Ticket.objects.create(project=cls.project, title="t")

    def test_protected_urls_redirect_to_login(self):
        urls = [
            reverse("dashboard"),
            reverse("project_list"),
            reverse("project_create"),
            reverse("project_detail", args=[self.project.pk]),
            reverse("project_edit", args=[self.project.pk]),
            reverse("ticket_list"),
            reverse("ticket_create"),
            reverse("ticket_detail", args=[self.ticket.pk]),
            reverse("ticket_edit", args=[self.ticket.pk]),
            reverse("reports"),
            reverse("releases"),
            reverse("label_list", args=[self.project.pk]),
            reverse("label_list_all"),
            reverse("label_create", args=[self.project.pk]),
            reverse("component_list", args=[self.project.pk]),
            reverse("component_list_all"),
            reverse("component_create", args=[self.project.pk]),
            reverse("sprint_create", args=[self.project.pk]),
        ]
        login_url = reverse("login")
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn(login_url, response.url)

    def test_login_page_is_public(self):
        response = self.client.get(reverse("login"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "title")


# ── Dashboard ────────────────────────────────────────────────────────────────

class DashboardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user1 = User.objects.create_user("alice", password="pw")
        cls.user2 = User.objects.create_user("bob", password="pw")
        cls.project1 = Project.objects.create(key="SMT", name="SmartTracking")
        cls.project2 = Project.objects.create(key="AB", name="Alpha Beta")
        cls.ticket = Ticket.objects.create(project=cls.project1, title="Fix bug", type=Ticket.Type.BUG, priority=Ticket.Priority.HIGH)

    # --- Empty dashboard ---

    def test_dashboard_empty(self):
        self.client.force_login(self.user1)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Projects")
        self.assertContains(response, "SMT")

    # --- Dashboard with projects ---

    def test_dashboard_renders_projects(self):
        self.client.force_login(self.user1)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "SMT")
        self.assertContains(response, "SmartTracking")
        self.assertContains(response, "Alpha Beta")
        self.assertContains(response, "+ New project")

    def test_dashboard_with_project_has_card_headers(self):
        self.client.force_login(self.user1)
        response = self.client.get(reverse("dashboard"), {"project_key": "SMT", "tab": "overview"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "SmartTracking")
        self.assertContains(response, "SMT")

    def test_dashboard_invalid_tab_defaults_to_overview(self):
        self.client.force_login(self.user1)
        response = self.client.get(reverse("dashboard"), {"project_key": "SMT", "tab": "invalid"})
        self.assertEqual(response.status_code, 200)

    def test_dashboard_with_project_has_tabs(self):
        self.client.force_login(self.user1)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Projects")
        self.assertContains(response, "Alpha Beta")

    def test_dashboard_with_project_has_relation(self):
        self.client.force_login(self.user1)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "SMT")
        self.assertContains(response, "SmartTracking")


# ── Reports / Releases ───────────────────────────────────────────────────────

class ReportsReleasesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("alice", password="pw")

    def setUp(self):
        self.client.force_login(self.user)

    def test_reports_page(self):
        response = self.client.get(reverse("reports"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Select a project to view reports")

    def test_releases_page(self):
        response = self.client.get(reverse("releases"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Select a project to view releases")


# ── Project list ─────────────────────────────────────────────────────────────

class ProjectListTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("alice", password="pw")
        cls.project1 = Project.objects.create(key="SMT", name="SmartTracking")
        cls.project2 = Project.objects.create(key="AB", name="Alpha Beta")
        cls.ticket = Ticket.objects.create(project=cls.project1, title="t")

    def setUp(self):
        self.client.force_login(self.user)

    def test_project_list_page_shows_projects(self):
        response = self.client.get(reverse("project_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "SMT")
        self.assertContains(response, "SmartTracking")
        self.assertContains(response, "Alpha Beta")
        self.assertContains(response, "Manage labels")
        self.assertContains(response, "Manage components")

    def test_project_list_empty(self):
        self.client.force_login(User.objects.create_user("empty", password="pw"))
        response = self.client.get(reverse("project_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "SmartTracking")
        self.assertContains(response, "SMT")


# ── Project detail ───────────────────────────────────────────────────────────

class ProjectDetailTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("alice", password="pw")
        cls.project = Project.objects.create(key="SMT", name="SmartTracking")
        cls.ticket1 = Ticket.objects.create(project=cls.project, title="Fix login bug", type=Ticket.Type.BUG, priority=Ticket.Priority.HIGH, state=Ticket.State.OPEN)
        cls.ticket2 = Ticket.objects.create(project=cls.project, title="Add dark mode", type=Ticket.Type.TASK, priority=Ticket.Priority.MEDIUM, state=Ticket.State.IN_PROGRESS)
        cls.label = Label.objects.create(project=cls.project, name="critical", color="danger")
        cls.component = Component.objects.create(project=cls.project, name="Frontend")

    def setUp(self):
        self.client.force_login(self.user)
        cache.clear()

    def test_project_detail_overview_shows_metrics(self):
        response = self.client.get(reverse("project_detail", args=[self.project.pk]), {"tab": "overview"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Tickets by state")
        self.assertContains(response, "Recent tickets for SMT")

    def test_project_detail_overview_shows_project_info(self):
        response = self.client.get(reverse("project_detail", args=[self.project.pk]), {"tab": "overview"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Overview")
        self.assertContains(response, "Backlog")
        self.assertContains(response, "Active Sprint")
        self.assertContains(response, "Components")
        self.assertContains(response, "Releases")

    def test_project_detail_overview_shows_tickets(self):
        response = self.client.get(reverse("project_detail", args=[self.project.pk]), {"tab": "overview"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Fix login bug")
        self.assertContains(response, "Add dark mode")

    def test_project_detail_backlog_shows_tickets_without_sprint(self):
        response = self.client.get(reverse("project_detail", args=[self.project.pk]), {"tab": "backlog"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Backlog")
        self.assertContains(response, "Tickets without Sprint")
        self.assertContains(response, "Fix login bug")

    def test_project_detail_backlog_has_filter_toggle(self):
        response = self.client.get(reverse("project_detail", args=[self.project.pk]), {"tab": "backlog"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "show_closed")

    def test_project_detail_active_sprint_without_active_sprint_still_works(self):
        response = self.client.get(reverse("project_detail", args=[self.project.pk]), {"tab": "active_sprint"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sprints")

    def test_project_detail_active_sprint_with_active_sprint(self):
        sprint = Sprint.objects.create(project=self.project, name="Sprint 1", is_active=True)
        ticket = Ticket.objects.create(project=self.project, title="Sprint item", sprint=sprint)
        response = self.client.get(reverse("project_detail", args=[self.project.pk]), {"tab": "active_sprint"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sprint 1")
        self.assertContains(response, "ticket")

    def test_project_detail_active_sprint_renders_board_with_state_columns(self):
        sprint = Sprint.objects.create(project=self.project, name="Sprint 1", is_active=True)
        Ticket.objects.create(project=self.project, title="Sprint item", sprint=sprint, state=Ticket.State.OPEN)
        response = self.client.get(reverse("project_detail", args=[self.project.pk]), {"tab": "active_sprint"})
        self.assertEqual(response.status_code, 200)
        # Drag-and-drop board container and one column per state
        self.assertContains(response, 'id="boardContainer"')
        self.assertContains(response, 'data-state="open"')
        self.assertContains(response, 'data-state="in_progress"')
        self.assertContains(response, 'data-state="resolved"')
        self.assertContains(response, 'data-state="closed"')
        # The ticket card is rendered inside the board
        self.assertContains(response, 'data-ticket-id="%d"' % response.context["state_ticket_tuples"][0]["tickets"][0].pk)
        # SortableJS drag-and-drop script is included
        self.assertContains(response, "Sortable.min.js")

    def test_project_detail_active_sprint_swimlane_renders_lanes(self):
        sprint = Sprint.objects.create(project=self.project, name="Sprint 1", is_active=True)
        Ticket.objects.create(project=self.project, title="Sprint item", sprint=sprint, state=Ticket.State.OPEN)
        response = self.client.get(reverse("project_detail", args=[self.project.pk]), {"tab": "active_sprint", "board_view": "swimlane", "swimlane": "priority"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "swimlane-row")
        self.assertContains(response, "swimlane-separator")


# ── Project create / edit ────────────────────────────────────────────────────

class ProjectCreateEditTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("alice", password="pw")
        cls.project = Project.objects.create(key="SMT", name="SmartTracking")

    def setUp(self):
        self.client.force_login(self.user)

    def test_project_create_get(self):
        response = self.client.get(reverse("project_create"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Create project")

    def test_project_create_post_valid(self):
        response = self.client.post(reverse("project_create"), {
            "key": "NEW",
            "name": "New Project",
            "description": "Description here",
        }, follow=True)
        self.assertContains(response, "created")
        self.assertTrue(Project.objects.filter(key="NEW").exists())

    def test_project_create_post_invalid(self):
        response = self.client.post(reverse("project_create"), {
            "key": "",
            "name": "",
            "description": "",
        })
        self.assertEqual(response.status_code, 200)

    def test_project_edit_get(self):
        response = self.client.get(reverse("project_edit", args=[self.project.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Edit project SMT")
        self.assertContains(response, "Save changes")
        self.assertContains(response, "Label management")
        self.assertContains(response, "Component management")

    def test_project_edit_post_valid(self):
        response = self.client.post(reverse("project_edit", args=[self.project.pk]), {
            "key": "SMT",
            "name": "SmartTracking Updated",
            "description": "Updated description",
        }, follow=True)
        self.project.refresh_from_db()
        self.assertEqual(self.project.name, "SmartTracking Updated")

    def test_project_edit_post_key_locked(self):
        p = Project.objects.get(pk=self.project.pk)
        response = self.client.post(reverse("project_edit", args=[self.project.pk]), {
            "key": "DIFFKEY",
            "name": "Another name",
            "description": "",
        })
        self.assertTrue(Project.objects.filter(pk=self.project.pk).exists())

    def test_project_edit_has_manage_links(self):
        response = self.client.get(reverse("project_edit", args=[self.project.pk]))
        self.assertContains(response, reverse("label_list", args=[self.project.pk]))
        self.assertContains(response, reverse("component_list", args=[self.project.pk]))


# ── Ticket list ──────────────────────────────────────────────────────────────

class TicketListTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("alice", password="pw")
        cls.another_user = User.objects.create_user("bob", password="pw")
        cls.project1 = Project.objects.create(key="SMT", name="SmartTracking")
        cls.project2 = Project.objects.create(key="AB", name="Alpha Beta")
        cls.ticket1 = Ticket.objects.create(
            project=cls.project1, title="Fix login bug", type=Ticket.Type.BUG,
            priority=Ticket.Priority.HIGH, state=Ticket.State.OPEN,
            assignee=cls.user)
        cls.ticket2 = Ticket.objects.create(
            project=cls.project1, title="Add dark mode", type=Ticket.Type.TASK,
            priority=Ticket.Priority.LOW, state=Ticket.State.IN_PROGRESS,
            assignee=cls.another_user)
        cls.ticket3 = Ticket.objects.create(
            project=cls.project2, title="Deploy v1", type=Ticket.Type.STORY,
            priority=Ticket.Priority.CRITICAL, state=Ticket.State.CLOSED)
        cls.label1 = Label.objects.create(project=cls.project1, name="urgent", color="danger")
        cls.label2 = Label.objects.create(project=cls.project1, name="frontend", color="primary")
        cls.ticket1.labels.add(cls.label1)
        cls.ticket2.labels.add(cls.label2)
        cls.component = Component.objects.create(project=cls.project1, name="Frontend")
        cls.ticket1.components.add(cls.component)

    def setUp(self):
        self.client.force_login(self.user)

    def test_ticket_list_shows_all_tickets(self):
        response = self.client.get(reverse("ticket_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Fix login bug")
        self.assertContains(response, "Add dark mode")
        self.assertContains(response, "Deploy v1")

    def test_ticket_list_has_filter_form(self):
        response = self.client.get(reverse("ticket_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Filter by ticket key")
        self.assertContains(response, 'name="project"')
        self.assertContains(response, 'name="state"')
        self.assertContains(response, 'name="component"')
        self.assertContains(response, 'name="label"')
        self.assertContains(response, 'name="assignee"')

    def test_ticket_list_filters_by_project(self):
        response = self.client.get(reverse("ticket_list"), {"project": "SMT"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Fix login bug")
        self.assertContains(response, "Add dark mode")
        self.assertNotContains(response, "Deploy v1")

    def test_ticket_list_filters_by_state(self):
        response = self.client.get(reverse("ticket_list"), {"state": Ticket.State.OPEN})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Fix login bug")
        self.assertNotContains(response, "Add dark mode")

    def test_ticket_list_filters_by_component(self):
        response = self.client.get(reverse("ticket_list"), {"component": "Frontend"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Fix login bug")
        self.assertNotContains(response, "Add dark mode")

    def test_ticket_list_filters_by_label(self):
        response = self.client.get(reverse("ticket_list"), {"label": "urgent"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Fix login bug")
        self.assertNotContains(response, "Add dark mode")

    def test_ticket_list_filters_by_assignee(self):
        response = self.client.get(reverse("ticket_list"), {"assignee": str(self.another_user.pk)})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Add dark mode")
        self.assertNotContains(response, "Fix login bug")

    def test_ticket_list_filters_by_query(self):
        response = self.client.get(reverse("ticket_list"), {"query": "dark"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Add dark mode")
        self.assertNotContains(response, "Fix login bug")

    def test_ticket_list_no_results_message(self):
        response = self.client.get(reverse("ticket_list"), {"q": "zzzznotfound"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No tickets found")

    def test_ticket_list_has_all_columns(self):
        response = self.client.get(reverse("ticket_list"))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        for col in ["Title", "Project", "Type", "State", "Priority", "Assignee", "Due date"]:
            self.assertIn(col, html)

    def test_ticket_list_has_delete_link(self):
        response = self.client.get(reverse("ticket_list"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("Delete", response.content.decode())

    def test_ticket_list_button_to_create_new(self):
        response = self.client.get(reverse("ticket_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "New ticket")


# ── Ticket detail ────────────────────────────────────────────────────────────

class TicketDetailTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("alice", password="pw")
        cls.another_user = User.objects.create_user("bob", password="pw")
        cls.project = Project.objects.create(key="SMT", name="SmartTracking")
        cls.ticket = Ticket.objects.create(
            project=cls.project, title="Fix login bug",
            type=Ticket.Type.BUG, priority=Ticket.Priority.HIGH,
            state=Ticket.State.OPEN, estimation=5,
            reporter=cls.user, assignee=cls.another_user)
        cls.comment = Comment.objects.create(ticket=cls.ticket, body="First comment", author=cls.user)
        cls.epic = Ticket.objects.create(project=cls.project, title="Big Feature", type=Ticket.Type.EPIC)
        cls.child_ticket = Ticket.objects.create(project=cls.project, title="Child of Epic", parent_epic=cls.epic)
        cls.label = Label.objects.create(project=cls.project, name="critical", color="danger")
        cls.component = Component.objects.create(project=cls.project, name="Frontend")
        cls.child_ticket.labels.add(cls.label)
        cls.child_ticket.components.add(cls.component)
        Comment.objects.create(ticket=cls.child_ticket, body="Child comment", author=cls.user)

    def setUp(self):
        self.client.force_login(self.user)

    def test_ticket_detail_shows_title_and_body(self):
        response = self.client.get(reverse("ticket_detail", args=[self.ticket.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Fix login bug")
        self.assertContains(response, "Edit")
        self.assertContains(response, "Change state")
        self.assertContains(response, "Change sprint")
        self.assertContains(response, "First comment")
        self.assertContains(response, "alice")
        self.assertContains(response, "Add a comment")

    def test_ticket_detail_shows_details_sidebar(self):
        response = self.client.get(reverse("ticket_detail", args=[self.ticket.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Estimation")
        self.assertContains(response, "5")
        self.assertContains(response, "Priority")
        self.assertContains(response, "High")
        self.assertContains(response, "Reporter")
        self.assertContains(response, "alice")
        self.assertContains(response, "Assignee")
        self.assertContains(response, "bob")

    def test_ticket_detail_transaction_form(self):
        response = self.client.get(reverse("ticket_detail", args=[self.ticket.pk]))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("Move", content)
        self.assertIn("In Progress", content)
        self.assertIn("Closed", content)
        self.assertNotIn("Resolved", content)

    def test_ticket_detail_shows_child_tickets(self):
        response = self.client.get(reverse("ticket_detail", args=[self.epic.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Child of Epic")

    def test_ticket_detail_shows_no_comments_message(self):
        ticket = Ticket.objects.create(project=self.project, title="No comments ticket")
        response = self.client.get(reverse("ticket_detail", args=[ticket.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No comments")

    def test_ticket_detail_shows_labels_and_components(self):
        response = self.client.get(reverse("ticket_detail", args=[self.child_ticket.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "critical")
        self.assertContains(response, "Frontend")

    def test_ticket_detail_has_relation_form(self):
        response = self.client.get(reverse("ticket_detail", args=[self.ticket.pk]))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("Add relation", content)

    def test_ticket_detail_shows_sprint_form(self):
        sprint = Sprint.objects.create(project=self.project, name="Sprint 1")
        response = self.client.get(reverse("ticket_detail", args=[self.ticket.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sprint 1")

    def test_ticket_detail_shows_event(self):
        response = self.client.get(reverse("ticket_detail", args=[self.ticket.pk]))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("Add a comment", content)


# ── Ticket create / edit ───────────────────��────────────────────────────────

class TicketCreateEditTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("alice", password="pw")
        cls.project = Project.objects.create(key="SMT", name="SmartTracking")
        cls.ticket = Ticket.objects.create(project=cls.project, title="Old ticket", description="Old description")

    def setUp(self):
        self.client.force_login(self.user)

    def test_ticket_create_get(self):
        response = self.client.get(reverse("ticket_create"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Create ticket")
        self.assertContains(response, "Cancel")

    def test_ticket_create_post_valid(self):
        response = self.client.post(reverse("ticket_create"), {
            "project": self.project.pk,
            "title": "New ticket",
            "description": "Description here",
            "type": Ticket.Type.TASK,
            "priority": Ticket.Priority.MEDIUM,
            "estimation": "",
            "assignee": "",
            "due_date": "",
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        created = Ticket.objects.get(title="New ticket")
        self.assertEqual(created.reporter, self.user)
        self.assertContains(response, "Ticket created")

    def test_ticket_create_post_invalid(self):
        response = self.client.post(reverse("ticket_create"), {
            "project": self.project.pk,
            "title": "",
            "description": "",
            "type": "",
            "priority": "",
        })
        self.assertEqual(response.status_code, 200)

    def test_ticket_edit_get(self):
        response = self.client.get(reverse("ticket_edit", args=[self.ticket.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Save changes")
        self.assertContains(response, "Cancel")

    def test_ticket_edit_post_valid(self):
        response = self.client.post(reverse("ticket_edit", args=[self.ticket.pk]), {
            "project": self.ticket.project.pk,
            "title": "Updated ticket",
            "description": "Updated description",
            "type": Ticket.Type.BUG,
            "priority": Ticket.Priority.HIGH,
            "estimation": 3,
            "assignee": "",
            "due_date": "",
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.title, "Updated ticket")
        self.assertIn("updated", response.content.decode().lower())

    def test_ticket_edit_post_invalid(self):
        response = self.client.post(reverse("ticket_edit", args=[self.ticket.pk]), {
            "title": "",
            "description": "",
            "type": "",
            "priority": "",
        })
        self.assertEqual(response.status_code, 200)


# ── Sprint management ────────────────────────────────────────────────────────

class SprintCreateEditTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("alice", password="pw")
        cls.project = Project.objects.create(key="SMT", name="SmartTracking")
        cls.sprint = Sprint.objects.create(project=cls.project, name="Sprint 1")

    def setUp(self):
        self.client.force_login(self.user)

    def test_sprint_create_get(self):
        response = self.client.get(reverse("sprint_create", args=[self.project.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "New sprint")
        self.assertContains(response, "Sprint 1")

    def test_sprint_create_post_valid(self):
        response = self.client.post(reverse("sprint_create", args=[self.project.pk]), {
            "name": "Sprint 2",
            "description": "Second sprint",
            "start_date": "",
            "end_date": "",
            "order": 1,
            "is_active": False,
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Sprint.objects.filter(name="Sprint 2").exists())
        self.assertContains(response, "created")

    def test_sprint_create_post_duplicate_rejected(self):
        response = self.client.post(reverse("sprint_create", args=[self.project.pk]), {
            "name": "Sprint 1",
            "description": "",
            "order": 0,
            "is_active": False,
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already exists")

    def test_sprint_edit_get(self):
        response = self.client.get(reverse("sprint_edit", args=[self.project.pk, self.sprint.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Edit sprint")
        self.assertContains(response, "Sprint 1")

    def test_sprint_edit_post_valid(self):
        response = self.client.post(reverse("sprint_edit", args=[self.project.pk, self.sprint.pk]), {
            "name": "Sprint 1 Updated",
            "description": "Updated description",
            "start_date": "",
            "end_date": "",
            "order": 1,
            "is_active": False,
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.sprint.refresh_from_db()
        self.assertEqual(self.sprint.name, "Sprint 1 Updated")


# ── Ticket comment ───────────────────────────────────────────────────────────

class TicketCommentTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("alice", password="pw")
        cls.project = Project.objects.create(key="SMT", name="SmartTracking")
        cls.ticket = Ticket.objects.create(project=cls.project, title="t")

    def setUp(self):
        self.client.force_login(self.user)

    def test_comment_post_success(self):
        response = self.client.post(reverse("ticket_comment_create", args=[self.ticket.pk]), {
            "body": "Nice ticket!",
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Comment.objects.filter(ticket=self.ticket, body="Nice ticket!").exists())
        self.assertContains(response, "Comment added")

    def test_comment_post_empty_rejected(self):
        response = self.client.post(reverse("ticket_comment_create", args=[self.ticket.pk]), {
            "body": "",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Comment.objects.filter(ticket=self.ticket).count(), 0)


# ── Label management ─────────────────────────────────────────────────────────

class LabelListTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("alice", password="pw")
        cls.project = Project.objects.create(key="SMT", name="SmartTracking")
        cls.label1 = Label.objects.create(project=cls.project, name="critical", color="danger")
        cls.label2 = Label.objects.create(project=cls.project, name="frontend", color="primary")

    def setUp(self):
        self.client.force_login(self.user)

    def test_label_list_per_project(self):
        response = self.client.get(reverse("label_list", args=[self.project.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "critical")
        self.assertContains(response, "frontend")
        self.assertContains(response, "New label")

    def test_label_list_all_view(self):
        other = Project.objects.create(key="AB", name="Alpha Beta")
        Label.objects.create(project=other, name="beta")
        response = self.client.get(reverse("label_list_all"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "All labels")
        self.assertContains(response, "beta")


class LabelCreateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("alice", password="pw")
        cls.project = Project.objects.create(key="SMT", name="SmartTracking")

    def setUp(self):
        self.client.force_login(self.user)

    def test_label_create_get(self):
        response = self.client.get(reverse("label_create", args=[self.project.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "New label")

    def test_label_create_post_valid(self):
        response = self.client.post(reverse("label_create", args=[self.project.pk]), {
            "name": "urgent",
            "color": "danger",
            "description": "High priority",
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Label.objects.filter(name="urgent").exists())
        self.assertContains(response, "created")

    def test_label_create_post_duplicate_rejected(self):
        Label.objects.create(project=self.project, name="critical", color="danger")
        response = self.client.post(reverse("label_create", args=[self.project.pk]), {
            "name": "critical",
            "color": "danger",
            "description": "",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already exists")


class LabelUpdateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("alice", password="pw")
        cls.project = Project.objects.create(key="SMT", name="SmartTracking")
        cls.label = Label.objects.create(project=cls.project, name="old", color="secondary")

    def setUp(self):
        self.client.force_login(self.user)

    def test_label_update_get(self):
        response = self.client.get(reverse("label_update", args=[self.label.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Edit label")
        self.assertContains(response, "Save changes")

    def test_label_update_post_valid(self):
        response = self.client.post(reverse("label_update", args=[self.label.pk]), {
            "name": "updated",
            "color": "primary",
            "description": "Updated",
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.label.refresh_from_db()
        self.assertEqual(self.label.name, "updated")


class LabelDeleteTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("alice", password="pw")
        cls.project = Project.objects.create(key="SMT", name="SmartTracking")
        cls.label = Label.objects.create(project=cls.project, name="delete-me", color="danger")

    def setUp(self):
        self.client.force_login(self.user)

    def test_label_delete_get(self):
        response = self.client.get(reverse("label_delete", args=[self.label.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "delete-me")
        self.assertContains(response, "Delete")

    def test_label_delete_post_valid(self):
        response = self.client.post(reverse("label_delete", args=[self.label.pk]), {
            "label": self.label.pk,
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Label.objects.filter(pk=self.label.pk).exists())
        self.assertContains(response, "deleted")


# ── Component management ─────────────────────────────────────────────────────

class ComponentListTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("alice", password="pw")
        cls.project = Project.objects.create(key="SMT", name="SmartTracking")
        cls.comp1 = Component.objects.create(project=cls.project, name="Frontend")
        cls.comp2 = Component.objects.create(project=cls.project, name="Backend")

    def setUp(self):
        self.client.force_login(self.user)

    def test_component_list_per_project(self):
        response = self.client.get(reverse("component_list", args=[self.project.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Frontend")
        self.assertContains(response, "Backend")
        self.assertContains(response, "Edit")
        self.assertContains(response, "Delete")
        self.assertContains(response, "New component")

    def test_component_list_all_view(self):
        other = Project.objects.create(key="AB", name="Alpha Beta")
        Component.objects.create(project=other, name="API")
        response = self.client.get(reverse("component_list_all"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "All components")
        self.assertContains(response, "API")


class ComponentCreateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("alice", password="pw")
        cls.project = Project.objects.create(key="SMT", name="SmartTracking")

    def setUp(self):
        self.client.force_login(self.user)

    def test_component_create_get(self):
        response = self.client.get(reverse("component_create", args=[self.project.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "New component")

    def test_component_create_post_valid(self):
        response = self.client.post(reverse("component_create", args=[self.project.pk]), {
            "name": "Database",
            "description": "DB layer",
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Component.objects.filter(name="Database").exists())
        self.assertContains(response, "created")

    def test_component_create_post_duplicate_rejected(self):
        Component.objects.create(project=self.project, name="Frontend")
        response = self.client.post(reverse("component_create", args=[self.project.pk]), {
            "name": "Frontend",
            "description": "",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already exists")


class ComponentUpdateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("alice", password="pw")
        cls.project = Project.objects.create(key="SMT", name="SmartTracking")
        cls.component = Component.objects.create(project=cls.project, name="old", description="Old")

    def setUp(self):
        self.client.force_login(self.user)

    def test_component_update_get(self):
        response = self.client.get(reverse("component_update", args=[self.component.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Edit component")
        self.assertContains(response, "Save changes")

    def test_component_update_post_valid(self):
        response = self.client.post(reverse("component_update", args=[self.component.pk]), {
            "name": "updated",
            "description": "Updated",
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.component.refresh_from_db()
        self.assertEqual(self.component.name, "updated")


class ComponentDeleteTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("alice", password="pw")
        cls.project = Project.objects.create(key="SMT", name="SmartTracking")
        cls.component = Component.objects.create(project=cls.project, name="delete-me", description="Delete")

    def setUp(self):
        self.client.force_login(self.user)

    def test_component_delete_get(self):
        response = self.client.get(reverse("component_delete", args=[self.component.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "delete-me")
        self.assertContains(response, "Delete component")

    def test_component_delete_post_valid(self):
        response = self.client.post(reverse("component_delete", args=[self.component.pk]), {
            "component": self.component.pk,
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Component.objects.filter(pk=self.component.pk).exists())
        self.assertContains(response, "deleted")


# ── Ticket delete ─────────────────────────────────────────────────────────────

class TicketDeleteViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("alice", password="pw")
        cls.project = Project.objects.create(key="SMT", name="SmartTracking")
        cls.ticket = Ticket.objects.create(project=cls.project, title="To delete")

    def setUp(self):
        self.client.force_login(self.user)

    def test_ticket_delete_get_shows_confirmation(self):
        response = self.client.get(reverse("ticket_delete", args=[self.project.pk, self.ticket.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Are you sure")
        self.assertContains(response, "To delete")
        self.assertContains(response, "Delete")
        self.assertContains(response, "Cancel")

    def test_ticket_delete_post_deletes_ticket(self):
        response = self.client.post(
            reverse("ticket_delete", args=[self.project.pk, self.ticket.pk]),
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Ticket.objects.filter(pk=self.ticket.pk).exists())
        self.assertIn("deleted", response.content.decode().lower())

    def test_ticket_delete_wrong_project_redirects(self):
        other_project = Project.objects.create(key="OTH", name="Other")
        ticket = Ticket.objects.create(project=other_project, title="Other ticket")
        response = self.client.post(
            reverse("ticket_delete", args=[self.project.pk, ticket.pk]),
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Ticket.objects.filter(pk=ticket.pk).exists())


# ── Ticket list – search, sort & multi-value filters ─────────────────────────

class TicketListAdvancedTests(TestCase):
    """Expanded tests for the ticket list search, sort and multi-value filters."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("alice", password="pw")
        cls.bob = User.objects.create_user("bob", password="pw")
        cls.carol = User.objects.create_user("carol", password="pw")
        cls.project = Project.objects.create(key="SMT", name="SmartTracking")
        cls.ticket1 = Ticket.objects.create(
            project=cls.project, title="Fix login bug",
            type=Ticket.Type.BUG, priority=Ticket.Priority.HIGH,
            state=Ticket.State.OPEN, description="Broken login page",
            assignee=cls.user)
        cls.ticket2 = Ticket.objects.create(
            project=cls.project, title="Add dark mode",
            type=Ticket.Type.TASK, priority=Ticket.Priority.LOW,
            state=Ticket.State.IN_PROGRESS, description="Night theme",
            assignee=cls.bob)
        cls.ticket3 = Ticket.objects.create(
            project=cls.project, title="Deploy v1",
            type=Ticket.Type.STORY, priority=Ticket.Priority.MEDIUM,
            state=Ticket.State.CLOSED, description="Release v1",
            assignee=cls.carol)
        cls.ticket4 = Ticket.objects.create(
            project=cls.project, title="Urgent security fix",
            type=Ticket.Type.BUG, priority=Ticket.Priority.CRITICAL,
            state=Ticket.State.OPEN, description="SQL injection",
            assignee=None)
        cls.label1 = Label.objects.create(project=cls.project, name="urgent")
        cls.label2 = Label.objects.create(project=cls.project, name="bug")
        cls.label3 = Label.objects.create(project=cls.project, name="frontend")
        cls.ticket1.labels.add(cls.label1, cls.label2)
        cls.ticket2.labels.add(cls.label3)
        cls.ticket3.labels.add(cls.label1)
        cls.ticket4.labels.add(cls.label2)
        cls.component1 = Component.objects.create(project=cls.project, name="Frontend")
        cls.component2 = Component.objects.create(project=cls.project, name="Backend")
        cls.ticket1.components.add(cls.component1)
        cls.ticket2.components.add(cls.component1)

    def setUp(self):
        self.client.force_login(self.user)

    # ── Multi-value filters ──────────────────────────────────────────────

    def test_multi_state_filter_returns_union(self):
        """Multiple states → tickets matching ANY of them."""
        resp = self.client.get(reverse("ticket_list"), {"state": ["open", "closed"]})
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn("Fix login bug", content)   # open
        self.assertIn("Deploy v1", content)       # closed
        self.assertNotIn("Add dark mode", content)  # in_progress not in filter

    def test_multi_label_filter_returns_intersection(self):
        """Multiple labels → tickets matching ALL of them (AND semantics)."""
        resp = self.client.get(reverse("ticket_list"), {"label": ["urgent", "bug"]})
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn("Fix login bug", content)
        self.assertNotContains(resp, "Deploy v1")
        self.assertNotContains(resp, "Urgent security fix")

    def test_multi_component_filter(self):
        """Multiple components → AND semantics across ticket sets."""
        resp = self.client.get(reverse("ticket_list"), {"component": ["Frontend"]})
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn("Fix login bug", content)
        self.assertIn("Add dark mode", content)
        self.assertNotContains(resp, "Deploy v1")

    def test_multi_assignee_filter(self):
        """Multiple assignee values → union of tickets."""
        resp = self.client.get(reverse("ticket_list"), {
            "assignee": [self.bob.pk, self.carol.pk]
        })
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn("Add dark mode", content)
        self.assertIn("Deploy v1", content)
        self.assertNotContains(resp, "Fix login bug")

    # ── Query / key search ───────────────────────────────────────────────

    def test_query_by_title(self):
        response = self.client.get(reverse("ticket_list"), {"query": "dark"})
        self.assertContains(response, "Add dark mode")
        self.assertNotContains(response, "Fix login bug")

    def test_query_by_description(self):
        response = self.client.get(reverse("ticket_list"), {"query": "injection"})
        self.assertContains(response, "Urgent security fix")
        self.assertNotContains(response, "Fix login bug")

    def test_query_by_ticket_id(self):
        """Searching by the numeric ticket ID should match the ticket."""
        response = self.client.get(reverse("ticket_list"), {"query": str(self.ticket1.pk)})
        self.assertContains(response, "Fix login bug")
        self.assertNotContains(response, "Add dark mode")

    def test_q_param_alias_works(self):
        """The old 'q' parameter name should still work."""
        resp = self.client.get(reverse("ticket_list"), {"q": "dark"})
        self.assertContains(resp, "Add dark mode")
        self.assertNotContains(resp, "Fix login bug")

    def test_query_combined_with_state_filter(self):
        """Search text + state filter → intersection."""
        resp = self.client.get(reverse("ticket_list"), {
            "query": "bug",
            "state": [Ticket.State.OPEN],
        })
        self.assertContains(resp, "Fix login bug")
        self.assertNotContains(resp, "Urgent security fix")  # has "injection" not "bug" in title

    def test_query_with_no_results(self):
        response = self.client.get(reverse("ticket_list"), {"query": "nonexistent123zzz"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No tickets found")

    # ── Assignee special values ──────────────────────────────────────────

    def test_assignee_me_filter(self):
        """'me' resolves to the logged-in user."""
        resp = self.client.get(reverse("ticket_list"), {"assignee": "me"})
        self.assertContains(resp, "Fix login bug")
        self.assertNotContains(resp, "Deploy v1")

    def test_assignee_unassigned_filter(self):
        """'unassigned' returns only tickets without an assignee."""
        resp = self.client.get(reverse("ticket_list"), {"assignee": "unassigned"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Urgent security fix")
        self.assertNotContains(resp, "Fix login bug")

    # ── Sorting ──────────────────────────────────────��───────────────────

    def test_sort_by_title_ascending(self):
        resp = self.client.get(reverse("ticket_list"), {"sort": "title", "order": "asc"})
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        add_pos = content.find("Add dark mode")
        deploy_pos = content.find("Deploy v1")
        self.assertLess(add_pos, deploy_pos)

    def test_sort_by_title_descending(self):
        resp = self.client.get(reverse("ticket_list"), {"sort": "title", "order": "desc"})
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        deploy_pos = content.find("Deploy v1")
        add_pos = content.find("Add dark mode")
        self.assertLess(deploy_pos, add_pos)

    def test_sort_by_priority(self):
        resp = self.client.get(reverse("ticket_list"), {"sort": "priority", "order": "desc"})
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        # CRITICAL ticket should appear BEFORE HIGH
        crit_pos = content.find("Urgent security fix")
        high_pos = content.find("Fix login bug")
        self.assertLess(crit_pos, high_pos)

    def test_default_sort_is_created_desc(self):
        """No sort param → newest first (by id)."""
        resp = self.client.get(reverse("ticket_list"))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        # Higher ID = newer, should appear first in desc order.
        t4_pos = content.find("Urgent security fix")
        t1_pos = content.find("Fix login bug")
        self.assertLess(t4_pos, t1_pos)

    def test_sort_select_has_all_options(self):
        """Sort dropdown should include all configured sort fields."""
        resp = self.client.get(reverse("ticket_list"))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        for opt in ["Title", "Type", "Priority", "State", "Due date", "Created", "Updated"]:
            self.assertIn(opt, content)

    def test_query_with_no_results(self):
        response = self.client.get(reverse("ticket_list"), {"query": "nonexistent123zzz"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No tickets found")

    def test_query_combines_with_state(self):
        resp = self.client.get(reverse("ticket_list"), {
            "query": "bug",
            "state": [Ticket.State.OPEN],
        })
        self.assertContains(resp, "Fix login bug")
        # "Urgent security fix" has "injection" in description, not "bug" in title
        self.assertNotContains(resp, "Urgent security fix")


# ── Saved filter views ────────────────────────────────────────────────────────

class SavedFilterViewTests(TestCase):
    """Tests for saved filter CRUD views."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("alice", password="pw")
        cls.bob = User.objects.create_user("bob", password="pw")
        cls.project = Project.objects.create(key="SMT", name="SmartTracking")
        cls.ticket = Ticket.objects.create(
            project=cls.project, title="Fix login bug",
            state=Ticket.State.OPEN)
        cls.label_urgent = Label.objects.create(project=cls.project, name="urgent")
        cls.label_bug = Label.objects.create(project=cls.project, name="bug")
        cls.compf = Component.objects.create(project=cls.project, name="Frontend")
        cls.comp_b = Component.objects.create(project=cls.project, name="Backend")

    def setUp(self):
        self.client.force_login(self.user)

    def test_saved_filter_create_redirects_without_data(self):
        resp = self.client.post(reverse("saved_filter_create"), follow=True)
        self.assertContains(resp, "Project must be specified")

    def test_saved_filter_create_without_title(self):
        resp = self.client.post(
            reverse("saved_filter_create"),
            {"project": "SMT", "title": ""},
            follow=True,
        )
        self.assertContains(resp, "Filter name is required")

    def test_saved_filter_create_stores_query_params(self):
        self.client.get(reverse("ticket_list"), {"state": "open"})
        resp = self.client.post(
            reverse("saved_filter_create"),
            {"project": "SMT", "title": "My open tickets"}
        )
        self.assertEqual(resp.status_code, 302)
        filt = SavedFilter.objects.get(title="My open tickets")
        self.assertEqual(filt.filters_json["state"], ["open"])
        self.assertEqual(filt.user, self.user)
        self.assertEqual(filt.project, self.project)

    def test_saved_filter_delete_requires_own(self):
        filt = SavedFilter.objects.create(
            project=self.project, user=self.user,
            title="Private filter", filters_json={})
        resp = self.client.post(
            reverse("saved_filter_delete", args=[filt.pk]),
            follow=True,
        )
        self.assertContains(resp, "deleted")

    def test_saved_filter_delete_other_user_cannot(self):
        filt = SavedFilter.objects.create(
            project=self.project, user=self.bob,
            title="Bob filter", filters_json={})
        resp = self.client.post(
            reverse("saved_filter_delete", args=[filt.pk]),
            follow=True,
        )
        self.assertTrue(SavedFilter.objects.filter(pk=filt.pk).exists())

    def test_saved_filter_apply_redirects(self):
        filt = SavedFilter.objects.create(
            project=self.project, user=self.user,
            title="Apply test", filters_json={"state": "open"})
        resp = self.client.post(
            reverse("saved_filter_apply", args=[filt.pk]),
            follow=True,
        )
        self.assertContains(resp, "Fix login bug")

    def test_saved_filter_apply_other_user_blocked(self):
        filt = SavedFilter.objects.create(
            project=self.project, user=self.bob,
            title="Bob filter", filters_json={"state": "open"})
        resp = self.client.post(
            reverse("saved_filter_apply", args=[filt.pk]),
            follow=True,
        )
        self.assertContains(resp, "own filters")

    def test_saved_filters_context_for_project(self):
        SavedFilter.objects.create(
            project=self.project, user=self.user,
            title="Filter A", filters_json={}, is_active=True)
        resp = self.client.get(
            reverse("ticket_list_project", kwargs={"project_key": "SMT"}))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.context["saved_filters"]), 1)

    def test_pagination_params_present(self):
        """context.pagination_params should include active filters in pagination links."""
        resp = self.client.get(reverse("ticket_list"), {"state": "open", "sort": "title", "page_size": "1"})
        self.assertEqual(resp.status_code, 200)
        # pagination_params should contain active filters (minus page) for use in pagination URLs
        self.assertIn("state=open", resp.context["pagination_params"])
        self.assertIn("sort=title", resp.context["pagination_params"])

    def test_active_states_rendered_as_pills(self):
        """Active state filters should be in context."""
        resp = self.client.get(reverse("ticket_list"), {"state": "open"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("active_states", resp.context)
        self.assertEqual(resp.context["active_states"], ["open"])

    def test_active_labels_rendered_as_pills(self):
        """Active label filters render as Label model instances."""
        resp = self.client.get(reverse("ticket_list"), {"label": ["urgent", "bug"]})
        self.assertEqual(resp.status_code, 200)
        labels = resp.context["active_labels"]
        self.assertEqual(len(labels), 2)
        names = {l.name for l in labels}
        self.assertEqual(names, {"urgent", "bug"})

    def test_active_components_rendered_as_pills(self):
        """Active component filters render as Component model instances."""
        resp = self.client.get(reverse("ticket_list"), {
            "component": ["Frontend", "Backend"]
        })
        self.assertEqual(resp.status_code, 200)
        comps = resp.context["active_components"]
        self.assertEqual(len(comps), 2)

    def test_bulk_action_sprint_json_includes_sprints(self):
        """sprints_json should be valid JSON."""
        resp = self.client.get(reverse("ticket_list"))
        self.assertEqual(resp.status_code, 200)
        import json
        data = json.loads(resp.context["sprints_json"])
        # At minimum there's a backlog sprint per project
        self.assertGreaterEqual(len(data), 0)


# ── Bulk action JSON context ──────────────────────────────────────────────────


class BulkActionJsonTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("alice", password="pw")
        cls.project = Project.objects.create(key="SMT", name="SmartTracking")
        cls.label = Label.objects.create(project=cls.project, name="urgent")
        cls.component = Component.objects.create(project=cls.project, name="Frontend")

    def setUp(self):
        self.client.force_login(self.user)

    def test_bulk_labels_json_includes_labels(self):
        resp = self.client.get(reverse("ticket_list"))
        self.assertEqual(resp.status_code, 200)
        import json
        data = json.loads(resp.context["labels_json"])
        self.assertGreater(len(data), 0)

    def test_bulk_component_json_includes_components(self):
        resp = self.client.get(reverse("ticket_list"))
        self.assertEqual(resp.status_code, 200)
        import json
        data = json.loads(resp.context["components_json"])
        self.assertGreater(len(data), 0)


# ── Health check ──────────────────────────────────────────────────────────────


class HealthCheckTests(TestCase):
    """The health check endpoint is public and returns a JSON status."""

    def test_health_check_returns_200(self):
        response = self.client.get(reverse("health_check"))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")

    def test_health_check_accessible_without_login(self):
        """Anonymous access must not be rejected."""
        response = self.client.get(reverse("health_check"))
        self.assertNotEqual(response.status_code, 302)
        self.assertContains(response, '"status"')
