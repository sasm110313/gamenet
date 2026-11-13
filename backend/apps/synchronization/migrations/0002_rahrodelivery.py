from django.db import migrations, models
from django.utils import timezone


class Migration(migrations.Migration):
    dependencies = [("synchronization", "0001_initial")]
    operations = [
        migrations.CreateModel(
            name="RahroDelivery",
            fields=[
                ("session_id", models.UUIDField(primary_key=True, serialize=False)),
                ("payload", models.JSONField(default=dict)),
                ("attempts", models.PositiveIntegerField(default=0)),
                ("next_attempt_at", models.DateTimeField(default=timezone.now, db_index=True)),
                ("delivered_at", models.DateTimeField(null=True, blank=True)),
                ("last_error", models.TextField(blank=True)),
            ],
        ),
    ]
