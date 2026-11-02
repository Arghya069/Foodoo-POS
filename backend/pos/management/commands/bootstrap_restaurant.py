from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from pos.models import Membership, Restaurant

class Command(BaseCommand):
    help = "Create the first restaurant and link an existing Django user as admin."

    def add_arguments(self, parser):
        parser.add_argument("--admin-username", required=True)
        parser.add_argument("--restaurant-name", required=True)

    @transaction.atomic
    def handle(self, *args, **options):
        user = get_user_model().objects.filter(username=options["admin_username"]).first()
        if user is None:
            raise CommandError("Create the admin user first with createsuperuser.")
        if Membership.objects.filter(user=user).exists():
            raise CommandError("This user already has a restaurant membership.")
        restaurant = Restaurant.objects.create(name=options["restaurant_name"])
        Membership.objects.create(user=user, restaurant=restaurant, role="admin")
        self.stdout.write(self.style.SUCCESS(f"Created restaurant {restaurant.id} and linked admin {user.username}"))
