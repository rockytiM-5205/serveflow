"""Customer accounts. One ServeFlow account works at every restaurant, and ordering as a guest still works.

A customer account is a sign-in plus this profile. It is kept apart from the people who run restaurants: it carries no restaurant
membership and no platform rights, the customer routes only accept accounts that have a profile, and an account with a profile can't
create a restaurant. (Today a person who wants both uses two email addresses.)"""
from django.conf import settings
from django.db import models


class CustomerProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="customer_profile")
    phone = models.CharField(max_length=20, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.user.email
