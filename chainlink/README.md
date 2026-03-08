# BorrowBot x Chainlink CRE — AI Risk Oracle

Chainlink CRE (Compute Runtime Environment) integration for BorrowBot, an autonomous DeFi lending agent on Base.

## What It Does

A CRE workflow that runs every 5 minutes to monitor BorrowBot positions with decentralized consensus:

1. **Handler 1 (Cron)**: Fetches position data from BorrowBot API + market prices from CoinGecko (consensus-verified across DON nodes) → asks Gemini LLM to assess risk → writes risk assessment to `BorrowBotRiskOracle` contract on-chain
2. **Handler 2 (Log Trigger)**: When RiskOracle emits `CriticalRisk` event → fetches latest position data → asks Gemini for optimal rebalance strategy → writes rebalance command to `BorrowBotExecutor` contract

## Architecture

```
                  CRE Workflow (DON)
                  ┌─────────────────────────────────┐
  Every 5 min     │                                 │
  ─────────────►  │  Handler 1: Risk Assessment     │
                  │  ┌───────────────────────────┐  │
                  │  │ HTTP: BorrowBot API        │  │
                  │  │ HTTP: CoinGecko (prices)   │  │
                  │  │ HTTP: Gemini LLM (risk)    │  │
                  │  │ EVM Write: RiskOracle      │──┼──► BorrowBotRiskOracle.sol
                  │  └───────────────────────────┘  │         │
                  │                                 │    CriticalRisk event
                  │  Handler 2: Auto-Protect        │         │
                  │  ┌───────────────────────────┐  │         ▼
                  │  │ Log Trigger: CriticalRisk  │◄─┼──── (on-chain event)
                  │  │ HTTP: BorrowBot API        │  │
                  │  │ HTTP: Gemini LLM (strategy)│  │
                  │  │ EVM Write: Executor        │──┼──► BorrowBotExecutor.sol
                  │  └───────────────────────────┘  │
                  └─────────────────────────────────┘
```

## Files Using Chainlink

### Smart Contracts (Foundry)
- [`contracts/src/BorrowBotRiskOracle.sol`](contracts/src/BorrowBotRiskOracle.sol) — Receives CRE risk assessments, stores on-chain, emits `CriticalRisk`
- [`contracts/src/BorrowBotExecutor.sol`](contracts/src/BorrowBotExecutor.sol) — Receives CRE rebalance commands for the agent to execute
- [`contracts/src/interfaces/IReceiver.sol`](contracts/src/interfaces/IReceiver.sol) — CRE receiver interface
- [`contracts/src/interfaces/ReceiverTemplate.sol`](contracts/src/interfaces/ReceiverTemplate.sol) — CRE receiver base with forwarder validation
- [`contracts/script/Deploy.s.sol`](contracts/script/Deploy.s.sol) — Sepolia deployment script
- [`contracts/test/BorrowBotRiskOracle.t.sol`](contracts/test/BorrowBotRiskOracle.t.sol) — Oracle contract tests
- [`contracts/test/BorrowBotExecutor.t.sol`](contracts/test/BorrowBotExecutor.t.sol) — Executor contract tests

### CRE Workflow (TypeScript)
- [`workflow/main.ts`](workflow/main.ts) — Workflow entry point with cron + log trigger handlers
- [`workflow/riskAssessment.ts`](workflow/riskAssessment.ts) — Handler 1: cron-based risk assessment
- [`workflow/autoProtect.ts`](workflow/autoProtect.ts) — Handler 2: event-driven auto-protection
- [`workflow/gemini.ts`](workflow/gemini.ts) — Gemini LLM integration with consensus
- [`workflow/config.ts`](workflow/config.ts) — Zod config schema
- [`workflow/config.staging.json`](workflow/config.staging.json) — Sepolia configuration
- [`workflow/config.production.json`](workflow/config.production.json) — Production configuration

### CRE Configuration
- [`project.yaml`](project.yaml) — CRE project settings (RPC endpoints)
- [`workflow/workflow.yaml`](workflow/workflow.yaml) — Workflow settings (name, paths)
- [`secrets.yaml`](secrets.yaml) — Secret references (Gemini API key)

### BorrowBot API Integration
- [`../api/money_hack/api/v1_api.py`](../api/money_hack/api/v1_api.py) — Added `GET /v1/cre/position-data` public endpoint
- [`../api/money_hack/api/v1_endpoints.py`](../api/money_hack/api/v1_endpoints.py) — CRE position data request/response types
- [`../api/money_hack/agent_manager.py`](../api/money_hack/agent_manager.py) — `get_cre_position_data()` method

## CRE Capabilities Used

| Capability | Usage |
|-----------|-------|
| **Cron Trigger** | Every 5 minutes, triggers risk assessment |
| **Log Trigger** | Fires on `CriticalRisk` event from RiskOracle |
| **HTTP Client** | Fetches BorrowBot API, CoinGecko prices, Gemini LLM |
| **Consensus** | All HTTP responses verified across DON nodes |
| **EVM Write** | Publishes risk assessments and rebalance commands on-chain |
| **Secrets** | Gemini API key managed via CRE secrets |

## Setup

### Prerequisites
- Node.js v20+
- Bun v1.3+
- Foundry (for contract development)
- CRE CLI: `npm install -g @chainlink/cre`

### Install Dependencies
```bash
# Workflow
cd chainlink/workflow && bun install

# Contracts
cd chainlink/contracts && forge install
```

### Deploy Contracts (Sepolia)
```bash
cd chainlink/contracts
DEPLOYER_PRIVATE_KEY=<key> forge script script/Deploy.s.sol --rpc-url https://ethereum-sepolia-rpc.publicnode.com --broadcast
```

Update `riskOracleAddress` and `executorAddress` in `workflow/config.staging.json` with deployed addresses.

### Configure Secrets
```bash
cre secrets set GEMINI_API_KEY <your-gemini-api-key>
```

### Simulate
```bash
cd chainlink/workflow
cre workflow simulate --settings staging-settings
```

### Run Tests
```bash
cd chainlink/contracts
forge test -vv
```

## Why CRE

BorrowBot's Python worker monitors positions from a single server — a centralized point of failure. CRE replaces this with decentralized consensus:

- **Price data** verified by multiple DON nodes (not a single RPC)
- **AI risk assessment** produced deterministically with consensus
- **On-chain audit trail** — every risk assessment is permanently recorded
- **Event-driven protection** — CriticalRisk triggers immediate response without polling
- **Tamper-proof** — no single party can manipulate the risk assessment
