// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

interface IERC20BaseUsdc {
    function balanceOf(address account) external view returns (uint256);
    function transferFrom(address from, address to, uint256 value) external returns (bool);
}

/// @notice Signed-invoice direct checkout for Circle native USDC on Base mainnet.
/// @dev Buyer funds move directly to merchant; the contract has no custody or withdrawal path.
contract BaseUsdcDirectCheckoutSepolia {
    address public constant BASE_USDC = 0x036CbD53842c5426634e7929541eC2318f3dCF7e;
    uint256 public constant BASE_SEPOLIA_CHAIN_ID = 84532;
    uint256 private constant SECP256K1_HALF_N =
        0x7fffffffffffffffffffffffffffffff5d576e7357a4501ddfe92f46681b20a0;

    bytes32 private constant DOMAIN_TYPEHASH =
        keccak256("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)");
    bytes32 private constant NAME_HASH = keccak256("AAE Base USDC Checkout");
    bytes32 private constant VERSION_HASH = keccak256("1");
    bytes32 private constant INVOICE_TYPEHASH =
        keccak256("Invoice(bytes32 orderId,uint256 amount,uint256 deadline,address merchant)");

    address public immutable merchant;
    address public immutable invoiceSigner;
    bytes32 public immutable DOMAIN_SEPARATOR;
    mapping(bytes32 => bool) public paidOrder;

    event OrderPaid(
        bytes32 indexed orderId,
        address indexed buyer,
        address indexed merchant,
        uint256 amount,
        address token
    );

    error WrongNetwork();
    error InvalidMerchant();
    error InvalidSigner();
    error InvalidOrderId();
    error InvalidAmount();
    error ExpiredInvoice();
    error InvalidSignature();
    error AlreadyPaid();
    error TokenCallFailed();
    error IncorrectTransferAmount();

    constructor(address merchant_, address invoiceSigner_) {
        if (block.chainid != BASE_SEPOLIA_CHAIN_ID) revert WrongNetwork();
        if (merchant_ == address(0)) revert InvalidMerchant();
        if (invoiceSigner_ == address(0)) revert InvalidSigner();
        merchant = merchant_;
        invoiceSigner = invoiceSigner_;
        DOMAIN_SEPARATOR = keccak256(abi.encode(
            DOMAIN_TYPEHASH, NAME_HASH, VERSION_HASH, block.chainid, address(this)
        ));
    }

    function invoiceDigest(bytes32 orderId, uint256 amount, uint256 deadline)
        public view returns (bytes32)
    {
        bytes32 structHash = keccak256(abi.encode(
            INVOICE_TYPEHASH, orderId, amount, deadline, merchant
        ));
        return keccak256(abi.encodePacked("\x19\x01", DOMAIN_SEPARATOR, structHash));
    }

    /// @notice Pay the exact signed invoice amount. Buyer first approves this exact USDC amount.
    function pay(bytes32 orderId, uint256 amount, uint256 deadline, bytes calldata signature) external {
        if (orderId == bytes32(0)) revert InvalidOrderId();
        if (amount == 0) revert InvalidAmount();
        if (block.timestamp > deadline) revert ExpiredInvoice();
        if (paidOrder[orderId]) revert AlreadyPaid();
        if (_recover(invoiceDigest(orderId, amount, deadline), signature) != invoiceSigner) {
            revert InvalidSignature();
        }

        IERC20BaseUsdc token = IERC20BaseUsdc(BASE_USDC);
        uint256 beforeBalance = token.balanceOf(merchant);
        if (!token.transferFrom(msg.sender, merchant, amount)) revert TokenCallFailed();
        uint256 afterBalance = token.balanceOf(merchant);
        if (afterBalance < beforeBalance || afterBalance - beforeBalance != amount) {
            revert IncorrectTransferAmount();
        }

        paidOrder[orderId] = true;
        emit OrderPaid(orderId, msg.sender, merchant, amount, BASE_USDC);
    }

    function _recover(bytes32 digest, bytes calldata signature) private pure returns (address) {
        if (signature.length != 65) return address(0);
        bytes32 r;
        bytes32 s;
        uint8 v;
        assembly {
            r := calldataload(signature.offset)
            s := calldataload(add(signature.offset, 32))
            v := byte(0, calldataload(add(signature.offset, 64)))
        }
        if (uint256(s) > SECP256K1_HALF_N || (v != 27 && v != 28)) return address(0);
        return ecrecover(digest, v, r, s);
    }
}
