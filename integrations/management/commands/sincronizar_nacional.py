from django.core.management.base import BaseCommand
from django.utils import timezone

from integrations.services.federal import sincronizar_nacional


class Command(BaseCommand):
    help = (
        "Carrega a base nacional de emendas (Brasil inteiro) de um exercício "
        "a partir da API da CGU. Todos os municípios são abastecidos a partir "
        "dela — inclusive os cadastrados depois da carga."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--ano", type=int, default=timezone.localdate().year,
            help="Exercício a carregar (padrão: ano corrente)",
        )
        parser.add_argument(
            "--forcar", action="store_true",
            help="Recarrega mesmo que já exista carga recente do exercício",
        )

    def handle(self, *args, **options):
        log = sincronizar_nacional(options["ano"], forcar=options["forcar"])
        self.stdout.write(self.style.SUCCESS(
            f"Carga nacional {log.ano}: {log.get_status_display()} — "
            f"{log.registros_novos} novos, {log.registros_atualizados} atualizados"
        ))
