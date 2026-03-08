// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {ReceiverTemplate} from "./interfaces/ReceiverTemplate.sol";

/// @title BorrowBotExecutor
/// @notice Receives AI-determined rebalance commands from CRE workflows triggered by CriticalRisk events.
///         Records the recommended action on-chain for the BorrowBot backend to execute.
contract BorrowBotExecutor is ReceiverTemplate {
    // Action types: 0 = REPAY, 1 = BORROW, 2 = PAUSE, 3 = CLOSE
    uint8 public constant ACTION_REPAY = 0;
    uint8 public constant ACTION_BORROW = 1;
    uint8 public constant ACTION_PAUSE = 2;
    uint8 public constant ACTION_CLOSE = 3;

    error InvalidActionType();

    struct RebalanceCommand {
        bytes32 agentId;
        uint8 actionType;
        uint256 amount;            // amount in token base units (e.g., USDC 6 decimals)
        uint16 targetLtvBps;       // desired LTV after rebalance
        uint16 confidence;         // AI confidence 0-10000
        uint48 timestamp;
        bool executed;
    }

    /// @dev agentId => latest pending command
    mapping(bytes32 => RebalanceCommand) public pendingCommands;

    /// @dev chronological log
    RebalanceCommand[] public commandHistory;

    event RebalanceRequested(
        bytes32 indexed agentId,
        uint8 actionType,
        uint256 amount,
        uint16 targetLtvBps,
        uint16 confidence,
        uint48 timestamp
    );

    event CommandExecuted(bytes32 indexed agentId, uint256 commandIndex);

    /// @param _forwarderAddress Chainlink KeystoneForwarder on Sepolia: 0x15fc6ae953e024d975e77382eeec56a9101f9f88
    constructor(address _forwarderAddress) ReceiverTemplate(_forwarderAddress) {}

    /// @notice Process incoming CRE rebalance command report
    /// @dev Report ABI-encoded as (bytes32 agentId, uint8 actionType, uint256 amount,
    ///      uint16 targetLtvBps, uint16 confidence)
    function _processReport(bytes calldata report) internal override {
        (
            bytes32 agentId,
            uint8 actionType,
            uint256 amount,
            uint16 targetLtvBps,
            uint16 confidence
        ) = abi.decode(report, (bytes32, uint8, uint256, uint16, uint16));

        if (actionType > ACTION_CLOSE) revert InvalidActionType();

        RebalanceCommand memory command = RebalanceCommand({
            agentId: agentId,
            actionType: actionType,
            amount: amount,
            targetLtvBps: targetLtvBps,
            confidence: confidence,
            timestamp: uint48(block.timestamp),
            executed: false
        });

        pendingCommands[agentId] = command;
        commandHistory.push(command);

        emit RebalanceRequested(
            agentId,
            actionType,
            amount,
            targetLtvBps,
            confidence,
            uint48(block.timestamp)
        );
    }

    /// @notice Mark a pending command as executed (called by BorrowBot backend)
    function markExecuted(bytes32 agentId) external onlyOwner {
        pendingCommands[agentId].executed = true;
        emit CommandExecuted(agentId, commandHistory.length - 1);
    }

    function getPendingCommand(bytes32 agentId) external view returns (RebalanceCommand memory) {
        return pendingCommands[agentId];
    }

    function getCommandCount() external view returns (uint256) {
        return commandHistory.length;
    }
}
