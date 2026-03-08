# BorrowBot - System Architecture

## System Architecture Diagram

```
                                  +---------------------------+
                                  |      User's Browser       |
                                  |  (React SPA + wagmi)      |
                                  +------------+--------------+
                                               |
                                    HTTPS (signature auth)
                                               |
+------------------+               +-----------v-----------+               +----------------+
|   CloudFront     |  static SPA   |                       |  SQL (async)  |                |
|   + S3 Bucket    | ------------> |     API Server         | <-----------> |   PostgreSQL   |
|   (app hosting)  |               |   (Starlette/Docker)   |               |                |
+------------------+               |                       |               +----------------+
                                   +-----------+-----------+
                                               |
                                   +-----------+-----------+
                                   |                       |
                          +--------v--------+     +--------v--------+
                          |     Worker      |     | External Clients |
                          | (same image,    |     +--------+---------+
                          |  background     |              |
                          |  loop)          |     +--------v------------------+
                          +-----------------+     |                           |
                                                  |  Morpho Blue (Base)       |
                                                  |  Yo/40acres Vault (Base)  |
                                                  |  Coinbase CDP (REST)      |
                                                  |  Coinbase Bundler (RPC)   |
                                                  |  ENS NameWrapper (L1)     |
                                                  |  LI.FI (REST)             |
                                                  |  Telegram Bot API         |
                                                  |  Google Gemini (REST)     |
                                                  |  Alchemy (REST + RPC)     |
                                                  +---------------------------+
```

## Component Breakdown

### Frontend (React SPA)
- **Runtime**: React 19 with TypeScript, built with Vite
- **Hosting**: Static files on S3, served via CloudFront CDN
- **Domain**: `borrowbot.kibalabs.com`
- **Wallet**: wagmi + Reown (WalletConnect) for wallet connections
- **State**: React Context (Auth, Globals, PageData) + TanStack React Query
- **Key views**: Setup wizard, agent dashboard (LTV gauge, terminal, cross-chain panel, constitution panel, chat)

### API Server
- **Runtime**: Python 3.12, Starlette framework (via kiba-core), uvicorn ASGI server
- **Hosting**: Docker container on EC2, exposed via nginx reverse proxy with Let's Encrypt TLS
- **Domain**: `borrowbot-api.kibalabs.com`
- **Endpoints**: 32 REST endpoints covering collaterals, market data, user config, agents, positions, ENS, chat, Telegram, cross-chain actions
- **Entry point**: `application.py` creates the ASGI app with routes from `create_v1_routes()`

### Worker
- **Runtime**: Same Docker image as the API, started with `make start-worker`
- **Behavior**: Infinite loop calling `check_positions_once()` every 300 seconds
- **Responsibilities**: LTV monitoring, auto-rebalance execution, cross-chain status polling, Telegram notifications

### Database (PostgreSQL)
- **Schema**: 7 tables managed by Alembic migrations
- **Access**: SQLAlchemy via `EntityRepository` generic class
- **Data volume**: Persistent volume mount at `/home/ec2-user/borrowbot-data`

## Authentication Flow

```
1. User connects wallet (WalletConnect/Reown)
                    |
2. Frontend constructs SIWE message
                    |
3. User signs message with wallet
                    |
4. Frontend sends signed message to API
                    |
5. API verifies signature (authorizer.py)
   - Recovers signer address from signature
   - Creates/retrieves User + UserWallet records
                    |
6. API returns JWT token
                    |
7. Frontend includes JWT + wallet signature on subsequent requests
                    |
8. @authorize_signature decorator validates on each endpoint
```

## Agent Lifecycle

### 1. Create Agent
- User provides name and emoji
- API creates a Coinbase CDP EOA wallet for the agent
- EOA is upgraded to a smart wallet via EIP-7702 delegation to the Coinbase Smart Wallet implementation
- Agent record created in DB with wallet address
- ENS subname `<name>.borrowbott.eth` registered on mainnet via NameWrapper
- Initial constitution records written via `resolver.multicall()` (8 `setText` calls batched)

### 2. Fund Agent
- **Direct deposit (Base)**: User transfers WETH, cbBTC, or USDC directly to the agent wallet address on Base
- **Cross-chain deposit (any chain)**: User deposits via embedded LI.FI Widget, which routes funds to the agent wallet on Base

