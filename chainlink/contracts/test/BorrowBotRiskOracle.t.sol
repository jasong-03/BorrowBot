// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import "forge-std/Test.sol";
import {BorrowBotRiskOracle} from "../src/BorrowBotRiskOracle.sol";

contract BorrowBotRiskOracleTest is Test {
    BorrowBotRiskOracle oracle;
    address forwarder = address(0xF00F00);
    address owner;

    function setUp() public {
        owner = address(this);
        oracle = new BorrowBotRiskOracle(forwarder);
    }

    function _buildReport(
        bytes32 agentId,
        uint8 riskLevel,
        uint16 currentLtvBps,
        uint16 targetLtvBps,
        uint16 maxLtvBps,
        int16 yieldSpreadBps,
        uint16 confidence,
        bytes32 actionHash
    ) internal pure returns (bytes memory) {
        return abi.encode(agentId, riskLevel, currentLtvBps, targetLtvBps, maxLtvBps, yieldSpreadBps, confidence, actionHash);
    }

    // #given a valid risk report
    // #when the forwarder calls onReport
    // #then the assessment is stored and event emitted
    function test_processReport_storesAssessment() public {
        bytes32 agentId = keccak256("agent-1");
        bytes memory report = _buildReport(
            agentId, 1, 7500, 7000, 8500, 250, 8500, keccak256("hold")
        );

        vm.prank(forwarder);
        oracle.onReport("", report);

        BorrowBotRiskOracle.RiskAssessment memory a = oracle.getAssessment(agentId);
        assertEq(a.riskLevel, 1);
        assertEq(a.currentLtvBps, 7500);
        assertEq(a.confidence, 8500);
        assertEq(oracle.getAssessmentCount(), 1);
    }

    // #given a CRITICAL risk level
    // #when processed
    // #then CriticalRisk event is emitted
    function test_processReport_emitsCriticalRisk() public {
        bytes32 agentId = keccak256("agent-1");
        bytes memory report = _buildReport(
            agentId, 3, 8800, 7000, 8500, -100, 9200, keccak256("repay")
        );

        vm.expectEmit(true, false, false, true);
        emit BorrowBotRiskOracle.CriticalRisk(agentId, 8800, 8500);

        vm.prank(forwarder);
        oracle.onReport("", report);
    }

    // #given an invalid risk level (> 3)
    // #when processed
    // #then it reverts
    function test_processReport_revertsOnInvalidRiskLevel() public {
        bytes32 agentId = keccak256("agent-1");
        bytes memory report = _buildReport(
            agentId, 4, 7500, 7000, 8500, 250, 8500, keccak256("hold")
        );

        vm.prank(forwarder);
        vm.expectRevert(BorrowBotRiskOracle.InvalidRiskLevel.selector);
        oracle.onReport("", report);
    }

    // #given a non-forwarder caller
    // #when calling onReport
    // #then it reverts with InvalidSender
    function test_onReport_revertsNonForwarder() public {
        bytes memory report = _buildReport(
            keccak256("agent-1"), 0, 5000, 7000, 8500, 500, 9000, keccak256("hold")
        );

        vm.expectRevert();
        oracle.onReport("", report);
    }

    // #given multiple assessments
    // #when querying history
    // #then getLatestAssessments returns correct count
    function test_getLatestAssessments() public {
        bytes32 agent1 = keccak256("agent-1");
        bytes32 agent2 = keccak256("agent-2");

        vm.startPrank(forwarder);
        oracle.onReport("", _buildReport(agent1, 0, 5000, 7000, 8500, 500, 9000, keccak256("hold")));
        oracle.onReport("", _buildReport(agent2, 1, 7200, 7000, 8500, 300, 8000, keccak256("monitor")));
        oracle.onReport("", _buildReport(agent1, 2, 8000, 7000, 8500, 100, 7500, keccak256("repay")));
        vm.stopPrank();

        BorrowBotRiskOracle.RiskAssessment[] memory latest = oracle.getLatestAssessments(2);
        assertEq(latest.length, 2);
        assertEq(latest[0].agentId, agent2);
        assertEq(latest[1].agentId, agent1);
        assertEq(latest[1].riskLevel, 2);
    }
}
