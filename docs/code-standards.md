# BorrowBot - Code Standards

## Python Conventions

### Naming
- **Functions**: `snake_case` (e.g., `get_supported_collaterals`, `execute_withdraw`)
- **Variables**: `camelCase` (e.g., `userAddress`, `agentManager`, `collateralAmount`)
- **Classes**: `PascalCase` (e.g., `AgentManager`, `LtvManager`, `ChatBot`)
- **Constants**: `SCREAMING_SNAKE_CASE` (e.g., `BASE_CHAIN_ID`, `NATIVE_TOKEN_ADDRESS`)

### Style Rules
- Use named parameters wherever possible
- No newlines within function bodies
- No comments that are easily inferred from the code itself
- Use explanatory variable and function names instead of comments
- Do not broadly catch exceptions unless there is a specific reason to do so
- Do not use placeholder values; ask for clarification if unsure

### Tooling
- **Package manager**: `uv` (dependencies in `pyproject.toml`, lockfile in `uv.lock`)
- **Linting**: `uv run lint-check` (with `--fix` for auto-fix via `make lint-fix`)
- **Type checking**: `uv run type-check`
- **Security scanning**: `uv run security-check`
- **Server**: uvicorn with ASGI
- **Formatting**: isort for import sorting (single-line, line length 1000)

### Error Handling
- Handle specific error scenarios, not blanket try/catch
- Custom exceptions via `core.exceptions` (e.g., `KibaException`, `NotFoundException`)

## TypeScript Conventions

### Naming
- **Functions and variables**: `camelCase`
- **Components**: `PascalCase`
- **Types/Interfaces**: `PascalCase`

### Tooling
- **Package manager**: npm (with `--legacy-peer-deps`)
- **Build**: Vite via `@kibalabs/build` (`npx build-react-app-vite`)
- **Linting**: `npx lint` (with `--fix` for auto-fix via `make lint-fix`)
- **Type checking**: `npx type-check`

## Database Conventions

### Primary Keys
- **User-related entities** (`users`, `user_wallets`, `agents`): UUID primary keys
- **All other entities** (`agent_positions`, `agent_actions`, `chat_events`, `cross_chain_actions`): Integer auto-increment primary keys

### Patterns
- Repository pattern via `EntityRepository` generic class (no raw SQL in business logic)
- All tables prefixed with `tbl_` (e.g., `tbl_users`, `tbl_agents`)
- All entities have `createdDate` and `updatedDate` timestamps
- Domain models defined in `model.py` as Pydantic `BaseModel` subclasses
- Entity-to-resource mapping isolated in `v1_resource_builder.py`

### Migrations
- Use `./create-migration.sh "message"` to create schema migrations
- Never create migration files manually
- Never run migrations in agentic (automated) workflows
- Alembic manages all schema changes

## API Patterns

### Routing
- Starlette `Route` objects constructed in `create_v1_routes()`
- Each route uses `@json_route` decorator for automatic request/response serialization
- Request and response types are Pydantic models in `v1_endpoints.py`

### Authentication
- SIWE (Sign-In with Ethereum): user signs a message with their wallet
- `@authorize_signature` decorator validates the signature and injects user context
- JWT tokens for session persistence after initial SIWE authentication

### Request/Response
- All requests and responses are Pydantic `BaseModel` subclasses
- Resource models (API-facing) are separate from domain models (internal)
- `v1_resource_builder.py` handles the mapping between domain entities and API resources

### Async
- All endpoint handlers and business logic are `async` functions
- Database access, external API calls, and blockchain reads are all awaited

## Frontend Patterns

### State Management
- React Context for global state: `AuthContext`, `GlobalsContext`, `PageDataContext`
- No Redux or external state management library
- `@tanstack/react-query` for server state

### Component Architecture
- Page components in `src/pages/` (route-level)
- Shared components in `src/components/`
- Dialog pattern for modal interactions (e.g., `DepositDialog`, `WithdrawDialog`)
- `@kibalabs/ui-react` component library for base UI primitives

### API Client
- `MoneyHackClient` extends `ServiceClient` from `@kibalabs/core`
- Signature-based authentication on all requests
- Typed endpoint definitions in `client/endpoints.ts`
- Resource types in `client/resources.ts`

### Styling
- SCSS modules
- Dark mode design
- Host Grotesk font family
- Accent colors: orange, green, yellow

### Wallet Integration
- `wagmi` for wallet connections
- `@kibalabs/web3-react` with Reown (WalletConnect) connector

## Development Workflow

### Commands (via Makefile)

Both `api/` and `app/` directories have a `makefile` with consistent targets:

| Command | API | App |
|---------|-----|-----|
| `make install` | `uv sync --all-extras` | `npm ci --legacy-peer-deps` |
| `make start` | uvicorn with reload on port 5000 | Vite dev server |
| `make lint-check` | `uv run lint-check` | `npx lint` |
| `make lint-fix` | isort + lint-check --fix | `npx lint --fix` |
| `make type-check` | `uv run type-check` | `npx type-check` |
| `make security-check` | `uv run security-check` | Not supported |
| `make start-worker` | Runs `worker.py` | N/A |

### Environment Management
- `envrc` (direnv) manages environment variables per directory
- `envrc` only loads when the directory is entered; you must `cd` into a directory before running commands
- Environment variables stored in `.envrc` files (not committed)
- Production environment variables stored in `~/.borrowbot-api.vars` on the server

### Development Rules
- Do not create test scripts; write Python code to execute in a console when necessary
- Do not compile files manually; use `make lint-fix` to check for syntax errors
- Do not pipe command output; nothing in this project produces output large enough to warrant it
- Only run syntactic checks after implementation is complete and verified
- Use the Makefile for all commands

## CI/CD Standards

### PR Checks (required before merge)

**API (`api-check.yml`)**:
- `make lint-check-ci` (JSON annotation output)
- `make type-check-ci` (JSON annotation output)
- `make security-check-ci` (JSON annotation output)
- All checks run inside Docker for reproducibility

**App (`app-check.yml`)**:
- `make lint-check-ci`
- `make type-check-ci`

### Deployment (on merge to `main`)

**API (`api-deploy.yml`)**:
1. Build Docker image from `api/`
2. Push to GitHub Container Registry (`ghcr.io`)
3. SSH to EC2, pull image, restart `borrowbot-api` container
4. SSH to EC2, pull image, restart `borrowbot-worker` container (same image, different entrypoint)

**App (`app-deploy.yml`)**:
1. Build static files in Docker
2. Extract `dist/` from container
3. Sync to S3 bucket
4. Invalidate CloudFront cache

### Key Files for Reference
- `api/money_hack/api/v1_api.py` - All route definitions and Pydantic models
- `api/money_hack/agent_manager.py` - Entry point for all backend business logic
- `api/money_hack/model.py` - Domain model definitions
- `app/src/pages/AgentPage.tsx` - Main dashboard logic
