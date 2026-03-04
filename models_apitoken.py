# dashboard/models.py  — ADD these classes to your existing models.py
# Do not replace the file; append or integrate.

import secrets
from django.conf import settings
from django.db import models
from django.utils import timezone


class APIToken(models.Model):
    """
    API access token. Plaintext is never stored; only SHA-256 hash.

    Creation flow (management command or admin action):
        from core.auth import generate_token, hash_token
        plaintext = generate_token()          # show once to the user
        APIToken.objects.create(
            user=user,
            name="CI pipeline",
            token_hash=hash_token(plaintext),
            scopes=["threats:read"],
        )
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="api_tokens",
    )
    name = models.CharField(max_length=200, help_text="Human label, e.g. 'CI pipeline'")
    token_hash = models.CharField(max_length=64, unique=True, db_index=True)
    scopes = models.JSONField(
        default=list,
        help_text='List of scope strings, e.g. ["threats:read", "iocs:read"]',
    )
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(
        null=True, blank=True,
        help_text="Leave null for non-expiring tokens.",
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["token_hash", "is_active"]),
        ]

    def __str__(self):
        return f"{self.user.username} / {self.name}"

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return timezone.now() > self.expires_at


# Management command: dashboard/management/commands/create_api_token.py
# -----------------------------------------------------------------------
# from django.core.management.base import BaseCommand
# from django.contrib.auth import get_user_model
# from core.auth import generate_token, hash_token
# from dashboard.models import APIToken
#
# class Command(BaseCommand):
#     help = "Create an API token for a user"
#
#     def add_arguments(self, parser):
#         parser.add_argument("username")
#         parser.add_argument("--name", default="CLI token")
#         parser.add_argument("--scopes", nargs="+", default=["threats:read"])
#
#     def handle(self, *args, **options):
#         User = get_user_model()
#         user = User.objects.get(username=options["username"])
#         plaintext = generate_token()
#         APIToken.objects.create(
#             user=user,
#             name=options["name"],
#             token_hash=hash_token(plaintext),
#             scopes=options["scopes"],
#         )
#         self.stdout.write(f"\nToken (copy now — shown once):\n{plaintext}\n")
