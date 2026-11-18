// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Test.sol";
import "../src/BaseUsdcDirectCheckoutSepolia.sol";

contract MockSepoliaUsdc {
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

contract BaseUsdcDirectCheckoutSepoliaTest is Test {
    address internal constant USDC = 0x036CbD53842c5426634e7929541eC2318f3dCF7e;
    uint256 internal constant SIGNER_KEY = 0xA11CE;
    address internal merchant = address(0xBEEF);
    address internal buyer = address(0xCAFE);
    address internal signer;
    BaseUsdcDirectCheckoutSepolia internal checkout;

    function setUp() public {
        vm.chainId(84532);
        signer = vm.addr(SIGNER_KEY);
        MockSepoliaUsdc mock = new MockSepoliaUsdc();
        vm.etch(USDC, address(mock).code);
        checkout = new BaseUsdcDirectCheckoutSepolia(merchant, signer);
        MockSepoliaUsdc(USDC).mint(buyer, 20_000_000);
        vm.prank(buyer);
        MockSepoliaUsdc(USDC).approve(address(checkout), type(uint256).max);
    }

    function _signature(bytes32 orderId, uint256 amount, uint256 deadline)
        internal returns (bytes memory)
    {
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(
            SIGNER_KEY, checkout.invoiceDigest(orderId, amount, deadline)
        );
        return abi.encodePacked(r, s, v);
    }

    function testSepoliaPaymentUsesTestUsdcAndPaysMerchantDirectly() public {
        bytes32 orderId = keccak256("sepolia-order-001");
        uint256 amount = 5_000_000;
        uint256 deadline = block.timestamp + 1 hours;
        vm.prank(buyer);
        checkout.pay(orderId, amount, deadline, _signature(orderId, amount, deadline));
        assertEq(MockSepoliaUsdc(USDC).balanceOf(merchant), amount);
        assertEq(MockSepoliaUsdc(USDC).balanceOf(buyer), 15_000_000);
        assertTrue(checkout.paidOrder(orderId));
    }

    function testSepoliaRejectsReplayAndExpiredInvoice() public {
        bytes32 orderId = keccak256("sepolia-replay");
        uint256 deadline = block.timestamp + 1 hours;
        bytes memory sig = _signature(orderId, 1_000_000, deadline);
        vm.prank(buyer);
        checkout.pay(orderId, 1_000_000, deadline, sig);
        vm.expectRevert(BaseUsdcDirectCheckoutSepolia.AlreadyPaid.selector);
        vm.prank(buyer);
        checkout.pay(orderId, 1_000_000, deadline, sig);

        bytes32 expiredOrder = keccak256("sepolia-expired");
        uint256 expired = block.timestamp - 1;
        vm.expectRevert(BaseUsdcDirectCheckoutSepolia.ExpiredInvoice.selector);
        vm.prank(buyer);
        checkout.pay(expiredOrder, 1_000_000, expired, _signature(expiredOrder, 1_000_000, expired));
    }

    function testSepoliaContractCannotDeployOnMainnet() public {
        vm.chainId(8453);
        vm.expectRevert(BaseUsdcDirectCheckoutSepolia.WrongNetwork.selector);
        new BaseUsdcDirectCheckoutSepolia(merchant, signer);
    }
}
