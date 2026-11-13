from __future__ import annotations

from django.contrib.auth.models import AbstractUser
from django.db import models

from apps.core.ids import uuid7


class User(AbstractUser):
    """Administrator account. The MVP deliberately has a single role.

    Per-operator accountability comes from real user rows + the audit log, not
    from a role matrix.
    """

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    display_name = models.CharField(max_length=120, blank=True)

    @property
    def label(self) -> str:
        return self.display_name or self.get_full_name() or self.username
