from unittest import mock

from django.test import TestCase
from django.utils import timezone

from emendas.models import Emenda
from tenants.models import Tenant

from .models import SincronizacaoEmendas, StatusSincronizacao
from .services import federal

ANO_ATUAL = timezone.localdate().year


def resposta_api(numero, autor, valor):
    return {
        "codigoEmenda": numero,
        "ano": ANO_ATUAL,
        "autor": autor,
        "valorEmpenhado": valor,
        "funcao": "Saúde",
        "localidadeDoGasto": "Município Alfa",
    }


class SeloAtualizacaoTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(
            slug="alfa", nome="Município Alfa", exigir_recaptcha=False,
        )

    def test_sem_sincronizacao_mostra_estado_aguardando(self):
        resposta = self.client.get("/alfa/")
        self.assertContains(
            resposta, "Aguardando a primeira sincronização"
        )

    def test_dashboard_exibe_data_da_ultima_sincronizacao(self):
        sync = SincronizacaoEmendas.objects.create(
            tenant=self.tenant, ano=ANO_ATUAL,
            status=StatusSincronizacao.SUCESSO,
        )
        sync.concluido_em = timezone.now()
        sync.save()
        resposta = self.client.get("/alfa/")
        self.assertContains(resposta, "Dados atualizados em")
        self.assertContains(
            resposta, timezone.localtime(sync.concluido_em).strftime("%d/%m/%Y")
        )


class SincronizacaoIncrementalTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(
            slug="alfa", nome="Município Alfa", codigo_ibge="2900000",
            ano_inicio_sincronizacao=ANO_ATUAL - 2,
        )

    def test_primeira_execucao_faz_carga_historica_completa(self):
        self.assertEqual(
            federal.anos_pendentes(self.tenant),
            [ANO_ATUAL - 2, ANO_ATUAL - 1, ANO_ATUAL],
        )

    def test_execucoes_seguintes_sao_incrementais(self):
        for ano in (ANO_ATUAL - 2, ANO_ATUAL - 1):
            SincronizacaoEmendas.objects.create(
                tenant=self.tenant, ano=ano, status=StatusSincronizacao.SUCESSO,
            )
        # Históricos concluídos são pulados; o ano corrente sempre atualiza.
        self.assertEqual(federal.anos_pendentes(self.tenant), [ANO_ATUAL])

    def test_ano_com_erro_volta_a_ser_sincronizado(self):
        SincronizacaoEmendas.objects.create(
            tenant=self.tenant, ano=ANO_ATUAL - 2, status=StatusSincronizacao.ERRO,
        )
        SincronizacaoEmendas.objects.create(
            tenant=self.tenant, ano=ANO_ATUAL - 1, status=StatusSincronizacao.SUCESSO,
        )
        self.assertEqual(
            federal.anos_pendentes(self.tenant), [ANO_ATUAL - 2, ANO_ATUAL]
        )

    @mock.patch.object(federal.PortalTransparenciaClient, "emendas_por_municipio")
    def test_sincronizar_grava_no_banco_sem_duplicar(self, api):
        api.return_value = iter([
            resposta_api("9001", "Dep. Alfa", "100000.00"),
            resposta_api("9002", "Dep. Beta", "200000.00"),
        ])
        federal.sincronizar_emendas(self.tenant, ANO_ATUAL)
        self.assertEqual(Emenda.objects.count(), 2)

        # Segunda passada com os mesmos registros (valor alterado em um deles):
        api.return_value = iter([
            resposta_api("9001", "Dep. Alfa", "150000.00"),
            resposta_api("9002", "Dep. Beta", "200000.00"),
        ])
        federal.sincronizar_emendas(self.tenant, ANO_ATUAL)
        self.assertEqual(Emenda.objects.count(), 2)  # nada duplicado
        atualizada = Emenda.objects.get(numero="9001")
        self.assertEqual(str(atualizada.valor_total), "150000.00")

    @mock.patch.object(federal.PortalTransparenciaClient, "emendas_por_municipio")
    def test_sincronizar_tenant_registra_logs(self, api):
        api.side_effect = lambda ibge, ano: iter(
            [resposta_api(f"{ano}01", "Dep. Alfa", "1000.00")]
        )
        execucoes = federal.sincronizar_tenant(self.tenant)
        self.assertEqual(len(execucoes), 3)
        self.assertTrue(
            all(e.status == StatusSincronizacao.SUCESSO for e in execucoes)
        )
        self.assertEqual(Emenda.objects.count(), 3)
        # Próxima rodada: só o ano corrente é reprocessado.
        api.side_effect = lambda ibge, ano: iter([])
        segunda = federal.sincronizar_tenant(self.tenant)
        self.assertEqual([e.ano for e in segunda], [ANO_ATUAL])

    @mock.patch.object(federal.PortalTransparenciaClient, "emendas_por_municipio")
    def test_falha_na_api_gera_log_de_erro_e_nao_interrompe(self, api):
        def lancar(ibge, ano):
            if ano == ANO_ATUAL - 1:
                raise RuntimeError("API fora do ar")
            return iter([resposta_api(f"{ano}01", "Dep. Alfa", "1000.00")])

        api.side_effect = lancar
        execucoes = federal.sincronizar_tenant(self.tenant)
        por_ano = {e.ano: e.status for e in execucoes}
        self.assertEqual(por_ano[ANO_ATUAL - 1], StatusSincronizacao.ERRO)
        self.assertEqual(por_ano[ANO_ATUAL], StatusSincronizacao.SUCESSO)
