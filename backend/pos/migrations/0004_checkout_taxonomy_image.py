from django.db import migrations, models

def classify_legacy(apps, schema_editor):
    MenuItem=apps.get_model("pos","MenuItem")
    for item in MenuItem.objects.all().iterator():
        if item.food_type in ("egg","chicken","mutton"):
            item.food_subtype=item.food_type
            item.food_type="non_veg"
        elif item.food_type in ("paneer","mushroom"):
            item.food_subtype=item.food_type
            item.food_type="veg"
        elif item.food_type=="other":
            item.food_subtype="other"
            item.food_type="veg"
        item.save(update_fields=["food_type","food_subtype"])

class Migration(migrations.Migration):
    dependencies=[("pos","0003_menu_taxonomy_restaurant_logo")]
    operations=[
        migrations.AddField(model_name="menuitem",name="food_subtype",field=models.CharField(max_length=20,default="none",choices=[("none","None"),("egg","Egg"),("chicken","Chicken"),("mutton","Mutton"),("fish","Fish"),("paneer","Paneer"),("mushroom","Mushroom"),("other","Other")])),
        migrations.AddField(model_name="menuitem",name="image_data",field=models.TextField(blank=True)),
        migrations.AddField(model_name="order",name="payment_method",field=models.CharField(max_length=10,blank=True,choices=[("cash","Cash"),("card","Card"),("upi","UPI")])),
        migrations.AddField(model_name="order",name="whatsapp_consent",field=models.BooleanField(default=False)),
        migrations.RunPython(classify_legacy,migrations.RunPython.noop),
        migrations.AlterField(model_name="menuitem",name="food_type",field=models.CharField(max_length=20,default="veg",choices=[("veg","Veg"),("non_veg","Non Veg")])),
    ]
