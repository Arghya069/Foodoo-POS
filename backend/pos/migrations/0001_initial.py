# Generated for the Sprint 01 starter schema. Validate against makemigrations --check before release.
import uuid
from decimal import Decimal
from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name="Restaurant",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=200)),
                ("address", models.TextField(blank=True)),
                ("contact_phone", models.CharField(blank=True, max_length=25)),
                ("gstin", models.CharField(blank=True, max_length=15)),
                ("cgst_rate", models.DecimalField(decimal_places=2, default=Decimal("2.50"), max_digits=5, validators=[MinValueValidator(0), MaxValueValidator(100)])),
                ("sgst_rate", models.DecimalField(decimal_places=2, default=Decimal("2.50"), max_digits=5, validators=[MinValueValidator(0), MaxValueValidator(100)])),
            ],
        ),
        migrations.CreateModel(
            name="Membership",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("role", models.CharField(choices=[("admin", "Admin"), ("staff", "Staff")], max_length=10)),
                ("restaurant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="pos.restaurant")),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="pos_membership", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="MenuItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=160)),
                ("price", models.DecimalField(decimal_places=2, max_digits=12, validators=[MinValueValidator(Decimal("0"))])),
                ("active", models.BooleanField(default=True)),
                ("restaurant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="pos.restaurant")),
            ],
        ),
        migrations.CreateModel(
            name="Order",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("customer_name", models.CharField(blank=True, max_length=160)),
                ("customer_phone", models.CharField(blank=True, max_length=20)),
                ("status", models.CharField(choices=[("draft", "Draft"), ("paid", "Paid")], default="draft", max_length=10)),
                ("subtotal", models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ("cgst_rate", models.DecimalField(decimal_places=2, default=0, max_digits=5)),
                ("sgst_rate", models.DecimalField(decimal_places=2, default=0, max_digits=5)),
                ("cgst_amount", models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ("sgst_amount", models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ("total", models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ("receipt_number", models.CharField(blank=True, max_length=40, null=True, unique=True)),
                ("paid_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
                ("restaurant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="pos.restaurant")),
            ],
        ),
        migrations.CreateModel(
            name="OrderLine",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name_snapshot", models.CharField(max_length=160)),
                ("unit_price", models.DecimalField(decimal_places=2, max_digits=12)),
                ("quantity", models.PositiveIntegerField()),
                ("line_total", models.DecimalField(decimal_places=2, max_digits=12)),
                ("menu_item", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="pos.menuitem")),
                ("order", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="lines", to="pos.order")),
            ],
        ),
    ]
