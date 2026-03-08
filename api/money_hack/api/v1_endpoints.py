from pydantic import BaseModel
from pydantic import ConfigDict

from money_hack.api import v1_resources as resources


class GetSupportedCollateralsRequest(BaseModel):
    pass


class GetSupportedCollateralsResponse(BaseModel):
    collaterals: list[resources.CollateralAsset]


class GetUserConfigRequest(BaseModel):
    pass


class GetUserConfigResponse(BaseModel):
    user_config: resources.UserConfig


class UpdateUserConfigRequest(BaseModel):
    telegram_handle: str | None = None
    preferred_ltv: float | None = None


class UpdateUserConfigResponse(BaseModel):
    user_config: resources.UserConfig


class GetPositionRequest(BaseModel):
    pass


class GetPositionResponse(BaseModel):
    position: resources.Position | None


class CreatePositionRequest(BaseModel):
    collateral_asset_address: str
    collateral_amount: str
    target_ltv: float
    agent_name: str
    agent_emoji: str


class CreatePositionResponse(BaseModel):
    position: resources.Position
    agent: resources.Agent


class WithdrawRequest(BaseModel):
    amount: str


class WithdrawResponse(BaseModel):
    transactions: list[resources.TransactionCall]
    withdraw_amount: str
    vault_address: str


class WithdrawPreviewRequest(BaseModel):
    amount: str


class WithdrawPreviewResponse(BaseModel):
    preview: resources.WithdrawPreview


class ClosePositionRequest(BaseModel):
    pass


class ClosePositionResponse(BaseModel):
    transactions: list[resources.TransactionCall]
    collateral_amount: str
    repay_amount: str
    vault_withdraw_amount: str
    morpho_address: str
    vault_address: str
    transaction_hash: str | None = None


class GetMarketDataRequest(BaseModel):
    pass


class GetMarketDataResponse(BaseModel):
    collateral_markets: list[resources.CollateralMarketData]
    yield_apy: float
    yield_vault_address: str
    yield_vault_name: str


class GetWalletRequest(BaseModel):
    pass


class GetWalletResponse(BaseModel):
    wallet: resources.Wallet


class GetPositionTransactionsRequest(BaseModel):
    collateral_asset_address: str
    collateral_amount: str
    target_ltv: float


class GetPositionTransactionsResponse(BaseModel):
    transactions: list[resources.TransactionCall]
    morpho_address: str
    vault_address: str
    estimated_borrow_amount: str
    needs_approval: bool


class GetTelegramLoginUrlRequest(BaseModel):
    pass


class GetTelegramLoginUrlResponse(BaseModel):
    bot_username: str


class TelegramSecretVerifyRequest(BaseModel):
    telegram_secret: str


class TelegramSecretVerifyResponse(BaseModel):
    user_config: resources.UserConfig


class TelegramWebhookRequest(BaseModel):
    model_config = ConfigDict(extra='allow')


class TelegramWebhookResponse(BaseModel):
    pass


class DisconnectTelegramRequest(BaseModel):
    pass


class DisconnectTelegramResponse(BaseModel):
    user_config: resources.UserConfig


class CheckEnsNameRequest(BaseModel):
    label: str


class CheckEnsNameResponse(BaseModel):
    label: str
    full_name: str
    available: bool
    error: str | None = None


class PreviewAgentNameRequest(BaseModel):
    name: str


class PreviewAgentNameResponse(BaseModel):
    name: str
    label: str
    full_ens_name: str
    available: bool
    error: str | None = None


class GetEnsConfigTransactionsRequest(BaseModel):
    collateral: str | None = None
    target_ltv: int | None = None
    max_ltv: int | None = None
    min_ltv: int | None = None
    auto_rebalance: bool = True
    risk_tolerance: str = 'medium'
    description: str | None = None


class GetEnsConfigTransactionsResponse(BaseModel):
    transactions: list[resources.TransactionCall]
    ens_name: str


class GetEnsConstitutionRequest(BaseModel):
    pass


class GetEnsConstitutionResponse(BaseModel):
    constitution: resources.EnsConstitutionResource


class SetEnsConstitutionRequest(BaseModel):
    max_ltv: float | None = None
    min_spread: float | None = None
    max_position_usd: float | None = None
    allowed_collateral: str | None = None
    pause: bool = False


class SetEnsConstitutionResponse(BaseModel):
    constitution: resources.EnsConstitutionResource


class CreateAgentRequest(BaseModel):
    name: str
    emoji: str


class CreateAgentResponse(BaseModel):
    agent: resources.Agent


class DeployAgentRequest(BaseModel):
    collateral_asset_address: str
    collateral_amount: str
    target_ltv: float


class DeployAgentResponse(BaseModel):
    position: resources.Position
    transaction_hash: str | None = None


class RegisterEnsRequest(BaseModel):
    collateral_asset_address: str
    target_ltv: float


class RegisterEnsResponse(BaseModel):
    ens_name: str | None = None
    success: bool = False


class GetAgentRequest(BaseModel):
    pass


class GetAgentResponse(BaseModel):
    agent: resources.Agent | None


class GetAgentsRequest(BaseModel):
    pass


class GetAgentsResponse(BaseModel):
    agents: list[resources.Agent]


class SendChatMessageRequest(BaseModel):
    message: str
    conversation_id: str | None = None


class SendChatMessageResponse(BaseModel):
    messages: list[resources.ChatMessage]
    conversation_id: str


class GetChatHistoryRequest(BaseModel):
    conversation_id: str | None = None
    limit: int = 50


class GetChatHistoryResponse(BaseModel):
    messages: list[resources.ChatMessage]
    conversation_id: str


class GetAgentThoughtsRequest(BaseModel):
    limit: int = 100
    hours_back: int = 24


class GetAgentThoughtsResponse(BaseModel):
    actions: list[resources.AgentActionResource]


class GetAgentPositionRequest(BaseModel):
    pass


class GetAgentPositionResponse(BaseModel):
    position: resources.Position | None


class GetAgentWalletRequest(BaseModel):
    pass


class GetAgentWalletResponse(BaseModel):
    wallet: resources.Wallet


class GetAgentEnsConstitutionRequest(BaseModel):
    pass


class GetAgentEnsConstitutionResponse(BaseModel):
    constitution: resources.EnsConstitutionResource


class GetCrePositionDataRequest(BaseModel):
    pass


class GetCrePositionDataResponse(BaseModel):
    agentId: str
    collateralValueUsd: float
    borrowValueUsd: float
    vaultBalanceUsd: float
    currentLtvBps: int
    targetLtvBps: int
    maxLtvBps: int
    yieldApyBps: int
    borrowAprBps: int
