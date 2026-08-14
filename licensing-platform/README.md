# Camera360 - Plataforma de Licenciamento

Painel web multi-tenant pra controlar licenças do Camera360: você (super
admin) cadastra vendedores com marca própria (logo/cor/nome), cada um
controla seus próprios clientes finais, licenças (diária/mensal/anual/
vitalícia) e vendas (manuais ou via Stripe Checkout). O Camera360 desktop
consulta essa plataforma pra validar a licença antes de rodar
(`license_client.py` no projeto `camera_360/`).

## Rodar localmente (dev, sem Docker)

```
python -m venv venv
venv\Scripts\pip install -r requirements.txt
venv\Scripts\python manage.py migrate
venv\Scripts\python manage.py createsuperuser
venv\Scripts\python manage.py runserver 8000
```

Sem `DATABASE_NAME` no ambiente, usa SQLite automaticamente (mais rápido
pra testar). Acesse `http://localhost:8000/accounts/login/`.

## Rodar com Docker (Postgres de verdade)

```
copy .env.example .env
docker compose up --build
docker compose exec web python manage.py migrate
docker compose exec web python manage.py createsuperuser
```

## Stripe (pagamento automático)

1. Crie uma conta Stripe (ou use uma de teste) e pegue as chaves em
   dashboard.stripe.com/apikeys - preencha `STRIPE_SECRET_KEY` e
   `STRIPE_PUBLISHABLE_KEY` no `.env`.
2. Configure um webhook apontando pra
   `https://SEU_DOMINIO/api/v1/stripe/webhook` escutando o evento
   `checkout.session.completed`, e copie o "Signing secret" gerado pra
   `STRIPE_WEBHOOK_SECRET`.
3. No painel do vendedor, "Cobrar automaticamente (Stripe)" gera um link
   de pagamento por licença - a licença é ativada sozinha quando o Stripe
   confirmar o pagamento via webhook.

Sem Stripe configurado, o fluxo manual ("Emitir licença" + "Marcar como
paga") continua funcionando normalmente.

## Deploy na AWS (visão geral)

Não tenho como provisionar isso a partir daqui - esse projeto já vem
Dockerizado justamente pra facilitar o deploy em qualquer serviço de
container da AWS. Caminho mais simples:

1. **Banco**: RDS Postgres (instância pequena já basta pro volume inicial).
2. **App**: **AWS App Runner** (mais simples: aponta pra uma imagem no ECR
   e ele cuida do resto) ou **ECS Fargate** (mais controle, precisa de
   task definition + load balancer). Configure as variáveis de ambiente do
   `.env.example` diretamente no serviço (nunca commitar o `.env`).
3. **Estáticos**: já servidos pelo próprio container via WhiteNoise
   (`collectstatic` roda no build da imagem) - não precisa de S3 pra isso.
4. **Mídia** (logos dos vendedores): o container é efêmero, então logos
   enviados se perdem a cada deploy/restart se ficarem só no filesystem do
   container. Pra produção de verdade, trocar `MEDIA_ROOT` por um bucket
   S3 (via `django-storages`) é a próxima melhoria recomendada - não
   incluído neste v1 pra manter o escopo simples.
5. **Domínio/HTTPS**: Route 53 + ACM certificate na frente do App
   Runner/ALB - sem isso, o Camera360 (que fala com a API por HTTPS
   idealmente) e o Stripe webhook (exige HTTPS) não funcionam direito.
6. Depois do deploy, atualize `license_api_url` no `config.json` de cada
   instalação do Camera360 pra apontar pro domínio de produção (por
   padrão aponta pra `http://127.0.0.1:8000`, só serve pra desenvolvimento
   local).

## Estrutura

- `accounts/` - login e o modelo de usuário (`vendor=None` = super admin).
- `licensing/` - modelos (Vendor/Customer/License/Sale), API pro Camera360
  (`/api/v1/license/activate` e `/validate`), painéis web, Stripe.
- `templates/` - HTML dos painéis (branding dinâmico via CSS vars, a
  partir do `Vendor` do usuário logado).
