// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Test.sol";
import "../src/BaseUsdcDirectCheckout.sol";

contract MockUsdc {
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    function mint(address to, uint256 amount) external {
        balanceOf[to] += amount;
    }

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
    address internal merchant = address(0xBEEF);
    address internal buyer = address(0xCAFE);
    BaseUsdcDirectCheckout internal checkout;
    MockUsdc internal mock;

    function setUp() public {
        vm.chainId(8453);
        mock = new MockUsdc();
        vm.etch(USDC, address(mock).code);
        checkout = new BaseUsdcDirectCheckout(merchant);
        MockUsdc(USDC).mint(buyer, 20_000_000);
        vm.prank(buyer);
        MockUsdc(USDC).approve(address(checkout), type(uint256).max);
    }

    function testPaymentTransfersExactAmountDirectlyToMerchant() public {
        bytes32 orderId = keccak256("order-001");
        uint256 amount = 5_000_000;

        vm.prank(buyer);
        checkout.pay(orderId, amount);

        assertEq(MockUsdc(USDC).balanceOf(merchant), amount);
        assertEq(MockUsdc(USDC).balanceOf(buyer), 15_000_000);
        assertTrue(checkout.paidOrder(orderId));
    }

    function testPaymentEmitsIndexedOrderAndBuyer() public {
        bytes32 orderId = keccak256("order-event");
        vm.expectEmit(true, true, true, true);
        emit BaseUsdcDirectCheckout.OrderPaid(orderId, buyer, merchant, 5_000_000, USDC);

        vm.prank(buyer);
        checkout.pay(orderId, 5_000_000);
    }

    function testCannotReplayOrderId() public {
        bytes32 orderId = keccak256("order-replay");
        vm.prank(buyer);
        checkout.pay(orderId, 1_000_000);

        vm.expectRevert(BaseUsdcDirectCheckout.AlreadyPaid.selector);
        vm.prank(buyer);
        checkout.pay(orderId, 1_000_000);
    }

    function testRejectsZeroOrderId() public {
        vm.expectRevert(BaseUsdcDirectCheckout.InvalidOrderId.selector);
        vm.prank(buyer);
        checkout.pay(bytes32(0), 1_000_000);
    }

    function testRejectsZeroAmount() public {
        vm.expectRevert(BaseUsdcDirectCheckout.InvalidAmount.selector);
        vm.prank(buyer);
        checkout.pay(keccak256("zero-amount"), 0);
    }

    function testCannotDeployOnWrongChain() public {
        vm.chainId(1);
        vm.expectRevert(BaseUsdcDirectCheckout.WrongNetwork.selector);
        new BaseUsdcDirectCheckout(merchant);
    }

    function testRejectsZeroMerchant() public {
        vm.expectRevert(BaseUsdcDirectCheckout.InvalidMerchant.selector);
        new BaseUsdcDirectCheckout(address(0));
    }
}
