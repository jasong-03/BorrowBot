import asyncio
import base64
import typing
import uuid
from datetime import UTC
from datetime import datetime

from core import logging
from core.exceptions import BadRequestException
from core.exceptions import KibaException
from core.exceptions import NotFoundException
from core.exceptions import UnauthorizedException
from core.requester import Requester
from core.util import chain_util
from core.web3.eth_client import ABI
from core.web3.eth_client import EncodedCall
from core.web3.eth_client import RestEthClient
from eth_account import Account
from eth_account.messages import _hash_eip191_message
from eth_account.messages import encode_defunct
from hexbytes import HexBytes
from siwe import SiweMessage  # type: ignore[import-untyped]
from web3 import Web3
from web3.types import TxParams

from money_hack import constants
from money_hack.agent.chat_bot import ChatBot
from money_hack.agent.chat_history_store import ChatHistoryStore
from money_hack.agent.constants import BORROWBOT_SYSTEM_PROMPT
from money_hack.agent.constants import BORROWBOT_USER_PROMPT
from money_hack.agent.constants import TELEGRAM_FORMATTING_NOTE
from money_hack.agent.runtime_state import RuntimeState
from money_hack.api.authorizer import Authorizer
from money_hack.api.v1_resources import Agent as AgentResource
from money_hack.api.v1_resources import AgentActionResource
from money_hack.api.v1_resources import AssetBalance
from money_hack.api.v1_resources import AuthToken
from money_hack.api.v1_resources import ClosePositionTransactionsData
from money_hack.api.v1_resources import CollateralAsset
from money_hack.api.v1_resources import CollateralMarketData
from money_hack.api.v1_resources import EnsConstitutionResource
from money_hack.api.v1_resources import Position
from money_hack.api.v1_resources import PositionTransactionsData
from money_hack.api.v1_resources import TransactionCall
from money_hack.api.v1_resources import UserConfig
from money_hack.api.v1_resources import Wallet
from money_hack.api.v1_resources import WithdrawPreview
from money_hack.api.v1_resources import WithdrawTransactionsData
from money_hack.blockchain_data.alchemy_client import AlchemyClient
from money_hack.blockchain_data.moralis_client import MoralisClient
from money_hack.blockchain_data.price_intelligence_service import PriceIntelligenceService
from money_hack.cross_chain_yield_manager import CrossChainManager
from money_hack.external.coinbase_cdp_client import CoinbaseCdpClient
from money_hack.external.ens_client import ENS_NAME_WRAPPER_ABI
from money_hack.external.ens_client import ENS_NAME_WRAPPER_ADDRESS
from money_hack.external.ens_client import PARENT_NAME
from money_hack.external.ens_client import EnsAgentConfig
from money_hack.external.ens_client import EnsClient
from money_hack.external.ens_client import EnsConstitution
from money_hack.external.ens_client import namehash
from money_hack.external.lifi_client import LiFiClient
from money_hack.external.telegram_client import TelegramClient
from money_hack.forty_acres.forty_acres_client import FortyAcresClient
from money_hack.morpho import morpho_abis
from money_hack.morpho.ltv_manager import LtvManager
from money_hack.morpho.morpho_client import MorphoClient
from money_hack.morpho.transaction_builder import MORPHO_BLUE_ADDRESS
from money_hack.morpho.transaction_builder import TransactionBuilder
from money_hack.morpho.transaction_builder import encode_transfer
from money_hack.notification_service import NotificationService
from money_hack.smart_wallets.coinbase_bundler import CoinbaseBundler
from money_hack.smart_wallets.coinbase_constants import COINBASE_EIP7702PROXY_ADDRESS
from money_hack.smart_wallets.coinbase_constants import COINBASE_SMART_WALLET_IMPLEMENTATION_ADDRESS
from money_hack.smart_wallets.coinbase_smart_wallet import CoinbaseSmartWallet
from money_hack.store.database_store import DatabaseStore

JsonObject = dict[str, object]

w3 = Web3()

ERC1271_ABI: ABI = [
    {
        'inputs': [{'name': '_hash', 'type': 'bytes32'}, {'name': '_signature', 'type': 'bytes'}],
        'name': 'isValidSignature',
        'outputs': [{'name': '', 'type': 'bytes4'}],
        'type': 'function',
    },
]

SUPPORTED_COLLATERALS = [
    CollateralAsset(chain_id=8453, address='0x4200000000000000000000000000000000000006', symbol='WETH', name='Wrapped Ether', decimals=18, logo_uri='https://assets.coingecko.com/coins/images/2518/small/weth.png'),
    CollateralAsset(chain_id=8453, address='0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf', symbol='cbBTC', name='Coinbase Wrapped BTC', decimals=8, logo_uri='https://assets.coingecko.com/coins/images/40143/standard/cbbtc.webp'),
]

ERC20_BALANCE_ABI: ABI = [
    {
        'inputs': [{'name': 'account', 'type': 'address'}],
        'name': 'balanceOf',
        'outputs': [{'name': '', 'type': 'uint256'}],
        'stateMutability': 'view',
        'type': 'function',
    },
]

WITHDRAW_HARD_LTV_FACTOR = 0.85

YO_VAULT_ADDRESS = '0x0000000f2eB9f69274678c76222B35eEc7588a65'
YO_VAULT_NAME = 'Yo USDC Vault'


