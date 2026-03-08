# BorrowBot - Product Development Requirements

## Project Identity

- **Name**: BorrowBot
- **Tagline**: Autonomous DeFi lending agent on Base
- **Origin**: EthGlobal HackMoney 2026 hackathon project
- **Repository**: `BorrowBot` monorepo (api + app)

## Problem Statement

Generating yield from overcollateralized lending in DeFi requires constant manual effort. Users must select lending markets, monitor loan-to-value ratios around the clock, rebalance positions when prices move, bridge assets across chains, and manage gas across multiple networks. A single missed rebalance during a price drop can result in liquidation and significant loss of funds.

Most DeFi users either avoid lending entirely due to this complexity or accept suboptimal returns because they cannot monitor positions 24/7.

## Solution Overview

BorrowBot is a fully autonomous DeFi agent that lives on Base. Users deposit collateral (WETH or cbBTC), and the agent handles everything else:

1. Borrows USDC against the collateral via Morpho Blue
2. Deposits borrowed USDC into a yield vault (40acres/Yo.xyz) earning ~7-10% APY
3. Monitors the position every 5 minutes
4. Auto-rebalances to prevent liquidation (repays debt when LTV rises)
5. Auto-optimizes to maximize yield (borrows more when LTV is safely low)
6. Communicates proactively via Telegram
7. Accepts deposits from any chain and withdraws to any chain

The user never pays gas. All agent transactions are sponsored by the Coinbase Paymaster.

## Target Users

- DeFi participants holding WETH or cbBTC who want passive yield without active management
- Users on any EVM chain who want exposure to Base-native yield opportunities
- Crypto holders who want overcollateralized borrowing without liquidation risk

## Key Features

### Autonomous LTV Management
A background worker checks all active positions every 300 seconds. The `LtvManager` compares current LTV against the user's target and applies profitability gates (yield APY vs borrow APR, minimum annual gain threshold, price volatility suppression using 1h/24h historical data). Actions:

- **Auto-Repay**: When LTV exceeds target, the agent withdraws USDC from the yield vault and repays Morpho debt
- **Auto-Optimize**: When LTV is significantly below target and the yield spread is positive, the agent borrows more USDC to increase yield
- **Auto-Deploy**: Idle wallet assets (collateral or USDC) are automatically deployed into the position

### ENS On-Chain Constitution
Each agent receives a `<name>.borrowbott.eth` subname registered via the ENS NameWrapper on Ethereum mainnet. ENS text records serve as a decentralized governance layer:

- **Owner-set guardrails**: `com.borrowbot.max-ltv`, `com.borrowbot.min-spread`, `com.borrowbot.max-position-usd`, `com.borrowbot.allowed-collateral`, `com.borrowbot.pause`
- **Agent-written status**: `com.borrowbot.status`, `com.borrowbot.last-action`, `com.borrowbot.last-check`
- The agent reads its constitution before every action cycle and writes status back, creating a verifiable on-chain audit trail
- Owners can modify agent behavior from any ENS-compatible interface

### Cross-Chain Access (LI.FI)
- **Deposits**: Users deposit from any EVM chain via the embedded LI.FI Widget. LI.FI Composer routes funds to Base and delivers them to the agent wallet.
- **Withdrawals**: The agent fetches a LI.FI quote, approves USDC to the LI.FI Diamond, and executes the bridge transaction on Base via paymaster-sponsored UserOperations.
- **Status tracking**: All cross-chain actions are logged with bridge name, route, and live status polling.

### Telegram Notifications
- Rebalancing event alerts (auto-repay, auto-optimize)
- Critical liquidation warnings (80% of max LTV)
- Cross-chain bridge completion/failure notifications
- Two-way communication: users can message their agent via Telegram

### AI Chat Interface
Gemini-powered conversational interface available in-app and via Telegram. The agent has access to 5 tools:
- `get_position` - current position data
- `get_market_data` - live rates and spreads
- `get_price_analysis` - historical price data
- `get_action_history` - recent agent actions
- `set_target_ltv` - modify the target LTV

