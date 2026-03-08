// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import "forge-std/Script.sol";
import {BorrowBotRiskOracle} from "../src/BorrowBotRiskOracle.sol";
import {BorrowBotExecutor} from "../src/BorrowBotExecutor.sol";

contract Deploy is Script {
    // Chainlink KeystoneForwarder on Sepolia
    address constant SEPOLIA_FORWARDER = 0x15fC6ae953E024d975e77382eEeC56A9101f9F88;

    function run() external {
        uint256 deployerPrivateKey = vm.envUint("DEPLOYER_PRIVATE_KEY");
        vm.startBroadcast(deployerPrivateKey);

        BorrowBotRiskOracle riskOracle = new BorrowBotRiskOracle(SEPOLIA_FORWARDER);
        BorrowBotExecutor executor = new BorrowBotExecutor(SEPOLIA_FORWARDER);

        console.log("BorrowBotRiskOracle deployed to:", address(riskOracle));
        console.log("BorrowBotExecutor deployed to:", address(executor));

        vm.stopBroadcast();
    }
}
