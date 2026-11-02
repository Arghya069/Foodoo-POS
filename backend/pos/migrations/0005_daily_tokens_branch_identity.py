from django.db import migrations,models
import django.db.models.deletion

class Migration(migrations.Migration):
 dependencies=[("pos","0004_checkout_taxonomy_image")]
 operations=[
  migrations.AddField(model_name="restaurant",name="branch_code",field=models.SlugField(default="main",max_length=48)),
  migrations.AddField(model_name="restaurant",name="branch_name",field=models.CharField(default="Main",max_length=120)),
  migrations.AddField(model_name="restaurant",name="branch_type",field=models.CharField(choices=[("main","Main"),("branch","Branch")],default="main",max_length=12)),
  migrations.AddField(model_name="order",name="token_date",field=models.DateField(blank=True,null=True)),
  migrations.AddField(model_name="order",name="token_number",field=models.PositiveIntegerField(blank=True,null=True)),
  migrations.CreateModel(name="DailyTokenCounter",fields=[
   ("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name="ID")),
   ("service_date",models.DateField()),
   ("last_number",models.PositiveIntegerField(default=0)),
   ("serving_number",models.PositiveIntegerField(default=0)),
   ("restaurant",models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,to="pos.restaurant")),
  ]),
  migrations.AddConstraint(model_name="dailytokencounter",constraint=models.UniqueConstraint(fields=("restaurant","service_date"),name="unique_daily_token_counter")),
  migrations.AddConstraint(model_name="order",constraint=models.UniqueConstraint(fields=("restaurant","token_date","token_number"),name="unique_restaurant_daily_order_token")),
 ]
