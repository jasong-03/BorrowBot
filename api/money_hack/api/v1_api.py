from datetime import datetime

from core.api.api_request import KibaApiRequest
from core.api.json_route import json_route
from starlette.routing import Route

from money_hack.agent_manager import AgentManager
from money_hack.api import v1_endpoints as endpoints
from money_hack.api.authorizer import authorize_signature
from money_hack.api.v1_resources import ChatMessage
from money_hack.api.v1_resources import EnsConstitutionResource


def create_v1_routes(agentManager: AgentManager) -> list[Route]:
    @json_route(requestType=endpoints.GetSupportedCollateralsRequest, responseType=endpoints.GetSupportedCollateralsResponse)
    @authorize_signature(authorizer=agentManager)
    async def get_supported_collaterals(request: KibaApiRequest[endpoints.GetSupportedCollateralsRequest]) -> endpoints.GetSupportedCollateralsResponse:  # noqa: ARG001
        collaterals = await agentManager.get_supported_collaterals()
        return endpoints.GetSupportedCollateralsResponse(collaterals=collaterals)

    @json_route(requestType=endpoints.GetUserConfigRequest, responseType=endpoints.GetUserConfigResponse)
    @authorize_signature(authorizer=agentManager)
    async def get_user_config(request: KibaApiRequest[endpoints.GetUserConfigRequest]) -> endpoints.GetUserConfigResponse:
        userAddress = request.path_params.get('userAddress', '')
        user_config = await agentManager.get_user_config(user_address=userAddress)
        return endpoints.GetUserConfigResponse(user_config=user_config)

    @json_route(requestType=endpoints.UpdateUserConfigRequest, responseType=endpoints.UpdateUserConfigResponse)
    @authorize_signature(authorizer=agentManager)
    async def update_user_config(request: KibaApiRequest[endpoints.UpdateUserConfigRequest]) -> endpoints.UpdateUserConfigResponse:
        userAddress = request.path_params.get('userAddress', '')
        user_config = await agentManager.update_user_config(user_address=userAddress, telegram_handle=request.data.telegram_handle, preferred_ltv=request.data.preferred_ltv)
        return endpoints.UpdateUserConfigResponse(user_config=user_config)

    @json_route(requestType=endpoints.GetPositionRequest, responseType=endpoints.GetPositionResponse)
    @authorize_signature(authorizer=agentManager)
    async def get_position(request: KibaApiRequest[endpoints.GetPositionRequest]) -> endpoints.GetPositionResponse:
        userAddress = request.path_params.get('userAddress', '')
        agentId = request.query_params.get('agentId') or None
        position = await agentManager.get_position(user_address=userAddress, agent_id=agentId)
        return endpoints.GetPositionResponse(position=position)

    @json_route(requestType=endpoints.CreatePositionRequest, responseType=endpoints.CreatePositionResponse)
    @authorize_signature(authorizer=agentManager)
    async def create_position(request: KibaApiRequest[endpoints.CreatePositionRequest]) -> endpoints.CreatePositionResponse:
        userAddress = request.path_params.get('userAddress', '')
        position, agent = await agentManager.create_position(
            user_address=userAddress,
            collateral_asset_address=request.data.collateral_asset_address,
            collateral_amount=request.data.collateral_amount,
            target_ltv=request.data.target_ltv,
            agent_name=request.data.agent_name,
            agent_emoji=request.data.agent_emoji,
        )
        return endpoints.CreatePositionResponse(position=position, agent=agent)

    @json_route(requestType=endpoints.CreateAgentRequest, responseType=endpoints.CreateAgentResponse)
    @authorize_signature(authorizer=agentManager)
    async def create_agent(request: KibaApiRequest[endpoints.CreateAgentRequest]) -> endpoints.CreateAgentResponse:
        userAddress = request.path_params.get('userAddress', '')
        agent = await agentManager.create_agent(
            user_address=userAddress,
            name=request.data.name,
            emoji=request.data.emoji,
        )
        return endpoints.CreateAgentResponse(agent=agent)

    @json_route(requestType=endpoints.GetAgentRequest, responseType=endpoints.GetAgentResponse)
    @authorize_signature(authorizer=agentManager)
    async def get_agent(request: KibaApiRequest[endpoints.GetAgentRequest]) -> endpoints.GetAgentResponse:
        userAddress = request.path_params.get('userAddress', '')
        agent = await agentManager.get_agent(user_address=userAddress)
        return endpoints.GetAgentResponse(agent=agent)

    @json_route(requestType=endpoints.GetAgentsRequest, responseType=endpoints.GetAgentsResponse)
    @authorize_signature(authorizer=agentManager)
    async def get_agents(request: KibaApiRequest[endpoints.GetAgentsRequest]) -> endpoints.GetAgentsResponse:
        userAddress = request.path_params.get('userAddress', '')
        agents = await agentManager.get_agents(user_address=userAddress)
        return endpoints.GetAgentsResponse(agents=agents)

    @json_route(requestType=endpoints.DeployAgentRequest, responseType=endpoints.DeployAgentResponse)
    @authorize_signature(authorizer=agentManager)
    async def deploy_agent(request: KibaApiRequest[endpoints.DeployAgentRequest]) -> endpoints.DeployAgentResponse:
        userAddress = request.path_params.get('userAddress', '')
        agentId = request.path_params.get('agentId', '')
        position, transactionHash = await agentManager.deploy_agent(
            user_address=userAddress,
            agent_id=agentId,
            collateral_asset_address=request.data.collateral_asset_address,
            collateral_amount=request.data.collateral_amount,
            target_ltv=request.data.target_ltv,
        )
        return endpoints.DeployAgentResponse(position=position, transaction_hash=transactionHash)

    @json_route(requestType=endpoints.RegisterEnsRequest, responseType=endpoints.RegisterEnsResponse)
    @authorize_signature(authorizer=agentManager)
    async def register_ens(request: KibaApiRequest[endpoints.RegisterEnsRequest]) -> endpoints.RegisterEnsResponse:
        userAddress = request.path_params.get('userAddress', '')
        agentId = request.path_params.get('agentId', '')
        ensName = await agentManager.register_ens_for_agent(
            user_address=userAddress,
            agent_id=agentId,
            collateral_asset_address=request.data.collateral_asset_address,
            target_ltv=request.data.target_ltv,
        )
        return endpoints.RegisterEnsResponse(ens_name=ensName, success=ensName is not None)

    @json_route(requestType=endpoints.WithdrawRequest, responseType=endpoints.WithdrawResponse)
    @authorize_signature(authorizer=agentManager)
    async def withdraw_usdc(request: KibaApiRequest[endpoints.WithdrawRequest]) -> endpoints.WithdrawResponse:
        userAddress = request.path_params.get('userAddress', '')
        agentId = request.query_params.get('agentId') or None
        withdrawData = await agentManager.execute_withdraw(user_address=userAddress, amount=request.data.amount, agent_id=agentId)
        return endpoints.WithdrawResponse(
            transactions=withdrawData.transactions,
            withdraw_amount=withdrawData.withdraw_amount,
            vault_address=withdrawData.vault_address,
        )

    @json_route(requestType=endpoints.WithdrawPreviewRequest, responseType=endpoints.WithdrawPreviewResponse)
    @authorize_signature(authorizer=agentManager)
    async def withdraw_preview(request: KibaApiRequest[endpoints.WithdrawPreviewRequest]) -> endpoints.WithdrawPreviewResponse:
        userAddress = request.path_params.get('userAddress', '')
        agentId = request.query_params.get('agentId') or None
        preview = await agentManager.get_withdraw_preview(user_address=userAddress, amount=request.data.amount, agent_id=agentId)
        return endpoints.WithdrawPreviewResponse(preview=preview)

    @json_route(requestType=endpoints.ClosePositionRequest, responseType=endpoints.ClosePositionResponse)
    @authorize_signature(authorizer=agentManager)
    async def close_position(request: KibaApiRequest[endpoints.ClosePositionRequest]) -> endpoints.ClosePositionResponse:
        userAddress = request.path_params.get('userAddress', '')
        agentId = request.query_params.get('agentId') or None
        closeData = await agentManager.execute_close_position(user_address=userAddress, agent_id=agentId)
        return endpoints.ClosePositionResponse(
            transactions=closeData.transactions,
            collateral_amount=closeData.collateral_amount,
            repay_amount=closeData.repay_amount,
            vault_withdraw_amount=closeData.vault_withdraw_amount,
            morpho_address=closeData.morpho_address,
            vault_address=closeData.vault_address,
            transaction_hash=closeData.transaction_hash,
        )

    @json_route(requestType=endpoints.GetMarketDataRequest, responseType=endpoints.GetMarketDataResponse)
    async def get_market_data(request: KibaApiRequest[endpoints.GetMarketDataRequest]) -> endpoints.GetMarketDataResponse:  # noqa: ARG001
        collateralMarkets, yieldApy, vaultAddress, vaultName = await agentManager.get_market_data()
        return endpoints.GetMarketDataResponse(collateral_markets=collateralMarkets, yield_apy=yieldApy, yield_vault_address=vaultAddress, yield_vault_name=vaultName)

    @json_route(requestType=endpoints.GetWalletRequest, responseType=endpoints.GetWalletResponse)
    @authorize_signature(authorizer=agentManager)
    async def get_wallet(request: KibaApiRequest[endpoints.GetWalletRequest]) -> endpoints.GetWalletResponse:
        walletAddress = request.path_params.get('walletAddress', '')
        wallet = await agentManager.get_wallet(wallet_address=walletAddress)
        return endpoints.GetWalletResponse(wallet=wallet)

    @json_route(requestType=endpoints.GetPositionTransactionsRequest, responseType=endpoints.GetPositionTransactionsResponse)
    @authorize_signature(authorizer=agentManager)
    async def get_position_transactions(request: KibaApiRequest[endpoints.GetPositionTransactionsRequest]) -> endpoints.GetPositionTransactionsResponse:
        userAddress = request.path_params.get('userAddress', '')
        result = await agentManager.get_position_transactions(
            user_address=userAddress,
            collateral_asset_address=request.data.collateral_asset_address,
            collateral_amount=request.data.collateral_amount,
            target_ltv=request.data.target_ltv,
        )
        return endpoints.GetPositionTransactionsResponse(**result.model_dump())

    @json_route(requestType=endpoints.GetTelegramLoginUrlRequest, responseType=endpoints.GetTelegramLoginUrlResponse)
    @authorize_signature(authorizer=agentManager)
    async def get_telegram_login_url(request: KibaApiRequest[endpoints.GetTelegramLoginUrlRequest]) -> endpoints.GetTelegramLoginUrlResponse:  # noqa: ARG001
        botUsername = await agentManager.get_telegram_login_url()
        return endpoints.GetTelegramLoginUrlResponse(bot_username=botUsername)

    @json_route(requestType=endpoints.TelegramSecretVerifyRequest, responseType=endpoints.TelegramSecretVerifyResponse)
    @authorize_signature(authorizer=agentManager)
    async def telegram_secret_verify(request: KibaApiRequest[endpoints.TelegramSecretVerifyRequest]) -> endpoints.TelegramSecretVerifyResponse:
        userAddress = request.path_params.get('userAddress', '')
        user_config = await agentManager.telegram_secret_verify(
            user_address=userAddress,
            telegramSecret=request.data.telegram_secret,
        )
        return endpoints.TelegramSecretVerifyResponse(user_config=user_config)

    @json_route(requestType=endpoints.TelegramWebhookRequest, responseType=endpoints.TelegramWebhookResponse)
    async def process_telegram_webhook(request: KibaApiRequest[endpoints.TelegramWebhookRequest]) -> endpoints.TelegramWebhookResponse:
        await agentManager.process_telegram_webhook(updateDict=request.data.model_dump())
        return endpoints.TelegramWebhookResponse()

    @json_route(requestType=endpoints.DisconnectTelegramRequest, responseType=endpoints.DisconnectTelegramResponse)
    @authorize_signature(authorizer=agentManager)
    async def disconnect_telegram(request: KibaApiRequest[endpoints.DisconnectTelegramRequest]) -> endpoints.DisconnectTelegramResponse:
        userAddress = request.path_params.get('userAddress', '')
        user_config = await agentManager.disconnect_telegram(user_address=userAddress)
        return endpoints.DisconnectTelegramResponse(user_config=user_config)

    @json_route(requestType=endpoints.CheckEnsNameRequest, responseType=endpoints.CheckEnsNameResponse)
    async def check_ens_name(request: KibaApiRequest[endpoints.CheckEnsNameRequest]) -> endpoints.CheckEnsNameResponse:
        isAvailable, fullName, error = agentManager.check_ens_name_available(label=request.data.label)
        return endpoints.CheckEnsNameResponse(label=request.data.label, full_name=fullName, available=isAvailable, error=error)

    @json_route(requestType=endpoints.PreviewAgentNameRequest, responseType=endpoints.PreviewAgentNameResponse)
    async def preview_agent_name(request: KibaApiRequest[endpoints.PreviewAgentNameRequest]) -> endpoints.PreviewAgentNameResponse:
        label, fullName, available, error = agentManager.preview_agent_name(name=request.data.name)
        return endpoints.PreviewAgentNameResponse(name=request.data.name, label=label, full_ens_name=fullName, available=available, error=error)

    @json_route(requestType=endpoints.GetEnsConfigTransactionsRequest, responseType=endpoints.GetEnsConfigTransactionsResponse)
    @authorize_signature(authorizer=agentManager)
    async def get_ens_config_transactions(request: KibaApiRequest[endpoints.GetEnsConfigTransactionsRequest]) -> endpoints.GetEnsConfigTransactionsResponse:
        userAddress = request.path_params.get('userAddress', '')
        agentId = request.query_params.get('agentId') or None
        transactions, ensName = await agentManager.get_ens_config_transactions(
            userAddress=userAddress,
            agent_id=agentId,
            collateral=request.data.collateral,
            targetLtv=request.data.target_ltv,
            maxLtv=request.data.max_ltv,
            minLtv=request.data.min_ltv,
            autoRebalance=request.data.auto_rebalance,
            riskTolerance=request.data.risk_tolerance,
            description=request.data.description,
        )
        return endpoints.GetEnsConfigTransactionsResponse(transactions=transactions, ens_name=ensName)

    @json_route(requestType=endpoints.GetEnsConstitutionRequest, responseType=endpoints.GetEnsConstitutionResponse)
    @authorize_signature(authorizer=agentManager)
    async def get_ens_constitution(request: KibaApiRequest[endpoints.GetEnsConstitutionRequest]) -> endpoints.GetEnsConstitutionResponse:
        userAddress = request.path_params.get('userAddress', '')
        agentId = request.query_params.get('agentId') or None
        data = await agentManager.get_ens_constitution(userAddress=userAddress, agent_id=agentId)
        return endpoints.GetEnsConstitutionResponse(constitution=EnsConstitutionResource.model_validate(data))

    @json_route(requestType=endpoints.SetEnsConstitutionRequest, responseType=endpoints.SetEnsConstitutionResponse)
    @authorize_signature(authorizer=agentManager)
    async def set_ens_constitution(request: KibaApiRequest[endpoints.SetEnsConstitutionRequest]) -> endpoints.SetEnsConstitutionResponse:
        userAddress = request.path_params.get('userAddress', '')
        agentId = request.query_params.get('agentId') or None
        data = await agentManager.set_ens_constitution(
            userAddress=userAddress,
            maxLtv=request.data.max_ltv,
            minSpread=request.data.min_spread,
            maxPositionUsd=request.data.max_position_usd,
            allowedCollateral=request.data.allowed_collateral,
            pause=request.data.pause,
            agent_id=agentId,
        )
        return endpoints.SetEnsConstitutionResponse(constitution=EnsConstitutionResource.model_validate(data))

    @json_route(requestType=endpoints.SendChatMessageRequest, responseType=endpoints.SendChatMessageResponse)
    @authorize_signature(authorizer=agentManager)
    async def send_chat_message(request: KibaApiRequest[endpoints.SendChatMessageRequest]) -> endpoints.SendChatMessageResponse:
        userAddress = request.path_params.get('userAddress', '')
        agentId = request.path_params.get('agentId', '')
        messages_data, conversationId = await agentManager.send_chat_message(
            userAddress=userAddress,
            agentId=agentId,
            message=request.data.message,
            conversationId=request.data.conversation_id,
            channel='web',
        )
        messages = [
            ChatMessage(
                message_id=int(str(msg['message_id'])),
                created_date=datetime.fromisoformat(str(msg['created_date'])),
                is_user=bool(msg['is_user']),
                content=str(msg['content']),
            )
            for msg in messages_data
        ]
        return endpoints.SendChatMessageResponse(messages=messages, conversation_id=conversationId)

    @json_route(requestType=endpoints.GetChatHistoryRequest, responseType=endpoints.GetChatHistoryResponse)
    @authorize_signature(authorizer=agentManager)
    async def get_chat_history(request: KibaApiRequest[endpoints.GetChatHistoryRequest]) -> endpoints.GetChatHistoryResponse:
        userAddress = request.path_params.get('userAddress', '')
        agentId = request.path_params.get('agentId', '')
        messages_data, conversationId = await agentManager.get_chat_history(
            userAddress=userAddress,
            agentId=agentId,
            conversationId=request.data.conversation_id,
            limit=request.data.limit,
            channel='web',
        )
        messages = [
            ChatMessage(
                message_id=int(str(msg['message_id'])),
                created_date=datetime.fromisoformat(str(msg['created_date'])),
                is_user=bool(msg['is_user']),
                content=str(msg['content']),
            )
            for msg in messages_data
        ]
        return endpoints.GetChatHistoryResponse(messages=messages, conversation_id=conversationId)

    @json_route(requestType=endpoints.GetAgentThoughtsRequest, responseType=endpoints.GetAgentThoughtsResponse)
    @authorize_signature(authorizer=agentManager)
    async def get_agent_thoughts(request: KibaApiRequest[endpoints.GetAgentThoughtsRequest]) -> endpoints.GetAgentThoughtsResponse:
        agentId = request.path_params.get('agentId', '')
        thoughts = await agentManager.get_agent_thoughts(
            agentId=agentId,
            limit=request.data.limit,
            hoursBack=request.data.hours_back,
        )
        return endpoints.GetAgentThoughtsResponse(actions=thoughts)

    @json_route(requestType=endpoints.GetAgentPositionRequest, responseType=endpoints.GetAgentPositionResponse)
    @authorize_signature(authorizer=agentManager)
    async def get_agent_position(request: KibaApiRequest[endpoints.GetAgentPositionRequest]) -> endpoints.GetAgentPositionResponse:
        agentId = request.path_params.get('agentId', '')
        position = await agentManager.get_agent_position(agent_id=agentId)
        return endpoints.GetAgentPositionResponse(position=position)

    @json_route(requestType=endpoints.GetAgentWalletRequest, responseType=endpoints.GetAgentWalletResponse)
    @authorize_signature(authorizer=agentManager)
    async def get_agent_wallet(request: KibaApiRequest[endpoints.GetAgentWalletRequest]) -> endpoints.GetAgentWalletResponse:
        agentId = request.path_params.get('agentId', '')
        wallet = await agentManager.get_agent_wallet(agent_id=agentId)
        return endpoints.GetAgentWalletResponse(wallet=wallet)

    @json_route(requestType=endpoints.GetAgentEnsConstitutionRequest, responseType=endpoints.GetAgentEnsConstitutionResponse)
    @authorize_signature(authorizer=agentManager)
    async def get_agent_ens_constitution(request: KibaApiRequest[endpoints.GetAgentEnsConstitutionRequest]) -> endpoints.GetAgentEnsConstitutionResponse:
        agentId = request.path_params.get('agentId', '')
        constitution = await agentManager.get_agent_ens_constitution(agent_id=agentId)
        return endpoints.GetAgentEnsConstitutionResponse(constitution=constitution)

    @json_route(requestType=endpoints.GetCrePositionDataRequest, responseType=endpoints.GetCrePositionDataResponse)
    async def get_cre_position_data(request: KibaApiRequest[endpoints.GetCrePositionDataRequest]) -> endpoints.GetCrePositionDataResponse:
        positionData = await agentManager.get_cre_position_data()
        return endpoints.GetCrePositionDataResponse(**positionData)

    return [
        Route('/v1/collaterals', endpoint=get_supported_collaterals, methods=['GET']),
        Route('/v1/market-data', endpoint=get_market_data, methods=['GET']),
        Route('/v1/wallets/{walletAddress:str}', endpoint=get_wallet, methods=['GET']),
        Route('/v1/users/{userAddress:str}/config', endpoint=get_user_config, methods=['GET']),
        Route('/v1/users/{userAddress:str}/config', endpoint=update_user_config, methods=['POST']),
        Route('/v1/users/{userAddress:str}/agent', endpoint=get_agent, methods=['GET']),
        Route('/v1/users/{userAddress:str}/agents', endpoint=get_agents, methods=['GET']),
        Route('/v1/users/{userAddress:str}/agent', endpoint=create_agent, methods=['POST']),
        Route('/v1/users/{userAddress:str}/agents/{agentId:str}/deploy', endpoint=deploy_agent, methods=['POST']),
        Route('/v1/users/{userAddress:str}/agents/{agentId:str}/register-ens', endpoint=register_ens, methods=['POST']),
        Route('/v1/users/{userAddress:str}/position', endpoint=get_position, methods=['GET']),
        Route('/v1/users/{userAddress:str}/position', endpoint=create_position, methods=['POST']),
        Route('/v1/users/{userAddress:str}/position/transactions', endpoint=get_position_transactions, methods=['POST']),
        Route('/v1/users/{userAddress:str}/position/withdraw', endpoint=withdraw_usdc, methods=['POST']),
        Route('/v1/users/{userAddress:str}/position/withdraw/preview', endpoint=withdraw_preview, methods=['POST']),
        Route('/v1/users/{userAddress:str}/position/close', endpoint=close_position, methods=['POST']),
        Route('/v1/users/{userAddress:str}/telegram/login-url', endpoint=get_telegram_login_url, methods=['GET']),
        Route('/v1/users/{userAddress:str}/telegram/secret-verify', endpoint=telegram_secret_verify, methods=['POST']),
        Route('/v1/users/{userAddress:str}/telegram', endpoint=disconnect_telegram, methods=['DELETE']),
        Route('/v1/telegram-webhook', endpoint=process_telegram_webhook, methods=['POST']),
        Route('/v1/ens/check-name', endpoint=check_ens_name, methods=['POST']),
        Route('/v1/agent-name/preview', endpoint=preview_agent_name, methods=['POST']),
        Route('/v1/users/{userAddress:str}/ens/config-transactions', endpoint=get_ens_config_transactions, methods=['POST']),
        Route('/v1/users/{userAddress:str}/ens/constitution', endpoint=get_ens_constitution, methods=['GET']),
        Route('/v1/users/{userAddress:str}/ens/constitution', endpoint=set_ens_constitution, methods=['POST']),
        Route('/v1/users/{userAddress:str}/agents/{agentId:str}/chat', endpoint=send_chat_message, methods=['POST']),
        Route('/v1/users/{userAddress:str}/agents/{agentId:str}/chat/history', endpoint=get_chat_history, methods=['GET']),
        Route('/v1/agents/{agentId:str}/thoughts', endpoint=get_agent_thoughts, methods=['GET']),
        Route('/v1/agents/{agentId:str}/position', endpoint=get_agent_position, methods=['GET']),
        Route('/v1/agents/{agentId:str}/wallet', endpoint=get_agent_wallet, methods=['GET']),
        Route('/v1/agents/{agentId:str}/ens-constitution', endpoint=get_agent_ens_constitution, methods=['GET']),
        Route('/v1/cre/position-data', endpoint=get_cre_position_data, methods=['GET']),
    ]
