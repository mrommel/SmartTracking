"""Test for sprint creation via UI."""
from django.test import TestCase, Client
from django.contrib.auth.models import User
from tracking.models import Project, Sprint


class SprintCreateViewTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username='testuser', password='testpass123')
        cls.project = Project.objects.create(key="SMT", name="SmartTracking")

    def test_sprint_create_via_ui(self):
        """Test creating a sprint via the UI form."""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.post(
            f'/tracking/projects/{self.project.pk}/sprints/new/',
            {
                'name': 'Sprint 1',
                'description': 'Test sprint',
                'start_date': '2024-01-01',
                'end_date': '2024-01-14',
                'order': 0,
                'is_active': False,
            },
        )
        # Should redirect on success
        self.assertEqual(response.status_code, 302)
        # Sprint should be created
        self.assertTrue(Sprint.objects.filter(project=self.project, name='Sprint 1').exists())

    def test_sprint_create_form_validation(self):
        """Test that SprintForm validates correctly for new sprints."""
        from tracking.forms import SprintForm
        form = SprintForm(data={
            'name': 'Sprint 1',
            'description': 'Test sprint',
            'start_date': '2024-01-01',
            'end_date': '2024-01-14',
            'order': 0,
            'is_active': False,
        }, project=self.project)
        self.assertTrue(form.is_valid(), form.errors)
        sprint = form.save()
        self.assertEqual(sprint.project, self.project)
        self.assertEqual(sprint.name, 'Sprint 1')

