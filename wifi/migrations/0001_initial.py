from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Network",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("ssid", models.CharField(max_length=64, verbose_name="Network name")),
                ("password", models.CharField(blank=True, max_length=128)),
                ("audience", models.CharField(choices=[("guests", "Everyone"), ("admins", "Signed-in admins only")],
                                              default="guests", max_length=10)),
                ("order", models.PositiveIntegerField(default=0)),
            ],
            options={"ordering": ("order", "id")},
        ),
        migrations.CreateModel(
            name="LegacyImport",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("done_at", models.DateTimeField(auto_now_add=True)),
            ],
        ),
    ]