class AgentManager(Authorizer):  # Core manager
    def __init__(
        self,
        requester: Requester,
        chainId: int,
        ethClient: RestEthClient,
        moralisClient: MoralisClient,
        alchemyClient: AlchemyClient,
        morphoClient: MorphoClient,
        fortyAcresClient: FortyAcresClient,
        telegramClient: TelegramClient,
        ensClient: EnsClient,
        databaseStore: DatabaseStore,
        coinbaseCdpClient: CoinbaseCdpClient | None,
        coinbaseSmartWallet: CoinbaseSmartWallet | None,
        coinbaseBundler: CoinbaseBundler | None,
        deployerPrivateKey: str,
        chatBot: ChatBot | None = None,
        chatHistoryStore: ChatHistoryStore | None = None,
        ltvManager: LtvManager | None = None,
        notificationService: NotificationService | None = None,
        priceIntelligenceService: 'PriceIntelligenceService | None' = None,
        mainnetEthClient: RestEthClient | None = None,
        lifiClient: LiFiClient | None = None,
        crossChainManager: CrossChainManager | None = None,
    ) -> None:
        self.chainId = chainId
        self.requester = requester
        self.ethClient = ethClient
        self.mainnetEthClient = mainnetEthClient
        self.moralisClient = moralisClient
        self.alchemyClient = alchemyClient
        self.morphoClient = morphoClient
        self.fortyAcresClient = fortyAcresClient
        self.telegramClient = telegramClient
        self.ensClient = ensClient
        self.databaseStore = databaseStore
        self.coinbaseCdpClient = coinbaseCdpClient
        self.coinbaseSmartWallet = coinbaseSmartWallet
        self.coinbaseBundler = coinbaseBundler
        self.deployerPrivateKey = deployerPrivateKey
        self.ltvManager = ltvManager
        self.notificationService = notificationService
        self.priceIntelligenceService = priceIntelligenceService
        self.deployerAddress = Account.from_key(deployerPrivateKey).address if deployerPrivateKey else None
        self.deployerTransactionLock = asyncio.Lock()
        self.chatBot = chatBot
        self.chatHistoryStore = chatHistoryStore
        self.lifiClient = lifiClient
        self.crossChainManager = crossChainManager
        self._signatureSignerMap: dict[str, str] = {}
        self._userConfigsCache: dict[str, UserConfig] = {}
        self._lastDailyDigestSent: dict[str, datetime] = {}

    async def _get_asset_price(self, assetAddress: str) -> float:
        """Get the current USD price for an asset. Tries Alchemy first, falls back to Moralis."""
        try:
            priceData = await self.alchemyClient.get_asset_current_price(chainId=self.chainId, assetAddress=assetAddress)
        except Exception as e:  # noqa: BLE001
            logging.warning(f'Alchemy price fetch failed for {assetAddress}, trying Moralis: {e}')
            try:
                priceData = await self.moralisClient.get_asset_current_price(chainId=self.chainId, assetAddress=assetAddress)
            except Exception as e2:
                logging.error(f'Both Alchemy and Moralis price fetch failed for {assetAddress}: {e2}')
                raise
            else:
                return priceData.priceUsd
        else:
            return priceData.priceUsd

    async def _get_price_analysis(self, assetSymbol: str) -> object | None:
        """Get price analysis for an asset by symbol (WETH, cbBTC). Used by chat tools."""
        symbolAddressMap: dict[str, str] = {
            'weth': constants.CHAIN_WETH_MAP.get(self.chainId, ''),
            'cbbtc': '0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf',
        }
        address = symbolAddressMap.get(assetSymbol.lower())
        if not address or not self.priceIntelligenceService:
            return None
        try:
            return await self.priceIntelligenceService.get_price_analysis(chainId=self.chainId, assetAddress=address)
        except Exception as e:  # noqa: BLE001
            logging.warning(f'Failed to get price analysis for {assetSymbol}: {e}')
            return None

    async def _retrieve_signature_signer_address(self, signatureString: str) -> str:
        if signatureString in self._signatureSignerMap:
            return self._signatureSignerMap[signatureString]
        authTokenJson = base64.b64decode(signatureString).decode('utf-8')
        authToken = AuthToken.model_validate_json(authTokenJson)
        messageHash = encode_defunct(text=authToken.message)
        isSmartWallet = len(authToken.signature) != 132  # noqa: PLR2004
        siweMessage = SiweMessage.from_message(message=authToken.message)
        signerId = chain_util.normalize_address(siweMessage.address)
        if isSmartWallet:
            prefixedMessageHash = '0x' + HexBytes(_hash_eip191_message(messageHash)).hex()
            response = await self.ethClient.call_function_by_name(
                toAddress=signerId,
                contractAbi=ERC1271_ABI,
                functionName='isValidSignature',
                arguments={'_hash': prefixedMessageHash, '_signature': authToken.signature},
            )
            responseValue = '0x' + response[0].hex()
            if responseValue != '0x1626ba7e':
                raise UnauthorizedException
        else:
            messageSignerId = chain_util.normalize_address(w3.eth.account.recover_message(messageHash, signature=authToken.signature))
            if messageSignerId != signerId:
                raise UnauthorizedException
        self._signatureSignerMap[signatureString] = signerId
        return signerId

    async def retrieve_signature_signer(self, signatureString: str) -> str:
        signerAddress = await self._retrieve_signature_signer_address(signatureString=signatureString)
        return signerAddress

    async def get_supported_collaterals(self) -> list[CollateralAsset]:
        return SUPPORTED_COLLATERALS

    async def get_user_config(self, user_address: str) -> UserConfig:
        normalized_address = chain_util.normalize_address(user_address)
        if normalized_address in self._userConfigsCache:
            return self._userConfigsCache[normalized_address]
        user = await self.databaseStore.get_user_by_wallet(walletAddress=normalized_address)
        if user is not None:
            config = UserConfig(telegram_handle=user.telegramUsername, telegram_chat_id=user.telegramChatId, preferred_ltv=0.75)
            self._userConfigsCache[normalized_address] = config
            return config
        return UserConfig(telegram_handle=None, telegram_chat_id=None, preferred_ltv=0.75)

    async def update_user_config(self, user_address: str, telegram_handle: str | None, preferred_ltv: float | None) -> UserConfig:
        normalized_address = chain_util.normalize_address(user_address)
        currentConfig = await self.get_user_config(user_address=normalized_address)
        user = await self.databaseStore.get_or_create_user_by_wallet(walletAddress=normalized_address)
        telegramChatId = str(currentConfig.telegram_chat_id) if currentConfig.telegram_chat_id is not None else None
        await self.databaseStore.update_user_telegram(
            userId=user.userId,
            telegramId=user.telegramId,
            telegramChatId=telegramChatId,
            telegramUsername=telegram_handle,
        )
        config = UserConfig(telegram_handle=telegram_handle, telegram_chat_id=currentConfig.telegram_chat_id, preferred_ltv=preferred_ltv)
        self._userConfigsCache[normalized_address] = config
        return config

    async def create_agent(self, user_address: str, name: str, emoji: str) -> AgentResource:
        if self.coinbaseCdpClient is None:
            raise KibaException('Coinbase CDP client not configured')
        normalizedAddress = chain_util.normalize_address(user_address)
        user = await self.databaseStore.get_or_create_user_by_wallet(walletAddress=normalizedAddress)
        ensLabel = self.normalize_agent_name(name)
        if not self.ensClient.check_name_available(ensLabel):
            raise BadRequestException(message=f'Agent name "{name}" is already taken (resolves to {ensLabel}.borrowbott.eth)')
        agentId = str(uuid.uuid4())
        walletAddress = await self.coinbaseCdpClient.create_eoa(name=agentId)
        agent = await self.databaseStore.create_agent(userId=user.userId, name=name, emoji=emoji, walletAddress=walletAddress)
        self.ensClient.reserve_name(ensLabel)
        return AgentResource(
            agent_id=agent.agentId,
            name=agent.name,
            emoji=agent.emoji,
            agent_index=agent.agentIndex,
            wallet_address=agent.walletAddress,
            ens_name=agent.ensName,
            created_date=agent.createdDate,
        )

    async def get_agent(self, user_address: str) -> AgentResource | None:
        normalizedAddress = chain_util.normalize_address(user_address)
        user = await self.databaseStore.get_user_by_wallet(walletAddress=normalizedAddress)
        if user is None:
            return None
        agents = await self.databaseStore.get_agents_by_user(userId=user.userId)
        if not agents:
            return None
        agent = agents[0]
        return AgentResource(
            agent_id=agent.agentId,
            name=agent.name,
            emoji=agent.emoji,
            agent_index=agent.agentIndex,
            wallet_address=agent.walletAddress,
            ens_name=agent.ensName,
            created_date=agent.createdDate,
        )

    async def get_agents(self, user_address: str) -> list[AgentResource]:
        normalizedAddress = chain_util.normalize_address(user_address)
        user = await self.databaseStore.get_user_by_wallet(walletAddress=normalizedAddress)
        if user is None:
            return []
        agents = await self.databaseStore.get_agents_by_user(userId=user.userId)
        return [
            AgentResource(
                agent_id=agent.agentId,
                name=agent.name,
                emoji=agent.emoji,
                agent_index=agent.agentIndex,
                wallet_address=agent.walletAddress,
                ens_name=agent.ensName,
                created_date=agent.createdDate,
            )
            for agent in agents
        ]

    async def deploy_agent(self, user_address: str, agent_id: str, collateral_asset_address: str, collateral_amount: str, target_ltv: float) -> tuple[Position, str | None]:
        if self.coinbaseCdpClient is None:
            raise KibaException('Coinbase CDP client not configured')
        normalizedAddress = chain_util.normalize_address(user_address)
        user = await self.databaseStore.get_user_by_wallet(walletAddress=normalizedAddress)
        if user is None:
            raise KibaException('User not found')
        agent = await self.databaseStore.get_agent_by_id(agentId=agent_id)
        if agent is None or agent.userId != user.userId:
            raise KibaException('Agent not found')
        collateral = next((c for c in SUPPORTED_COLLATERALS if c.address.lower() == collateral_asset_address.lower()), SUPPORTED_COLLATERALS[0])
        try:
            priceUsd = await self._get_asset_price(assetAddress=collateral_asset_address)
            collateralAmountHuman = int(collateral_amount) / (10**collateral.decimals)
            collateralValue = collateralAmountHuman * priceUsd
        except Exception:  # noqa: BLE001
            logging.exception(f'Failed to fetch price for {collateral_asset_address}')
            collateralValue = 100000.0
        borrowValue = collateralValue * target_ltv
        borrowAmountRaw = int(borrowValue * 1e6)
        estimatedApy = 0.08
        try:
            yieldApy = await self.fortyAcresClient.get_yield_apy(chainId=self.chainId)
            if yieldApy is not None:
                estimatedApy = yieldApy
        except Exception:  # noqa: BLE001
            logging.exception('Failed to get yield APY for position')
        market = await self.morphoClient.get_market(chain_id=self.chainId, collateral_address=collateral_asset_address)
        morphoMarketId = market.unique_key if market else ''
        await self.databaseStore.create_position(
            agentId=agent.agentId,
            collateralAsset=collateral_asset_address,
            targetLtv=target_ltv,
            morphoMarketId=morphoMarketId,
        )
        transactionHash = await self._execute_agent_deploy_transactions(
            agentWalletAddress=agent.walletAddress,
            userAddress=normalizedAddress,
            collateralAssetAddress=collateral_asset_address,
            collateralAmount=collateral_amount,
            targetLtv=target_ltv,
        )
        position = Position(
            position_id=f'pos-{normalizedAddress[:8]}',
            created_date=datetime.now(tz=UTC),
            user_address=normalizedAddress,
            collateral_asset=collateral,
            collateral_amount=collateral_amount,
            collateral_value_usd=collateralValue,
            borrow_amount=str(borrowAmountRaw),
            borrow_value_usd=borrowValue,
            current_ltv=target_ltv,
            target_ltv=target_ltv,
            health_factor=1.0 / target_ltv,
            vault_balance=str(borrowAmountRaw),
            vault_balance_usd=borrowValue,
            accrued_yield='0',
            accrued_yield_usd=0.0,
            estimated_apy=estimatedApy,
            status='active',
            wallet_collateral_balance='0',
            wallet_collateral_balance_usd=0.0,
            wallet_usdc_balance='0',
            wallet_usdc_balance_usd=0.0,
        )
        return position, transactionHash

    async def register_ens_for_agent(self, user_address: str, agent_id: str, collateral_asset_address: str, target_ltv: float) -> str | None:
        """Register an ENS subname under borrowbott.eth and set initial constitution on mainnet.

        Returns the ENS name if successful, None otherwise.
        """
        import re as _re

        if self.mainnetEthClient is None or self.deployerAddress is None:
            raise KibaException('Mainnet client or deployer not configured for ENS registration')
        normalizedAddress = chain_util.normalize_address(user_address)
        user = await self.databaseStore.get_user_by_wallet(walletAddress=normalizedAddress)
        if user is None:
            raise KibaException('User not found')
        agent = await self.databaseStore.get_agent_by_id(agentId=agent_id)
        if agent is None or agent.userId != user.userId:
            raise KibaException('Agent not found')
        if agent.ensName:
            return agent.ensName
        collateralAssetAddress = collateral_asset_address
        targetLtv = target_ltv
        ensLabel = _re.sub(r'[^a-z0-9-]', '', agent.name.lower().replace(' ', '-'))
        if len(ensLabel) < 3:
            ensLabel = f'agent-{agent.agentIndex}'
        ensName = self.ensClient.get_full_ens_name(ensLabel)
        logging.info(f'Registering ENS subname: {ensName} for agent {agent.agentId}')
        # Check if subname is already registered in NameWrapper
        parentNode = namehash(PARENT_NAME)
        parentData = await self.mainnetEthClient.call_function_by_name(
            toAddress=ENS_NAME_WRAPPER_ADDRESS,
            contractAbi=ENS_NAME_WRAPPER_ABI,
            functionName='getData',
            arguments={'id': int.from_bytes(parentNode, 'big')},
        )
        parentExpiry = parentData[2]
        subnameNode = namehash(ensName)
        subnameData = await self.mainnetEthClient.call_function_by_name(
            toAddress=ENS_NAME_WRAPPER_ADDRESS,
            contractAbi=ENS_NAME_WRAPPER_ABI,
            functionName='getData',
            arguments={'id': int.from_bytes(subnameNode, 'big')},
        )
        subnameOwner = subnameData[0]
        if not subnameOwner or subnameOwner == '0x0000000000000000000000000000000000000000':
            subnameTx = self.ensClient.build_register_subname_transaction(
                label=ensLabel,
                ownerAddress=self.deployerAddress,
                expiry=parentExpiry,
            )
            await self._make_deployer_transaction(
                params={'to': Web3.to_checksum_address(subnameTx.to), 'data': subnameTx.data},  # type: ignore[typeddict-item]
                ethClient=self.mainnetEthClient,
            )
            logging.info(f'Registered ENS subname: {ensName}')
        # Set initial constitution + status via multicall
        collateral = next((c for c in SUPPORTED_COLLATERALS if c.address.lower() == collateralAssetAddress.lower()), None)
        collateralSymbol = collateral.symbol if collateral else 'WETH'
        constitution = EnsConstitution(
            max_ltv=min(targetLtv + 0.10, 0.90),
            min_spread=0.005,
            pause=False,
            allowed_collateral=collateralSymbol,
        )
        multicallTx = self.ensClient.build_full_constitution_multicall(
            ensName=ensName,
            constitution=constitution,
            status='active',
            lastAction='agent deployed',
            lastCheck=datetime.now(tz=UTC).isoformat(),
        )
        await self._make_deployer_transaction(
            params={'to': Web3.to_checksum_address(multicallTx.to), 'data': multicallTx.data},  # type: ignore[typeddict-item]
            ethClient=self.mainnetEthClient,
        )
        logging.info(f'Set ENS constitution for {ensName}')
        await self.databaseStore.update_agent(agentId=agent.agentId, ensName=ensName)
        logging.info(f'Updated agent {agent.agentId} with ensName={ensName}')
        return ensName

    async def _make_deployer_transaction(self, params: TxParams, maxRetryCount: int = 3, ethClient: RestEthClient | None = None) -> str:
        if self.deployerPrivateKey is None or self.deployerAddress is None:
            raise BadRequestException('Deployer private key is not configured')
        client = ethClient or self.ethClient
        async with self.deployerTransactionLock:
            params['from'] = Web3.to_checksum_address(self.deployerAddress)  # type: ignore[typeddict-item]
            baseParams = await client.fill_transaction_params(params=params, fromAddress=self.deployerAddress)
            retryCount = 0
            while True:
                paramsToSend = dict(baseParams)
                if retryCount > 0:
                    multiplier = 1 + (retryCount * 0.15)
                    paramsToSend['gas'] = int(baseParams['gas'] * multiplier)
                    paramsToSend['maxFeePerGas'] = hex(int(int(baseParams['maxFeePerGas'], 16) * multiplier))  # type: ignore[arg-type]
                    paramsToSend['maxPriorityFeePerGas'] = hex(int(int(baseParams['maxPriorityFeePerGas'], 16) * multiplier))  # type: ignore[arg-type]
                signedParams = client.w3.eth.account.sign_transaction(transaction_dict=paramsToSend, private_key=self.deployerPrivateKey)
                transactionHash = await client.send_raw_transaction(transactionData=signedParams.raw_transaction.hex())
                logging.info(f'Sending deployer transaction (retry={retryCount}): {transactionHash}')
                try:
                    await client.wait_for_transaction_receipt(transactionHash=transactionHash)
                    logging.info(f'Deployer transaction confirmed: {transactionHash}')
                    return transactionHash  # noqa: TRY300
                except BadRequestException as exception:
                    if not exception.message or 'replacement transaction underpriced' not in exception.message:
                        raise
                    if retryCount >= (maxRetryCount - 1):
                        raise
                    retryCount += 1

    async def _sign_hash_with_cdp(self, messageHash: str, walletAddress: str) -> str:
        if self.coinbaseCdpClient is None:
            raise BadRequestException('Coinbase CDP client is not configured')
        return await self.coinbaseCdpClient.sign_hash(walletAddress=walletAddress, messageHash=messageHash)

    async def _set_delegation(self, agentWalletAddress: str, userAddress: str) -> None:
        if self.coinbaseSmartWallet is None or self.deployerPrivateKey is None:
            raise BadRequestException('Smart wallet or deployer is not configured')
        currentDelegationStatus = await self.coinbaseSmartWallet.get_eoa_delegation_status(address=agentWalletAddress)
        if currentDelegationStatus.isDelegatedToCoinbaseSmartWallet:
            return
        upgradeData = hex(0)
        if currentDelegationStatus.implementationAddress != COINBASE_SMART_WALLET_IMPLEMENTATION_ADDRESS:
            initArgs = self.coinbaseSmartWallet.encode_initialize_call(owners=[agentWalletAddress, userAddress])
            setImplementationHash = await self.coinbaseSmartWallet.create_set_implementation_hash(
                address=agentWalletAddress,
                callData=initArgs,
                currentImplementationAddress=currentDelegationStatus.implementationAddress or chain_util.BURN_ADDRESS,
            )
            signedSetImplementationHash = await self._sign_hash_with_cdp(messageHash=setImplementationHash, walletAddress=agentWalletAddress)
            upgradeData = self.coinbaseSmartWallet.encode_set_implementation_call(
                initArgs=initArgs,
                signedSetImplementationHash=signedSetImplementationHash,
            )
        unsignedAuthorization = await self.coinbaseSmartWallet.build_unsigned_authorization(
            walletAddress=agentWalletAddress,
            targetAddress=COINBASE_EIP7702PROXY_ADDRESS,
            isUserMakingTransaction=False,
        )
        authHash = unsignedAuthorization.hash().hex()
        authSignatureHex = await self._sign_hash_with_cdp(messageHash=authHash, walletAddress=agentWalletAddress)
        signedAuth = self.coinbaseSmartWallet.build_signed_authorization(
            unsignedAuthorization=unsignedAuthorization,
            authSignatureHex=authSignatureHex,
        )
        params = await self.coinbaseSmartWallet.build_delegation_transaction_params(
            walletAddress=agentWalletAddress,
            signedAuthorization=signedAuth,
            data=upgradeData,
        )
        await self._make_deployer_transaction(params=params)
        logging.info(f'Delegation set for {agentWalletAddress}')

    async def _send_user_operation(self, agentWalletAddress: str, calls: list[EncodedCall]) -> str:
        if self.coinbaseSmartWallet is None or self.coinbaseBundler is None or self.coinbaseCdpClient is None:
            raise BadRequestException('Smart wallet infrastructure is not configured')
        self.coinbaseBundler.validate_calls(calls=calls, chainId=self.chainId)
        await self.coinbaseSmartWallet.validate_calls(calls=calls, chainId=self.chainId)
        callData = await self.coinbaseSmartWallet.build_execute_call_data(chainId=self.chainId, calls=calls)
        userOperation = await self.coinbaseBundler.build_user_operation(
            chainId=self.chainId,
            sender=agentWalletAddress,
            callData=callData,
            shouldSponsorGas=True,
        )
        userOpHashToSign = await self.coinbaseBundler.generate_user_operation_hash(userOperation=userOperation)
        signature = await self._sign_hash_with_cdp(messageHash=userOpHashToSign, walletAddress=agentWalletAddress)
        userOperationSignature = self.coinbaseSmartWallet.encode_user_operation_signature(signature=signature)
        userOperationHash = await self.coinbaseBundler.send_user_operation(userOperation=userOperation, signature=userOperationSignature)
        logging.info(f'Sent user operation: {userOperationHash}')
        receipt = await self.coinbaseBundler.wait_for_user_operation_receipt(userOperationHash=userOperationHash, raiseOnFailure=True)
        transactionHash = typing.cast(str, receipt['receipt']['transactionHash'])
        logging.info(f'User operation confirmed: {transactionHash}')
        return transactionHash

    async def check_positions_once(self) -> None:
        """Check all active positions once and take necessary actions. Should be called within a database context."""
        if not self.ltvManager or not self.notificationService:
            logging.error('LTV Manager or Notification Service not configured.')
            return
        CRITICAL_LTV_THRESHOLD = 0.80
        positions = await self.databaseStore.get_all_active_positions()
        logging.info(f'Checking LTV for {len(positions)} active positions')
        for position in positions:
            try:
                # Look up collateral asset to get correct decimals
                collateral = next((c for c in SUPPORTED_COLLATERALS if c.address.lower() == position.collateralAsset.lower()), None)
                collateralDecimals = collateral.decimals if collateral else 18
                agent = await self.databaseStore.get_agent(agentId=position.agentId)
                if not agent:
                    continue
                # Read ENS constitution if agent has a name
                constitution: EnsConstitution | None = None
                if agent.ensName and self.mainnetEthClient:
                    try:
                        constitution = await self.ensClient.read_constitution(ethClient=self.mainnetEthClient, ensName=agent.ensName)
                        logging.info(f'Read ENS constitution for {agent.ensName}: pause={constitution.pause}, max_ltv={constitution.max_ltv}')
                    except Exception:  # noqa: BLE001
                        logging.exception(f'Failed to read ENS constitution for {agent.ensName}')
                # Emergency kill switch
                if constitution and constitution.pause:
                    logging.info(f'Agent {agent.ensName} is PAUSED by ENS constitution. Skipping all actions.')
                    continue
                # Fetch live on-chain values
                onchainCollateral, onchainBorrow, _borrowShares = await self._get_onchain_position(
                    agentWalletAddress=agent.walletAddress,
                    morphoMarketId=position.morphoMarketId,
                )
                _vaultShares, onchainVaultAssets = await self._get_actual_vault_balance(agentWalletAddress=agent.walletAddress)
                hasPositionValue = onchainCollateral > 0 or onchainBorrow > 0 or (onchainVaultAssets or 0) > 0
                result = await self.ltvManager.check_position_ltv(
                    position=position,
                    collateralDecimals=collateralDecimals,
                    onchainCollateral=onchainCollateral,
                    onchainBorrow=onchainBorrow,
                    onchainVaultAssets=onchainVaultAssets,
                )
                await self.ltvManager.log_ltv_check(result)
                # Apply ENS constitution overrides
                if constitution and constitution.max_ltv is not None and result.current_ltv > constitution.max_ltv and not (result.needs_action and result.action_type == 'auto_repay'):
                    logging.info(f'ENS constitution max-ltv {constitution.max_ltv:.2%} exceeded (current {result.current_ltv:.2%}), forcing repay')
                    collateralPriceUsd = (await self.alchemyClient.get_asset_current_price(chainId=self.chainId, assetAddress=position.collateralAsset)).priceUsd
                    collateralValueUsd = (onchainCollateral / (10**collateralDecimals)) * collateralPriceUsd
                    repayUsd = (result.current_ltv - constitution.max_ltv) * collateralValueUsd
                    result.needs_action = True
                    result.action_type = 'auto_repay'
                    result.action_amount = int(repayUsd * 1e6)
                    result.reason = f'ENS constitution max-ltv {constitution.max_ltv:.2%} exceeded'
                if constitution and constitution.min_spread is not None and result.needs_action and result.action_type == 'auto_optimize':
                    marketData = await self.morphoClient.get_market(chain_id=self.chainId, collateral_address=position.collateralAsset)
                    borrowApy = marketData.borrow_apy if marketData else 0
                    vaultInfo = await self.fortyAcresClient.get_vault_info(chainId=self.chainId) if self.fortyAcresClient else None
                    yieldApy = vaultInfo.apy if vaultInfo else 0
                    spread = yieldApy - borrowApy
                    if spread < constitution.min_spread:
                        logging.info(f'ENS constitution min-spread {constitution.min_spread:.4f} not met (spread={spread:.4f}), suppressing optimization')
                        result.needs_action = False
                        result.action_type = None
                        result.action_amount = None
                        result.reason = f'Spread {spread:.4f} below ENS constitution min-spread {constitution.min_spread:.4f}'
                user = await self.databaseStore.get_user(userId=agent.userId)
                if not user:
                    continue
                # Handle Action
                if result.needs_action and result.action_type == 'auto_repay':
                    logging.info(f'Position {position.agentPositionId}: Auto-repaying {result.action_amount} USDC')
                    try:
                        actionTx = await self.ltvManager.build_auto_repay_transactions(
                            position=position,
                            repayAmount=result.action_amount or 0,
                            userAddress=agent.walletAddress,
                        )
                        calls = [EncodedCall(toAddress=tx.to, data=HexBytes(tx.data).hex(), value=int(tx.value)) for tx in actionTx.transactions]
                        await self._send_user_operation(
                            agentWalletAddress=agent.walletAddress,
                            calls=calls,
                        )
                        if hasPositionValue:
                            await self.notificationService.send_auto_repay_success(
                                agent=agent,
                                user=user,
                                repayAmount=float(result.action_amount or 0) / 1e6,
                                oldLtv=result.current_ltv,
                                newLtv=result.target_ltv,
                            )
                    except Exception:  # noqa: BLE001
                        logging.exception(f'Failed to auto-repay for position {position.agentPositionId}')
                elif result.needs_action and result.action_type == 'auto_optimize':
                    logging.info(f'Position {position.agentPositionId}: Auto-optimizing — borrowing {result.action_amount} USDC to maximize yield')
                    try:
                        actionTx = await self.ltvManager.build_auto_borrow_transactions(
                            position=position,
                            borrowAmount=result.action_amount or 0,
                            userAddress=agent.walletAddress,
                        )
                        calls = [EncodedCall(toAddress=tx.to, data=HexBytes(tx.data).hex(), value=int(tx.value)) for tx in actionTx.transactions]
                        await self._send_user_operation(
                            agentWalletAddress=agent.walletAddress,
                            calls=calls,
                        )
                        # Get price context for notification
                        priceContext = None
                        if self.priceIntelligenceService:
                            try:
                                priceAnalysis = await self.priceIntelligenceService.get_price_analysis(
                                    chainId=self.chainId,
                                    assetAddress=position.collateralAsset,
                                )
                                priceContext = priceAnalysis.to_summary()
                            except Exception:  # noqa: BLE001
                                pass
                        if hasPositionValue:
                            await self.notificationService.send_auto_optimize_success(
                                agent=agent,
                                user=user,
                                borrowAmount=float(result.action_amount or 0) / 1e6,
                                oldLtv=result.current_ltv,
                                newLtv=result.target_ltv,
                                priceContext=priceContext,
                            )
                        # Cross-chain yield deployment removed — all yield stays on Base
                    except Exception:  # noqa: BLE001
                        logging.exception(f'Failed to auto-optimize for position {position.agentPositionId}')
                elif result.needs_action and result.action_type == 'manual_repay':
                    logging.info(f'Position {position.agentPositionId}: Vault has insufficient funds for auto-repay, warning user')
                    if hasPositionValue:
                        await self.notificationService.send_insufficient_vault_warning(
                            agent=agent,
                            user=user,
                            currentLtv=result.current_ltv,
                            maxLtv=result.max_ltv,
                            requiredAmount=float(result.action_amount or 0) / 1e6,
                        )
                # Deploy idle wallet assets into the position
                usdcAddress = constants.CHAIN_USDC_MAP[self.chainId]
                walletCollateral = await self._get_erc20_balance(tokenAddress=position.collateralAsset, walletAddress=agent.walletAddress)
                walletUsdc = await self._get_erc20_balance(tokenAddress=usdcAddress, walletAddress=agent.walletAddress)
                # Deploy idle collateral: supply to Morpho + borrow USDC at target LTV + deposit to vault
                if walletCollateral > 0:
                    try:
                        collateralPriceUsd = (await self.alchemyClient.get_asset_current_price(chainId=self.chainId, assetAddress=position.collateralAsset)).priceUsd
                        collateralValueUsd = (walletCollateral / (10**collateralDecimals)) * collateralPriceUsd
                        if collateralValueUsd >= 0.01:
                            borrowAmountRaw = int(position.targetLtv * collateralValueUsd * 1e6)
                            market = await self.morphoClient.get_market(chain_id=self.chainId, collateral_address=position.collateralAsset)
                            if market is not None:
                                transactions = self.ltvManager.transactionBuilder.build_position_transactions_from_market(
                                    user_address=agent.walletAddress,
                                    collateral_address=position.collateralAsset,
                                    collateral_amount=walletCollateral,
                                    borrow_amount=borrowAmountRaw,
                                    market=market,
                                )
                                calls = [EncodedCall(toAddress=tx.to, data=HexBytes(tx.data).hex(), value=int(tx.value)) for tx in transactions]
                                await self._send_user_operation(agentWalletAddress=agent.walletAddress, calls=calls)
                                logging.info(f'Position {position.agentPositionId}: Deployed idle collateral ({walletCollateral} raw) + borrowed ${borrowAmountRaw / 1e6:.2f} USDC')
                                await self.databaseStore.log_agent_action(
                                    agentId=position.agentId,
                                    actionType='deploy_idle_collateral',
                                    value=f'{walletCollateral}',
                                    valueId=str(position.agentPositionId),
                                    details={'collateral_amount': walletCollateral, 'borrow_amount': borrowAmountRaw, 'collateral_value_usd': collateralValueUsd},
                                )
                    except Exception:  # noqa: BLE001
                        logging.exception(f'Failed to deploy idle collateral for position {position.agentPositionId}')
                # Deploy idle USDC: deposit to vault
                if walletUsdc > 0:
                    try:
                        if walletUsdc / 1e6 >= 0.01:
                            transactions = self.ltvManager.transactionBuilder.build_vault_deposit_transactions(
                                user_address=agent.walletAddress,
                                deposit_amount=walletUsdc,
                            )
                            calls = [EncodedCall(toAddress=tx.to, data=HexBytes(tx.data).hex(), value=int(tx.value)) for tx in transactions]
                            await self._send_user_operation(agentWalletAddress=agent.walletAddress, calls=calls)
                            logging.info(f'Position {position.agentPositionId}: Deposited idle ${walletUsdc / 1e6:.2f} USDC to vault')
                            await self.databaseStore.log_agent_action(
                                agentId=position.agentId,
                                actionType='deploy_idle_usdc',
                                value=f'${walletUsdc / 1e6:.2f}',
                                valueId=str(position.agentPositionId),
                                details={'usdc_amount': walletUsdc},
                            )
                    except Exception:  # noqa: BLE001
                        logging.exception(f'Failed to deploy idle USDC for position {position.agentPositionId}')
                # Cross-chain yield: poll pending actions and log results
                if self.crossChainManager:
                    try:
                        statusResults = await self.crossChainManager.check_pending_actions(agentId=position.agentId)
                        for statusResult in statusResults:
                            await self.databaseStore.log_agent_action(
                                agentId=position.agentId,
                                actionType='cross_chain_status',
                                value=statusResult.new_status,
                                valueId=str(statusResult.action_id),
                                details={
                                    'old_status': statusResult.old_status,
                                    'new_status': statusResult.new_status,
                                    'is_complete': statusResult.is_complete,
                                },
                            )
                            if statusResult.new_status == 'failed' and self.notificationService:
                                await self.notificationService.send_cross_chain_failed(
                                    agent=agent,
                                    user=user,
                                    actionId=statusResult.action_id,
                                )
                    except Exception:  # noqa: BLE001
                        logging.exception(f'Failed to check cross-chain status for position {position.agentPositionId}')
                # Handle Critical Threshold warning (even after action attempts)
                currentLtv = result.current_ltv
                maxLtv = result.max_ltv
                isCritical = currentLtv >= CRITICAL_LTV_THRESHOLD * maxLtv and maxLtv > 0
                canAgentManage = (onchainVaultAssets or 0) > 0
                if isCritical and not canAgentManage:
                    if hasPositionValue:
                        await self.notificationService.send_critical_ltv_warning(
                            agent=agent,
                            user=user,
                            currentLtv=currentLtv,
                            maxLtv=maxLtv,
                        )
                DAILY_DIGEST_INTERVAL_SECONDS = 86400
                now = datetime.now(UTC)
                lastSent = self._lastDailyDigestSent.get(position.agentId)
                shouldSendDigest = lastSent is None or (now - lastSent).total_seconds() >= DAILY_DIGEST_INTERVAL_SECONDS
                if hasPositionValue and shouldSendDigest and not result.needs_action:
                    priceData = await self.alchemyClient.get_asset_current_price(chainId=self.chainId, assetAddress=position.collateralAsset)
                    collateralValue = (onchainCollateral / (10**collateralDecimals)) * priceData.priceUsd
                    debtValue = onchainBorrow / 1e6
                    await self.notificationService.send_daily_digest(
                        agent=agent,
                        user=user,
                        currentLtv=currentLtv,
                        collateralValue=collateralValue,
                        debtValue=debtValue,
                    )
                    self._lastDailyDigestSent[position.agentId] = now
                # ENS status writes are on mainnet — too expensive for every check cycle.
                # Status is written via scripts/set_ens_constitution.py when needed.
            except Exception:  # noqa: BLE001
                logging.exception(f'Error checking position {position.agentPositionId}')

    async def _execute_agent_deploy_transactions(self, agentWalletAddress: str, userAddress: str, collateralAssetAddress: str, collateralAmount: str, targetLtv: float) -> str | None:
        if self.coinbaseCdpClient is None or self.coinbaseSmartWallet is None or self.coinbaseBundler is None or self.deployerPrivateKey is None:
            return None
        await self._set_delegation(agentWalletAddress=agentWalletAddress, userAddress=userAddress)
        transactionsData = await self._build_position_transactions(
            userAddress=agentWalletAddress,
            collateralAssetAddress=collateralAssetAddress,
            collateralAmount=collateralAmount,
            targetLtv=targetLtv,
        )
        calls = [
            EncodedCall(
                toAddress=tx.to,
                data=tx.data if tx.data.startswith('0x') else f'0x{tx.data}',
                value=int(tx.value or '0'),
            )
            for tx in transactionsData.transactions
        ]
        if not calls:
            return None
        transactionHash = await self._send_user_operation(agentWalletAddress=agentWalletAddress, calls=calls)
        return transactionHash

    async def _build_position_transactions(self, userAddress: str, collateralAssetAddress: str, collateralAmount: str, targetLtv: float) -> PositionTransactionsData:
        return await self.get_position_transactions(user_address=userAddress, collateral_asset_address=collateralAssetAddress, collateral_amount=collateralAmount, target_ltv=targetLtv)

    async def create_position(self, user_address: str, collateral_asset_address: str, collateral_amount: str, target_ltv: float, agent_name: str, agent_emoji: str) -> tuple[Position, AgentResource]:
        collateral = next((c for c in SUPPORTED_COLLATERALS if c.address.lower() == collateral_asset_address.lower()), SUPPORTED_COLLATERALS[0])
        try:
            price_usd = await self._get_asset_price(assetAddress=collateral_asset_address)
            collateral_amount_human = int(collateral_amount) / (10**collateral.decimals)
            collateral_value = collateral_amount_human * price_usd
            logging.info(f'Price for {collateral.symbol}: ${price_usd:.2f}, collateral value: ${collateral_value:.2f}')
        except Exception:  # noqa: BLE001
            logging.exception(f'Failed to fetch price for {collateral_asset_address}, using fallback')
            collateral_value = 100000.0
        borrow_value = collateral_value * target_ltv
        normalized_address = chain_util.normalize_address(user_address)
        estimated_apy = 0.08
        try:
            yield_apy = await self.fortyAcresClient.get_yield_apy(chainId=self.chainId)
            if yield_apy is not None:
                estimated_apy = yield_apy
        except Exception:  # noqa: BLE001
            logging.exception('Failed to get yield APY for position')
        user = await self.databaseStore.get_or_create_user_by_wallet(walletAddress=normalized_address)
        agentId = str(uuid.uuid4())
        walletAddress = normalized_address
        if self.coinbaseCdpClient is not None:
            walletAddress = await self.coinbaseCdpClient.create_eoa(name=agentId)
        agent = await self.databaseStore.create_agent(userId=user.userId, name=agent_name, emoji=agent_emoji, walletAddress=walletAddress)
        market = await self.morphoClient.get_market(chain_id=self.chainId, collateral_address=collateral_asset_address)
        morphoMarketId = market.unique_key if market else ''
        borrowAmountRaw = int(borrow_value * 1e6)
        await self.databaseStore.create_position(
            agentId=agent.agentId,
            collateralAsset=collateral_asset_address,
            targetLtv=target_ltv,
            morphoMarketId=morphoMarketId,
        )
        position = Position(
            position_id=f'pos-{user_address[:8]}',
            created_date=datetime.now(tz=UTC),
            user_address=normalized_address,
            collateral_asset=collateral,
            collateral_amount=collateral_amount,
            collateral_value_usd=collateral_value,
            borrow_amount=str(borrowAmountRaw),
            borrow_value_usd=borrow_value,
            current_ltv=target_ltv,
            target_ltv=target_ltv,
            health_factor=1.0 / target_ltv,
            vault_balance=str(borrowAmountRaw),
            vault_balance_usd=borrow_value,
            accrued_yield='0',
            accrued_yield_usd=0.0,
            estimated_apy=estimated_apy,
            status='active',
            wallet_collateral_balance='0',
            wallet_collateral_balance_usd=0.0,
            wallet_usdc_balance='0',
            wallet_usdc_balance_usd=0.0,
        )
        agentResource = AgentResource(
            agent_id=agent.agentId,
            name=agent.name,
            emoji=agent.emoji,
            agent_index=agent.agentIndex,
            wallet_address=agent.walletAddress,
            ens_name=agent.ensName,
            created_date=agent.createdDate,
        )
        logging.info(f'Created position for {normalized_address}: {position.position_id}, agent: {agent.name}')
        return position, agentResource

    async def get_position(self, user_address: str, agent_id: str | None = None) -> Position | None:
        """Get position with all values fetched from on-chain (collateral, borrow, vault balance)."""
        normalized_address = chain_util.normalize_address(user_address)
        user = await self.databaseStore.get_user_by_wallet(walletAddress=normalized_address)
        if user is None:
            return None
        agents = await self.databaseStore.get_agents_by_user(userId=user.userId)
        if not agents:
            return None
        if agent_id:
            agent = next((a for a in agents if a.agentId == agent_id), None)
            if agent is None:
                return None
        else:
            agent = agents[0]
        dbPosition = await self.databaseStore.get_position_by_agent(agentId=agent.agentId)
        if dbPosition is None:
            return None
        collateral = next((c for c in SUPPORTED_COLLATERALS if c.address.lower() == dbPosition.collateralAsset.lower()), SUPPORTED_COLLATERALS[0])
        # Fetch all on-chain data: collateral amount, borrow amount, vault balance, price
        try:
            onchainCollateral, onchainBorrow, _borrowShares = await self._get_onchain_position(
                agentWalletAddress=agent.walletAddress,
                morphoMarketId=dbPosition.morphoMarketId,
            )
        except Exception:  # noqa: BLE001
            logging.exception('Failed to fetch on-chain position from Morpho Blue')
            onchainCollateral = 0
            onchainBorrow = 0
        _actualVaultShares, actualVaultAssets = await self._get_actual_vault_balance(agentWalletAddress=agent.walletAddress)
        # Fetch wallet balances (free tokens not deposited into Morpho/vault)
        usdcAddress = constants.CHAIN_USDC_MAP[self.chainId]
        walletCollateralBalance = await self._get_erc20_balance(tokenAddress=dbPosition.collateralAsset, walletAddress=agent.walletAddress)
        walletUsdcBalance = await self._get_erc20_balance(tokenAddress=usdcAddress, walletAddress=agent.walletAddress)
        collateralAmountHuman = onchainCollateral / (10**collateral.decimals)
        walletCollateralHuman = walletCollateralBalance / (10**collateral.decimals)
        borrowValueUsd = onchainBorrow / 1e6
        try:
            priceUsd = await self._get_asset_price(assetAddress=dbPosition.collateralAsset)
            collateralValueUsd = collateralAmountHuman * priceUsd
            walletCollateralValueUsd = walletCollateralHuman * priceUsd
        except Exception:  # noqa: BLE001
            collateralValueUsd = 100000.0
            walletCollateralValueUsd = 0.0
        walletUsdcValueUsd = walletUsdcBalance / 1e6
        currentLtv = borrowValueUsd / collateralValueUsd if collateralValueUsd > 0 else 0
        market = await self.morphoClient.get_market(chain_id=self.chainId, collateral_address=dbPosition.collateralAsset)
        maxLtv = market.lltv if market else 0.86
        estimatedApy = 0.08
        try:
            yieldApy = await self.fortyAcresClient.get_yield_apy(chainId=self.chainId)
            if yieldApy is not None:
                estimatedApy = yieldApy
        except Exception:  # noqa: BLE001
            logging.debug('Failed to get yield APY, using default')
        position = Position(
            position_id=f'pos-{normalized_address[:8]}',
            created_date=dbPosition.createdDate,
            user_address=normalized_address,
            collateral_asset=collateral,
            collateral_amount=str(onchainCollateral),
            collateral_value_usd=collateralValueUsd,
            borrow_amount=str(onchainBorrow),
            borrow_value_usd=borrowValueUsd,
            current_ltv=currentLtv,
            target_ltv=dbPosition.targetLtv,
            health_factor=maxLtv / currentLtv if currentLtv > 0 else 999,
            vault_balance=str(actualVaultAssets),
            vault_balance_usd=actualVaultAssets / 1e6,
            accrued_yield='0',
            accrued_yield_usd=0.0,
            estimated_apy=estimatedApy,
            status=dbPosition.status,
            wallet_collateral_balance=str(walletCollateralBalance),
            wallet_collateral_balance_usd=walletCollateralValueUsd,
            wallet_usdc_balance=str(walletUsdcBalance),
            wallet_usdc_balance_usd=walletUsdcValueUsd,
        )
        return position

    async def _get_actual_vault_balance(self, agentWalletAddress: str) -> tuple[int, int]:
        """Get actual vault shares and their USDC value from on-chain data.
        Returns: (shares, assets_in_usdc)
        """
        sharesResponse = await self.ethClient.call_function_by_name(
            toAddress=YO_VAULT_ADDRESS,
            contractAbi=morpho_abis.ERC4626_VAULT_ABI,
            functionName='balanceOf',
            arguments={'account': agentWalletAddress},
        )
        shares = int(sharesResponse[0])
        if shares == 0:
            return 0, 0
        assetsResponse = await self.ethClient.call_function_by_name(
            toAddress=YO_VAULT_ADDRESS,
            contractAbi=morpho_abis.ERC4626_VAULT_ABI,
            functionName='convertToAssets',
            arguments={'shares': shares},
        )
        assets = int(assetsResponse[0])
        return shares, assets

    async def _resolve_agent(self, user_address: str, agent_id: str | None = None):
        """Look up user + agent. If agent_id is given, find that specific agent; otherwise fall back to agents[0]."""
        normalized = chain_util.normalize_address(user_address)
        user = await self.databaseStore.get_user_by_wallet(walletAddress=normalized)
        if user is None:
            raise NotFoundException(message='User not found')
        agents = await self.databaseStore.get_agents_by_user(userId=user.userId)
        if not agents:
            raise NotFoundException(message='No agents found')
        if agent_id:
            agent = next((a for a in agents if a.agentId == agent_id), None)
            if agent is None:
                raise NotFoundException(message=f'Agent {agent_id} not found')
        else:
            agent = agents[0]
        return user, agent

    async def _get_onchain_position(self, agentWalletAddress: str, morphoMarketId: str) -> tuple[int, int, int]:
        """Get live collateral and borrow amounts from Morpho Blue contract.
        Returns: (collateral_amount_raw, borrow_amount_raw_usdc, borrow_shares)
        """
        from money_hack.morpho.transaction_builder import MORPHO_BLUE_ADDRESS

        marketIdBytes = bytes.fromhex(morphoMarketId[2:]) if morphoMarketId.startswith('0x') else bytes.fromhex(morphoMarketId)
        # Fetch user position: (supplyShares, borrowShares, collateral)
        positionResponse = await self.ethClient.call_function_by_name(
            toAddress=MORPHO_BLUE_ADDRESS,
            contractAbi=morpho_abis.MORPHO_BLUE_ABI,
            functionName='position',
            arguments={'id': marketIdBytes, 'user': agentWalletAddress},
        )
        collateralAmount = int(positionResponse[2])
        borrowShares = int(positionResponse[1])
        if borrowShares == 0:
            return collateralAmount, 0, 0
        # Fetch market state to convert borrowShares -> borrowAssets
        marketResponse = await self.ethClient.call_function_by_name(
            toAddress=MORPHO_BLUE_ADDRESS,
            contractAbi=morpho_abis.MORPHO_BLUE_ABI,
            functionName='market',
            arguments={'id': marketIdBytes},
        )
        totalBorrowAssets = int(marketResponse[2])
        totalBorrowShares = int(marketResponse[3])
        if totalBorrowShares == 0:
            return collateralAmount, 0, 0
        # borrowAssets = borrowShares * totalBorrowAssets / totalBorrowShares (round up for debt)
        borrowAmount = (borrowShares * totalBorrowAssets + totalBorrowShares - 1) // totalBorrowShares
        return collateralAmount, borrowAmount, borrowShares

    async def _get_erc20_balance(self, tokenAddress: str, walletAddress: str) -> int:
        """Get ERC20 token balance for a wallet address."""
        response = await self.ethClient.call_function_by_name(
            toAddress=tokenAddress,
            contractAbi=ERC20_BALANCE_ABI,
            functionName='balanceOf',
            arguments={'account': walletAddress},
        )
        return int(response[0])

    async def get_market_data(self) -> tuple[list[CollateralMarketData], float, str, str]:
        collateralMarkets: list[CollateralMarketData] = []
        for collateral in SUPPORTED_COLLATERALS:
            market = await self.morphoClient.get_market(
                chain_id=self.chainId,
                collateral_address=collateral.address,
                loan_address=None,
            )
            if market is None:
                raise ValueError(f'No Morpho market found for collateral {collateral.symbol} ({collateral.address})')
            collateralMarkets.append(
                CollateralMarketData(
                    collateral_address=collateral.address,
                    collateral_symbol=collateral.symbol,
                    borrow_apy=market.borrow_apy,
                    max_ltv=market.lltv,
                    market_id=market.unique_key,
                )
            )
        yieldApy = await self.fortyAcresClient.get_yield_apy(chainId=self.chainId)
        if yieldApy is None:
            raise ValueError('Failed to get Yo.xyz yield APY')
        return collateralMarkets, yieldApy, YO_VAULT_ADDRESS, YO_VAULT_NAME

    async def _calc_withdraw_preview(self, userAddress: str, withdrawAmountRaw: int, agent_id: str | None = None) -> WithdrawPreview:
        _user, agent = await self._resolve_agent(userAddress, agent_id)
        dbPosition = await self.databaseStore.get_position_by_agent(agentId=agent.agentId)
        if dbPosition is None:
            raise NotFoundException(message='No active position found')
        onchainCollateral, onchainBorrow, _borrowShares = await self._get_onchain_position(
            agentWalletAddress=agent.walletAddress,
            morphoMarketId=dbPosition.morphoMarketId,
        )
        _actualVaultShares, actualVaultAssets = await self._get_actual_vault_balance(agentWalletAddress=agent.walletAddress)
        collateral = next((c for c in SUPPORTED_COLLATERALS if c.address.lower() == dbPosition.collateralAsset.lower()), SUPPORTED_COLLATERALS[0])
        collateralAmountHuman = onchainCollateral / (10**collateral.decimals)
        try:
            priceUsd = await self._get_asset_price(assetAddress=dbPosition.collateralAsset)
            collateralValueUsd = collateralAmountHuman * priceUsd
        except Exception:  # noqa: BLE001
            collateralValueUsd = 0.0
        market = await self.morphoClient.get_market(chain_id=self.chainId, collateral_address=dbPosition.collateralAsset)
        maxLtv = market.lltv if market else 0.86
        vaultRaw = actualVaultAssets
        borrowRaw = onchainBorrow
        targetLtv = dbPosition.targetLtv
        hardLtv = WITHDRAW_HARD_LTV_FACTOR * maxLtv
        withdrawRaw = max(min(withdrawAmountRaw, vaultRaw), 0)
        borrowValueUsd = borrowRaw / 1e6
        currentLtv = borrowValueUsd / collateralValueUsd if collateralValueUsd > 0 else 0.0
        estimatedNewLtv = currentLtv
        repayBuffer = max(borrowRaw - int(targetLtv * collateralValueUsd * 1e6), 0)
        maxSafeWithdraw = max(vaultRaw - repayBuffer, 0)
        isWarning = withdrawRaw > maxSafeWithdraw and withdrawRaw <= vaultRaw
        hardRepayBuffer = max(borrowRaw - int(hardLtv * collateralValueUsd * 1e6), 0)
        maxHardWithdraw = max(vaultRaw - hardRepayBuffer, 0)
        isBlocked = withdrawRaw > maxHardWithdraw
        warningMessage: str | None = None
        if isBlocked:
            warningMessage = f'This withdrawal would leave insufficient funds for the agent to manage your position safely. Maximum withdrawal: ${maxHardWithdraw / 1e6:.2f} USDC.'
        elif isWarning:
            warningMessage = f"This withdrawal reduces the agent's ability to auto-repay if your LTV rises. The agent recommends keeping at least ${repayBuffer / 1e6:.2f} USDC in the vault."
        return WithdrawPreview(
            withdraw_amount=str(withdrawRaw),
            vault_balance=str(vaultRaw),
            max_safe_withdraw=str(maxSafeWithdraw),
            current_ltv=currentLtv,
            estimated_new_ltv=estimatedNewLtv,
            target_ltv=targetLtv,
            max_ltv=maxLtv,
            hard_max_ltv=hardLtv,
            is_warning=isWarning,
            is_blocked=isBlocked,
            warning_message=warningMessage,
        )

    async def get_withdraw_preview(self, user_address: str, amount: str, agent_id: str | None = None) -> WithdrawPreview:
        withdrawAmountRaw = int(amount)
        return await self._calc_withdraw_preview(userAddress=user_address, withdrawAmountRaw=withdrawAmountRaw, agent_id=agent_id)

    async def execute_withdraw(self, user_address: str, amount: str, agent_id: str | None = None) -> WithdrawTransactionsData:
        """Execute a partial withdrawal from vault via the agent's smart wallet."""
        _user, agent = await self._resolve_agent(user_address, agent_id)
        dbPosition = await self.databaseStore.get_position_by_agent(agentId=agent.agentId)
        if dbPosition is None:
            raise NotFoundException(message='No active position found')
        withdrawAmount = int(amount)
        _actualVaultShares, actualAssets = await self._get_actual_vault_balance(agentWalletAddress=agent.walletAddress)
        logging.info(f'Vault balance check: Actual assets={actualAssets}, Requested withdrawal={withdrawAmount}')
        if withdrawAmount > actualAssets:
            raise BadRequestException(message=f'Requested withdrawal ${withdrawAmount / 1e6:.2f} exceeds actual vault balance ${actualAssets / 1e6:.2f}')
        sharesToRedeemResponse = await self.ethClient.call_function_by_name(
            toAddress=YO_VAULT_ADDRESS,
            contractAbi=morpho_abis.ERC4626_VAULT_ABI,
            functionName='convertToShares',
            arguments={'assets': withdrawAmount},
        )
        sharesToRedeem = int(sharesToRedeemResponse[0])
        preview = await self._calc_withdraw_preview(userAddress=user_address, withdrawAmountRaw=withdrawAmount)
        if preview.is_blocked:
            raise BadRequestException(message=preview.warning_message or 'Withdrawal amount is too large')
        usdcAddress = constants.CHAIN_USDC_MAP.get(self.chainId)
        if usdcAddress is None:
            raise ValueError(f'USDC not supported on chain {self.chainId}')
        transactionBuilder = TransactionBuilder(chainId=self.chainId, usdcAddress=usdcAddress, yoVaultAddress=YO_VAULT_ADDRESS)
        transactions = transactionBuilder.build_withdraw_transactions(user_address=agent.walletAddress, withdraw_shares=sharesToRedeem)
        calls = [EncodedCall(toAddress=tx.to, data=tx.data if tx.data.startswith('0x') else f'0x{tx.data}', value=int(tx.value or '0')) for tx in transactions]
        transactionHash = await self._send_user_operation(agentWalletAddress=agent.walletAddress, calls=calls)
        logging.info(f'Executed withdraw for {normalizedAddress} via agent {agent.walletAddress}: {withdrawAmount} USDC ({sharesToRedeem} shares), tx={transactionHash}')
        if self.notificationService:
            await self.notificationService.send_ltv_adjustment(
                agent=agent,
                user=user,
                actionType='withdraw',
                amount=f'{withdrawAmount / 1e6:.2f}',
                oldLtv=preview.current_ltv,
                newLtv=preview.estimated_new_ltv,
            )
        return WithdrawTransactionsData(transactions=transactions, withdraw_amount=str(withdrawAmount), vault_address=YO_VAULT_ADDRESS)

    async def get_close_position_transactions(self, user_address: str, agent_id: str | None = None) -> ClosePositionTransactionsData:
        """Build transactions to fully close a position: withdraw from vault, repay debt, withdraw collateral."""
        _user, agent = await self._resolve_agent(user_address, agent_id)
        agentWalletAddress = chain_util.normalize_address(agent.walletAddress)
        dbPosition = await self.databaseStore.get_position_by_agent(agentId=agent.agentId)
        if dbPosition is None:
            raise NotFoundException(message='No active position found')
        market = await self.morphoClient.get_market(chain_id=self.chainId, collateral_address=dbPosition.collateralAsset)
        if market is None:
            raise ValueError(f'No Morpho market found for collateral {dbPosition.collateralAsset}')
        usdcAddress = constants.CHAIN_USDC_MAP.get(self.chainId)
        if usdcAddress is None:
            raise ValueError(f'USDC not supported on chain {self.chainId}')
        onchainCollateral, onchainBorrow, borrowShares = await self._get_onchain_position(
            agentWalletAddress=agent.walletAddress,
            morphoMarketId=dbPosition.morphoMarketId,
        )
        actualVaultShares, actualVaultAssets = await self._get_actual_vault_balance(agentWalletAddress=agent.walletAddress)
        repayAmount = onchainBorrow
        collateralAmount = onchainCollateral
        if actualVaultAssets < repayAmount:
            raise BadRequestException(message=f'Insufficient USDC in vault to close position. needed_raw={repayAmount} available_raw={actualVaultAssets}')
        transactionBuilder = TransactionBuilder(chainId=self.chainId, usdcAddress=usdcAddress, yoVaultAddress=YO_VAULT_ADDRESS)
        transactions = transactionBuilder.build_close_position_transactions_from_market(
            user_address=agentWalletAddress,
            collateral_address=dbPosition.collateralAsset,
            collateral_amount=collateralAmount,
            repay_amount=repayAmount,
            vault_withdraw_amount=actualVaultAssets,
            market=market,
            needs_usdc_approval=True,
            vault_shares=actualVaultShares,
            borrow_shares=borrowShares,
        )
        logging.info(f'Built close position transactions for {agentWalletAddress}: vault_shares={actualVaultShares}, vault_assets={actualVaultAssets}, repay={repayAmount}, borrow_shares={borrowShares}, collateral={collateralAmount}')
        return ClosePositionTransactionsData(
            transactions=transactions,
            collateral_amount=str(collateralAmount),
            repay_amount=str(repayAmount),
            vault_withdraw_amount=str(actualVaultAssets),
            morpho_address=transactionBuilder.morphoAddress,
            vault_address=YO_VAULT_ADDRESS,
        )

    async def execute_close_position(self, user_address: str, agent_id: str | None = None) -> ClosePositionTransactionsData:
        """Build and execute transactions to fully close a position via the agent's smart wallet."""
        _user, agent = await self._resolve_agent(user_address, agent_id)
        agentWalletAddress = chain_util.normalize_address(agent.walletAddress)
        normalizedUserAddress = chain_util.normalize_address(user_address)
        dbPosition = await self.databaseStore.get_position_by_agent(agentId=agent.agentId)
        if dbPosition is None:
            raise NotFoundException(message='No active position found')
        market = await self.morphoClient.get_market(chain_id=self.chainId, collateral_address=dbPosition.collateralAsset)
        if market is None:
            raise ValueError(f'No Morpho market found for collateral {dbPosition.collateralAsset}')
        usdcAddress = constants.CHAIN_USDC_MAP.get(self.chainId)
        if usdcAddress is None:
            raise ValueError(f'USDC not supported on chain {self.chainId}')
        transactionBuilder = TransactionBuilder(chainId=self.chainId, usdcAddress=usdcAddress, yoVaultAddress=YO_VAULT_ADDRESS)
        lastTransactionHash: str | None = None
        actualVaultShares, actualVaultAssets = await self._get_actual_vault_balance(agentWalletAddress=agent.walletAddress)
        if actualVaultShares > 0:
            redeemTransactions = transactionBuilder.build_withdraw_transactions(user_address=agentWalletAddress, withdraw_shares=actualVaultShares)
            redeemCalls = [EncodedCall(toAddress=tx.to, data=tx.data if tx.data.startswith('0x') else f'0x{tx.data}', value=int(tx.value or '0')) for tx in redeemTransactions]
            lastTransactionHash = await self._send_user_operation(agentWalletAddress=agent.walletAddress, calls=redeemCalls)
            logging.info(f'Redeemed vault shares for {agentWalletAddress}: shares={actualVaultShares}, assets={actualVaultAssets}, tx={lastTransactionHash}')
        actualVaultShares, actualVaultAssets = await self._get_actual_vault_balance(agentWalletAddress=agent.walletAddress)
        onchainCollateral, _onchainBorrow, borrowShares = await self._get_onchain_position(agentWalletAddress=agent.walletAddress, morphoMarketId=dbPosition.morphoMarketId)
        marketIdBytes = bytes.fromhex(dbPosition.morphoMarketId[2:]) if dbPosition.morphoMarketId.startswith('0x') else bytes.fromhex(dbPosition.morphoMarketId)
        marketResponse = await self.ethClient.call_function_by_name(
            toAddress=MORPHO_BLUE_ADDRESS,
            contractAbi=morpho_abis.MORPHO_BLUE_ABI,
            functionName='market',
            arguments={'id': marketIdBytes},
        )
        totalBorrowAssets = int(marketResponse[2])
        totalBorrowShares = int(marketResponse[3])
        onchainBorrow = (borrowShares * totalBorrowAssets + totalBorrowShares - 1) // totalBorrowShares if totalBorrowShares > 0 else 0
        walletUsdcBalance = await self._get_erc20_balance(tokenAddress=usdcAddress, walletAddress=agent.walletAddress)
        if walletUsdcBalance < onchainBorrow:
            raise BadRequestException(message=f'Insufficient USDC in wallet after redeem. needed_raw={onchainBorrow} available_raw={walletUsdcBalance}')
        repayTransactions = transactionBuilder.build_repay_and_withdraw_collateral_transactions_from_market(user_address=agentWalletAddress, collateral_address=dbPosition.collateralAsset, collateral_amount=onchainCollateral, repay_amount=onchainBorrow, market=market, needs_usdc_approval=True, borrow_shares=borrowShares)
        repayCalls = [EncodedCall(toAddress=tx.to, data=tx.data if tx.data.startswith('0x') else f'0x{tx.data}', value=int(tx.value or '0')) for tx in repayTransactions]
        lastTransactionHash = await self._send_user_operation(agentWalletAddress=agent.walletAddress, calls=repayCalls)
        logging.info(f'Repaid and withdrew collateral for {agentWalletAddress}: repay={onchainBorrow}, borrow_shares={borrowShares}, collateral={onchainCollateral}, tx={lastTransactionHash}')
        walletUsdcBalance = await self._get_erc20_balance(tokenAddress=usdcAddress, walletAddress=agent.walletAddress)
        walletCollateralBalance = await self._get_erc20_balance(tokenAddress=dbPosition.collateralAsset, walletAddress=agent.walletAddress)
        transferTransactions: list[TransactionCall] = []
        if walletUsdcBalance > 0:
            transferTransactions.append(TransactionCall(to=usdcAddress, data=encode_transfer(recipient=normalizedUserAddress, amount=walletUsdcBalance)))
        if walletCollateralBalance > 0:
            transferTransactions.append(TransactionCall(to=dbPosition.collateralAsset, data=encode_transfer(recipient=normalizedUserAddress, amount=walletCollateralBalance)))
        if transferTransactions:
            transferCalls = [EncodedCall(toAddress=tx.to, data=tx.data if tx.data.startswith('0x') else f'0x{tx.data}', value=int(tx.value or '0')) for tx in transferTransactions]
            try:
                lastTransactionHash = await self._send_user_operation(agentWalletAddress=agent.walletAddress, calls=transferCalls)
            except BadRequestException as error:
                if error.message and 'replacement underpriced' in error.message:
                    await asyncio.sleep(3)
                    lastTransactionHash = await self._send_user_operation(agentWalletAddress=agent.walletAddress, calls=transferCalls)
                else:
                    raise
            logging.info(f'Transferred remaining assets to user {normalizedUserAddress}: usdc={walletUsdcBalance}, collateral={walletCollateralBalance}, tx={lastTransactionHash}')
        return ClosePositionTransactionsData(transactions=[], collateral_amount=str(onchainCollateral), repay_amount=str(onchainBorrow), vault_withdraw_amount=str(actualVaultAssets), morpho_address=transactionBuilder.morphoAddress, vault_address=YO_VAULT_ADDRESS, transaction_hash=lastTransactionHash)

    async def get_wallet(self, wallet_address: str) -> Wallet:
        walletAddress = chain_util.normalize_address(wallet_address)
        clientAssetBalances = await self.alchemyClient.get_wallet_asset_balances(chainId=self.chainId, walletAddress=walletAddress)
        # Include both collateral assets and USDC
        usdcAddress = constants.CHAIN_USDC_MAP.get(self.chainId)
        supportedAddresses = {c.address.lower() for c in SUPPORTED_COLLATERALS}
        if usdcAddress:
            supportedAddresses.add(usdcAddress.lower())
        assetBalances: list[AssetBalance] = []
        for clientBalance in clientAssetBalances:
            normalizedBalance = clientBalance.assetAddress.lower()
            if normalizedBalance not in supportedAddresses:
                continue
            collateral = next((c for c in SUPPORTED_COLLATERALS if c.address.lower() == normalizedBalance), None)
            if collateral:
                symbol = collateral.symbol
                decimals = collateral.decimals
            elif usdcAddress and normalizedBalance == usdcAddress.lower():
                symbol = 'USDC'
                decimals = 6
            else:
                continue
            try:
                if symbol == 'USDC':
                    balanceHuman = clientBalance.balance / (10**decimals)
                    balanceUsd = balanceHuman  # USDC is $1
                else:
                    priceUsd = await self._get_asset_price(assetAddress=clientBalance.assetAddress)
                    balanceHuman = clientBalance.balance / (10**decimals)
                    balanceUsd = balanceHuman * priceUsd
            except Exception:  # noqa: BLE001
                balanceUsd = 0.0
            assetBalances.append(
                AssetBalance(
                    asset_address=clientBalance.assetAddress,
                    asset_symbol=symbol,
                    asset_decimals=decimals,
                    balance=str(clientBalance.balance),
                    balance_usd=balanceUsd,
                )
            )
        return Wallet(wallet_address=walletAddress, asset_balances=assetBalances)

    async def get_position_transactions(self, user_address: str, collateral_asset_address: str, collateral_amount: str, target_ltv: float) -> PositionTransactionsData:
        collateral = next((c for c in SUPPORTED_COLLATERALS if c.address.lower() == collateral_asset_address.lower()), None)
        if collateral is None:
            raise ValueError(f'Unsupported collateral asset: {collateral_asset_address}')
        market = await self.morphoClient.get_market(chain_id=self.chainId, collateral_address=collateral_asset_address)
        if market is None:
            raise ValueError(f'No Morpho market found for collateral {collateral.symbol}')
        priceUsd = await self._get_asset_price(assetAddress=collateral_asset_address)
        collateralAmountHuman = int(collateral_amount) / (10**collateral.decimals)
        collateralValueUsd = collateralAmountHuman * priceUsd
        borrowValueUsd = collateralValueUsd * target_ltv
        borrowAmount = int(borrowValueUsd * 1e6)
        logging.info(f'Building position transactions: collateral={collateral.symbol}, amount={collateralAmountHuman}, value=${collateralValueUsd:.2f}, borrow=${borrowValueUsd:.2f}')
        usdcAddress = constants.CHAIN_USDC_MAP.get(self.chainId)
        if usdcAddress is None:
            raise ValueError(f'USDC not supported on chain {self.chainId}')
        transactionBuilder = TransactionBuilder(chainId=self.chainId, usdcAddress=usdcAddress, yoVaultAddress=YO_VAULT_ADDRESS)
        transactions = transactionBuilder.build_position_transactions_from_market(
            user_address=user_address,
            collateral_address=collateral_asset_address,
            collateral_amount=int(collateral_amount),
            borrow_amount=borrowAmount,
            market=market,
        )
        return PositionTransactionsData(
            transactions=transactions,
            morpho_address=transactionBuilder.morphoAddress,
            vault_address=transactionBuilder.yoVaultAddress,
            estimated_borrow_amount=str(borrowAmount),
            needs_approval=True,
        )

    async def get_telegram_login_url(self) -> str:
        botUsername = await self.telegramClient.get_bot_username()
        return botUsername

    async def telegram_secret_verify(self, user_address: str, telegramSecret: str) -> UserConfig:
        normalizedAddress = chain_util.normalize_address(user_address)
        loginResult = await self.telegramClient.verify_secret_code(walletAddress=normalizedAddress, secretCode=telegramSecret)
        user = await self.databaseStore.get_or_create_user_by_wallet(walletAddress=normalizedAddress)
        await self.databaseStore.update_user_telegram(
            userId=user.userId,
            telegramId=loginResult.telegramUsername,
            telegramChatId=loginResult.chatId,
            telegramUsername=loginResult.telegramUsername,
        )
        await self.telegramClient.send_message(
            chatId=loginResult.chatId,
            text=f'✅ Your Telegram account has been linked to wallet {normalizedAddress[:8]}...{normalizedAddress[-6:]}. You will now receive notifications about your BorrowBot positions.',
        )
        updatedConfig = UserConfig(telegram_handle=loginResult.telegramUsername, telegram_chat_id=loginResult.chatId, preferred_ltv=0.75)
        self._userConfigsCache[normalizedAddress] = updatedConfig
        return updatedConfig

    async def process_telegram_webhook(self, updateDict: JsonObject) -> None:
        messageDict = typing.cast(JsonObject | None, updateDict.get('message'))
        if messageDict is None:
            logging.warning('Invalid Telegram update format: no message found')
            return
        chatId = typing.cast(int | None, typing.cast(JsonObject, messageDict.get('chat', {})).get('id'))
        if chatId is None:
            logging.warning('Invalid Telegram update format: no chat_id found')
            return
        senderUsername = typing.cast(str | None, typing.cast(JsonObject, messageDict.get('from', {})).get('username'))
        if senderUsername is None:
            logging.warning('Telegram message does not have a username set. Cannot proceed.')
            await self.telegramClient.send_message(
                chatId=str(chatId),
                text='Please make sure you have a Telegram username set to use this bot. You can set one in your Telegram settings.',
            )
            return
        messageText = typing.cast(str | None, messageDict.get('text'))
        if messageText is None:
            logging.warning('Telegram message has no text content, skipping processing.')
            return
        try:
            user = await self.databaseStore.get_user_by_telegram_id(telegramId=senderUsername)
            if user.telegramChatId != str(chatId):
                logging.info(f'Updating Telegram chat ID for user {user.userId} from {user.telegramChatId} to {chatId}')
                await self.databaseStore.update_user_telegram(
                    userId=user.userId,
                    telegramId=senderUsername,
                    telegramChatId=str(chatId),
                    telegramUsername=senderUsername,
                )
            if messageText.startswith('/start'):
                await self.telegramClient.send_message(
                    chatId=str(chatId),
                    text='Welcome back! Your Telegram is already linked. You can now chat with your BorrowBot agent here. Try asking "What\'s my position?" or "What are the current rates?"',
                )
            else:
                agents = await self.databaseStore.get_agents_by_user(userId=user.userId)
                if not agents:
                    await self.telegramClient.send_message(
                        chatId=str(chatId),
                        text="You don't have an agent yet. Please set up a position in the web app first.",
                    )
                    return
                agent = agents[0]
                userWallets = await self.databaseStore.get_user_wallets(userId=user.userId)
                if not userWallets:
                    await self.telegramClient.send_message(
                        chatId=str(chatId),
                        text='No wallet found for your account.',
                    )
                    return
                walletAddress = userWallets[0].walletAddress
                await self.telegramClient.send_message(chatId=str(chatId), text='Thinking...')
                try:
                    messages, _ = await self.send_chat_message(
                        userAddress=walletAddress,
                        agentId=agent.agentId,
                        message=messageText,
                        conversationId=f'telegram_{chatId}',
                        channel='telegram',
                    )
                    agentMessages = [m for m in messages if not m.get('is_user', True)]
                    if agentMessages:
                        for msg in agentMessages:
                            await self.telegramClient.send_message(
                                chatId=str(chatId),
                                text=str(msg.get('content', '')),
                            )
                    else:
                        await self.telegramClient.send_message(
                            chatId=str(chatId),
                            text="I couldn't generate a response. Please try again.",
                        )
                except Exception as e:  # noqa: BLE001
                    logging.error(f'Error processing Telegram chat message: {e}')
                    await self.telegramClient.send_message(
                        chatId=str(chatId),
                        text='Sorry, I encountered an error processing your message. Please try again.',
                    )
        except NotFoundException:
            await self.telegramClient.send_login_message(chatId=str(chatId), senderUsername=senderUsername)

    async def disconnect_telegram(self, user_address: str) -> UserConfig:
        normalizedAddress = chain_util.normalize_address(user_address)
        user = await self.databaseStore.get_or_create_user_by_wallet(walletAddress=normalizedAddress)
        await self.databaseStore.update_user_telegram(
            userId=user.userId,
            telegramId=None,
            telegramChatId=None,
            telegramUsername=None,
        )
        updatedConfig = UserConfig(telegram_handle=None, telegram_chat_id=None, preferred_ltv=0.75)
        self._userConfigsCache[normalizedAddress] = updatedConfig
        return updatedConfig

    def normalize_agent_name(self, name: str) -> str:
        """Normalize a display name into a valid ENS label."""
        import re as _re

        label = name.lower().strip().replace(' ', '-')
        label = _re.sub(r'[^a-z0-9-]', '', label)
        label = _re.sub(r'-+', '-', label)
        label = label.strip('-')
        if len(label) < 3:
            label = f'agent-{label}' if label else 'agent'
        if len(label) > 32:
            label = label[:32].rstrip('-')
        return label

    def preview_agent_name(self, name: str) -> tuple[str, str, bool, str | None]:
        """Preview what ENS name an agent name would produce.
        Returns (label, full_ens_name, is_available, error_or_none).
        """
        label = self.normalize_agent_name(name)
        isValid, errorMsg = self.ensClient.validate_label(label)
        if not isValid:
            return label, self.ensClient.get_full_ens_name(label), False, errorMsg
        isAvailable = self.ensClient.check_name_available(label)
        fullName = self.ensClient.get_full_ens_name(label)
        return label, fullName, isAvailable, None if isAvailable else 'Name is already taken'

    def check_ens_name_available(self, label: str) -> tuple[bool, str, str | None]:
        """Check if an ENS subdomain label is available."""
        isValid, errorMsg = self.ensClient.validate_label(label)
        if not isValid:
            return False, self.ensClient.get_full_ens_name(label), errorMsg
        isAvailable = self.ensClient.check_name_available(label)
        fullName = self.ensClient.get_full_ens_name(label)
        return isAvailable, fullName, None if isAvailable else 'Name is already taken'

    def reserve_ens_name(self, label: str) -> str:
        """Reserve an ENS name and return the full ENS name."""
        return self.ensClient.reserve_name(label)

    async def get_ens_config_transactions(
        self, userAddress: str, collateral: str | None, targetLtv: int | None, maxLtv: int | None, minLtv: int | None, autoRebalance: bool, riskTolerance: str, description: str | None, agent_id: str | None = None
    ) -> tuple[list[TransactionCall], str]:
        """Get transactions to set ENS text records for agent configuration."""
        _user, agent = await self._resolve_agent(userAddress, agent_id)
        if not agent.ensName:
            raise ValueError('Agent does not have an ENS name')
        config = EnsAgentConfig(
            collateral=collateral,
            target_ltv=targetLtv,
            max_ltv=maxLtv,
            min_ltv=minLtv,
            auto_rebalance=autoRebalance,
            risk_tolerance=riskTolerance,
            emoji=agent.emoji,
            description=description,
        )
        transactions = self.ensClient.build_set_agent_config_transactions(agent.ensName, config)
        return transactions, agent.ensName

    async def get_ens_constitution(self, userAddress: str, agent_id: str | None = None) -> dict[str, object]:
        """Read the full ENS constitution + status for an agent."""
        _user, agent = await self._resolve_agent(userAddress, agent_id)
        if not agent.ensName:
            return {'ens_name': None, 'max_ltv': None, 'min_spread': None, 'max_position_usd': None, 'allowed_collateral': None, 'pause': False, 'status': None, 'last_action': None, 'last_check': None}
        if not self.mainnetEthClient:
            raise BadRequestException(message='Mainnet ETH client not configured for ENS reads')
        constitution = await self.ensClient.read_constitution(ethClient=self.mainnetEthClient, ensName=agent.ensName)
        status = await self.ensClient.read_status(ethClient=self.mainnetEthClient, ensName=agent.ensName)
        return {
            'ens_name': agent.ensName,
            'max_ltv': constitution.max_ltv,
            'min_spread': constitution.min_spread,
            'max_position_usd': constitution.max_position_usd,
            'allowed_collateral': constitution.allowed_collateral,
            'pause': constitution.pause,
            'status': status.status,
            'last_action': status.last_action,
            'last_check': status.last_check,
        }

    async def set_ens_constitution(self, userAddress: str, maxLtv: float | None, minSpread: float | None, maxPositionUsd: float | None, allowedCollateral: str | None, pause: bool, agent_id: str | None = None) -> dict[str, object]:
        """Set the ENS constitution for an agent via mainnet deployer multicall."""
        _user, agent = await self._resolve_agent(userAddress, agent_id)
        if not agent.ensName:
            raise BadRequestException(message='Agent does not have an ENS name')
        if not self.mainnetEthClient or not self.deployerPrivateKey:
            raise BadRequestException(message='Mainnet ETH client or deployer not configured')
        constitution = EnsConstitution(
            max_ltv=maxLtv,
            min_spread=minSpread,
            max_position_usd=maxPositionUsd,
            allowed_collateral=allowedCollateral,
            pause=pause,
        )
        multicallTx = self.ensClient.build_constitution_multicall(agent.ensName, constitution)
        deployerAddress = Account.from_key(self.deployerPrivateKey).address
        txParams: TxParams = {
            'to': Web3.to_checksum_address(multicallTx.to),
            'data': HexBytes(multicallTx.data),
            'value': Web3.to_wei(0, 'ether'),
        }
        filledParams = await self.mainnetEthClient.fill_transaction_params(params=txParams, fromAddress=deployerAddress)
        signed = Web3().eth.account.sign_transaction(transaction_dict=filledParams, private_key=self.deployerPrivateKey)
        txHash = await self.mainnetEthClient.send_raw_transaction(transactionData=signed.raw_transaction.hex())
        await self.mainnetEthClient.wait_for_transaction_receipt(transactionHash=txHash)
        logging.info(f'Set ENS constitution for {agent.ensName}: max_ltv={maxLtv}, pause={pause} (tx: {txHash})')
        return await self.get_ens_constitution(userAddress=userAddress)

    async def send_chat_message(
        self,
        userAddress: str,
        agentId: str,
        message: str,
        conversationId: str | None = None,
        channel: str = 'web',
    ) -> tuple[list[dict[str, object]], str]:
        """Send a message to the chat and get the agent's response."""
        if self.chatBot is None:
            raise BadRequestException(message='Chat functionality not configured')
        normalizedAddress = chain_util.normalize_address(userAddress)
        user = await self.databaseStore.get_user_by_wallet(walletAddress=normalizedAddress)
        if user is None:
            raise NotFoundException(message='User not found')
        agent = await self.databaseStore.get_agent_by_id(agentId=agentId)
        if agent is None or agent.userId != user.userId:
            raise NotFoundException(message='Agent not found')
        if conversationId is None:
            conversationId = f'{channel}_{agentId}'
        runtimeState = RuntimeState(
            userId=user.userId,
            agentId=agentId,
            conversationId=conversationId,
            walletAddress=normalizedAddress,
            chainId=self.chainId,
            databaseStore=self.databaseStore,
            getMarketData=self.get_market_data,
            getPosition=self.get_position,
            getPriceAnalysis=self._get_price_analysis if self.priceIntelligenceService else None,
        )
        systemPrompt = BORROWBOT_SYSTEM_PROMPT.format(agent_name=f'{agent.emoji} {agent.name}')
        userPrompt = BORROWBOT_USER_PROMPT
        if channel == 'telegram':
            systemPrompt += TELEGRAM_FORMATTING_NOTE
        messages: list[dict[str, object]] = []
        async for event in self.chatBot.execute(
            systemPrompt=systemPrompt,
            userPromptTemplate=userPrompt,
            runtimeState=runtimeState,
            userMessage=message,
        ):
            if event.eventType in ('user', 'agent'):
                content = event.content
                text = content.get('text', '') if isinstance(content, dict) else str(content)
                messages.append(
                    {
                        'message_id': event.chatEventId,
                        'created_date': event.createdDate.isoformat(),
                        'is_user': event.eventType == 'user',
                        'content': text,
                    }
                )
        return messages, conversationId

    async def get_chat_history(
        self,
        userAddress: str,
        agentId: str,
        conversationId: str | None = None,
        limit: int = 50,
        channel: str = 'web',
    ) -> tuple[list[dict[str, object]], str]:
        """Get the chat history for an agent."""
        if self.chatHistoryStore is None:
            raise BadRequestException(message='Chat functionality not configured')
        normalizedAddress = chain_util.normalize_address(userAddress)
        user = await self.databaseStore.get_user_by_wallet(walletAddress=normalizedAddress)
        if user is None:
            raise NotFoundException(message='User not found')
        agent = await self.databaseStore.get_agent_by_id(agentId=agentId)
        if agent is None or agent.userId != user.userId:
            raise NotFoundException(message='Agent not found')
        if conversationId is None:
            conversationId = f'{channel}_{agentId}'
        events = await self.chatHistoryStore.get_user_agent_events(
            userId=user.userId,
            agentId=agentId,
            conversationId=conversationId,
            maxEvents=limit,
        )
        messages: list[dict[str, object]] = []
        for event in events:
            content = event.content
            text = content.get('text', '') if isinstance(content, dict) else str(content)
            messages.append(
                {
                    'message_id': event.chatEventId,
                    'created_date': event.createdDate.isoformat(),
                    'is_user': event.eventType == 'user',
                    'content': text,
                }
            )
        return messages, conversationId

    async def get_agent_thoughts(
        self,
        agentId: str,
        limit: int = 100,
        hoursBack: int = 24,
    ) -> list[AgentActionResource]:
        """Get the agent's recent thoughts."""
        thoughts = await self.databaseStore.get_agent_thoughts(
            agentId=agentId,
            limit=limit,
            hoursBack=hoursBack,
        )
        return [
            AgentActionResource(
                action_id=thought.agentActionId,
                created_date=thought.createdDate,
                agent_id=thought.agentId,
                action_type=thought.actionType,
                value=thought.value,
                details=typing.cast('dict[str, object]', thought.details),
            )
            for thought in thoughts
        ]

    async def get_agent_position(self, agent_id: str) -> Position | None:
        """Get position for a specific agent."""
        agent = await self.databaseStore.get_agent(agentId=agent_id)
        if agent is None:
            raise NotFoundException(message='Agent not found')
        dbPosition = await self.databaseStore.get_position_by_agent(agentId=agent.agentId)
        if dbPosition is None:
            return None
        collateral = next((c for c in SUPPORTED_COLLATERALS if c.address.lower() == dbPosition.collateralAsset.lower()), SUPPORTED_COLLATERALS[0])
        onchainCollateral, onchainBorrow, _borrowShares = await self._get_onchain_position(
            agentWalletAddress=agent.walletAddress,
            morphoMarketId=dbPosition.morphoMarketId,
        )
        _actualVaultShares, actualVaultAssets = await self._get_actual_vault_balance(agentWalletAddress=agent.walletAddress)
        walletCollateralBalance = await self._get_erc20_balance(tokenAddress=dbPosition.collateralAsset, walletAddress=agent.walletAddress)
        usdcAddress = constants.CHAIN_USDC_MAP.get(self.chainId)
        if usdcAddress is None:
            raise ValueError(f'USDC not supported on chain {self.chainId}')
        walletUsdcBalance = await self._get_erc20_balance(tokenAddress=usdcAddress, walletAddress=agent.walletAddress)
        try:
            collateralPriceUsd = await self._get_asset_price(assetAddress=dbPosition.collateralAsset)
            collateralValueUsd = onchainCollateral * collateralPriceUsd / (10 ** collateral.decimals)
            walletCollateralValueUsd = walletCollateralBalance * collateralPriceUsd / (10 ** collateral.decimals)
        except Exception as e:  # noqa: BLE001
            logging.error(f'Failed to get price for {dbPosition.collateralAsset}: {e!r}', exc_info=True)
            collateralValueUsd = 0.0
            walletCollateralValueUsd = 0.0
        borrowValueUsd = onchainBorrow / 1e6
        walletUsdcValueUsd = walletUsdcBalance / 1e6
        currentLtv = borrowValueUsd / collateralValueUsd if collateralValueUsd > 0 else 0
        market = await self.morphoClient.get_market(chain_id=self.chainId, collateral_address=dbPosition.collateralAsset)
        maxLtv = market.lltv if market else 0.86
        estimatedApy = 0.08
        try:
            yieldApy = await self.fortyAcresClient.get_yield_apy(chainId=self.chainId)
            if yieldApy is not None:
                estimatedApy = yieldApy
        except Exception:  # noqa: BLE001
            logging.debug('Failed to get yield APY, using default')
        position = Position(
            position_id=f'pos-{agent.agentId[:8]}',
            created_date=dbPosition.createdDate,
            user_address=agent.walletAddress,
            collateral_asset=collateral,
            collateral_amount=str(onchainCollateral),
            collateral_value_usd=collateralValueUsd,
            borrow_amount=str(onchainBorrow),
            borrow_value_usd=borrowValueUsd,
            current_ltv=currentLtv,
            target_ltv=dbPosition.targetLtv,
            health_factor=maxLtv / currentLtv if currentLtv > 0 else 999,
            vault_balance=str(actualVaultAssets),
            vault_balance_usd=actualVaultAssets / 1e6,
            accrued_yield='0',
            accrued_yield_usd=0.0,
            estimated_apy=estimatedApy,
            status=dbPosition.status,
            wallet_collateral_balance=str(walletCollateralBalance),
            wallet_collateral_balance_usd=walletCollateralValueUsd,
            wallet_usdc_balance=str(walletUsdcBalance),
            wallet_usdc_balance_usd=walletUsdcValueUsd,
        )
        return position

    async def get_agent_wallet(self, agent_id: str) -> Wallet:
        """Get wallet balance for a specific agent."""
        agent = await self.databaseStore.get_agent(agentId=agent_id)
        if agent is None:
            raise NotFoundException(message='Agent not found')
        balances: list[AssetBalance] = []
        for collateral in SUPPORTED_COLLATERALS:
            balance = await self._get_erc20_balance(tokenAddress=collateral.address, walletAddress=agent.walletAddress)
            try:
                priceUsd = await self._get_asset_price(assetAddress=collateral.address)
                balanceUsd = balance * priceUsd / (10 ** collateral.decimals)
            except Exception:  # noqa: BLE001
                balanceUsd = 0.0
            balances.append(
                AssetBalance(
                    asset_address=collateral.address,
                    asset_symbol=collateral.symbol,
                    asset_decimals=collateral.decimals,
                    balance=str(balance),
                    balance_usd=balanceUsd,
                )
            )
        return Wallet(wallet_address=agent.walletAddress, asset_balances=balances)

    async def get_agent_ens_constitution(self, agent_id: str) -> EnsConstitutionResource:
        """Get ENS constitution for a specific agent."""
        agent = await self.databaseStore.get_agent(agentId=agent_id)
        if agent is None:
            raise NotFoundException(message='Agent not found')
        if agent.ensName is None:
            return EnsConstitutionResource(
                ens_name=None,
                max_ltv=None,
                min_spread=None,
                max_position_usd=None,
                allowed_collateral=None,
                pause=False,
                status=None,
                last_action=None,
                last_check=None,
            )
        try:
            if self.mainnetEthClient is None:
                raise ValueError('Mainnet client not configured')
            rawConstitution = await self.ensClient.read_text_record(ethClient=self.mainnetEthClient, ensName=agent.ensName, key='constitution')
            if rawConstitution:
                import json

                constitution = json.loads(rawConstitution)
                return EnsConstitutionResource(
                    ens_name=agent.ensName,
                    max_ltv=constitution.get('max_ltv'),
                    min_spread=constitution.get('min_spread'),
                    max_position_usd=constitution.get('max_position_usd'),
                    allowed_collateral=constitution.get('allowed_collateral'),
                    pause=constitution.get('pause', False),
                    status=constitution.get('status'),
                    last_action=constitution.get('last_action'),
                    last_check=constitution.get('last_check'),
                )
        except Exception:  # noqa: BLE001
            logging.exception('Failed to fetch ENS constitution')
        return EnsConstitutionResource(
            ens_name=agent.ensName,
            max_ltv=None,
            min_spread=None,
            max_position_usd=None,
            allowed_collateral=None,
            pause=False,
            status=None,
            last_action=None,
            last_check=None,
        )

    async def get_cre_position_data(self) -> dict:
        """Public endpoint for Chainlink CRE workflow to fetch aggregate position data."""
        agents = await self.databaseStore.get_all_agents()
        if not agents:
            return {
                'agentId': 'none',
                'collateralValueUsd': 0.0,
                'borrowValueUsd': 0.0,
                'vaultBalanceUsd': 0.0,
                'currentLtvBps': 0,
                'targetLtvBps': 7000,
                'maxLtvBps': 8500,
                'yieldApyBps': 0,
                'borrowAprBps': 0,
            }
        agent = agents[0]
        dbPosition = await self.databaseStore.get_position_by_agent(agentId=agent.agentId)
        if dbPosition is None:
            return {
                'agentId': agent.agentId,
                'collateralValueUsd': 0.0,
                'borrowValueUsd': 0.0,
                'vaultBalanceUsd': 0.0,
                'currentLtvBps': 0,
                'targetLtvBps': 7000,
                'maxLtvBps': 8500,
                'yieldApyBps': 0,
                'borrowAprBps': 0,
            }
        collateral = next((c for c in SUPPORTED_COLLATERALS if c.address.lower() == dbPosition.collateralAsset.lower()), SUPPORTED_COLLATERALS[0])
        onchainCollateral, onchainBorrow, _borrowShares = await self._get_onchain_position(
            agentWalletAddress=agent.walletAddress,
            morphoMarketId=dbPosition.morphoMarketId,
        )
        _vaultShares, vaultAssets = await self._get_actual_vault_balance(agentWalletAddress=agent.walletAddress)
        collateralAmountHuman = onchainCollateral / (10**collateral.decimals)
        borrowAmountHuman = onchainBorrow / (10**6)
        vaultAmountHuman = vaultAssets / (10**6)
        try:
            priceUsd = await self._get_asset_price(assetAddress=dbPosition.collateralAsset)
        except Exception:  # noqa: BLE001
            priceUsd = 0.0
        collateralValueUsd = collateralAmountHuman * priceUsd
        currentLtvBps = int((borrowAmountHuman / collateralValueUsd) * 10000) if collateralValueUsd > 0 else 0
        targetLtvBps = int(dbPosition.targetLtv * 10000) if dbPosition.targetLtv else 7000
        market = await self.morphoClient.get_market(chain_id=self.chainId, collateral_address=dbPosition.collateralAsset, loan_address=None)
        maxLtvBps = int(market.lltv * 10000) if market else 8500
        borrowAprBps = int(market.borrow_apy * 10000) if market else 0
        yieldApy = await self.fortyAcresClient.get_yield_apy(chainId=self.chainId)
        yieldApyBps = int(yieldApy * 10000) if yieldApy else 0
        return {
            'agentId': agent.agentId,
            'collateralValueUsd': round(collateralValueUsd, 2),
            'borrowValueUsd': round(borrowAmountHuman, 2),
            'vaultBalanceUsd': round(vaultAmountHuman, 2),
            'currentLtvBps': currentLtvBps,
            'targetLtvBps': targetLtvBps,
            'maxLtvBps': maxLtvBps,
            'yieldApyBps': yieldApyBps,
            'borrowAprBps': borrowAprBps,
        }