The LLM runs a tool-calling loop (up to 10 iterations) to answer questions with real data.

### Smart Wallet Architecture
Agent wallets are EOAs created via Coinbase CDP, then upgraded to smart wallets using EIP-7702. This enables batching multiple contract calls into a single UserOperation. All transactions use `shouldSponsorGas=True` with the Coinbase Paymaster.

## Target Chains

| Chain | Role |
|-------|------|
| Base (8453) | Execution chain: collateral, Morpho borrowing, vault yield, LTV management |
| Ethereum Mainnet (1) | ENS name registration and constitution storage |
| Any EVM chain | Deposit source and withdrawal destination via LI.FI |

## Protocol Integrations

| Protocol | Purpose | Integration Type |
|----------|---------|-----------------|
| Morpho Blue | Overcollateralized USDC borrowing against WETH/cbBTC | GraphQL API + on-chain (supply, borrow, repay, withdraw) |
| 40acres / Yo.xyz | ERC-4626 USDC yield vault (~7-10% APY) | On-chain (deposit, redeem) |
| Coinbase CDP | Agent EOA wallet creation | REST API |
| Coinbase Smart Wallet | EIP-7702 wallet upgrade + paymaster gas sponsorship | Bundler API (UserOperations) |
| ENS (NameWrapper) | Agent identity + on-chain constitution | On-chain (mainnet) |
| LI.FI | Cross-chain deposits and withdrawals | REST API (`/v1/quote`, `/v1/status`) + React Widget |
| Telegram Bot API | User notifications and two-way messaging | Webhook + REST API |
| Google Gemini | AI chat with tool calling | REST API |
| Alchemy | Token balances, historical pricing, RPC | REST API + JSON-RPC |
| Moralis | Supplementary blockchain data | REST API |
| Blockscout | Transaction and contract data | REST API |

## User Flows

### New User Setup
1. Connect wallet (WalletConnect/Reown) on the HomePage
2. Sign SIWE message to authenticate
3. Choose collateral asset (WETH or cbBTC)
4. Name the agent and select an emoji
5. Fund the agent wallet (direct deposit on Base or cross-chain via LI.FI)
6. Deploy: the agent executes a 5-transaction batch (approve collateral, supply to Morpho, borrow USDC, approve USDC, deposit to vault)
7. Agent begins autonomous monitoring

### Returning User
1. Connect wallet, auto-redirected to agent dashboard
2. View position: LTV gauge, yield spread, assets vs debt, net position value
3. View agent terminal showing recent autonomous actions
4. Optionally: deposit more, withdraw USDC, adjust target LTV, close position

### Cross-Chain Deposit
1. Click deposit on the agent dashboard
2. Select "Cross-Chain" to open the LI.FI Widget
3. Choose source chain and token
4. Sign one transaction on the source chain
5. Funds arrive in the agent wallet on Base
6. Agent auto-detects and deploys idle assets on the next worker cycle

### Withdrawal
1. Request withdrawal (on-Base or cross-chain) specifying amount and destination
2. Agent checks LTV safety (ensures withdrawal does not breach hard max LTV)
3. Agent redeems vault shares, bridges if cross-chain, delivers funds
4. Telegram notification on completion

## Non-Functional Requirements

| Requirement | Specification |
|-------------|---------------|
| Monitoring interval | Every 300 seconds (5 minutes) |
| Gas cost to user | Zero (all agent transactions sponsored by Coinbase Paymaster) |
| Authentication | SIWE (Sign-In with Ethereum) + JWT tokens |
| Position data source | Live on-chain reads (no cached holdings in DB) |
| Wallet security | EOA keys managed by Coinbase CDP, EIP-7702 smart wallet with bundler address whitelist |
| Availability | API and Worker run as separate Docker containers with `--restart on-failure` |
| Frontend delivery | Static SPA via CloudFront + S3 |
