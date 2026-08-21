from django.apps import AppConfig


class TrackingConfig(AppConfig):
    name = 'tracking'

    def ready(self) -> None:
        import tracking.signals  # noqa: F401
