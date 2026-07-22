# EmendasGov.com

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

## Testar no navegador (GitHub Codespaces)

[![Abrir no GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/kauasantossacramento/EmendasGov.com/tree/claude/emendas-transparency-portal-2li2es)

Sem instalar nada: o link acima cria um ambiente na nuvem do GitHub que
instala as dependências, aplica as migrações, carrega os dados de
demonstração e sobe o servidor automaticamente. Quando o Codespace abrir,
a porta 8000 é exposta com uma URL pública — acesse `/demo/` (portal
público) e `/admin/demo/` (gestor: `gestor-demo` / `transparencia`).

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

Os dados importados são **gravados no banco local** — o portal público lê
sempre do banco e continua no ar mesmo com as APIs federais indisponíveis.

### Base nacional (arquitetura em duas camadas)

A API de emendas da CGU devolve o Brasil inteiro. Em vez de descartar o que
não é do município, o sistema guarda **tudo** na base nacional
(`EmendaNacional`, uma carga por exercício via `CargaNacional`) e cada
município apenas **materializa** dali as suas emendas — casando a
localidade do gasto com o nome do município:

- **Cadastrou uma prefeitura nova?** As emendas dela são materializadas na
  hora, a partir da base nacional já carregada — sem nenhuma chamada à API.
- **Uma carga por ano serve a todos** os municípios (antes, cada um
  repetiria o download do país inteiro).
- Carga manual pelo painel do desenvolvedor (/dev/, seção "Base nacional")
  ou via terminal: `python manage.py sincronizar_nacional --ano 2024`.

**Periodicidade:** exercícios encerrados são baixados **uma única vez**; o
**ano corrente** é revalidado no máximo a cada **20 horas** (cliques do
gestor dentro desse intervalo usam a base local, sem re-baixar o país). O
agendamento da atualização é o cron diário documentado abaixo.

```bash
python manage.py sincronizar_emendas --tenant demo
```

A sincronização é **incremental e sem duplicação**:

- **Primeira execução do cliente**: carga histórica completa, do
  `ano_inicio_sincronizacao` do tenant até a data atual.
- **Execuções seguintes**: apenas exercícios ainda pendentes (ou com erro)
  são consultados; o ano corrente é sempre re-sincronizado, pois novas
  emendas continuam chegando durante o exercício.
- A deduplicação usa a chave natural `(tenant, numero, ano)` via
  `update_or_create` — registros existentes são atualizados, nunca duplicados.

Cada execução fica registrada em `SincronizacaoEmendas` (exercício, status,
contagens, erro), visível no painel do gestor em `/admin/<slug>/sincronizacao/`
— onde o gestor também pode disparar a sincronização manualmente.

Agende diariamente (cron) para manter os dados atualizados. Requer o código
IBGE configurado no tenant e a chave da API do Portal da Transparência.
Para um único exercício: `--ano 2024`.

### Sincronização em segundo plano

Com **Sincronização em segundo plano** ativada (padrão) no `/superadmin/` →
Configuração da plataforma, o clique do gestor em "Sincronizar" dispara a
carga em uma thread do próprio servidor e responde na hora — o gestor pode
sair da página e acompanhar pelo histórico (a tela se atualiza sozinha a
cada 10 s). Uma trava impede duas cargas simultâneas do mesmo município;
registros "Executando" órfãos (ex.: servidor reiniciado no meio) deixam de
bloquear após 2 horas. Desative a opção para voltar ao modo síncrono.

**Configuração no servidor (produção):**

- Nenhum serviço extra é necessário — a thread roda dentro do worker web
  (funciona com `runserver` e com Gunicorn/UWSGI). Atenção: se o worker
  for reiniciado no meio de uma carga, ela é interrompida (a trava expira
  sozinha e basta sincronizar de novo).
- Mantenha o **cron diário** como rede de segurança — ele completa qualquer
  carga interrompida, pois a sincronização é incremental:

  ```cron
  # /etc/cron.d/emendasgov — todo dia às 05:00
  0 5 * * * app cd /caminho/do/projeto && python manage.py sincronizar_emendas >> /var/log/emendasgov-sync.log 2>&1
  ```

- Com Gunicorn, evite `--max-requests` muito baixo (reciclagem de worker
  mata a thread da carga) e use PostgreSQL em produção — o SQLite trava
  escritas concorrentes sob carga.

### Limites da API da CGU

As consultas já são espaçadas para respeitar as cotas oficiais
(400 req/min de dia, 700 de madrugada). Ajustáveis via ambiente:
`CGU_INTERVALO_REQUISICOES` (padrão `0.2` s entre requisições) e
`CGU_MAX_PAGINAS` (padrão `600` páginas por execução — atingir o teto gera
aviso de carga parcial; basta rodar de novo para continuar).

## Variáveis de ambiente

O projeto lê automaticamente um arquivo `.env` na raiz. Comece copiando o
modelo comentado, que explica onde obter cada chave (CGU, Gemini, reCAPTCHA):

```bash
cp .env.example .env
```

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