### 3. Deploy Position
- Agent executes a 5-transaction batch via a single UserOperation:
  1. Approve collateral token to Morpho
  2. Supply collateral to Morpho market
  3. Borrow USDC from Morpho at target LTV
  4. Approve USDC to Yo vault
  5. Deposit USDC to Yo vault
- Position record created in DB with status `active`
- All gas sponsored by Coinbase Paymaster

### 4. Monitor (Autonomous)
- Worker loop runs every 300 seconds
- For each active position:
  - Fetch live on-chain data (Morpho collateral/borrow, vault shares, wallet balances)
  - Read ENS constitution from mainnet
  - Check `com.borrowbot.pause` -- if `true`, skip all actions
  - Calculate current LTV and compare to target
  - Apply profitability gates (yield spread, minimum annual gain, price volatility)
  - Determine action: auto-repay, auto-optimize, deploy idle assets, or do nothing

### 5. Rebalance (Autonomous)
- **Auto-Repay** (LTV too high): Withdraw USDC from vault, repay Morpho debt
- **Auto-Optimize** (LTV safely low + positive spread): Borrow more USDC from Morpho, deposit to vault
- **Auto-Deploy** (idle wallet assets detected): Supply collateral to Morpho, borrow and deposit
- Each action logged to `tbl_agent_actions`, Telegram notification sent

### 6. Withdraw / Close
- **Partial withdraw**: User requests USDC amount, agent checks LTV safety, redeems vault shares, delivers funds
- **Cross-chain withdraw**: Same as above, plus agent bridges via LI.FI Diamond on Base
- **Close position**: Full unwind -- redeem all vault shares, repay all Morpho debt, withdraw all collateral, return to user

## Position Management Flow

```
                  +------------------+
                  | Collateral       |
                  | (WETH or cbBTC)  |
                  +--------+---------+
                           |
                    Supply to Morpho
                           |
                  +--------v---------+
                  | Morpho Blue      |   <-- Borrow USDC against collateral
                  | (Base)           |
                  +--------+---------+
                           |
                    Borrow USDC
                           |
                  +--------v---------+
                  | Yo/40acres Vault |   <-- Earn ~7-10% APY on borrowed USDC
                  | (ERC-4626, Base) |
                  +------------------+

Current LTV = Borrow Value / Collateral Value
Target LTV  = User-configured (constrained by ENS constitution)
Max LTV     = Morpho market LLTV (liquidation threshold)
```

## Cross-Chain Flow

### Deposits (Any Chain to Base)

```
User (source chain)
  --> LI.FI Widget (in frontend)
    --> LI.FI Composer routes: source token --> bridge --> Base collateral
      --> Funds arrive at agent wallet on Base
        --> Worker detects idle balance next cycle
          --> Auto-deploy into Morpho position
```

- User pays gas on the source chain
- `POST /cross-chain-deposit` records the action in `tbl_cross_chain_actions`
- Frontend shows status in `CrossChainPanel`

### Withdrawals (Base to Any Chain)

```
User requests: POST /cross-chain-withdraw
  --> Agent checks LTV safety
    --> Agent gets LI.FI quote (destination chain, token, address)
      --> UserOperation 1: Withdraw USDC from Yo vault
        --> UserOperation 2: Approve USDC + call LI.FI Diamond
          --> LI.FI bridges USDC to destination chain/token
            --> Worker polls /v1/status each cycle
              --> Telegram notification on completion
```

- Agent pays gas on Base via Coinbase Paymaster (user pays nothing)
- LI.FI Diamond (`0x1231DEB6f5749EF6cE6943a275A1D3E7486F4EaE`) is whitelisted in the bundler

## ENS Constitution Flow

### Owner Sets Rules
```
Owner (any ENS UI or BorrowBot frontend)
  --> setText on Public Resolver (mainnet)
    --> Records: com.borrowbot.max-ltv, min-spread, pause, etc.
```

### Agent Reads Constitution
```
Worker cycle (every 300s)
  --> EnsClient reads text records from mainnet resolver
    --> Parse constitution values
      --> If pause=true: halt all actions
      --> If LTV > max-ltv: force repay
      --> If spread < min-spread: suppress optimization
```

