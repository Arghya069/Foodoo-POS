from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [("pos", "0002_menu_item_details")]
    operations = [
        migrations.AddField(model_name="restaurant", name="logo_data", field=models.TextField(blank=True)),
        migrations.AddField(model_name="menuitem", name="food_type", field=models.CharField(max_length=20, default="veg", choices=[("veg","Veg"),("non_veg","Non Veg"),("egg","Egg"),("chicken","Chicken"),("mutton","Mutton"),("paneer","Paneer"),("mushroom","Mushroom"),("other","Other")])),
        migrations.AddField(model_name="menuitem", name="category", field=models.CharField(max_length=24, default="main_course", choices=[("snack","Snack"),("beverage","Beverage"),("combo","Combo"),("main_course","Main Course"),("starter","Starter"),("dessert","Dessert"),("breakfast","Breakfast"),("other","Other")])),
    ]
