// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

import {IERC165} from "./IERC165.sol";
import {IReceiver} from "./IReceiver.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";

/// @title ReceiverTemplate - CRE report receiver with forwarder validation
abstract contract ReceiverTemplate is IReceiver, Ownable {
    address private s_forwarderAddress;

    error InvalidForwarderAddress();
    error InvalidSender(address sender, address expected);

    event ForwarderAddressUpdated(address indexed previousForwarder, address indexed newForwarder);

    constructor(address _forwarderAddress) Ownable(msg.sender) {
        if (_forwarderAddress == address(0)) {
            revert InvalidForwarderAddress();
        }
        s_forwarderAddress = _forwarderAddress;
        emit ForwarderAddressUpdated(address(0), _forwarderAddress);
    }

    function getForwarderAddress() external view returns (address) {
        return s_forwarderAddress;
    }

    function onReport(bytes calldata metadata, bytes calldata report) external override {
        if (s_forwarderAddress != address(0) && msg.sender != s_forwarderAddress) {
            revert InvalidSender(msg.sender, s_forwarderAddress);
        }
        _processReport(report);
    }

    function setForwarderAddress(address _forwarder) external onlyOwner {
        address previousForwarder = s_forwarderAddress;
        s_forwarderAddress = _forwarder;
        emit ForwarderAddressUpdated(previousForwarder, _forwarder);
    }

    function _processReport(bytes calldata report) internal virtual;

    function supportsInterface(bytes4 interfaceId) public view virtual override returns (bool) {
        return interfaceId == type(IReceiver).interfaceId || interfaceId == type(IERC165).interfaceId;
    }
}
