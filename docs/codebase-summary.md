# BorrowBot - Codebase Summary

## High-Level Architecture

BorrowBot is a monorepo with two deployable units and shared CI/CD:

```
+------------------+       +------------------+       +------------------+
|   React SPA      | ----> |   REST API       | ----> |   PostgreSQL     |
|   (CloudFront)   |       |   (EC2/Docker)   |       |   (EC2)          |
+------------------+       +------------------+       +------------------+
                                    |
                            +-------+-------+
                            |               |
                    +-------v----+   +------v-------+
                    |   Worker   |   |   External   |
                    |  (EC2/     |   |   Services   |
                    |   Docker)  |   |              |
                    +------------+   +--------------+
```

- **Frontend**: React 19 SPA served as static files from CloudFront + S3
- **API Server**: Python (Starlette/kiba-core) serving REST endpoints, deployed as a Docker container on EC2
- **Worker**: Background process running the same Docker image with `make start-worker`, checking positions every 300 seconds
- **Database**: PostgreSQL with Alembic migrations

## Directory Structure

```
BorrowBot/
  api/                          # Python backend
    money_hack/                 # Main application package
      api/                      # REST endpoints, request/response models, auth
        v1_api.py               # Route definitions (32 endpoints)
        v1_endpoints.py         # Pydantic request/response models
        v1_resources.py         # Pydantic API resource models
        v1_resource_builder.py  # Entity-to-resource mapping
        authorizer.py           # SIWE signature verification + JWT
      agent/                    # AI chat system
        chat_bot.py             # Gemini tool-calling loop
        gemini_llm.py           # Google Gemini API wrapper
        chat_tool.py            # Base class for chat tools
        chat_history_store.py   # Conversation persistence
        runtime_state.py        # Per-request agent state
        tools/                  # 5 pluggable chat tools
      morpho/                   # Morpho Blue protocol integration
        morpho_client.py        # GraphQL client for market data
        morpho_queries.py       # GraphQL query definitions
        morpho_abis.py          # Contract ABIs
        transaction_builder.py  # Morpho transaction construction
        ltv_manager.py          # LTV calculation and rebalance decisions
      forty_acres/              # 40acres vault integration
        forty_acres_client.py   # ERC-4626 vault interactions
        forty_acres_abis.py     # Contract ABIs
      yo/                       # Yo.xyz vault integration
        yo_client.py            # ERC-4626 vault interactions
        yo_abis.py              # Contract ABIs
      blockchain_data/          # On-chain data providers
        alchemy_client.py       # Alchemy API (balances, history, RPC)
        moralis_client.py       # Moralis API
        blockscout_client.py    # Blockscout API
        findblock_client.py     # Block lookup by timestamp
        blockchain_data_client.py
        price_intelligence_service.py  # Historical price analysis
      external/                 # Third-party service clients
        coinbase_cdp_client.py  # Coinbase CDP wallet creation
        ens_client.py           # ENS name registration + text records
        lifi_client.py          # LI.FI quote + status API
        telegram_client.py      # Telegram Bot API
      smart_wallets/            # EIP-7702 smart wallet system
        coinbase_smart_wallet.py  # Smart wallet upgrade logic
        coinbase_bundler.py     # UserOperation bundler + paymaster
        coinbase_constants.py   # Contract addresses, whitelists
        model.py                # UserOperation data models
      store/                    # Data access layer
        schema.py               # SQLAlchemy table definitions
        database_store.py       # Database connection + repositories
        entity_repository.py    # Generic CRUD repository
        file_store.py           # File-based storage
      agent_manager.py          # Central orchestrator (1841 lines)
      create_agent_manager.py   # Factory for AgentManager with all dependencies
      cross_chain_yield_manager.py  # LI.FI cross-chain logic
      notification_service.py   # Telegram notification dispatch
      model.py                  # Core domain models (7 entities)
      constants.py              # Chain IDs, token addresses
      messages.py               # Notification message templates
      util.py                   # Shared utilities
    alembic/                    # Database migration scripts
    scripts/                    # Operational scripts
    application.py              # ASGI app entry point
    worker.py                   # Background worker entry point
    pyproject.toml              # Python dependencies (uv)
    makefile                    # Development commands
    Dockerfile                  # Production container

  app/                          # React frontend
    src/
      pages/                    # Route-level components
        HomePage.tsx            # Wallet connect landing
        AgentsPage.tsx          # Agent list
        AgentPage.tsx           # Agent dashboard (main view)
        CreateAgentPage.tsx     # Name + emoji wizard
        FundAgentPage.tsx       # Deposit flow
        DeployAgentPage.tsx     # Position deployment
        SetupPage.tsx           # All-in-one setup wizard
        AccountPage.tsx         # Telegram settings
      components/               # Shared UI components
        PositionDashboard.tsx   # LTV gauge, yield, assets vs debt
        AgentTerminal.tsx       # Streaming action log
        FloatingChat.tsx        # AI chat widget
        DepositDialog.tsx       # On-Base deposit
        LiFiDepositDialog.tsx   # Cross-chain deposit via LI.FI Widget
        WithdrawDialog.tsx      # USDC withdrawal
        ClosePositionDialog.tsx # Full position unwinding
        DepositForm.tsx         # Deposit amount input
        DepositUsdcDialog.tsx   # USDC-specific deposit
        StepProgress.tsx        # Multi-step progress indicator
        GlowingButton.tsx       # Branded CTA button
      client/                   # API client layer
        client.ts               # MoneyHackClient (extends ServiceClient)
        endpoints.ts            # Typed endpoint definitions
        resources.ts            # API resource TypeScript types
      AuthContext.tsx            # SIWE auth state
      GlobalsContext.tsx        # App-wide config
      PageDataContext.tsx       # Per-page data loading
      app.tsx                   # Router and layout
    makefile                    # Development commands
    package.json                # npm dependencies
    Dockerfile                  # Build container

  docs/                         # Documentation
  .github/
    workflows/                  # CI/CD pipelines
      api-check.yml             # PR checks (lint, type, security)
      api-deploy.yml            # Build + deploy API and Worker to EC2
      app-check.yml             # PR checks (lint, type)
      app-deploy.yml            # Build + deploy static to S3/CloudFront
    copilot-instructions.md     # Code conventions
```

