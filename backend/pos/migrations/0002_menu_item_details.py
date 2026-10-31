from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [("pos", "0001_initial")]
    operations = [
        migrations.AddField(model_name="menuitem", name="description", field=models.TextField(blank=True)),
        migrations.AddField(model_name="menuitem", name="image_url", field=models.URLField(max_length=1000, blank=True)),
    ]
