from django.db import migrations,models
class Migration(migrations.Migration):
 dependencies=[("pos","0005_daily_tokens_branch_identity")]
 operations=[migrations.AlterField(model_name="membership",name="role",field=models.CharField(max_length=10,choices=[("admin","Admin"),("staff","Cashier (legacy)"),("cashier","Cashier"),("chef","Chef"),("partner","Partner / guest")]))]
