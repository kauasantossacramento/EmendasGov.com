# Emendas.gov.com

Portal **multi-tenant de transparência de emendas parlamentares**: conecta o
Transferegov/CGU (origem do recurso), a contabilidade municipal (empenho) e o
PNCP (contrato), mostrando ao cidadão a jornada completa do dinheiro público.

## Arquitetura

- **Multi-tenant por URL path** — `dominio.com.br/<municipio-slug>/`, sem
  subdomínios. O `TenantMiddleware` resolve o município pela rota e todas as
  consultas públicas passam pelo filtro `tenant__slug=municipio_slug`
  (querysets `do_tenant()`), garantindo isolamento total de dados.
- **Rotas principais**
  - `/` — landing page da plataforma
  - `/<slug>/` — dashboard público do município (KPIs, gráficos, Sankey)
  - `/<slug>/emendas/` — pesquisa (Nível 1) → emenda (Nível 2) → empenho (Nível 3)
  - `/admin/<slug>/` — módulo do gestor municipal (white-label, vínculo PNCP)
  - `/superadmin/` — Django admin (operação da plataforma)

## Apps

| App            | Responsabilidade                                             |
|----------------|--------------------------------------------------------------|
| `tenants`      | Tenant (município), gestores, middleware de isolamento       |
| `emendas`      | Models `Emenda`, `Empenho`, `ContratoPNCP`                   |
| `portal`       | Área pública: gateway reCAPTCHA, dashboard, drill-downs, exportação CSV, chat IA |
| `gestor`       | Área administrativa municipal: white-label e rastreabilidade |
| `integrations` | Clientes Transferegov/CGU/PNCP e assistente Gemini (RAG)     |

## Rodando localmente

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py popular_demo        # dados fictícios (tenant "demo")
python manage.py createsuperuser
python manage.py runserver
```

Acesse `http://localhost:8000/demo/` (portal público) e
`http://localhost:8000/admin/demo/` (gestor).

## Sincronização com as APIs federais

```bash
python manage.py sincronizar_emendas --tenant demo --ano 2026
```

Agende diariamente (cron) para manter os dados atualizados. Requer o código
IBGE configurado no tenant e a chave da API do Portal da Transparência.

## Variáveis de ambiente

| Variável                        | Uso                                        |
|---------------------------------|---------------------------------------------|
| `DJANGO_SECRET_KEY`             | chave secreta em produção                  |
| `DJANGO_DEBUG`                  | `0` em produção                            |
| `POSTGRES_*`                    | banco PostgreSQL (opcional; padrão SQLite) |
| `RECAPTCHA_SITE_KEY` / `RECAPTCHA_SECRET_KEY` | gateway "não sou um robô"    |
| `GEMINI_API_KEY` / `GEMINI_MODEL` | Assistente de Transparência IA           |
| `PORTAL_TRANSPARENCIA_API_KEY`  | chave da API da CGU                        |

Sem `RECAPTCHA_SECRET_KEY` o gateway fica desativado (útil em desenvolvimento);
sem `GEMINI_API_KEY` o chat responde com mensagem orientativa.

## Testes

```bash
python manage.py test
```
