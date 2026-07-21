from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from integrations.services.federal import sincronizar_emendas
from tenants.models import Tenant


class Command(BaseCommand):
    help = (
        "Sincroniza as emendas dos municípios a partir das APIs federais "
        "(Portal da Transparência/CGU). Agende diariamente via cron."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--tenant", help="Slug do município (padrão: todos os ativos)"
        )
        parser.add_argument(
            "--ano", type=int, default=timezone.localdate().year,
            help="Exercício a sincronizar (padrão: ano corrente)",
        )

    def handle(self, *args, **options):
        tenants = Tenant.objects.filter(ativo=True)
        if options["tenant"]:
            tenants = tenants.filter(slug=options["tenant"])
            if not tenants.exists():
                raise CommandError(f"Tenant '{options['tenant']}' não encontrado.")

        for tenant in tenants:
            try:
                criadas, atualizadas = sincronizar_emendas(tenant, options["ano"])
            except Exception as exc:  # noqa: BLE001 — segue para o próximo município
                self.stderr.write(self.style.ERROR(f"{tenant.slug}: {exc}"))
                continue
            self.stdout.write(
                self.style.SUCCESS(
                    f"{tenant.slug} ({options['ano']}): "
                    f"{criadas} criadas, {atualizadas} atualizadas"
                )
            )
