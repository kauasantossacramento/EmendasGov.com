"""Sinais: novo município nasce com os dados da base nacional +
ajustes de concorrência do SQLite."""
import logging

from django.db.backends.signals import connection_created
from django.db.models.signals import post_save
from django.dispatch import receiver

from tenants.models import Tenant

logger = logging.getLogger(__name__)


@receiver(connection_created, dispatch_uid="configurar_sqlite")
def configurar_sqlite(sender, connection, **kwargs):
    """
    SQLite: modo WAL permite leituras durante as gravações das cargas em
    segundo plano, e o busy_timeout faz escritas concorrentes esperarem o
    lock em vez de estourar "database is locked".
    """
    if connection.vendor == "sqlite":
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("PRAGMA busy_timeout=30000;")


@receiver(post_save, sender=Tenant, dispatch_uid="materializar_novo_tenant")
def materializar_novo_tenant(sender, instance, created, **kwargs):
    """
    Ao cadastrar um município, aproveita a base nacional já carregada:
    as emendas dele são materializadas na hora, sem consultar a API.
    """
    if not created:
        return
    from integrations.services.federal import materializar_tenant_completo

    try:
        execucoes = materializar_tenant_completo(instance)
    except Exception:  # noqa: BLE001 — cadastro nunca falha por causa disso
        logger.exception(
            "Falha ao materializar dados iniciais do tenant %s", instance.slug
        )
        return
    if execucoes:
        total = sum(e.emendas_criadas for e in execucoes)
        logger.info(
            "Tenant %s criado com %s emendas da base nacional (%s exercícios)",
            instance.slug, total, len(execucoes),
        )
