"""Sinais: novo município nasce com os dados da base nacional."""
import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from tenants.models import Tenant

logger = logging.getLogger(__name__)


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
