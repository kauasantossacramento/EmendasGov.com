import time
from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from emendas.models import Emenda
from portal.models import ConfiguracaoPlataforma
from tenants.models import GestorMunicipal, Tenant

from .models import SincronizacaoEmendas, StatusSincronizacao
from .services import federal

ANO_ATUAL = timezone.localdate().year


def resposta_api(numero, autor, valor, localidade="Município Alfa"):
    return {
        "codigoEmenda": numero,
        "ano": ANO_ATUAL,
        "autor": autor,
        "valorEmpenhado": valor,
        "funcao": "Saúde",
        "localidadeDoGasto": localidade,
    }


class ConversaoValoresTests(TestCase):
    def test_formato_brasileiro_da_cgu(self):
        """A CGU devolve '1.234.567,89' — não pode virar 0,00."""
        self.assertEqual(str(federal._decimal("1.234.567,89")), "1234567.89")
        self.assertEqual(str(federal._decimal("1.503.000,00")), "1503000.00")
        self.assertEqual(str(federal._decimal("R$ 500,50")), "500.50")

    def test_formatos_numericos_e_invalidos(self):
        self.assertEqual(str(federal._decimal("1234567.89")), "1234567.89")
        self.assertEqual(str(federal._decimal(1000)), "1000.00")
        self.assertEqual(str(federal._decimal(None)), "0.00")
        self.assertEqual(str(federal._decimal("abc")), "0.00")
        self.assertEqual(str(federal._decimal("")), "0.00")


class SegundoPlanoTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(
            slug="alfa", nome="Município Alfa", codigo_ibge="2900000",
        )
        usuario = User.objects.create_user("gestor", password="senha123")
        GestorMunicipal.objects.create(usuario=usuario, tenant=self.tenant)
        self.client.login(username="gestor", password="senha123")

    def test_trava_detecta_execucao_recente(self):
        SincronizacaoEmendas.objects.create(
            tenant=self.tenant, ano=ANO_ATUAL,
            status=StatusSincronizacao.EXECUTANDO,
        )
        self.assertTrue(federal.sincronizacao_em_andamento(self.tenant))

    def test_execucao_orfa_antiga_nao_bloqueia(self):
        log = SincronizacaoEmendas.objects.create(
            tenant=self.tenant, ano=ANO_ATUAL,
            status=StatusSincronizacao.EXECUTANDO,
        )
        SincronizacaoEmendas.objects.filter(pk=log.pk).update(
            iniciado_em=timezone.now() - timedelta(hours=3)
        )
        self.assertFalse(federal.sincronizacao_em_andamento(self.tenant))

    def test_nao_inicia_duplicada(self):
        SincronizacaoEmendas.objects.create(
            tenant=self.tenant, ano=ANO_ATUAL,
            status=StatusSincronizacao.EXECUTANDO,
        )
        self.assertFalse(
            federal.sincronizar_tenant_em_segundo_plano(self.tenant)
        )

    @mock.patch("gestor.views.sincronizar_tenant_em_segundo_plano")
    def test_view_usa_segundo_plano_quando_ativado(self, iniciar):
        config = ConfiguracaoPlataforma.carregar()
        config.sincronizacao_em_segundo_plano = True
        config.save()
        resposta = self.client.post("/admin/alfa/sincronizacao/", {"ano": ""})
        self.assertEqual(resposta.status_code, 302)
        iniciar.assert_called_once()

    @mock.patch("gestor.views.sincronizar_tenant")
    @mock.patch("gestor.views.sincronizar_tenant_em_segundo_plano")
    def test_view_roda_sincrono_quando_desativado(self, iniciar, sincrono):
        config = ConfiguracaoPlataforma.carregar()
        config.sincronizacao_em_segundo_plano = False
        config.save()
        sincrono.return_value = []
        self.client.post("/admin/alfa/sincronizacao/", {"ano": ""})
        iniciar.assert_not_called()
        sincrono.assert_called_once()

    @mock.patch("gestor.views.sincronizar_tenant_em_segundo_plano")
    def test_view_bloqueia_quando_ja_em_andamento(self, iniciar):
        SincronizacaoEmendas.objects.create(
            tenant=self.tenant, ano=ANO_ATUAL,
            status=StatusSincronizacao.EXECUTANDO,
        )
        self.client.post("/admin/alfa/sincronizacao/", {"ano": ""})
        iniciar.assert_not_called()

    @mock.patch.object(federal, "sincronizar_tenant")
    def test_thread_executa_e_fecha_conexoes(self, sincronizar):
        iniciou = federal.sincronizar_tenant_em_segundo_plano(self.tenant)
        self.assertTrue(iniciou)
        for _ in range(50):  # aguarda a thread concluir (máx. ~1s)
            if sincronizar.called:
                break
            time.sleep(0.02)
        sincronizar.assert_called_once()


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

    @staticmethod
    def _envelhecer_carga(ano):
        """Faz a carga nacional do ano parecer antiga (força nova consulta)."""
        from .models import CargaNacional

        CargaNacional.objects.filter(ano=ano).update(
            concluido_em=timezone.now() - timedelta(hours=25)
        )

    @mock.patch.object(federal.PortalTransparenciaClient, "emendas_do_ano")
    def test_materializa_apenas_emendas_do_municipio(self, api):
        """A base nacional guarda o Brasil; o tenant só recebe o que é dele."""
        from .models import EmendaNacional

        api.return_value = iter([
            resposta_api("9001", "Dep. Alfa", "1.000,00"),
            resposta_api("8001", "Dep. Outro", "2.000,00", localidade="Outra Cidade - XX"),
            resposta_api("8002", "Dep. Outro", "3.000,00", localidade="Nacional"),
        ])
        criadas, _ = federal.sincronizar_emendas(self.tenant, ANO_ATUAL)
        self.assertEqual(criadas, 1)
        self.assertEqual(Emenda.objects.count(), 1)
        self.assertEqual(Emenda.objects.get().numero, "9001")
        # Nada se perde: as três ficam guardadas na base nacional
        self.assertEqual(EmendaNacional.objects.count(), 3)

    @mock.patch.object(federal.PortalTransparenciaClient, "emendas_do_ano")
    def test_valores_brasileiros_gravados_corretamente(self, api):
        api.return_value = iter([resposta_api("9001", "Dep. Alfa", "1.503.000,00")])
        federal.sincronizar_emendas(self.tenant, ANO_ATUAL)
        self.assertEqual(str(Emenda.objects.get().valor_total), "1503000.00")

    @mock.patch.object(federal.PortalTransparenciaClient, "emendas_do_ano")
    def test_sincronizar_apenas_um_ano(self, api):
        api.side_effect = lambda ano: iter(
            [resposta_api(f"{ano}01", "Dep. Alfa", "1.000,00")]
        )
        execucoes = federal.sincronizar_tenant(
            self.tenant, apenas_ano=ANO_ATUAL - 1
        )
        self.assertEqual([e.ano for e in execucoes], [ANO_ATUAL - 1])
        self.assertEqual(api.call_count, 1)

    @mock.patch.object(federal.PortalTransparenciaClient, "emendas_do_ano")
    def test_sincronizar_grava_no_banco_sem_duplicar(self, api):
        api.return_value = iter([
            resposta_api("9001", "Dep. Alfa", "100000.00"),
            resposta_api("9002", "Dep. Beta", "200000.00"),
        ])
        federal.sincronizar_emendas(self.tenant, ANO_ATUAL)
        self.assertEqual(Emenda.objects.count(), 2)

        # Segunda passada com os mesmos registros (valor alterado em um deles):
        self._envelhecer_carga(ANO_ATUAL)
        api.return_value = iter([
            resposta_api("9001", "Dep. Alfa", "150000.00"),
            resposta_api("9002", "Dep. Beta", "200000.00"),
        ])
        federal.sincronizar_emendas(self.tenant, ANO_ATUAL)
        self.assertEqual(Emenda.objects.count(), 2)  # nada duplicado
        atualizada = Emenda.objects.get(numero="9001")
        self.assertEqual(str(atualizada.valor_total), "150000.00")

    @mock.patch.object(federal.PortalTransparenciaClient, "emendas_do_ano")
    def test_carga_nacional_recente_nao_reconsulta_a_api(self, api):
        """Ano corrente: dentro da validade de 20h, não baixa de novo."""
        api.side_effect = lambda ano: iter(
            [resposta_api("9001", "Dep. Alfa", "1.000,00")]
        )
        federal.sincronizar_emendas(self.tenant, ANO_ATUAL)
        federal.sincronizar_emendas(self.tenant, ANO_ATUAL)  # 2ª: usa a base
        self.assertEqual(api.call_count, 1)

    @mock.patch.object(federal.PortalTransparenciaClient, "emendas_do_ano")
    def test_sincronizar_tenant_registra_logs(self, api):
        api.side_effect = lambda ano: iter(
            [resposta_api(f"{ano}01", "Dep. Alfa", "1000.00")]
        )
        execucoes = federal.sincronizar_tenant(self.tenant)
        self.assertEqual(len(execucoes), 3)
        self.assertTrue(
            all(e.status == StatusSincronizacao.SUCESSO for e in execucoes)
        )
        self.assertEqual(Emenda.objects.count(), 3)
        # Próxima rodada: só o ano corrente é reprocessado.
        segunda = federal.sincronizar_tenant(self.tenant)
        self.assertEqual([e.ano for e in segunda], [ANO_ATUAL])

    @mock.patch.object(federal.PortalTransparenciaClient, "emendas_do_ano")
    def test_falha_na_api_gera_log_de_erro_e_nao_interrompe(self, api):
        def lancar(ano):
            if ano == ANO_ATUAL - 1:
                raise RuntimeError("API fora do ar")
            return iter([resposta_api(f"{ano}01", "Dep. Alfa", "1000.00")])

        api.side_effect = lancar
        execucoes = federal.sincronizar_tenant(self.tenant)
        por_ano = {e.ano: e.status for e in execucoes}
        self.assertEqual(por_ano[ANO_ATUAL - 1], StatusSincronizacao.ERRO)
        self.assertEqual(por_ano[ANO_ATUAL], StatusSincronizacao.SUCESSO)

    @mock.patch.object(federal.PortalTransparenciaClient, "emendas_do_ano")
    def test_municipio_novo_nasce_com_dados_da_base_nacional(self, api):
        """A estratégia-chave: cadastrar prefeitura → dados na hora, sem API."""
        api.return_value = iter([
            resposta_api("9001", "Dep. Alfa", "1.000,00"),
            resposta_api("7001", "Dep. Gama", "5.000,00",
                         localidade="Cidade Nova - BA (MUNICÍPIO)"),
        ])
        federal.sincronizar_emendas(self.tenant, ANO_ATUAL)  # popula a base
        api.reset_mock()

        novo = Tenant.objects.create(
            slug="cidade-nova", nome="Cidade Nova",
            ano_inicio_sincronizacao=ANO_ATUAL - 2,
        )
        # O sinal de criação materializou da base nacional, sem chamar a API:
        self.assertEqual(api.call_count, 0)
        emendas_novo = Emenda.objects.filter(tenant=novo)
        self.assertEqual(emendas_novo.count(), 1)
        self.assertEqual(emendas_novo.get().numero, "7001")
        # E o log de sincronização registra o exercício aproveitado:
        self.assertTrue(
            SincronizacaoEmendas.objects.filter(
                tenant=novo, ano=ANO_ATUAL, status=StatusSincronizacao.SUCESSO
            ).exists()
        )