## Key Modules

### AgentManager (`agent_manager.py`)
Central orchestrator for all business logic. Handles user management, agent CRUD, position lifecycle (create, deploy, withdraw, close), autonomous monitoring (LTV checks, auto-repay, auto-optimize), ENS operations, cross-chain actions, and chat routing. All API endpoints delegate to this class.

### LtvManager (`morpho/ltv_manager.py`)
Decision engine for autonomous rebalancing. Compares current LTV to target, applies profitability gates (yield spread, minimum annual gain, price volatility suppression), and outputs an action recommendation.

### Worker (`worker.py`)
Background loop that calls `check_positions_once()` every 300 seconds. Iterates all active positions, fetches on-chain state, reads ENS constitution, runs the LTV decision engine, executes rebalancing transactions, checks cross-chain action status, and sends Telegram notifications.

### CrossChainManager (`cross_chain_yield_manager.py`)
Manages LI.FI integration for cross-chain deposits and withdrawals. Prepares quotes, records actions, and polls bridge status.

### ChatBot (`agent/chat_bot.py`)
Gemini-powered conversational agent with a tool-calling loop (up to 10 iterations). Uses pluggable `ChatTool` subclasses to access position data, market rates, price analysis, action history, and LTV adjustment.

## Data Flow

### User Action Flow
```
User (browser)
  --> React SPA (wagmi wallet interaction)
    --> MoneyHackClient (signature-authenticated HTTP)
      --> v1_api.py (route handler)
        --> AgentManager (business logic)
          --> Store (PostgreSQL read/write)
          --> External clients (Morpho, vault, Coinbase, ENS, LI.FI)
          --> Coinbase Bundler (UserOperation submission)
            --> Base blockchain (transaction execution)
```

### Background Processing Flow
```
Worker loop (every 300s)
  --> AgentManager.check_positions_once()
    --> For each active position:
      --> Fetch on-chain state (Morpho collateral/borrow, vault shares, wallet balances)
      --> Read ENS constitution from mainnet
      --> LtvManager evaluates action needed
      --> If rebalance needed:
        --> Build transaction(s)
        --> Submit via Coinbase Bundler (paymaster-sponsored)
        --> Log action to DB
        --> Send Telegram notification
      --> Check pending cross-chain actions (poll LI.FI status)
```

## Database Schema

7 tables using SQLAlchemy with Alembic migrations:

| Table | Primary Key | Description |
|-------|-------------|-------------|
| `tbl_users` | UUID | User accounts (wallet-linked, optional Telegram) |
| `tbl_user_wallets` | UUID | Wallet addresses associated with users |
| `tbl_agents` | UUID | Named agents with emoji, wallet address, ENS name |
| `tbl_agent_positions` | Integer | Active lending positions (collateral asset, target LTV, market ID, status) |
| `tbl_agent_actions` | Integer | Audit log of all agent actions (type, value, details JSON) |
| `tbl_chat_events` | Integer | Chat conversation history (user messages + agent responses) |
| `tbl_cross_chain_actions` | Integer | Cross-chain deposit/withdrawal tracking (chain, token, bridge, status) |

## External Service Dependencies

| Service | Client Module | Purpose |
|---------|---------------|---------|
| Morpho Blue (GraphQL) | `morpho/morpho_client.py` | Market data, borrow rates, LLTV |
| Morpho Blue (on-chain) | `morpho/transaction_builder.py` | Supply, borrow, repay, withdraw |
| 40acres / Yo.xyz vault | `forty_acres/`, `yo/` | ERC-4626 deposit and redeem |
| Coinbase CDP | `external/coinbase_cdp_client.py` | EOA wallet creation |
| Coinbase Bundler | `smart_wallets/coinbase_bundler.py` | UserOperation submission + paymaster |
| ENS NameWrapper | `external/ens_client.py` | Subname registration, text record read/write |
| LI.FI | `external/lifi_client.py` | Cross-chain quote and status |
| Telegram Bot API | `external/telegram_client.py` | Notifications and webhook |
| Google Gemini | `agent/gemini_llm.py` | LLM for chat tool-calling loop |
| Alchemy | `blockchain_data/alchemy_client.py` | Token balances, historical data, RPC |
| Moralis | `blockchain_data/moralis_client.py` | Supplementary blockchain data |
| Blockscout | `blockchain_data/blockscout_client.py` | Transaction and contract data |
