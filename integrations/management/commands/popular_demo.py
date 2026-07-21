"""Popula o banco com dados de demonstração para desenvolvimento local."""
import random
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from emendas.models import ContratoPNCP, Emenda, Empenho
from tenants.models import GestorMunicipal, Tenant

PARLAMENTARES = [
    "Dep. João Silva", "Dep. Maria Souza", "Sen. Carlos Pereira",
    "Dep. Ana Beatriz Lima", "Sen. Roberto Nunes", "Dep. Fernanda Alves",
]
AREAS = ["saude", "educacao", "infraestrutura", "assistencia_social", "custeio"]
FORNECEDORES = [
    ("12.345.678/0001-90", "Construtora Horizonte Ltda"),
    ("98.765.432/0001-10", "MedSupri Distribuidora de Medicamentos SA"),
    ("11.222.333/0001-44", "Educar Materiais Pedagógicos EIRELI"),
    ("55.666.777/0001-88", "Urbaniza Engenharia e Serviços Ltda"),
]
OBJETOS = [
    "Aquisição de equipamentos e material permanente para a Unidade Básica de Saúde.",
    "Contratação de empresa para pavimentação asfáltica de vias urbanas.",
    "Aquisição de material didático para a rede municipal de ensino.",
    "Construção do Posto de Saúde Central do município.",
    "Reforma e ampliação da Escola Municipal do bairro Centro.",
]


class Command(BaseCommand):
    help = "Cria tenants e emendas fictícias para demonstração/desenvolvimento."

    def handle(self, *args, **options):
        random.seed(42)
        tenant, _ = Tenant.objects.get_or_create(
            slug="demo",
            defaults={
                "nome": "Município Demonstração",
                "uf": "BA",
                "codigo_ibge": "2900000",
                "texto_introdutorio": (
                    "<p>Portal de Transparência de Emendas Parlamentares, mantido "
                    "conforme a <strong>Resolução nº 123/2025 - TCM</strong>. Aqui "
                    "você acompanha a jornada de cada recurso federal recebido pelo "
                    "município: da emenda ao contrato.</p>"
                ),
                "exigir_recaptcha": False,
            },
        )

        hoje = date.today()
        contador = 0
        for ano in (hoje.year - 1, hoje.year):
            for i in range(1, 13):
                contador += 1
                valor = Decimal(random.randrange(150, 2500) * 1000)
                emenda, criada = Emenda.objects.get_or_create(
                    tenant=tenant,
                    numero=f"{ano}{i:04d}",
                    ano=ano,
                    defaults={
                        "parlamentar": random.choice(PARLAMENTARES),
                        "valor_total": valor,
                        "area_aplicacao": random.choice(AREAS),
                        "objeto": random.choice(OBJETOS),
                        "data_recebimento": date(ano, random.randrange(1, 13), 15),
                        "fonte_importacao": "manual",
                    },
                )
                if not criada:
                    continue
                for j in range(random.randrange(1, 4)):
                    cnpj, nome = random.choice(FORNECEDORES)
                    empenhado = (valor / 3).quantize(Decimal("0.01"))
                    liquidado = (empenhado * Decimal("0.7")).quantize(Decimal("0.01"))
                    pago = (liquidado * Decimal("0.8")).quantize(Decimal("0.01"))
                    empenho = Empenho.objects.create(
                        emenda=emenda,
                        numero=f"{ano}NE{contador:03d}{j}",
                        data_empenho=hoje - timedelta(days=random.randrange(5, 400)),
                        unidade_executora="Secretaria Municipal de Administração",
                        projeto_atividade="1.024 — Implantação de Melhorias Urbanas",
                        elemento_despesa="4.4.90.52 — Equipamentos e Material Permanente",
                        fonte="1701 — Transferências da União",
                        subfonte="Emendas Individuais",
                        fornecedor_cnpj=cnpj,
                        fornecedor_nome=nome,
                        objeto=random.choice(OBJETOS),
                        valor_empenhado=empenhado,
                        valor_liquidado=liquidado,
                        valor_pago=pago,
                    )
                    if random.random() < 0.6:
                        ContratoPNCP.objects.create(
                            empenho=empenho,
                            numero_contrato=f"{j + 1:03d}/{ano}",
                            modalidade="pregao_eletronico",
                            id_pncp=f"29000000000100-1-{contador:06d}/{ano}",
                            url_pncp="https://pncp.gov.br/app/contratos",
                            data_assinatura=hoje - timedelta(days=random.randrange(1, 300)),
                        )
                        empenho.processo_administrativo = f"PA-{contador:04d}/{ano}"
                        empenho.save(update_fields=["processo_administrativo"])

        # Conta de gestor para testar o painel administrativo do município.
        # Apenas para demonstração — troque a senha (ou remova) em produção.
        usuario, criado = User.objects.get_or_create(username="gestor-demo")
        if criado:
            usuario.set_password("transparencia")
            usuario.save()
        GestorMunicipal.objects.get_or_create(usuario=usuario, tenant=tenant)

        self.stdout.write(self.style.SUCCESS(
            f"Dados de demonstração prontos: acesse /{tenant.slug}/\n"
            f"Painel do gestor: /admin/{tenant.slug}/ "
            f"(usuário: gestor-demo · senha: transparencia)"
        ))
