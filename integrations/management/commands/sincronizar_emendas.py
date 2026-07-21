from django.core.management.base import BaseCommand, CommandError

from integrations.services.federal import sincronizar_tenant
from tenants.models import Tenant


class Command(BaseCommand):
    help = (
        "Sincronização incremental das emendas com as APIs federais "
        "(Portal da Transparência/CGU). Na primeira execução de cada "
        "município faz a carga histórica (ano_inicio_sincronizacao até "
        "hoje); depois consulta apenas os exercícios pendentes e o ano "
        "corrente. Agende diariamente via cron."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--tenant", help="Slug do município (padrão: todos os ativos)"
        )
        parser.add_argument(
            "--ate-ano", type=int, default=None,
            help="Último exercício a sincronizar (padrão: ano corrente)",
        )

    def handle(self, *args, **options):
        tenants = Tenant.objects.filter(ativo=True)
        if options["tenant"]:
            tenants = tenants.filter(slug=options["tenant"])
            if not tenants.exists():
                raise CommandError(f"Tenant '{options['tenant']}' não encontrado.")

        for tenant in tenants:
            execucoes = sincronizar_tenant(tenant, ano_fim=options["ate_ano"])
            if not execucoes:
                self.stdout.write(f"{tenant.slug}: nada pendente.")
                continue
            for log in execucoes:
                if log.status == "sucesso":
                    self.stdout.write(self.style.SUCCESS(
                        f"{tenant.slug} ({log.ano}): {log.emendas_criadas} criadas, "
                        f"{log.emendas_atualizadas} atualizadas"
                    ))
                else:
                    self.stderr.write(self.style.ERROR(
                        f"{tenant.slug} ({log.ano}): ERRO — {log.mensagem_erro}"
                    ))
