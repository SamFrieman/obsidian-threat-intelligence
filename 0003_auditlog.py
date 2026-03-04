# dashboard/migrations/0003_auditlog.py
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0002_threateventgrid"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AuditLog",
            fields=[
                ("id",             models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("ts",             models.DateTimeField(default=django.utils.timezone.now, db_index=True)),
                ("actor",          models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="+",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("actor_username", models.CharField(blank=True, max_length=150)),
                ("action",         models.CharField(db_index=True, max_length=64)),
                ("resource",       models.CharField(blank=True, max_length=200)),
                ("ip_address",     models.GenericIPAddressField(blank=True, null=True)),
                ("request_id",     models.CharField(blank=True, max_length=64)),
                ("detail",         models.JSONField(default=dict)),
                ("outcome",        models.CharField(
                    choices=[("ok", "OK"), ("error", "Error"), ("denied", "Denied")],
                    default="ok",
                    max_length=16,
                )),
            ],
            options={
                "ordering": ["-ts"],
                "default_permissions": ("view",),
            },
        ),
        migrations.AddIndex(
            model_name="auditlog",
            index=models.Index(fields=["action", "ts"], name="ix_audit_action_ts"),
        ),
        migrations.AddIndex(
            model_name="auditlog",
            index=models.Index(fields=["actor", "ts"], name="ix_audit_actor_ts"),
        ),
        # PostgreSQL immutability triggers — apply manually post-migration:
        # See the trigger SQL in dashboard/audit.py
        migrations.RunSQL(
            sql="""
            CREATE OR REPLACE FUNCTION prevent_audit_mutation()
            RETURNS trigger AS $$
            BEGIN
              RAISE EXCEPTION 'AuditLog rows are immutable';
            END;
            $$ LANGUAGE plpgsql;

            CREATE TRIGGER audit_immutable_update
              BEFORE UPDATE ON dashboard_auditlog
              FOR EACH ROW EXECUTE FUNCTION prevent_audit_mutation();

            CREATE TRIGGER audit_immutable_delete
              BEFORE DELETE ON dashboard_auditlog
              FOR EACH ROW EXECUTE FUNCTION prevent_audit_mutation();
            """,
            reverse_sql="""
            DROP TRIGGER IF EXISTS audit_immutable_update ON dashboard_auditlog;
            DROP TRIGGER IF EXISTS audit_immutable_delete ON dashboard_auditlog;
            DROP FUNCTION IF EXISTS prevent_audit_mutation();
            """,
            # Triggers cannot run inside a transaction on some PG versions
            # If migration fails here, apply the SQL manually via dbshell
        ),
    ]
