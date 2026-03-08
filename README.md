# BorrowBot

Autonomous DeFi lending agent on Base. Deposit collateral, earn yield, never pay gas.

## What It Does

Users deposit WETH or cbBTC from any chain. BorrowBot takes over:

1. Borrows USDC against collateral via **Morpho Blue**
2. Deposits USDC into a yield vault (**40acres/Yo.xyz**) for ~7-10% APY
3. Monitors positions every 5 minutes
4. Auto-rebalances to prevent liquidation and maximize yield
5. Communicates via **Telegram** and an in-app **AI chat**

All agent transactions are gas-free, sponsored by the Coinbase Paymaster.

## Key Features

- **Autonomous LTV Management** -- Background worker checks positions every 300 seconds. Auto-repays debt when LTV rises, auto-borrows more when LTV is safely low.
- **ENS On-Chain Constitution** -- Each agent gets `<name>.borrowbott.eth`. Owners set guardrails (max LTV, min spread, pause) as ENS text records. The agent reads its constitution before every action and writes status back.
- **Cross-Chain Access** -- Deposit from any EVM chain via LI.FI. Withdraw to any chain. The agent handles bridging on Base via paymaster.
- **AI Chat** -- Gemini-powered conversational interface with 5 tools (position data, market rates, price analysis, action history, LTV adjustment).
- **Telegram Notifications** -- Rebalancing alerts, liquidation warnings, bridge status updates.
- **Smart Wallets** -- Coinbase CDP EOA upgraded via EIP-7702. Batched UserOperations with paymaster gas sponsorship.

## Architecture

```
React SPA (CloudFront)  -->  REST API (EC2/Docker)  -->  PostgreSQL
                                     |
                              Worker (EC2/Docker)
                              every 300s: check LTV, rebalance, notify
                                     |
                         External: Morpho, Yo vault, Coinbase,
                                   ENS, LI.FI, Telegram, Gemini
```

## Tech Stack

| Layer | Technology |
|-------|------------|
| Frontend | React 19, TypeScript, Vite, wagmi, SCSS modules |
| Backend | Python 3.12, Starlette (kiba-core), SQLAlchemy, Alembic |
| Database | PostgreSQL (7 tables) |
| Blockchain | Base (execution), Ethereum mainnet (ENS) |
| Wallets | Coinbase CDP + EIP-7702 + Coinbase Paymaster |
| Protocols | Morpho Blue, 40acres/Yo.xyz (ERC-4626), ENS NameWrapper, LI.FI |
| AI | Google Gemini (tool-calling loop) |
| CI/CD | GitHub Actions, Docker, GHCR, EC2, S3 + CloudFront |

## Getting Started

### Prerequisites

- Python 3.12+ with [uv](https://docs.astral.sh/uv/)
- Node.js 18+ with npm
- PostgreSQL
- [direnv](https://direnv.net/) for environment management

### API Setup

```bash
cd api
cp .envrc.example .envrc    # configure environment variables
direnv allow
make install
make start                  # starts API on port 5000
```

To run the background worker:

```bash
cd api
make start-worker
```

### App Setup

```bash
cd app
cp .envrc.example .envrc    # configure environment variables
direnv allow
make install
make start                  # starts Vite dev server
```

## Environment Variables

The API requires the following environment variables (set in `.envrc` or `.borrowbot-api.vars`):

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | PostgreSQL connection string |
| `COINBASE_CDP_API_KEY` | Coinbase CDP wallet creation |
| `COINBASE_CDP_API_SECRET` | Coinbase CDP authentication |
| `ALCHEMY_API_KEY` | Alchemy RPC and data API |
| `MORALIS_API_KEY` | Moralis blockchain data |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot API |
| `GEMINI_API_KEY` | Google Gemini LLM |
| `ENS_PRIVATE_KEY` | Deployer key for ENS NameWrapper operations (mainnet) |
| `LIFI_API_KEY` | LI.FI quote and status API |

The App requires:

| Variable | Purpose |
|----------|---------|
| `KRT_API_URL` | API server URL |
| `KRT_WALLETCONNECT_PROJECT_ID` | WalletConnect/Reown project ID |

## Development Commands

All commands are run via `make` in the respective directory.

### API (`cd api`)

| Command | Description |
|---------|-------------|
| `make install` | Install Python dependencies via uv |
| `make start` | Start API server with hot reload |
| `make start-worker` | Start background position monitor |
| `make lint-check` | Run linter |
| `make lint-fix` | Auto-fix lint issues |
| `make type-check` | Run type checker |
| `make security-check` | Run security scanner |

### App (`cd app`)

| Command | Description |
|---------|-------------|
| `make install` | Install npm dependencies |
| `make start` | Start Vite dev server |
| `make build` | Production build |
| `make lint-check` | Run linter |
| `make lint-fix` | Auto-fix lint issues |
| `make type-check` | Run type checker |

### Database Migrations

```bash
cd api
./create-migration.sh "description of change"
```

Never create migration files manually.

## Deployment

- **API + Worker**: Docker images pushed to GHCR, deployed to EC2 via SSH on merge to `main`
- **Frontend**: Static build synced to S3, CloudFront cache invalidated on merge to `main`
- **Domains**: `borrowbot-api.kibalabs.com` (API), `borrowbot.kibalabs.com` (frontend)

## Project Structure

```
BorrowBot/
  api/
    money_hack/
      api/              # 32 REST endpoints, auth, models
      agent/            # Gemini chat with 5 tools
      morpho/           # Morpho Blue client, LTV manager
      forty_acres/      # 40acres vault client
      yo/               # Yo.xyz vault client
      blockchain_data/  # Alchemy, Moralis, Blockscout
      external/         # Coinbase CDP, ENS, LI.FI, Telegram
      smart_wallets/    # EIP-7702, bundler, paymaster
      store/            # SQLAlchemy, repository pattern
      agent_manager.py  # Central business logic orchestrator
    worker.py           # Background monitoring loop
    alembic/            # Database migrations
    scripts/            # Operational utilities
  app/
    src/
      pages/            # Route-level components
      components/       # Shared UI (dashboard, chat, dialogs)
      client/           # Typed API client
  docs/                 # Documentation
  .github/workflows/    # CI/CD pipelines
```

## Documentation

- [Product Development Requirements](docs/project-overview-pdr.md)
- [Codebase Summary](docs/codebase-summary.md)
- [Code Standards](docs/code-standards.md)
- [System Architecture](docs/system-architecture.md)
- [Implementation Plan](docs/plan.md)
- [Presentation Notes](docs/presentation.md)

## License

TBD