### Agent Writes Status
```
After each action cycle
  --> Agent batches setText calls via resolver.multicall()
    --> Writes: com.borrowbot.status, last-action, last-check
      --> On-chain audit trail viewable at app.ens.domains
```

## Chat System Architecture

```
User message (web chat or Telegram)
  --> API endpoint (POST /chat or Telegram webhook)
    --> ChatBot.process_message()
      --> Build prompt with system context + conversation history
        --> Send to Gemini LLM
          --> LLM returns tool call(s) or final response
            --> If tool call:
              --> Execute tool (get_position, get_market_data, etc.)
              --> Feed result back to LLM
              --> Loop (up to 10 iterations)
            --> If final response:
              --> Store in chat_events
              --> Return to user

Available Tools:
  - get_position: Current position data (LTV, collateral, borrow, vault)
  - get_market_data: Live borrow rates and vault APY
  - get_price_analysis: Historical price data from Alchemy
  - get_action_history: Recent agent actions from DB
  - set_target_ltv: Modify the agent's target LTV
```

## Smart Wallet Architecture

```
1. Coinbase CDP creates EOA
     |
2. EIP-7702 delegation to Coinbase Smart Wallet implementation
     |
3. Smart wallet can batch multiple calls into single UserOperation
     |
4. UserOperation submitted to Coinbase Bundler
     |
5. Bundler validates call targets against whitelist:
     - Morpho Blue contract
     - USDC token contract
     - Yo Vault contract
     - LI.FI Diamond
     - ENS Resolver
     |
6. Paymaster sponsors gas (shouldSponsorGas=True)
     |
7. Transaction executed on Base
```

## Deployment Architecture

```
+--------------------------------------------------+
|                   EC2 Instance                    |
|                                                   |
|  +-------------------+  +---------------------+  |
|  | borrowbot-api     |  | borrowbot-worker    |  |
|  | (Docker)          |  | (Docker)            |  |
|  | Port: dynamic     |  | No port             |  |
|  | Restart: on-fail  |  | Restart: on-fail    |  |
|  +-------------------+  +---------------------+  |
|           |                       |               |
|           +----------+------------+               |
|                      |                            |
|              +-------v--------+                   |
|              | Shared volume  |                   |
|              | /borrowbot-data|                   |
|              +-------+--------+                   |
|                      |                            |
|              +-------v--------+                   |
|              |  PostgreSQL    |                    |
|              +----------------+                   |
|                                                   |
|  +-------------------+                            |
|  | nginx-proxy       |                            |
|  | + Let's Encrypt   |                            |
|  | TLS termination   |                            |
|  +-------------------+                            |
+--------------------------------------------------+

+--------------------------------------------------+
|                  AWS (Frontend)                   |
|                                                   |
|  +-------------------+  +---------------------+  |
|  | S3 Bucket         |  | CloudFront CDN      |  |
|  | Static SPA files  |->| borrowbot.kibalabs  |  |
|  +-------------------+  |  .com                |  |
|                          +---------------------+  |
+--------------------------------------------------+
```

### Container Configuration
- **API container**: Same Docker image, default entrypoint (`make start-prod` via uvicorn)
- **Worker container**: Same Docker image, overridden entrypoint (`make start-worker`)
- **Environment**: Variables loaded from `~/.borrowbot-api.vars` on the host
- **TLS**: nginx reverse proxy with automatic Let's Encrypt certificates
- **CI/CD**: GitHub Actions builds and pushes to GHCR, then SSH to EC2 to pull and restart

## Security Considerations

### Wallet Security
- Agent private keys managed by Coinbase CDP (never stored in application database)
- EIP-7702 smart wallet with bundler address whitelist restricts callable contracts
- Paymaster validates all call targets before sponsoring gas

### Authentication
- SIWE ensures only the wallet owner can access their agent
- JWT tokens for session persistence
- Signature verification on every API request via `@authorize_signature` decorator

### Position Safety
- LTV hard max enforced before all operations (withdraw, optimize)
- ENS constitution provides owner-controlled guardrails (max LTV, pause switch)
- Profitability gates prevent unprofitable optimization
- Price volatility suppression using historical data prevents rebalancing during flash crashes

### On-Chain Transparency
- All agent actions logged to `tbl_agent_actions` database table
- Agent status written to ENS text records (verifiable by anyone)
- Cross-chain actions tracked with bridge status in `tbl_cross_chain_actions`
