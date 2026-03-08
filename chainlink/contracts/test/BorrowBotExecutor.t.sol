// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import "forge-std/Test.sol";
import {BorrowBotExecutor} from "../src/BorrowBotExecutor.sol";

contract BorrowBotExecutorTest is Test {
    BorrowBotExecutor executor;
    address forwarder = address(0xF00F00);
    address owner;

    function setUp() public {
        owner = address(this);
        executor = new BorrowBotExecutor(forwarder);
    }

    function _buildReport(
        bytes32 agentId,
        uint8 actionType,
        uint256 amount,
        uint16 targetLtvBps,
        uint16 confidence
    ) internal pure returns (bytes memory) {
        return abi.encode(agentId, actionType, amount, targetLtvBps, confidence);
    }

    // #given a valid repay command
    // #when the forwarder calls onReport
    // #then the command is stored
    function test_processReport_storesCommand() public {
        bytes32 agentId = keccak256("agent-1");
        bytes memory report = _buildReport(agentId, 0, 1000e6, 7000, 9000);

        vm.prank(forwarder);
        executor.onReport("", report);

        BorrowBotExecutor.RebalanceCommand memory cmd = executor.getPendingCommand(agentId);
        assertEq(cmd.actionType, 0);
        assertEq(cmd.amount, 1000e6);
        assertEq(cmd.targetLtvBps, 7000);
        assertFalse(cmd.executed);
    }

    // #given an invalid action type (> 3)
    // #when processed
    // #then it reverts
    function test_processReport_revertsInvalidAction() public {
        bytes memory report = _buildReport(keccak256("agent-1"), 4, 100e6, 7000, 8000);

        vm.prank(forwarder);
        vm.expectRevert(BorrowBotExecutor.InvalidActionType.selector);
        executor.onReport("", report);
    }

    // #given a pending command
    // #when the owner marks it executed
    // #then the executed flag is set
    function test_markExecuted() public {
        bytes32 agentId = keccak256("agent-1");

        vm.prank(forwarder);
        executor.onReport("", _buildReport(agentId, 0, 500e6, 7000, 8500));

        executor.markExecuted(agentId);

        BorrowBotExecutor.RebalanceCommand memory cmd = executor.getPendingCommand(agentId);
        assertTrue(cmd.executed);
    }

    // #given a non-owner caller
    // #when calling markExecuted
    // #then it reverts
    function test_markExecuted_revertsNonOwner() public {
        bytes32 agentId = keccak256("agent-1");

        vm.prank(forwarder);
        executor.onReport("", _buildReport(agentId, 0, 500e6, 7000, 8500));

        vm.prank(address(0xBAD));
        vm.expectRevert();
        executor.markExecuted(agentId);
    }

    // #given a CLOSE command
    // #when processed
    // #then it stores with action type 3
    function test_processReport_closeAction() public {
        bytes32 agentId = keccak256("agent-1");
        bytes memory report = _buildReport(agentId, 3, 0, 0, 9500);

        vm.prank(forwarder);
        executor.onReport("", report);

        BorrowBotExecutor.RebalanceCommand memory cmd = executor.getPendingCommand(agentId);
        assertEq(cmd.actionType, 3);
        assertEq(cmd.amount, 0);
    }
}
