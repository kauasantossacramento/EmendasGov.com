from django.contrib.auth.models import User
from django.test import TestCase

from tenants.models import GestorMunicipal, Tenant

from .models import ConfiguracaoPlataforma, DestaquePlataforma


class LoginGlobalTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(slug="alfa", nome="Município Alfa")
        self.gestor = User.objects.create_user("gestor", password="senha123")
        GestorMunicipal.objects.create(usuario=self.gestor, tenant=self.tenant)
        self.dev = User.objects.create_superuser("dev", password="senha123")
        self.solto = User.objects.create_user("solto", password="senha123")

    def test_pagina_de_login_carrega(self):
        resposta = self.client.get("/login/")
        self.assertContains(resposta, "Entrar")

    def test_superusuario_vai_para_superadmin(self):
        resposta = self.client.post(
            "/login/", {"username": "dev", "password": "senha123"}
        )
        self.assertRedirects(
            resposta, "/superadmin/", target_status_code=200
        )

    def test_gestor_vai_para_seu_municipio(self):
        resposta = self.client.post(
            "/login/", {"username": "gestor", "password": "senha123"}
        )
        self.assertRedirects(resposta, "/admin/alfa/")

    def test_usuario_sem_vinculo_nao_mantem_sessao(self):
        resposta = self.client.post(
            "/login/", {"username": "solto", "password": "senha123"}
        )
        self.assertContains(resposta, "não está vinculado a nenhum município")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_next_malicioso_e_ignorado(self):
        resposta = self.client.post(
            "/login/?next=//evil.com", {"username": "dev", "password": "senha123"}
        )
        self.assertRedirects(resposta, "/superadmin/", target_status_code=200)

    def test_area_do_gestor_redireciona_para_login_unico(self):
        resposta = self.client.get("/admin/alfa/")
        self.assertEqual(resposta.status_code, 302)
        self.assertTrue(resposta["Location"].startswith("/login/?next="))

    def test_gestor_nao_acessa_outro_municipio(self):
        Tenant.objects.create(slug="beta", nome="Município Beta")
        self.client.login(username="gestor", password="senha123")
        self.assertEqual(self.client.get("/admin/alfa/").status_code, 200)
        self.assertEqual(self.client.get("/admin/beta/").status_code, 404)


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
