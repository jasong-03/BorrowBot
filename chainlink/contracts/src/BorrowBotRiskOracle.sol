// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {ReceiverTemplate} from "./interfaces/ReceiverTemplate.sol";

/// @title BorrowBotRiskOracle
/// @notice Receives AI-powered risk assessments from CRE workflows and stores them on-chain.
///         Emits CriticalRisk when a position exceeds danger thresholds, triggering auto-protection.
contract BorrowBotRiskOracle is ReceiverTemplate {
    error InvalidRiskLevel();

    // Risk levels: 0 = SAFE, 1 = WARNING, 2 = DANGER, 3 = CRITICAL
    uint8 public constant RISK_SAFE = 0;
    uint8 public constant RISK_WARNING = 1;
    uint8 public constant RISK_DANGER = 2;
    uint8 public constant RISK_CRITICAL = 3;

    struct RiskAssessment {
        bytes32 agentId;
        uint8 riskLevel;
        uint16 currentLtvBps;      // LTV in basis points (7500 = 75%)
        uint16 targetLtvBps;
        uint16 maxLtvBps;
        int16 yieldSpreadBps;      // yield APY - borrow APR in bps (can be negative)
        uint48 timestamp;
        uint16 confidence;         // AI confidence 0-10000
        bytes32 actionHash;        // keccak256 of recommended action string
    }

    /// @dev agentId => latest risk assessment
    mapping(bytes32 => RiskAssessment) public assessments;

    /// @dev chronological log of all assessments
    RiskAssessment[] public assessmentHistory;

    event RiskAssessed(
        bytes32 indexed agentId,
        uint8 riskLevel,
        uint16 currentLtvBps,
        uint16 confidence,
        uint48 timestamp
    );

    event CriticalRisk(
        bytes32 indexed agentId,
        uint16 currentLtvBps,
        uint16 maxLtvBps
    );

    /// @param _forwarderAddress Chainlink KeystoneForwarder on Sepolia: 0x15fc6ae953e024d975e77382eeec56a9101f9f88
    constructor(address _forwarderAddress) ReceiverTemplate(_forwarderAddress) {}

    /// @notice Process incoming CRE risk assessment report
    /// @dev Report ABI-encoded as (bytes32 agentId, uint8 riskLevel, uint16 currentLtvBps,
    ///      uint16 targetLtvBps, uint16 maxLtvBps, int16 yieldSpreadBps,
    ///      uint16 confidence, bytes32 actionHash)
    function _processReport(bytes calldata report) internal override {
        (
            bytes32 agentId,
            uint8 riskLevel,
            uint16 currentLtvBps,
            uint16 targetLtvBps,
            uint16 maxLtvBps,
            int16 yieldSpreadBps,
            uint16 confidence,
            bytes32 actionHash
        ) = abi.decode(report, (bytes32, uint8, uint16, uint16, uint16, int16, uint16, bytes32));

        if (riskLevel > RISK_CRITICAL) revert InvalidRiskLevel();

        RiskAssessment memory assessment = RiskAssessment({
            agentId: agentId,
            riskLevel: riskLevel,
            currentLtvBps: currentLtvBps,
            targetLtvBps: targetLtvBps,
            maxLtvBps: maxLtvBps,
            yieldSpreadBps: yieldSpreadBps,
            timestamp: uint48(block.timestamp),
            confidence: confidence,
            actionHash: actionHash
        });

        assessments[agentId] = assessment;
        assessmentHistory.push(assessment);

        emit RiskAssessed(agentId, riskLevel, currentLtvBps, confidence, uint48(block.timestamp));

        if (riskLevel == RISK_CRITICAL) {
            emit CriticalRisk(agentId, currentLtvBps, maxLtvBps);
        }
    }

    function getAssessment(bytes32 agentId) external view returns (RiskAssessment memory) {
        return assessments[agentId];
    }

    function getAssessmentCount() external view returns (uint256) {
        return assessmentHistory.length;
    }

    function getLatestAssessments(uint256 count) external view returns (RiskAssessment[] memory) {
        uint256 total = assessmentHistory.length;
        if (count > total) count = total;
        RiskAssessment[] memory result = new RiskAssessment[](count);
        for (uint256 i = 0; i < count; i++) {
            result[i] = assessmentHistory[total - count + i];
        }
        return result;
    }
}
