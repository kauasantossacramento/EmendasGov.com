from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from tenants.models import Tenant

from .models import ContratoPNCP, Emenda, Empenho, StatusRastreabilidade


def criar_cenario():
    """Dois municípios com dados distintos para validar o isolamento."""
    t1 = Tenant.objects.create(slug="alfa", nome="Município Alfa", exigir_recaptcha=False)
    t2 = Tenant.objects.create(slug="beta", nome="Município Beta", exigir_recaptcha=False)
    e1 = Emenda.objects.create(
        tenant=t1, numero="1001", parlamentar="Dep. Alfa", ano=2026,
        valor_total=Decimal("100000.00"), area_aplicacao="saude",
    )
    e2 = Emenda.objects.create(
        tenant=t2, numero="2001", parlamentar="Dep. Beta", ano=2026,
        valor_total=Decimal("200000.00"),
    )
    emp1 = Empenho.objects.create(
        emenda=e1, numero="NE001", data_empenho=date.today(),
        valor_empenhado=Decimal("60000.00"),
        valor_liquidado=Decimal("40000.00"),
        valor_pago=Decimal("30000.00"),
        fornecedor_nome="Fornecedor Alfa Ltda",
    )
    return t1, t2, e1, e2, emp1


class IsolamentoTenantTests(TestCase):
    def setUp(self):
        self.t1, self.t2, self.e1, self.e2, self.emp1 = criar_cenario()

    def test_queryset_do_tenant_filtra_por_slug(self):
        self.assertEqual(list(Emenda.objects.do_tenant("alfa")), [self.e1])
        self.assertEqual(list(Emenda.objects.do_tenant("beta")), [self.e2])

    def test_pesquisa_nao_vaza_dados_de_outro_municipio(self):
        resposta = self.client.get(reverse("portal:pesquisa", args=["alfa"]))
        self.assertContains(resposta, "1001")
        self.assertNotContains(resposta, "2001")

    def test_emenda_de_outro_tenant_retorna_404(self):
        resposta = self.client.get(
            reverse("portal:emenda_detalhe", args=["alfa", self.e2.pk])
        )
        self.assertEqual(resposta.status_code, 404)

    def test_tenant_inexistente_retorna_404(self):
        resposta = self.client.get("/nao-existe/")
        self.assertEqual(resposta.status_code, 404)


class DrillDownTests(TestCase):
    def setUp(self):
        self.t1, _, self.e1, _, self.emp1 = criar_cenario()

    def test_dashboard_exibe_kpis(self):
        resposta = self.client.get(reverse("portal:dashboard", args=["alfa"]))
        self.assertContains(resposta, "Total de emendas recebidas")

    def test_dashboard_embute_json_dos_graficos_como_objeto(self):
        """Dupla codificação JSON deixaria os gráficos vazios no navegador."""
        import json as json_mod

        resposta = self.client.get(reverse("portal:dashboard", args=["alfa"]))
        html = resposta.content.decode()
        inicio = html.index('id="dados-graficos"')
        corpo = html[html.index(">", inicio) + 1:html.index("</script>", inicio)]
        dados = json_mod.loads(corpo)
        self.assertIsInstance(dados, dict)  # objeto, não string re-encodada
        for chave in ("mensal", "ranking", "areas", "sankey"):
            self.assertIn(chave, dados)
        self.assertIn("labels", dados["ranking"])

    def test_nivel2_mostra_totais_e_empenhos(self):
        resposta = self.client.get(
            reverse("portal:emenda_detalhe", args=["alfa", self.e1.pk])
        )
        self.assertContains(resposta, "NE001")
        self.assertContains(resposta, "Valor pago")

    def test_nivel3_mostra_matriz_e_bloco_pncp(self):
        resposta = self.client.get(
            reverse("portal:empenho_detalhe", args=["alfa", self.e1.pk, self.emp1.pk])
        )
        self.assertContains(resposta, "A liquidar")
        self.assertContains(resposta, "Conformidade PNCP")
        self.assertContains(resposta, "Pendente de Vínculo Contratual")

    def test_valores_derivados(self):
        self.assertEqual(self.emp1.valor_a_liquidar, Decimal("20000.00"))
        self.assertEqual(self.emp1.valor_a_pagar, Decimal("10000.00"))

    def test_exportacao_csv(self):
        resposta = self.client.get(reverse("portal:exportar_emendas", args=["alfa"]))
        self.assertEqual(resposta["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("1001", resposta.content.decode("utf-8-sig"))


class ConformidadePNCPTests(TestCase):
    def setUp(self):
        self.t1, _, self.e1, _, self.emp1 = criar_cenario()

    def test_vinculo_contratual_muda_status(self):
        self.assertEqual(
            self.emp1.status_rastreabilidade, StatusRastreabilidade.PENDENTE
        )
        ContratoPNCP.objects.create(
            empenho=self.emp1,
            numero_contrato="012/2026",
            url_pncp="https://pncp.gov.br/app/contratos/x",
        )
        self.emp1.refresh_from_db()
        self.assertEqual(
            self.emp1.status_rastreabilidade, StatusRastreabilidade.VINCULADO
        )

    def test_alerta_prazo_30_dias(self):
        antigo = Empenho.objects.create(
            emenda=self.e1, numero="NE002",
            data_empenho=date.today() - timedelta(days=45),
            valor_empenhado=Decimal("1000.00"),
        )
        estourados = Empenho.objects.com_prazo_estourado()
        self.assertIn(antigo, estourados)
        self.assertNotIn(self.emp1, estourados)
        self.assertTrue(antigo.prazo_pncp_estourado)
