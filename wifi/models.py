from django.db import models

from .plugin import ADMINS, GUESTS

AUDIENCES = ((GUESTS, "Everyone"), (ADMINS, "Signed-in admins only"))


class Network(models.Model):
    ssid = models.CharField("Network name", max_length=64)
    password = models.CharField(max_length=128, blank=True)
    audience = models.CharField(max_length=10, choices=AUDIENCES, default=GUESTS)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("order", "id")

    def __str__(self):
        return self.ssid


class LegacyImport(models.Model):
    """One row once the old per-slot settings were copied into ``Network``,
    so removing every network doesn't bring them back."""

    done_at = models.DateTimeField(auto_now_add=True)
