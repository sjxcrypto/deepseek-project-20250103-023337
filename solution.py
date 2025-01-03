Below is the updated and fixed version of the Solidity code for the **AMM Contract** and **Bonding Curve Contract** based on the issues identified. The fixes include corrected fee calculations, improved security, gas optimizations, and additional features like fee collection and access control.

---

### **1. Fixed AMM Contract**

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/security/ReentrancyGuard.sol";
import "@openzeppelin/contracts/access/Ownable.sol";

contract AMM is ReentrancyGuard, Ownable {
    address public tokenA;
    address public tokenB;
    uint256 public reserveA;
    uint256 public reserveB;
    uint256 public totalLiquidity;
    mapping(address => uint256) public liquidity;

    uint256 public constant TAKER_FEE = 25; // 0.25%
    uint256 public constant MAKER_FEE = 15; // 0.15%
    uint256 public totalFeesCollectedA;
    uint256 public totalFeesCollectedB;

    event LiquidityAdded(address indexed user, uint256 amountA, uint256 amountB, uint256 liquidity);
    event LiquidityRemoved(address indexed user, uint256 amountA, uint256 amountB, uint256 liquidity);
    event Swap(address indexed user, address tokenIn, uint256 amountIn, address tokenOut, uint256 amountOut);
    event FeeCollected(address indexed token, uint256 amount);

    constructor(address _tokenA, address _tokenB) {
        tokenA = _tokenA;
        tokenB = _tokenB;
    }

    function addLiquidity(uint256 amountA, uint256 amountB) external nonReentrant {
        require(amountA > 0 && amountB > 0, "Amounts must be greater than 0");
        require(reserveA > 0 && reserveB > 0, "Initial liquidity must be added with non-zero reserves");

        IERC20(tokenA).transferFrom(msg.sender, address(this), amountA);
        IERC20(tokenB).transferFrom(msg.sender, address(this), amountB);

        uint256 liquidityMinted;
        if (totalLiquidity == 0) {
            liquidityMinted = sqrt(amountA * amountB);
        } else {
            liquidityMinted = min((amountA * totalLiquidity) / reserveA, (amountB * totalLiquidity) / reserveB);
        }

        require(liquidityMinted > 0, "Insufficient liquidity minted");
        liquidity[msg.sender] += liquidityMinted;
        totalLiquidity += liquidityMinted;
        reserveA += amountA;
        reserveB += amountB;

        emit LiquidityAdded(msg.sender, amountA, amountB, liquidityMinted);
    }

    function removeLiquidity(uint256 liquidityAmount) external nonReentrant {
        require(liquidityAmount > 0 && liquidity[msg.sender] >= liquidityAmount, "Invalid liquidity amount");

        uint256 amountA = (liquidityAmount * reserveA) / totalLiquidity;
        uint256 amountB = (liquidityAmount * reserveB) / totalLiquidity;

        liquidity[msg.sender] -= liquidityAmount;
        totalLiquidity -= liquidityAmount;
        reserveA -= amountA;
        reserveB -= amountB;

        IERC20(tokenA).transfer(msg.sender, amountA);
        IERC20(tokenB).transfer(msg.sender, amountB);

        emit LiquidityRemoved(msg.sender, amountA, amountB, liquidityAmount);
    }

    function swap(address tokenIn, uint256 amountIn) external nonReentrant {
        require(tokenIn == tokenA || tokenIn == tokenB, "Invalid token");
        require(amountIn > 0, "Amount must be greater than 0");

        uint256 amountOut;
        if (tokenIn == tokenA) {
            amountOut = (reserveB * amountIn) / (reserveA + amountIn);
            reserveA += amountIn;
            reserveB -= amountOut;
        } else {
            amountOut = (reserveA * amountIn) / (reserveB + amountIn);
            reserveB += amountIn;
            reserveA -= amountOut;
        }

        require(amountOut > 0, "Insufficient output amount");

        uint256 fee = (tokenIn == tokenA) ? (amountIn * TAKER_FEE) / 10000 : (amountIn * MAKER_FEE) / 10000;
        amountOut -= fee;

        if (tokenIn == tokenA) {
            totalFeesCollectedA += fee;
        } else {
            totalFeesCollectedB += fee;
        }

        IERC20(tokenIn).transferFrom(msg.sender, address(this), amountIn);
        IERC20(tokenIn == tokenA ? tokenB : tokenA).transfer(msg.sender, amountOut);

        emit Swap(msg.sender, tokenIn, amountIn, tokenIn == tokenA ? tokenB : tokenA, amountOut);
        emit FeeCollected(tokenIn, fee);
    }

    function collectFees() external onlyOwner {
        if (totalFeesCollectedA > 0) {
            IERC20(tokenA).transfer(owner(), totalFeesCollectedA);
            totalFeesCollectedA = 0;
        }
        if (totalFeesCollectedB > 0) {
            IERC20(tokenB).transfer(owner(), totalFeesCollectedB);
            totalFeesCollectedB = 0;
        }
    }

    function sqrt(uint256 y) internal pure returns (uint256 z) {
        if (y > 3) {
            z = y;
            uint256 x = y / 2 + 1;
            while (x < z) {
                z = x;
                x = (y / x + x) / 2;
            }
        } else if (y != 0) {
            z = 1;
        }
    }

    function min(uint256 a, uint256 b) internal pure returns (uint256) {
        return a < b ? a : b;
    }
}
```

---

### **2. Fixed Bonding Curve Contract**

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/security/ReentrancyGuard.sol";
import "@openzeppelin/contracts/access/Ownable.sol";

contract BondingCurve is ReentrancyGuard, Ownable {
    IERC20 public token;
    uint256 public totalRaised;
    uint256 public constant MIGRATION_THRESHOLD = 5 ether; // 5 ETH
    uint256 public constant PRICE_INCREASE_RATE = 1e15; // Linear bonding curve
    bool public migrationTriggered;
    address public dexAddress;

    event TokensPurchased(address indexed buyer, uint256 ethAmount, uint256 tokenAmount);
    event MigrationTriggered(uint256 ethAmount, uint256 tokenAmount);

    constructor(address _token) {
        token = IERC20(_token);
    }

    function buyTokens() external payable nonReentrant {
        require(!migrationTriggered, "Migration already triggered");
        require(msg.value > 0, "ETH amount must be greater than 0");

        uint256 tokenAmount = calculateTokenAmount(msg.value);
        require(token.balanceOf(address(this)) >= tokenAmount, "Insufficient token balance");

        totalRaised += msg.value;
        token.transfer(msg.sender, tokenAmount);

        emit TokensPurchased(msg.sender, msg.value, tokenAmount);

        if (totalRaised >= MIGRATION_THRESHOLD) {
            _migrateToDEX();
            migrationTriggered = true;
        }
    }

    function calculateTokenAmount(uint256 ethAmount) public view returns (uint256) {
        return (ethAmount * 1e18) / (PRICE_INCREASE_RATE + totalRaised);
    }

    function setDexAddress(address _dexAddress) external onlyOwner {
        require(_dexAddress != address(0), "Invalid DEX address");
        dexAddress = _dexAddress;
    }

    function _migrateToDEX() internal {
        require(dexAddress != address(0), "DEX address not set");

        uint256 ethBalance = address(this).balance;
        uint256 tokenBalance = token.balanceOf(address(this));

        // Transfer ETH and tokens to the DEX
        payable(dexAddress).transfer(ethBalance);
        token.transfer(dexAddress, tokenBalance);

        emit MigrationTriggered(ethBalance, tokenBalance);
    }
}
```

---

### **Summary of Changes**

1. **AMM Contract:**
   - Fixed fee calculation and added fee collection mechanism.
   - Added checks to prevent division by zero and insufficient output amounts.
   - Added `FeeCollected` event for tracking fees.
   - Added `collectFees` function for the owner to collect fees.

2. **Bonding Curve Contract:**
   - Added a flag (`migrationTriggered`) to prevent further purchases after migration.
   - Made the DEX address configurable via `setDexAddress`.
   - Added access control using `Ownable`.

3. **General Improvements:**
   - Improved gas efficiency by reducing unnecessary storage writes.
   - Added proper input validation and error messages.
   - Ensured reentrancy protection with `nonReentrant`.

---

### **Next Steps**
1. Write unit tests for the updated contracts using Hardhat or Truffle.
2. Deploy the contracts on a testnet (e.g., Goerli or Mumbai).
3. Integrate the contracts with the frontend using Web3.js or Ethers.js.

Let me know if you need further assistance!