// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Test.sol";
import "../src/BaseUsdcDirectCheckout.sol";

contract MockUsdc {
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    function mint(address to, uint256 amount) external { balanceOf[to] += amount; }
    function approve(address spender, uint256 amount) external returns (bool) {
        allowance[msg.sender][spender] = amount;
        return true;
    }
    function transferFrom(address from, address to, uint256 amount) external returns (bool) {
        require(allowance[from][msg.sender] >= amount, "allowance");
        require(balanceOf[from] >= amount, "balance");
        allowance[from][msg.sender] -= amount;
        balanceOf[from] -= amount;
        balanceOf[to] += amount;
        return true;
    }
}

contract BaseUsdcDirectCheckoutTest is Test {
    address internal constant USDC = 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913;
    uint256 internal constant SIGNER_KEY = 0xA11CE;
    address internal merchant = address(0xBEEF);
    address internal buyer = address(0xCAFE);
    address internal signer;
    BaseUsdcDirectCheckout internal checkout;
    MockUsdc internal mock;

    function setUp() public {
        vm.chainId(8453);
        signer = vm.addr(SIGNER_KEY);
        mock = new MockUsdc();
        vm.etch(USDC, address(mock).code);
        checkout = new BaseUsdcDirectCheckout(merchant, signer);
        MockUsdc(USDC).mint(buyer, 20_000_000);
        vm.prank(buyer);
        MockUsdc(USDC).approve(address(checkout), type(uint256).max);
    }

    function _signature(bytes32 orderId, uint256 amount, uint256 deadline)
        internal returns (bytes memory)
    {
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(
            SIGNER_KEY, checkout.invoiceDigest(orderId, amount, deadline)
        );
        return abi.encodePacked(r, s, v);
    }

    function testPaymentTransfersExactAmountDirectlyToMerchant() public {
        bytes32 orderId = keccak256("order-001");
        uint256 amount = 5_000_000;
        uint256 deadline = block.timestamp + 1 hours;
        bytes memory sig = _signature(orderId, amount, deadline);

        vm.prank(buyer);
        checkout.pay(orderId, amount, deadline, sig);

        assertEq(MockUsdc(USDC).balanceOf(merchant), amount);
        assertEq(MockUsdc(USDC).balanceOf(buyer), 15_000_000);
        assertTrue(checkout.paidOrder(orderId));
    }

    function testPaymentEmitsIndexedOrderAndBuyer() public {
        bytes32 orderId = keccak256("order-event");
        uint256 deadline = block.timestamp + 1 hours;
        vm.expectEmit(true, true, true, true);
        emit BaseUsdcDirectCheckout.OrderPaid(orderId, buyer, merchant, 5_000_000, USDC);
        vm.prank(buyer);
        checkout.pay(orderId, 5_000_000, deadline, _signature(orderId, 5_000_000, deadline));
    }

    function testCannotReplayOrderId() public {
        bytes32 orderId = keccak256("order-replay");
        uint256 deadline = block.timestamp + 1 hours;
        bytes memory sig = _signature(orderId, 1_000_000, deadline);
        vm.prank(buyer);
        checkout.pay(orderId, 1_000_000, deadline, sig);
        vm.expectRevert(BaseUsdcDirectCheckout.AlreadyPaid.selector);
        vm.prank(buyer);
        checkout.pay(orderId, 1_000_000, deadline, sig);
    }

    function testRejectsSignatureForDifferentAmount() public {
        bytes32 orderId = keccak256("amount-tamper");
        uint256 deadline = block.timestamp + 1 hours;
        bytes memory sig = _signature(orderId, 5_000_000, deadline);
        vm.expectRevert(BaseUsdcDirectCheckout.InvalidSignature.selector);
        vm.prank(buyer);
        checkout.pay(orderId, 1, deadline, sig);
    }

    function testRejectsSignatureForDifferentOrder() public {
        bytes32 orderId = keccak256("order-original");
        uint256 deadline = block.timestamp + 1 hours;
        bytes memory sig = _signature(orderId, 5_000_000, deadline);
        vm.expectRevert(BaseUsdcDirectCheckout.InvalidSignature.selector);
        vm.prank(buyer);
        checkout.pay(keccak256("order-substituted"), 5_000_000, deadline, sig);
    }

    function testRejectsExpiredInvoice() public {
        bytes32 orderId = keccak256("expired");
        uint256 deadline = block.timestamp - 1;
        bytes memory sig = _signature(orderId, 1_000_000, deadline);
        vm.expectRevert(BaseUsdcDirectCheckout.ExpiredInvoice.selector);
        vm.prank(buyer);
        checkout.pay(orderId, 1_000_000, deadline, sig);
    }

    function testRejectsInvalidSignature() public {
        bytes32 orderId = keccak256("invalid-sig");
        uint256 deadline = block.timestamp + 1 hours;
        bytes memory sig = _signature(orderId, 1_000_000, deadline);
        sig[0] = bytes1(uint8(sig[0]) ^ 0x01);
        vm.expectRevert(BaseUsdcDirectCheckout.InvalidSignature.selector);
        vm.prank(buyer);
        checkout.pay(orderId, 1_000_000, deadline, sig);
    }

    function testRejectsZeroOrderId() public {
        uint256 deadline = block.timestamp + 1 hours;
        bytes32 orderId = bytes32(0);
        vm.expectRevert(BaseUsdcDirectCheckout.InvalidOrderId.selector);
        vm.prank(buyer);
        checkout.pay(orderId, 1_000_000, deadline, _signature(orderId, 1_000_000, deadline));
    }

    function testRejectsZeroAmount() public {
        bytes32 orderId = keccak256("zero-amount");
        uint256 deadline = block.timestamp + 1 hours;
        vm.expectRevert(BaseUsdcDirectCheckout.InvalidAmount.selector);
        vm.prank(buyer);
        checkout.pay(orderId, 0, deadline, _signature(orderId, 0, deadline));
    }

    function testCannotDeployOnWrongChain() public {
        vm.chainId(1);
        vm.expectRevert(BaseUsdcDirectCheckout.WrongNetwork.selector);
        new BaseUsdcDirectCheckout(merchant, signer);
    }

    function testRejectsZeroMerchant() public {
        vm.expectRevert(BaseUsdcDirectCheckout.InvalidMerchant.selector);
        new BaseUsdcDirectCheckout(address(0), signer);
    }

    function testRejectsZeroSigner() public {
        vm.expectRevert(BaseUsdcDirectCheckout.InvalidSigner.selector);
        new BaseUsdcDirectCheckout(merchant, address(0));
    }
}
