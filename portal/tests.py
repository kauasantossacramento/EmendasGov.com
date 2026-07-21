from django.test import TestCase

from .models import ConfiguracaoPlataforma, DestaquePlataforma


class FaixaEstatisticasLandingTests(TestCase):
    def test_padrao_mostra_destaques_e_nao_numeros_reais(self):
        """Plataforma recém-lançada: destaques de fábrica, sem contadores reais."""
        resposta = self.client.get("/")
        self.assertContains(resposta, "Assistente de IA ao cidadão")
        self.assertNotContains(resposta, "Municípios no portal")

    def test_destaques_personalizados_substituem_o_padrao(self):
        config = ConfiguracaoPlataforma.carregar()
        DestaquePlataforma.objects.create(
            configuracao=config, valor="+50", rotulo="Prefeituras atendidas", ordem=1
        )
        resposta = self.client.get("/")
        self.assertContains(resposta, "Prefeituras atendidas")
        self.assertNotContains(resposta, "Assistente de IA ao cidadão")

    def test_dados_reais_quando_ativado(self):
        config = ConfiguracaoPlataforma.carregar()
        config.usar_dados_reais = True
        config.save()
        resposta = self.client.get("/")
        self.assertContains(resposta, "Municípios no portal")
        self.assertContains(resposta, "data-contador")

    def test_faixa_oculta_quando_desativada(self):
        config = ConfiguracaoPlataforma.carregar()
        config.exibir_estatisticas = False
        config.save()
        resposta = self.client.get("/")
        self.assertNotContains(resposta, 'class="numeros"')

    def test_singleton(self):
        a = ConfiguracaoPlataforma.carregar()
        b = ConfiguracaoPlataforma.carregar()
        self.assertEqual(a.pk, b.pk)
        self.assertEqual(ConfiguracaoPlataforma.objects.count(), 1)
