from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, TypedDict

class RebalanceResult(TypedDict):
    ticker: str
    current_value: Decimal
    current_weight: Decimal
    target_weight: Decimal
    target_value: Decimal
    shortfall: Decimal
    allocated_cash: Decimal
    post_value: Decimal
    post_weight: Decimal

def calculate_buy_only_rebalance(
    current_positions: Dict[str, Decimal],
    available_cash: Decimal,
    target_weights: Dict[str, Decimal]
) -> Dict[str, RebalanceResult]:
    """
    Calculates portfolio-aware buy-only rebalancing allocations.
    Never sells any asset; directs available cash strictly to underweight positions.
    """
    if available_cash <= Decimal("0"):
        # Zero allocation
        return {
            ticker: {
                "ticker": ticker,
                "current_value": current_positions.get(ticker, Decimal("0")),
                "current_weight": Decimal("0"),
                "target_weight": weight,
                "target_value": Decimal("0"),
                "shortfall": Decimal("0"),
                "allocated_cash": Decimal("0"),
                "post_value": current_positions.get(ticker, Decimal("0")),
                "post_weight": Decimal("0")
            }
            for ticker, weight in target_weights.items()
        }

    # 1. Total current value of target holdings
    total_current_val = sum(current_positions.get(t, Decimal("0")) for t in target_weights)
    
    # 2. Total portfolio value after investing new cash
    total_future_val = total_current_val + available_cash

    # 3. Calculate target dollar value & shortfall per asset
    shortfalls: Dict[str, Decimal] = {}
    target_values: Dict[str, Decimal] = {}
    
    for ticker, weight in target_weights.items():
        curr_val = current_positions.get(ticker, Decimal("0"))
        tgt_val = total_future_val * weight
        target_values[ticker] = tgt_val
        shortfall = max(Decimal("0"), tgt_val - curr_val)
        shortfalls[ticker] = shortfall

    total_shortfall = sum(shortfalls.values())

    # 4. Allocate cash based on shortfalls
    allocations: Dict[str, Decimal] = {}
    
    if total_shortfall > Decimal("0"):
        if available_cash <= total_shortfall:
            # Allocate available cash proportionally to shortfalls
            for ticker, shortfall in shortfalls.items():
                alloc = (available_cash * shortfall / total_shortfall).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                allocations[ticker] = alloc
        else:
            # Fill all shortfalls, then distribute leftover cash by target weight
            excess_cash = available_cash - total_shortfall
            for ticker, weight in target_weights.items():
                alloc = shortfalls[ticker] + (excess_cash * weight)
                allocations[ticker] = alloc.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    else:
        # All positions already at or above target weight ratio; split cash by target weights
        for ticker, weight in target_weights.items():
            alloc = (available_cash * weight).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            allocations[ticker] = alloc

    # 5. Fix any penny rounding difference to ensure sum(allocations) == available_cash
    allocated_total = sum(allocations.values())
    diff = available_cash - allocated_total
    if diff != Decimal("0"):
        # Add difference to ticker with largest allocation
        max_ticker = max(allocations.keys(), key=lambda t: allocations[t])
        allocations[max_ticker] += diff

    # 6. Build detailed results breakdown
    results: Dict[str, RebalanceResult] = {}
    post_total = total_current_val + available_cash
    
    for ticker, weight in target_weights.items():
        curr_v = current_positions.get(ticker, Decimal("0"))
        curr_w = (curr_v / total_current_val) if total_current_val > 0 else Decimal("0")
        alloc_c = allocations[ticker]
        post_v = curr_v + alloc_c
        post_w = (post_v / post_total) if post_total > 0 else Decimal("0")
        
        results[ticker] = {
            "ticker": ticker,
            "current_value": curr_v,
            "current_weight": curr_w,
            "target_weight": weight,
            "target_value": target_values[ticker].quantize(Decimal("0.01")),
            "shortfall": shortfalls[ticker].quantize(Decimal("0.01")),
            "allocated_cash": alloc_c,
            "post_value": post_v,
            "post_weight": post_w
        }

    return results
