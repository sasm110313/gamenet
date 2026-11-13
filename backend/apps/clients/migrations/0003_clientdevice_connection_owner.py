from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("clients", "0002_clientdevice_connection_status_and_more")]
    operations = [
        migrations.AddField(
            model_name="clientdevice", name="connection_owner",
            field=models.CharField(max_length=100, blank=True, default=""),
        ),
    ]
