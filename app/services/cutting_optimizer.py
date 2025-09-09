from collections import Counter, defaultdict
from itertools import product, combinations_with_replacement
import math
from typing import List, Tuple, Dict, Optional, Set, Union, Any
import json
from dataclasses import dataclass
from enum import Enum
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime
import uuid
import logging

from .. import models, schemas, crud_operations

logger = logging.getLogger(__name__)

# OR-Tools is now the primary and preferred solver
try:
    from ortools.sat.python import cp_model
    ORTOOLS_AVAILABLE = True
    logger.info("🚀 OR-Tools CP-SAT solver available - enhanced optimization enabled")
except ImportError:
    ORTOOLS_AVAILABLE = False
    logger.error("❌ OR-Tools not available - install with: pip install ortools")

# PuLP support commented out - OR-Tools is 3.1x faster and more reliable
# try:
#     from pulp import LpProblem, LpVariable, LpMinimize, LpStatus, lpSum, LpInteger
#     PULP_AVAILABLE = True
# except ImportError:
#     PULP_AVAILABLE = False

SOLVER_AVAILABLE = ORTOOLS_AVAILABLE

class Pattern:
    """Represents a cutting pattern for the ILP algorithm"""
    def __init__(self, lanes: Tuple[float, ...], deckle: float = 118.0):
        self.lanes = tuple(sorted(lanes, reverse=True))  # Sort for consistency
        self.total_width = sum(lanes)
        self.trim = deckle - self.total_width
        self.coeff = Counter(lanes)  # How many of each width this pattern produces
        
    def __hash__(self):
        return hash(self.lanes)
    
    def __eq__(self, other):
        return isinstance(other, Pattern) and self.lanes == other.lanes
    
    def __repr__(self):
        return f"Pattern({self.lanes}, trim={self.trim:.2f})"

class CutRollStatus(str, Enum):
    AVAILABLE = "available"
    RESERVED = "reserved"
    USED = "used"

@dataclass
class RollSpec:
    """Specification for paper rolls including dimensions and quality."""
    width: int
    length: int
    gsm: int
    bf: float
    shade: str

# --- CONFIGURATIONS ---
DEFAULT_JUMBO_WIDTH = 118  # Default width, can be overridden
MIN_TRIM = 1
MAX_TRIM = 20
MAX_TRIM_WITH_CONFIRMATION = 20
MAX_ROLLS_PER_JUMBO = 5

class CuttingOptimizer:
    def __init__(self, jumbo_roll_width: int = DEFAULT_JUMBO_WIDTH):
        """
        Initialize the cutting optimizer with configuration.
        
        Args:
            jumbo_roll_width: Width of jumbo rolls in inches (default: 118)
        """
        self.jumbo_roll_width = jumbo_roll_width
    
    def generate_combos(self, sizes: List[float]) -> List[Tuple[Tuple[float, ...], float]]:
        """
        Generate all combos (1 to 3 rolls) with trim calculation.
        Returns combos sorted by: more rolls first, then lower trim.
        """
        logger.info(f"🔍 COMBO DEBUG: Generating combos for sizes: {sizes}")
        valid_combos = []
        for r in range(1, MAX_ROLLS_PER_JUMBO + 1):
            for combo in product(sizes, repeat=r):
                total = sum(combo)
                trim = round(self.jumbo_roll_width - total, 2)
                if 0 <= trim <= MAX_TRIM_WITH_CONFIRMATION:
                    valid_combos.append((tuple(sorted(combo)), trim))
                    logger.debug(f"🔍 COMBO DEBUG: Valid combo: {tuple(sorted(combo))} → {total}\" used, {trim}\" trim")
                else:
                    logger.debug(f"🔍 COMBO DEBUG: Rejected combo: {tuple(sorted(combo))} → {total}\" used, {trim}\" trim (outside 0-20\" range)")
        
        # Prefer: more rolls, then lower trim
        sorted_combos = sorted(valid_combos, key=lambda x: (-len(x[0]), x[1]))
        logger.info(f"🔍 COMBO DEBUG: Generated {len(sorted_combos)} valid combos, showing first 10:")
        for i, (combo, trim) in enumerate(sorted_combos[:10]):
            logger.info(f"  {i+1}. {combo} → trim={trim}\" ({len(combo)} pieces)")
        return sorted_combos

    # === ILP-BASED OPTIMIZATION METHODS ===
    
    def _solve_cutting_with_ilp(self, demand: Dict[float, int], trim_cap: float = 6.0, max_lanes: int = MAX_ROLLS_PER_JUMBO) -> Dict:
        """Main ILP solving method - now enhanced with OR-Tools support."""
        precision = 0.01
        scale_factor = int(1 / precision)
        deckle = self.jumbo_roll_width
        
        # Generate all feasible cutting patterns
        patterns = self._generate_ilp_patterns(list(demand.keys()), trim_cap, max_lanes, deckle, scale_factor)
        
        if not patterns:
            return {'status': 'Infeasible', 'message': 'No feasible patterns found'}
            
        logger.info(f"🔢 ILP: Generated {len(patterns)} feasible patterns (trim ≤ {trim_cap}\", max_lanes={max_lanes})")
        
        # Debug: Log first few patterns
        logger.debug(f"🔍 DEBUG PATTERNS (first 5):")
        for i, pattern in enumerate(patterns[:5]):
            logger.debug(f"  Pattern {i+1}: {pattern.lanes} → trim={pattern.trim:.1f}\" ({len(pattern.lanes)} pieces)")
        
        # Use OR-Tools CP-SAT solver (3.1x faster than PuLP)
        if ORTOOLS_AVAILABLE:
            logger.info("🚀 Using OR-Tools CP-SAT solver")
            result = self._solve_ortools_exact(patterns, demand)
            if result['status'] in ['Optimal', 'Feasible']:
                return result
                
        # Fallback to greedy heuristic if OR-Tools fails
        logger.warning("⚠️ OR-Tools failed - falling back to greedy heuristic")
        return self._solve_greedy_exact(patterns, demand)
    
    def _generate_ilp_patterns(self, widths: List[float], trim_cap: float, max_lanes: int, deckle: float, scale_factor: int) -> List[Pattern]:
        """Generate all feasible cutting patterns for ILP"""
        patterns = set()
        scaled_deckle = int(deckle * scale_factor)
        scaled_widths = [int(w * scale_factor) for w in widths]
        scaled_trim_cap = int(trim_cap * scale_factor)
        
        # Generate all combinations with repetition up to max_lanes
        for num_lanes in range(1, max_lanes + 1):
            for combo in combinations_with_replacement(scaled_widths, num_lanes):
                total_scaled = sum(combo)
                if total_scaled <= scaled_deckle:
                    trim_scaled = scaled_deckle - total_scaled
                    if trim_scaled <= scaled_trim_cap:
                        # Convert back to float widths
                        float_lanes = tuple(w / scale_factor for w in combo)
                        pattern = Pattern(float_lanes, deckle)
                        patterns.add(pattern)
        
        return list(patterns)
    
    def _solve_ortools_exact(self, patterns: List[Pattern], demand: Dict[float, int], time_limit: int = 30) -> Dict:
        """
        Solve exact fulfillment using OR-Tools CP-SAT solver.
        Generally 3-10x faster than PuLP with better constraint handling.
        """
        try:
            # Create CP-SAT model
            model = cp_model.CpModel()
            solver = cp_model.CpSolver()
            solver.parameters.max_time_in_seconds = time_limit
            
            # Decision variables: how many times to run each pattern
            pattern_vars = {}
            max_patterns = sum(demand.values()) + 10  # Upper bound
            
            for i, pattern in enumerate(patterns):
                pattern_vars[i] = model.NewIntVar(0, max_patterns, f"pattern_{i}")
            
            # Constraints: meet demand exactly  
            logger.debug(f"🔍 OR-TOOLS DEBUG: Setting up constraints for demand: {demand}")
            for width in demand:
                width_productions = []
                patterns_for_width = []
                
                for i, pattern in enumerate(patterns):
                    width_count = pattern.coeff.get(width, 0)  # Use .get() to handle missing keys
                    if width_count > 0:
                        width_productions.append(pattern_vars[i] * width_count)
                        patterns_for_width.append(f"Pattern {i} ({pattern.lanes}) produces {width_count}x{width}")
                
                logger.debug(f"🔍 Width {width} (need {demand[width]}): {len(patterns_for_width)} producing patterns")
                for pattern_info in patterns_for_width[:3]:  # Show first 3
                    logger.debug(f"    {pattern_info}")
                
                if width_productions:
                    # Meet demand but don't massively over-produce
                    model.Add(sum(width_productions) >= demand[width])
                    model.Add(sum(width_productions) <= demand[width] * 3)  # Max 3x over-production per width
                    logger.debug(f"    ✅ Constraint added: {demand[width]} <= sum <= {demand[width] * 3}")
                else:
                    logger.error(f"❌ CONSTRAINT ERROR: No patterns can produce width {width}")
                    logger.debug(f"Available patterns: {[(p.lanes, p.coeff) for p in patterns[:5]]}")
                    return {'status': 'Infeasible', 'message': f'No patterns can produce width {width}'}
            
            # Add overall production constraint to prevent massive over-production
            total_demand = sum(demand.values())
            total_production_terms = []
            for i, pattern in enumerate(patterns):
                pieces_per_pattern = len(pattern.lanes)  # Number of pieces this pattern produces
                total_production_terms.append(pattern_vars[i] * pieces_per_pattern)
            
            if total_production_terms:
                total_production = sum(total_production_terms)
                model.Add(total_production <= total_demand * 2)  # Max 2x total over-production
                logger.debug(f"🔍 OR-TOOLS DEBUG: Total production constraint: <= {total_demand * 2} pieces (need {total_demand})")
            
            # Objective: minimize number of patterns first, then trim (scaled to integers for CP-SAT)
            trim_terms = []
            for i, pattern in enumerate(patterns):
                # Scale trim by 100 to work with integers
                scaled_trim = int(pattern.trim * 100)
                trim_terms.append(pattern_vars[i] * scaled_trim)
            
            # Primary objective: minimize number of patterns (prevent over-production)
            total_patterns = sum(pattern_vars)
            total_trim = sum(trim_terms)
            
            # Weighted objective: heavily prioritize fewer patterns, then minimize trim
            model.Minimize(total_patterns * 10000 + total_trim)
            
            # Solve the model
            import time
            start_time = time.time()
            logger.debug(f"🔍 OR-TOOLS DEBUG: Solving model with {len(patterns)} patterns, {len(demand)} constraints")
            logger.debug(f"🔍 Model stats: {model.Proto().constraints.__len__()} constraints, {len(pattern_vars)} variables")
            
            status = solver.Solve(model)
            solve_time = time.time() - start_time
            
            logger.debug(f"🔍 OR-TOOLS RESULT: Status={solver.StatusName(status)}, Time={solve_time:.3f}s")
            if status == cp_model.INFEASIBLE:
                logger.debug(f"🔍 INFEASIBLE ANALYSIS:")
                logger.debug(f"  - Patterns available: {len(patterns)}")
                logger.debug(f"  - Demand to satisfy: {demand}")
                logger.debug(f"  - Pattern samples: {[p.lanes for p in patterns[:3]]}")
            
            if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
                # Extract solution
                solution = {}
                for i in range(len(patterns)):
                    var_value = solver.Value(pattern_vars[i])
                    if var_value > 0:
                        solution[i] = var_value
                
                result = self._build_ilp_production_plan(patterns, solution, demand)
                result['solver'] = 'OR-Tools CP-SAT'
                result['solve_time'] = round(solve_time, 3)
                result['status'] = 'Optimal' if status == cp_model.OPTIMAL else 'Feasible'
                
                logger.info(f"✅ OR-Tools: {result['summary']['total_sets']} sets, {result['summary']['avg_trim']:.1f}\" avg trim, {solve_time:.2f}s")
                return result
            else:
                logger.warning(f"❌ OR-Tools failed with status: {solver.StatusName(status)}")
                return {'status': 'Infeasible', 'message': f'OR-Tools status: {solver.StatusName(status)}'}
                
        except Exception as e:
            logger.error(f"❌ OR-Tools Error: {e}")
            return {'status': 'Error', 'message': f'OR-Tools solver error: {str(e)}'}
    
    # def _solve_ilp_exact(self, patterns: List[Pattern], demand: Dict[float, int]) -> Dict:
    #     """Solve exact fulfillment using Integer Linear Programming (PuLP) - DEPRECATED"""
    #     # PuLP solver removed - OR-Tools is 3.1x faster and more reliable
    #     # This method is kept for reference but commented out
    #     pass
    
    def _solve_greedy_exact(self, patterns: List[Pattern], demand: Dict[float, int]) -> Dict:
        """Greedy heuristic for exact fulfillment"""
        remaining_demand = demand.copy()
        solution = defaultdict(int)
        
        # Sort patterns by efficiency (low trim, high utilization)
        def pattern_score(p):
            utilization = (self.jumbo_roll_width - p.trim) / self.jumbo_roll_width
            return (p.trim, -utilization)
        
        patterns.sort(key=pattern_score)
        
        max_iterations = 1000  # Prevent infinite loops
        iterations = 0
        
        while any(remaining_demand.values()) and iterations < max_iterations:
            iterations += 1
            best_pattern = None
            best_times = 0
            best_coverage = 0
            
            for i, pattern in enumerate(patterns):
                # How many times can we run this pattern?
                max_times = float('inf')
                for width, count in pattern.coeff.items():
                    if count > 0:
                        max_times = min(max_times, remaining_demand.get(width, 0) // count)
                
                max_times = max(int(max_times), 0)
                
                if max_times > 0:
                    # Score based on coverage and efficiency
                    coverage = sum(min(pattern.coeff[width] * max_times, remaining_demand.get(width, 0)) 
                                 for width in pattern.coeff)
                    efficiency = coverage / (pattern.trim + 0.1)  # Avoid division by zero
                    
                    if efficiency > best_coverage:
                        best_pattern = i
                        best_times = max_times
                        best_coverage = efficiency
            
            if best_pattern is None or best_times == 0:
                break
            
            # Apply the best pattern
            solution[best_pattern] += best_times
            pattern = patterns[best_pattern]
            
            for width, count in pattern.coeff.items():
                remaining_demand[width] = max(0, remaining_demand[width] - count * best_times)
        
        # Check if we satisfied all demand
        if any(remaining_demand.values()):
            return {'status': 'Infeasible', 'message': 'Greedy heuristic could not satisfy all demand'}
        
        return self._build_ilp_production_plan(patterns, solution, demand)
    
    def _build_ilp_production_plan(self, patterns: List[Pattern], solution: Dict[int, int], demand: Dict[float, int]) -> Dict:
        """Build the complete production plan from ILP solution"""
        # Convert solution to sets
        sets = []
        for pattern_idx, count in solution.items():
            pattern = patterns[pattern_idx]
            for _ in range(count):
                sets.append({
                    'pattern': pattern.lanes,
                    'used_width': pattern.total_width,
                    'trim': pattern.trim
                })
        
        # Sort sets for better sequencing
        sets.sort(key=lambda s: (s['trim'], -s['used_width'], s['pattern']))
        
        # Calculate metrics
        total_trim = sum(s['trim'] for s in sets)
        avg_trim = total_trim / len(sets) if sets else 0
        
        # Calculate production summary
        produced = defaultdict(int)
        for pattern_idx, count in solution.items():
            pattern = patterns[pattern_idx]
            for width, qty in pattern.coeff.items():
                produced[width] += qty * count
        
        return {
            'status': 'Optimal',
            'sets': sets,
            'summary': {
                'total_sets': len(sets),
                'total_trim': round(total_trim, 2),
                'avg_trim': round(avg_trim, 2),
            },
            'demand_vs_produced': {
                width: {
                    'demand': demand[width],
                    'produced': produced[width]
                }
                for width in demand
            },
            'patterns_used': len(solution)
        }
    
    def _convert_ilp_result_to_internal_format(self, ilp_result: Dict, order_counter: Counter) -> Tuple[List, Counter]:
        """Convert ILP result to the format expected by the rest of the system"""
        patterns_used = []
        
        # Convert sets to internal pattern format
        for set_info in ilp_result['sets']:
            pattern_tuple = set_info['pattern']
            trim = set_info['trim']
            patterns_used.append((pattern_tuple, trim))
        
        # Calculate remaining demand (should be zero for exact fulfillment)
        remaining_demand = Counter()
        produced = Counter()
        
        # Count what we produced
        for pattern_tuple, trim in patterns_used:
            for width in pattern_tuple:
                produced[width] += 1
        
        # Calculate remaining
        for width, demanded in order_counter.items():
            remaining = max(0, demanded - produced[width])
            if remaining > 0:
                remaining_demand[width] = remaining
        
        logger.info(f"✅ ILP CONVERSION: {len(patterns_used)} patterns, {sum(remaining_demand.values())} remaining demand")
        return patterns_used, remaining_demand

    # === USER'S SMART TRACKING ALGORITHM ===
    
    def _find_optimal_solution_with_tracking(self, order_counter: Counter):
        """
        User's brilliant approach: Use good patterns but track remaining demand in real-time.
        Applies patterns one at a time and regenerates when any width hits zero.
        """
        original_demand = order_counter.copy()
        remaining_demand = order_counter.copy()
        patterns_used = []
        
        logger.info(f"🎯 TRACKING ALGO: Starting with demand={sum(original_demand.values())}, widths={list(original_demand.keys())}")
        iterations = 0
        max_iterations = sum(original_demand.values()) + 10  # Safety limit
        
        while any(remaining_demand.values()) and iterations < max_iterations:
            iterations += 1
            
            # 1. Generate efficient patterns for CURRENT remaining demand
            current_widths = [w for w, qty in remaining_demand.items() if qty > 0]
            if not current_widths:
                break
                
            efficient_patterns = self._generate_efficient_patterns(current_widths)
            if not efficient_patterns:
                logger.warning(f"⚠️ TRACKING ALGO: No patterns found for widths {current_widths}")
                break
            
            # 2. Pick the BEST pattern (lowest trim first, then highest coverage)
            best_pattern = None
            best_score = float('inf')
            
            for pattern, trim in efficient_patterns:
                # Check how many rolls this pattern can satisfy from remaining demand
                coverage = sum(1 for width in pattern if remaining_demand.get(width, 0) > 0)
                can_apply = all(remaining_demand.get(width, 0) > 0 for width in pattern)
                
                if can_apply:
                    # Score: prioritize low trim, then high coverage
                    score = trim - (coverage * 0.1)  # Slight preference for coverage
                    
                    if score < best_score:
                        best_pattern = (pattern, trim)
                        best_score = score
            
            if not best_pattern:
                # Try patterns that only partially satisfy demand - but require higher utilization
                for pattern, trim in efficient_patterns:
                    usable_pieces = sum(1 for width in pattern if remaining_demand.get(width, 0) > 0)
                    # FIXED: Require at least 50% of pattern pieces to be useful
                    if usable_pieces >= len(pattern) * 0.5:  # At least half the pieces must be useful
                        score = trim - (usable_pieces * 0.1)
                        if score < best_score:
                            best_pattern = (pattern, trim)
                            best_score = score
                            
            if not best_pattern:
                logger.warning(f"⚠️ TRACKING ALGO: No applicable patterns found")
                break
                
            # 3. Apply the pattern ONCE and update remaining demand
            pattern, trim = best_pattern
            patterns_used.append((pattern, trim))
            
            # 4. CRITICAL: Subtract exactly what we used from remaining demand
            for width in pattern:
                if remaining_demand.get(width, 0) > 0:
                    remaining_demand[width] -= 1
                    if remaining_demand[width] <= 0:
                        del remaining_demand[width]  # Remove when zero
            
            # 5. When ANY roll type hits zero, patterns will be regenerated next iteration
            
        # Calculate final stats
        total_patterns = len(patterns_used)
        total_waste = sum(trim for _, trim in patterns_used)
        avg_waste = total_waste / total_patterns if total_patterns > 0 else 0
        remaining_total = sum(remaining_demand.values())
        
        logger.info(f"✅ TRACKING ALGO: Generated {total_patterns} patterns, avg trim={avg_waste:.1f}\", remaining={remaining_total}")
        
        if remaining_total == 0:
            return patterns_used, Counter()
        else:
            return patterns_used, remaining_demand

    def match_combos(self, orders: Dict[float, int], interactive: bool = False, algorithm: str = "ilp") -> Tuple[List[Tuple[Tuple[float, ...], float]], Dict[float, int], List[Tuple[Tuple[float, ...], float]]]:
        """
        Match combos with orders using best-fit algorithm logic.
        
        Args:
            orders: Dictionary of {width: quantity}
            interactive: Whether to prompt user for high trim combos
            
        Returns:
            Tuple of (used_combos, pending_orders, high_trim_log)
        """
        order_counter = Counter(orders)
        original_order_counter = order_counter.copy()  # Save original for reset if needed
        combos = self.generate_combos(list(orders.keys()))
        used = []
        high_trim_log = []
        pending = defaultdict(int)
        
        # GLOBAL PATTERN MIX OPTIMIZATION: Find optimal combination of all patterns
        
        # Try direct optimal pattern search first for small-medium problems
        total_demand = sum(order_counter.values())
        logger.info(f"🔍 DIRECT OPTIMIZATION DEBUG: Starting with demand={total_demand}")
        
        if total_demand <= 200:  # Use global optimization for manageable sizes
            logger.info(f"🔍 DIRECT OPTIMIZATION DEBUG: Demand ≤200, proceeding with direct optimization")
            
            # Try direct optimal solution first
            direct_solution = self._find_direct_optimal_solution(order_counter, algorithm)
            logger.info(f"🔍 DIRECT OPTIMIZATION DEBUG: Direct solution result = {direct_solution is not None}")
            
            if direct_solution:
                used_patterns, remaining_demand = direct_solution
                
                used.extend(used_patterns)
                for combo, trim in used_patterns:
                    if trim > 6:
                        high_trim_log.append((combo, trim))
                
                # Update order counter with remaining demand
                order_counter = Counter(remaining_demand)
                
                # CRITICAL FIX: Validate direct optimization results
                total_satisfied = 0
                for pattern, trim in used_patterns:
                    total_satisfied += len(pattern)  # Each pattern creates len(pattern) individual rolls
                
                original_total_demand = total_demand
                remaining_total = sum(remaining_demand.values())
                satisfaction_rate = 1 - (remaining_total / original_total_demand)
                
                # Debug logging
                logger.info(f"🔍 DIRECT OPTIMIZATION VALIDATION:")
                logger.info(f"   Original demand: {original_total_demand}")
                logger.info(f"   Patterns generated: {len(used_patterns)}")
                logger.info(f"   Individual rolls created: {total_satisfied}")
                logger.info(f"   Remaining demand: {remaining_total}")
                logger.info(f"   Satisfaction rate: {satisfaction_rate*100:.1f}%")
                
                # Accept direct optimization if satisfaction rate is good (≥85%) 
                # Allow some over-satisfaction but not massive under-satisfaction
                if satisfaction_rate < 0.85:
                    logger.warning(f"🚨 DIRECT OPTIMIZATION POOR SATISFACTION: {satisfaction_rate*100:.1f}%")
                    # Clear direct optimization results and use fallback
                    used.clear()
                    high_trim_log.clear()
                    order_counter = original_order_counter.copy()  # Reset to original demand
                else:
                    logger.info(f"✅ DIRECT OPTIMIZATION ACCEPTED: {satisfaction_rate*100:.1f}% satisfaction")
            else:
                logger.warning(f"🔍 DIRECT OPTIMIZATION DEBUG: No direct solution found, will use fallback")
        
        # Fallback to step-by-step best-fit for remaining items (if any)
        if any(order_counter.values()):
            initial_combos = combos.copy()
            
            step = 0
            while any(order_counter.values()):
                step += 1
                
                # Dynamic pattern adaptation: generate focused patterns for current demand
                if step > 1:  # After first step, adapt patterns
                    adaptive_combos = self._generate_adaptive_patterns(order_counter)
                    # Combine initial patterns with adaptive ones, but prioritize adaptive
                    working_combos = adaptive_combos + initial_combos
                else:
                    working_combos = initial_combos
                
                # Find the best-fit pattern for current demand
                best_pattern = self._select_best_fit_pattern(working_combos, order_counter)
                
                if best_pattern is None:
                    logger.warning(f"  ❌ No applicable patterns found for remaining demand: {dict(order_counter)}")
                    break
                
                combo, trim = best_pattern
                
                if trim <= MAX_TRIM:
                    # Apply the best-fit pattern once
                    for width in combo:
                        order_counter[width] -= 1
                    used.append((combo, trim))
                    
                    logger.info(f"    ✅ APPLIED BEST-FIT: {combo} → trim={trim}\" → remaining: {dict(order_counter)}")
                    
                    # Log trim decisions
                    if trim <= 6:
                        logger.debug(f"     ✅ ACCEPTED: {combo} → trim={trim}\" (normal)")
                    else:
                        logger.info(f"     ⚠️ ACCEPTED HIGH TRIM: {combo} → trim={trim}\" (6-20\" range)")
                        high_trim_log.append((combo, trim))
                elif trim <= MAX_TRIM_WITH_CONFIRMATION:
                    # Apply the best-fit pattern once
                    for width in combo:
                        order_counter[width] -= 1
                    used.append((combo, trim))
                    
                    logger.info(f"    ✅ APPLIED BEST-FIT: {combo} → trim={trim}\" → remaining: {dict(order_counter)}")
                    
                    # Log trim decisions
                    if trim <= 6:
                        logger.debug(f"     ✅ ACCEPTED: {combo} → trim={trim}\" (normal)")
                    else:
                        logger.info(f"     ⚠️ ACCEPTED HIGH TRIM: {combo} → trim={trim}\" (6-20\" range)")
                        high_trim_log.append((combo, trim))
                else:
                    # >20" trim - should not happen due to generate_combos filtering
                    logger.warning(f"     ❌ REJECTED: {combo} → trim={trim}\" (>20\" - goes to pending)")
                    break
        
        # Remaining orders become pending
        for size, qty in order_counter.items():
            if qty > 0:
                pending[size] = qty
                logger.warning(f"  📋 PENDING: {size}\" x{qty} (could not be optimally fulfilled)")
                
        return used, dict(pending), high_trim_log

    def _select_best_fit_pattern(self, combos: List[Tuple[Tuple[float, ...], float]], order_counter: Counter) -> Tuple[Tuple[float, ...], float]:
        """
        Select the best-fit pattern with look-ahead logic to avoid poor future states.
        
        Args:
            combos: List of (combo, trim) tuples
            order_counter: Current demand counter
            
        Returns:
            Best-fit pattern tuple (combo, trim) or None if no applicable patterns
        """
        best_score = -1
        best_pattern = None
        candidate_patterns = []
        
        logger.debug(f"    🔍 Evaluating {len(combos)} patterns for best fit...")
        
        # Phase 1: Score all applicable patterns
        for combo_idx, (combo, trim) in enumerate(combos):
            # Check if pattern is applicable (sufficient demand available)
            if not self._can_apply_pattern(combo, order_counter):
                continue
                
            # Calculate best-fit score with trim-prioritized metrics
            demand_fit = self._calculate_demand_fit(combo, order_counter)
            
            # CRITICAL: Exponential penalty for any trim (heavily favor 0 trim)
            if trim == 0:
                trim_penalty = 1.0  # Perfect score for zero trim
                zero_trim_bonus = 10.0  # Massive bonus for perfect patterns
            else:
                # Exponential penalty - makes any trim much worse than zero trim
                trim_penalty = 1 + (trim / MAX_TRIM) ** 3  # Cubic penalty
                zero_trim_bonus = 0
            
            # Material utilization (0-trim = 1.0, higher trim = lower)
            material_utilization = (self.jumbo_roll_width - trim) / self.jumbo_roll_width
            
            # Efficiency: pieces count only when material utilization is high
            if material_utilization > 0.94:  # >95% utilization
                efficiency_score = len(combo) * material_utilization * 2  # Double bonus for high utilization
            else:
                efficiency_score = len(combo) * material_utilization * 0.5  # Penalty for low utilization
            
            # Base score: heavily favor zero-trim patterns
            base_score = ((demand_fit * efficiency_score) + zero_trim_bonus) / trim_penalty
            
            candidate_patterns.append((combo, trim, base_score, combo_idx))
            
            logger.debug(f"      Pattern {combo_idx+1}: {combo} → trim={trim}\" → demand_fit={demand_fit:.3f}, trim_penalty={trim_penalty:.3f}, efficiency={efficiency_score:.3f}, base_score={base_score:.3f}")
        
        # Phase 2: Apply look-ahead logic to top candidates
        if candidate_patterns:
            # Sort candidates by base score and evaluate top candidates with look-ahead
            candidate_patterns.sort(key=lambda x: x[2], reverse=True)
            top_candidates = candidate_patterns[:min(5, len(candidate_patterns))]  # Top 5 candidates
            
            logger.debug(f"    🔮 Applying look-ahead logic to top {len(top_candidates)} candidates...")
            
            for combo, trim, base_score, combo_idx in top_candidates:
                # Simulate applying this pattern
                lookahead_score = self._calculate_lookahead_score(combo, order_counter, combos)
                
                # Final score combines base score with look-ahead assessment
                final_score = base_score + lookahead_score
                
                logger.debug(f"      Look-ahead Pattern {combo_idx+1}: {combo} → base={base_score:.3f}, lookahead={lookahead_score:.3f}, final={final_score:.3f}")
                
                if final_score > best_score:
                    best_score = final_score
                    best_pattern = (combo, trim)
                    logger.debug(f"        🏆 NEW BEST: {combo} with final score {final_score:.3f}")
        
        if best_pattern:
            pass
        
        return best_pattern
    
    def _can_apply_pattern(self, combo: Tuple[float, ...], order_counter: Counter) -> bool:
        """
        Check if pattern can be applied given current demand.
        
        Args:
            combo: Pattern tuple of widths
            order_counter: Current demand counter
            
        Returns:
            True if pattern is applicable
        """
        combo_count = Counter(combo)
        return all(order_counter[width] >= count for width, count in combo_count.items())
    
    def _calculate_demand_fit(self, combo: Tuple[float, ...], order_counter: Counter) -> float:
        """
        Calculate how well this pattern fits current demand distribution.
        Uses improved scoring without double-counting bias.
        
        Args:
            combo: Pattern tuple of widths
            order_counter: Current demand counter
            
        Returns:
            Demand fit score (higher is better)
        """
        combo_count = Counter(combo)
        total_demand = sum(order_counter.values())
        
        if total_demand == 0:
            return 0
        
        # Primary metric: Weighted demand satisfaction
        # Higher weight for widths with more remaining demand
        demand_satisfaction = 0
        for width, count in combo_count.items():
            if order_counter[width] > 0:
                # Weight by remaining demand ratio (prioritizes clearing backlogs)
                width_weight = order_counter[width] / total_demand
                demand_satisfaction += width_weight * count
        
        # Bonus for demand balance - penalize patterns that create imbalanced remainders
        balance_bonus = self._calculate_balance_bonus(combo_count, order_counter)
        
        # Completion bonus - extra points for fully satisfying specific widths
        completion_bonus = self._calculate_completion_bonus(combo_count, order_counter)
        
        # Combined fit score
        fit_score = demand_satisfaction + balance_bonus + completion_bonus
        
        return fit_score
    
    def _calculate_balance_bonus(self, combo_count: Counter, order_counter: Counter) -> float:
        """
        Calculate bonus for creating balanced remaining demand.
        Penalizes patterns that leave awkward single-piece remainders.
        """
        balance_bonus = 0
        for width, count in combo_count.items():
            remaining_after = order_counter[width] - count
            if remaining_after > 0:
                # Small bonus for leaving even numbers (easier to pair)
                if remaining_after % 2 == 0:
                    balance_bonus += 0.1
                # Penalty for leaving single pieces (harder to optimize)
                elif remaining_after == 1:
                    balance_bonus -= 0.2
        
        return balance_bonus
    
    def _calculate_completion_bonus(self, combo_count: Counter, order_counter: Counter) -> float:
        """
        Calculate bonus for completely satisfying specific width demands.
        Rewards patterns that fully clear specific widths.
        """
        completion_bonus = 0
        for width, count in combo_count.items():
            if order_counter[width] == count:
                # Bonus for completely satisfying this width
                completion_bonus += 0.5
        
        return completion_bonus

    def _calculate_lookahead_score(self, combo: Tuple[float, ...], order_counter: Counter, all_combos: List[Tuple[Tuple[float, ...], float]]) -> float:
        """
        Calculate look-ahead score by simulating what happens after applying this pattern.
        Penalizes patterns that leave difficult-to-fulfill remainders.
        
        Args:
            combo: Pattern being considered
            order_counter: Current demand counter
            all_combos: All available patterns
            
        Returns:
            Look-ahead score adjustment (can be negative for poor choices)
        """
        # Simulate applying this pattern
        combo_count = Counter(combo)
        simulated_counter = order_counter.copy()
        for width, count in combo_count.items():
            simulated_counter[width] -= count
        
        # Remove zeros to get actual remaining demand
        remaining_demand = {width: qty for width, qty in simulated_counter.items() if qty > 0}
        
        if not remaining_demand:
            # Perfect completion - highest bonus
            return 1.0
        
        # Evaluate quality of remaining demand state
        total_remaining = sum(remaining_demand.values())
        
        # Count how many patterns can still be applied to remaining demand
        applicable_patterns = 0
        best_remaining_utilization = 0
        
        for remaining_combo, remaining_trim in all_combos:
            if self._can_apply_pattern(remaining_combo, Counter(remaining_demand)):
                applicable_patterns += 1
                # Track best possible utilization for remainder
                utilization = (self.jumbo_roll_width - remaining_trim) / self.jumbo_roll_width
                best_remaining_utilization = max(best_remaining_utilization, utilization)
        
        # Look-ahead score components
        pattern_availability_score = min(applicable_patterns / 10.0, 1.0)  # More options = better
        utilization_score = best_remaining_utilization  # Better efficiency available = better
        
        # Penalty for leaving orphaned single pieces
        orphan_penalty = 0
        for qty in remaining_demand.values():
            if qty == 1:
                orphan_penalty -= 0.3  # Significant penalty for single pieces
            elif qty == 2:
                orphan_penalty -= 0.1  # Smaller penalty for pairs
        
        # Bonus for leaving balanced remainders
        balance_bonus = 0
        if len(remaining_demand) <= 2:  # Simple remainders are better
            balance_bonus += 0.2
        
        # Combined look-ahead score
        lookahead_score = (pattern_availability_score + utilization_score + balance_bonus + orphan_penalty) * 0.3
        
        return lookahead_score

    def _generate_adaptive_patterns(self, order_counter: Counter) -> List[Tuple[Tuple[float, ...], float]]:
        """
        Generate patterns specifically optimized for current remaining demand.
        Focus on clearing exact quantities and avoiding orphaned pieces.
        
        Args:
            order_counter: Current demand counter
            
        Returns:
            List of adaptive patterns optimized for current demand
        """
        remaining_widths = [width for width, qty in order_counter.items() if qty > 0]
        adaptive_patterns = []
        
        logger.debug(f"    🔄 Generating adaptive patterns for widths: {remaining_widths}")
        
        # Strategy 1: Perfect completion patterns (exactly clear specific widths)
        # Strategy 1: Perfect completion patterns (exactly clear specific widths)
        for target_width in remaining_widths:
            target_qty = order_counter[target_width]
    
    # Allow up to MAX_ROLLS_PER_JUMBO pieces of this width
            for consume_count in range(1, min(target_qty + 1, MAX_ROLLS_PER_JUMBO + 1)):
                target_usage = target_width * consume_count
                remaining_space = self.jumbo_roll_width - target_usage
        
                if remaining_space >= 0:
            # Case 1: single-width pattern (all of target_width)
                    if consume_count == MAX_ROLLS_PER_JUMBO:
                        combo = tuple([target_width] * consume_count)
                        trim = remaining_space
                        if 0 <= trim <= MAX_TRIM_WITH_CONFIRMATION:  # allow 6–20 with confirmation
                            adaptive_patterns.append((combo, trim))
                        continue
            
            # Case 2: multi-width fill (now allow target_width too)
                    for r in range(0, MAX_ROLLS_PER_JUMBO - consume_count + 1):
                        if r == 0:
                            combo = tuple([target_width] * consume_count)
                            trim = remaining_space
                            if 0 <= trim <= MAX_TRIM_WITH_CONFIRMATION:
                                adaptive_patterns.append((combo, trim))
                        else:
                    # Include target_width in fill set
                            for fill_combo in product(remaining_widths, repeat=r):
                                fill_usage = sum(fill_combo)
                                if fill_usage <= remaining_space:
                                    combo = tuple(sorted([target_width] * consume_count + list(fill_combo)))
                                    trim = round(remaining_space - fill_usage, 2)
                                    if 0 <= trim <= MAX_TRIM_WITH_CONFIRMATION and self._can_apply_pattern(combo, order_counter):
                                        adaptive_patterns.append((combo, trim))

        
        # Strategy 2: Balanced consumption patterns (consume proportionally)
        total_remaining = sum(order_counter.values())
        if total_remaining > 1:
            for pieces in range(2, min(MAX_ROLLS_PER_JUMBO + 1, total_remaining + 1)):
                # Try different balanced combinations
                for combo in product(remaining_widths, repeat=pieces):
                    if sum(combo) <= self.jumbo_roll_width:
                        trim = round(self.jumbo_roll_width - sum(combo), 2)
                        if 0 <= trim <= MAX_TRIM:
                            sorted_combo = tuple(sorted(combo))
                            if self._can_apply_pattern(sorted_combo, order_counter):
                                # Check if this creates good balance
                                balance_score = self._evaluate_balance_improvement(sorted_combo, order_counter)
                                if balance_score > 0:  # Only add if it improves balance
                                    adaptive_patterns.append((sorted_combo, trim))
        
        # Remove duplicates and sort by trim (prefer lower trim)
        unique_patterns = list(set(adaptive_patterns))
        unique_patterns.sort(key=lambda x: x[1])  # Sort by trim
        
        
        return unique_patterns[:20]  # Limit to top 20 patterns to avoid explosion

    def _evaluate_balance_improvement(self, combo: Tuple[float, ...], order_counter: Counter) -> float:
        """
        Evaluate how much this pattern improves demand balance.
        Returns positive score if it creates better balance, negative if worse.
        """
        combo_count = Counter(combo)
        balance_improvement = 0
        
        for width, count in combo_count.items():
            remaining_after = order_counter[width] - count
            current_qty = order_counter[width]
            
            # Reward patterns that bring high quantities closer to balanced levels
            if current_qty > 3:  # High quantity
                if remaining_after <= 2:  # Bringing it down to manageable level
                    balance_improvement += 0.3
            
            # Penalize patterns that create single orphans
            if remaining_after == 1:
                balance_improvement -= 0.5
            elif remaining_after == 2:
                balance_improvement += 0.1  # Pairs are okay
        
        return balance_improvement

    def _find_direct_optimal_solution(self, order_counter: Counter, algorithm="ilp"):
        """
        Optimal solver that supports multiple algorithms.
        
        Args:
            order_counter: Demand for each width
            algorithm: "ilp" for ILP optimization, "tracking" for user's tracking algorithm
        """
        if not any(order_counter.values()):
            return None
            
        total_demand = sum(order_counter.values())
        
        if algorithm == "tracking":
            # Use user's smart tracking algorithm
            logger.info(f"🎯 USER TRACKING: Starting with demand={total_demand}, widths={list(order_counter.keys())}")
            return self._find_optimal_solution_with_tracking(order_counter)
            
        else:  # algorithm == "ilp" (default) - now uses OR-Tools
            # Use OR-Tools optimization (3.1x faster than PuLP)
            demand = {float(width): int(qty) for width, qty in order_counter.items() if qty > 0}
            logger.info(f"🎯 OR-TOOLS OPTIMIZATION: Starting with demand={total_demand}, widths={list(demand.keys())}")
            
            # Use OR-Tools with progressive trim caps for better solutions
            result = self._solve_cutting_with_ilp(demand, trim_cap=6.0)  # Start with 6" trim cap
            
            # If 6" fails, try 8" then 10" for better solutions
            if not result or result['status'] not in ['Optimal', 'Feasible']:
                logger.info("🔄 OR-Tools: Trying higher trim cap (8\") for feasible solution")
                result = self._solve_cutting_with_ilp(demand, trim_cap=8.0)
                
            if not result or result['status'] not in ['Optimal', 'Feasible']:
                logger.info("🔄 OR-Tools: Trying higher trim cap (10\") for feasible solution")  
                result = self._solve_cutting_with_ilp(demand, trim_cap=10.0)
            
            if result and result['status'] in ['Optimal', 'Feasible']:
                logger.info(f"✅ OR-TOOLS OPTIMIZATION: Found solution with {result['summary']['total_sets']} sets, avg trim={result['summary']['avg_trim']:.1f}\"")
                return self._convert_ilp_result_to_internal_format(result, order_counter)
            else:
                logger.warning(f"❌ OR-TOOLS OPTIMIZATION: No solution found - {result.get('message', 'Unknown error') if result else 'OR-Tools failed'}")
                return None

    def _generate_efficient_patterns(self, widths: List[float]) -> List[Tuple[Tuple[float, ...], float]]:
        """
        Generate efficient pattern candidates for optimization.
        Focus on patterns with minimal waste (≤6" trim for maximum efficiency).
        """
        from itertools import product
        
        efficient_patterns = []
        
        # Generate patterns with 2-5 pieces, prioritizing low waste
        for num_pieces in range(2, min(MAX_ROLLS_PER_JUMBO + 1, 6)):
            for pattern in product(widths, repeat=num_pieces):
                total_width = sum(pattern)
                trim = self.jumbo_roll_width - total_width
                
                # Only keep patterns with ≤6" waste for maximum efficiency
                if 0 <= trim <= 18:
                    pattern_tuple = tuple(sorted(pattern))
                    if pattern_tuple not in [p[0] for p in efficient_patterns]:
                        efficient_patterns.append((pattern_tuple, trim))
        
        # If no ultra-efficient patterns found, expand to ≤10" trim
        if len(efficient_patterns) < 5:
            for num_pieces in range(2, min(MAX_ROLLS_PER_JUMBO + 1, 6)):
                for pattern in product(widths, repeat=num_pieces):
                    total_width = sum(pattern)
                    trim = self.jumbo_roll_width - total_width
                    
                    if 6 < trim <= 10:
                        pattern_tuple = tuple(sorted(pattern))
                        if pattern_tuple not in [p[0] for p in efficient_patterns]:
                            efficient_patterns.append((pattern_tuple, trim))
        
        # Sort by efficiency (lower trim first, more pieces second)
        efficient_patterns.sort(key=lambda x: (x[1], -len(x[0])))
        
        
        return efficient_patterns

    def _solve_optimal_pattern_combination(self, patterns: List[Tuple[Tuple[float, ...], float]], order_counter: Counter):
        """
        Solve for optimal pattern combination using comprehensive search.
        Minimizes total waste by finding the best mix of efficient patterns.
        """
        best_solution = None
        best_total_waste = float('inf')
        
        total_demand = sum(order_counter.values())
        max_patterns_per_type = min(total_demand, 60)  # Allow more patterns for better solutions
        
        
        # Use more patterns for comprehensive search  
        search_patterns = patterns[:min(15, len(patterns))]  # Expand search space
        
        # Try combinations of 1-4 pattern types for optimal mix
        from itertools import combinations
        
        logger.info(f"🔍 DIRECT OPTIMIZATION DEBUG: Trying combinations of {len(search_patterns)} patterns")
        combinations_tried = 0
        solutions_found = 0
        
        for num_pattern_types in range(1, min(5, len(search_patterns) + 1)):
            for pattern_combo in combinations(search_patterns, num_pattern_types):
                combinations_tried += 1
                # Use mathematical optimization to find best counts
                solution = self._find_optimal_counts(pattern_combo, order_counter, max_patterns_per_type)
                
                if solution:
                    solutions_found += 1
                    patterns_used, remaining_demand, total_waste = solution
                    
                    # Check if this is better (lower total waste)
                    if total_waste < best_total_waste:
                        # Verify satisfaction rate is acceptable
                        remaining_count = sum(remaining_demand.values())
                        satisfaction_rate = 1 - (remaining_count / total_demand)
                        
                        if satisfaction_rate >= 0.85:  # At least 85% satisfied
                            best_total_waste = total_waste
                            best_solution = solution
        
        logger.info(f"🔍 DIRECT OPTIMIZATION DEBUG: Tried {combinations_tried} combinations, found {solutions_found} valid solutions")
        logger.info(f"🔍 DIRECT OPTIMIZATION DEBUG: Best solution = {best_solution is not None}")
        
        return best_solution
    
    def _find_optimal_counts(self, pattern_combo, order_counter, max_per_pattern):
        """
        Find optimal application counts using intelligent optimization instead of brute-force search.
        OPTIMIZED: Reduces from 2000 random attempts to smart mathematical approach.
        """
        total_demand = sum(order_counter.values())
        logger.debug(f"🚀 OPTIMIZED COUNT: Finding counts for {len(pattern_combo)} patterns, demand={total_demand}")
        
        # Strategy 1: Mathematical estimation based on demand
        best_solution = self._mathematical_count_estimation(pattern_combo, order_counter, total_demand)
        
        if best_solution:
            patterns_used, remaining_demand, total_waste = best_solution
            satisfaction = 1 - (sum(remaining_demand.values()) / total_demand)
            
            # If mathematical solution is good enough, use it
            if satisfaction >= 0.85:
                logger.debug(f"✅ MATH SOLUTION: {total_waste:.1f}\" waste, {satisfaction*100:.1f}% satisfaction")
                return best_solution
        
        # Strategy 2: Smart sampling with early termination (max 200 attempts instead of 2000)
        return self._smart_sampling_optimization(pattern_combo, order_counter, total_demand, max_attempts=200)
    
    def _mathematical_count_estimation(self, pattern_combo, order_counter, total_demand):
        """
        Use mathematical estimation to find good pattern counts without random search.
        """
        try:
            # Create a simple linear programming approach
            pattern_contributions = []
            
            for pattern, trim in pattern_combo:
                contribution = {}
                for width in pattern:
                    contribution[width] = contribution.get(width, 0) + 1
                pattern_contributions.append((contribution, trim, len(pattern)))
            
            # Estimate counts based on demand proportions
            estimated_counts = []
            for i, (contribution, trim, pieces) in enumerate(pattern_contributions):
                # Calculate how much this pattern could help with remaining demand
                usefulness = 0
                for width, count in contribution.items():
                    if width in order_counter:
                        usefulness += (order_counter[width] / total_demand) * count
                
                # Estimate count based on usefulness and efficiency
                efficiency = (118 - trim) / 118  # Material efficiency
                base_count = max(1, int(total_demand * usefulness * efficiency / pieces))
                
                # Cap the count reasonably
                max_reasonable = min(max_per_pattern or 30, total_demand // pieces + 5, 30)
                estimated_counts.append(min(base_count, max_reasonable))
            
            # Evaluate the mathematical estimate
            result = self._evaluate_pattern_combination(pattern_combo, estimated_counts, order_counter)
            if result:
                return (result[0], result[1], result[2])  # patterns_used, remaining_demand, total_waste
                
        except Exception as e:
            logger.debug(f"Math estimation failed: {e}")
        
        return None
    
    def _smart_sampling_optimization(self, pattern_combo, order_counter, total_demand, max_attempts=200):
        """
        Optimized sampling with intelligent search space reduction and early termination.
        """
        best_solution = None
        best_waste = float('inf')
        
        # Calculate smart ranges based on demand analysis
        pattern_ranges = []
        for pattern, trim in pattern_combo:
            pattern_pieces = len(pattern)
            
            # Smart range calculation based on pattern utility
            pattern_demand_coverage = sum(order_counter.get(width, 0) for width in pattern)
            utility_ratio = pattern_demand_coverage / total_demand if total_demand > 0 else 0
            
            # More useful patterns get higher maximum counts
            base_max = max(1, int(total_demand * utility_ratio / pattern_pieces))
            max_reasonable = min(base_max + 5, max_per_pattern or 20, 25)  # Reduced from 50
            min_reasonable = max(1, base_max // 3) if base_max > 3 else 1
            
            pattern_ranges.append((min_reasonable, max_reasonable))
        
        # Smart sampling strategies
        strategies = [
            self._demand_proportional_strategy,
            self._efficiency_focused_strategy, 
            self._balanced_strategy
        ]
        
        attempts_per_strategy = max_attempts // len(strategies)
        valid_attempts = 0
        
        for strategy_idx, strategy in enumerate(strategies):
            strategy_attempts = 0
            consecutive_failures = 0
            
            for attempt in range(attempts_per_strategy):
                strategy_attempts += 1
                
                # Generate counts using current strategy
                counts = strategy(pattern_combo, pattern_ranges, order_counter, total_demand, attempt)
                
                if not counts or sum(counts) == 0:
                    consecutive_failures += 1
                    if consecutive_failures > 10:  # Early termination for poor strategies
                        break
                    continue
                
                consecutive_failures = 0
                
                # Evaluate solution
                result = self._evaluate_pattern_combination(pattern_combo, counts, order_counter)
                if result:
                    valid_attempts += 1
                    patterns_used, remaining_demand, total_waste, over_satisfaction = result
                    
                    # Optimized scoring
                    total_remaining = sum(remaining_demand.values())
                    satisfaction_rate = 1 - (total_remaining / total_demand)
                    
                    if satisfaction_rate < 0.85:
                        score = total_waste + (1 - satisfaction_rate) * 500  # Reduced penalty
                    else:
                        score = total_waste + over_satisfaction * 2  # Reduced penalty
                    
                    if score < best_waste:
                        best_waste = score
                        best_solution = (patterns_used, remaining_demand, total_waste)
                        
                        # Early termination if excellent solution found
                        if satisfaction_rate >= 0.95 and total_waste < total_demand * 0.1:
                            logger.debug(f"🎯 EXCELLENT SOLUTION FOUND: {satisfaction_rate*100:.1f}% satisfaction, {total_waste:.1f}\" waste")
                            break
            
            # Early termination if good solution found
            if best_solution:
                _, remaining, waste = best_solution
                satisfaction = 1 - (sum(remaining.values()) / total_demand)
                if satisfaction >= 0.9:
                    break
        
        logger.debug(f"🚀 OPTIMIZED: {valid_attempts} valid attempts out of {max_attempts}, best solution = {best_solution is not None}")
        return best_solution
    
    def _demand_proportional_strategy(self, pattern_combo, pattern_ranges, order_counter, total_demand, attempt):
        """Strategy: Allocate counts proportional to how much each pattern satisfies demand."""
        import random
        counts = []
        
        for i, ((pattern, trim), (min_count, max_count)) in enumerate(zip(pattern_combo, pattern_ranges)):
            # Calculate pattern's contribution to demand
            pattern_contribution = sum(order_counter.get(width, 0) for width in pattern)
            contribution_ratio = pattern_contribution / total_demand if total_demand > 0 else 0
            
            # Scale count based on contribution with some randomness
            base_count = max(min_count, int(contribution_ratio * total_demand / len(pattern)))
            random_factor = random.uniform(0.8, 1.2)  # ±20% variation
            count = min(max_count, max(min_count, int(base_count * random_factor)))
            counts.append(count)
        
        return counts
    
    def _efficiency_focused_strategy(self, pattern_combo, pattern_ranges, order_counter, total_demand, attempt):
        """Strategy: Favor patterns with better material efficiency (lower trim)."""
        import random
        counts = []
        
        # Calculate efficiency scores
        efficiencies = [(118 - trim) / 118 for _, trim in pattern_combo]
        max_efficiency = max(efficiencies)
        
        for i, ((pattern, trim), (min_count, max_count)) in enumerate(zip(pattern_combo, pattern_ranges)):
            # Higher counts for more efficient patterns
            efficiency_bonus = efficiencies[i] / max_efficiency if max_efficiency > 0 else 1
            base_count = int((min_count + max_count) / 2 * efficiency_bonus)
            
            # Add controlled randomness
            random_factor = random.uniform(0.9, 1.1)  # ±10% variation
            count = min(max_count, max(min_count, int(base_count * random_factor)))
            counts.append(count)
        
        return counts
    
    def _balanced_strategy(self, pattern_combo, pattern_ranges, order_counter, total_demand, attempt):
        """Strategy: Balance between demand satisfaction and efficiency."""
        import random
        counts = []
        
        for i, ((pattern, trim), (min_count, max_count)) in enumerate(zip(pattern_combo, pattern_ranges)):
            # Balanced approach: 60% demand-based, 40% efficiency-based
            pattern_contribution = sum(order_counter.get(width, 0) for width in pattern)
            contribution_ratio = pattern_contribution / total_demand if total_demand > 0 else 0
            efficiency = (118 - trim) / 118
            
            demand_component = contribution_ratio * total_demand / len(pattern)
            efficiency_component = efficiency * (min_count + max_count) / 2
            
            balanced_count = int(0.6 * demand_component + 0.4 * efficiency_component)
            
            # Add randomness and apply bounds
            random_factor = random.uniform(0.85, 1.15)  # ±15% variation  
            count = min(max_count, max(min_count, int(balanced_count * random_factor)))
            counts.append(count)
        
        return counts


    def _evaluate_pattern_combination(self, pattern_combo, counts, order_counter):
        """Evaluate a specific pattern combination with given counts."""
        patterns_used = []
        demand_satisfied = {}
        total_waste = 0
        
        # Initialize demand tracking
        for width in order_counter.keys():
            demand_satisfied[width] = 0
        
        # Apply patterns
        for (pattern, trim), count in zip(pattern_combo, counts):
            for _ in range(count):
                patterns_used.append((pattern, trim))
                total_waste += trim
                
                # Track demand satisfaction
                for width in pattern:
                    demand_satisfied[width] = demand_satisfied.get(width, 0) + 1
        
        # Calculate remaining demand and over-satisfaction
        remaining_demand = {}
        over_satisfaction = 0
        
        for width, needed in order_counter.items():
            satisfied = demand_satisfied.get(width, 0)
            remaining = max(0, needed - satisfied)
            excess = max(0, satisfied - needed)
            
            if remaining > 0:
                remaining_demand[width] = remaining
            over_satisfaction += excess
        
        return patterns_used, remaining_demand, total_waste, over_satisfaction




    def optimize_with_new_algorithm(
        self,
        order_requirements: List[Dict],
        pending_orders: List[Dict] = None,
        available_inventory: List[Dict] = None,
        interactive: bool = False,
        algorithm: str = "ilp"
    ) -> Dict:
        """
        NEW FLOW: 3-input/4-output optimization algorithm.
        Groups orders by complete specification (GSM + Shade + BF) to ensure
        different paper types are not mixed in the same jumbo roll.
        
        Args:
            order_requirements: List of new order dicts with width, quantity, etc.
            pending_orders: List of pending orders from previous cycles
            available_inventory: List of available inventory rolls for reuse
            interactive: Whether to prompt user for high trim decisions
            
        Returns:
            Dict with 3 outputs:
            - cut_rolls_generated: Rolls that can be fulfilled
            - jumbo_rolls_needed: Number of jumbo rolls to procure
            - pending_orders: Orders that cannot be fulfilled (>20" trim)
        """
        logger.info(f"🔧 OPTIMIZER: Starting optimize_with_new_algorithm")
        logger.info(f"📦 INPUT: Order Requirements: {len(order_requirements)} items")
        logger.info(f"⏳ INPUT: Pending Orders: {len(pending_orders) if pending_orders else 0} items")
        logger.info(f"📋 INPUT: Available Inventory: {len(available_inventory) if available_inventory else 0} items")
        
        # Initialize default values for optional inputs
        if pending_orders is None:
            pending_orders = []
            logger.warning("⚠️  OPTIMIZER: pending_orders was None, initialized to empty list")
        if available_inventory is None:
            available_inventory = []
            logger.warning("⚠️  OPTIMIZER: available_inventory was None, initialized to empty list")
        
        # Log detailed input analysis
        logger.debug(f"📋 INPUT DETAILS: Order Requirements: {order_requirements}")
        logger.debug(f"📋 INPUT DETAILS: Pending Orders: {pending_orders}")
        logger.debug(f"📋 INPUT DETAILS: Available Inventory: {available_inventory}")
        
        # Combine all requirements but preserve source information
        # Tag each requirement with its source (regular order vs pending order)
        all_requirements = []
        
        # Add regular orders with source tag
        for req in order_requirements:
            req_with_source = req.copy()
            req_with_source['source_type'] = 'regular_order'
            req_with_source['source_order_id'] = req.get('order_id')
            all_requirements.append(req_with_source)
        
        # Add pending orders with source tag
        logger.info(f"🔍 OPTIMIZER DEBUG: Processing {len(pending_orders)} pending orders for source tracking")
        for i, req in enumerate(pending_orders):
            logger.info(f"🔍 OPTIMIZER DEBUG: Pending order {i+1}: {req}")
            logger.info(f"🔍 OPTIMIZER DEBUG: Available keys in pending order: {list(req.keys())}")
            req_with_source = req.copy()
            req_with_source['source_type'] = 'pending_order'
            req_with_source['source_order_id'] = req.get('original_order_id')  # Pending orders use original_order_id
            
            # TRY MULTIPLE POSSIBLE FIELD NAMES for pending ID
            source_pending_id = req.get('pending_id') or req.get('id') or req.get('frontend_id')
            req_with_source['source_pending_id'] = source_pending_id
            logger.info(f"🔍 OPTIMIZER DEBUG: Enhanced pending order {i+1}: source_type={req_with_source['source_type']}, source_pending_id={req_with_source['source_pending_id']}")
            logger.info(f"🔍 OPTIMIZER DEBUG: Used field for pending_id: pending_id={req.get('pending_id')}, id={req.get('id')}, frontend_id={req.get('frontend_id')}")
            all_requirements.append(req_with_source)
        
        logger.info(f"🔄 OPTIMIZER: Combined all_requirements: {len(all_requirements)} total items")
        logger.debug(f"📋 COMBINED REQUIREMENTS: {all_requirements}")
        
        # Group all requirements by complete specification (GSM + Shade + BF)
        # This ensures that different paper types are NEVER mixed in the same jumbo roll
        # Each jumbo roll will contain only 3 sets of 118" rolls with identical paper specs
        spec_groups = {}
        logger.info(f"🔍 OPTIMIZER: Grouping requirements by specification...")
        
        for i, req in enumerate(all_requirements):
            logger.debug(f"  📝 Processing requirement {i+1}: {req}")
            # Create unique key for paper specification - CRITICAL for avoiding paper mixing
            spec_key = (req['gsm'], req['shade'], req['bf'])
            logger.debug(f"  🔑 Spec key: {spec_key}")
            
            if spec_key not in spec_groups:
                spec_groups[spec_key] = {
                    'orders': {},
                    'inventory': [],
                    'spec': {'gsm': req['gsm'], 'shade': req['shade'], 'bf': req['bf']},
                    'source_tracking': {}  # NEW: Track which widths came from which sources
                }
                logger.info(f"  ✨ Created new spec group for {spec_key}")
            
            # Add width and quantity to this specification group
            width = float(req['width'])
            if width in spec_groups[spec_key]['orders']:
                old_qty = spec_groups[spec_key]['orders'][width]
                spec_groups[spec_key]['orders'][width] += req['quantity']
                logger.debug(f"  ➕ Added {req['quantity']} to existing width {width}\" (was {old_qty}, now {spec_groups[spec_key]['orders'][width]})")
            else:
                spec_groups[spec_key]['orders'][width] = req['quantity']
                logger.debug(f"  🆕 Added new width {width}\" with quantity {req['quantity']}")
            
            # NEW: Track source information for this width
            if width not in spec_groups[spec_key]['source_tracking']:
                spec_groups[spec_key]['source_tracking'][width] = []
            source_entry = {
                'source_type': req['source_type'],
                'source_order_id': req.get('source_order_id'),
                'source_pending_id': req.get('source_pending_id'),
                'quantity': req['quantity']
            }
            spec_groups[spec_key]['source_tracking'][width].append(source_entry)
            logger.info(f"  📋 SOURCE TRACKING: width={width}\", type={req['source_type']}, pending_id={req.get('source_pending_id')}")
        
        logger.info(f"📊 OPTIMIZER: Final spec_groups structure:")
        for spec_key, group_data in spec_groups.items():
            logger.info(f"  📋 Spec {spec_key}: {group_data['orders']}")
        
        # Add available inventory to matching specification groups
        print(f"\n[DEBUG] Adding available inventory to spec groups...")
        for i, inv_item in enumerate(available_inventory):
            print(f"  Processing inventory item {i+1}: {inv_item}")
            inv_spec_key = (inv_item['gsm'], inv_item['shade'], inv_item['bf'])
            print(f"  Inventory spec key: {inv_spec_key}")
            
            if inv_spec_key in spec_groups:
                spec_groups[inv_spec_key]['inventory'].append(inv_item)
                print(f"  ✅ Added inventory item to matching spec group {inv_spec_key}")
            else:
                print(f"  ❌ No matching spec group found for inventory item {inv_spec_key}")
        
        print(f"\n[DEBUG] Spec groups after adding inventory:")
        for spec_key, group_data in spec_groups.items():
            print(f"  Spec {spec_key}: {len(group_data['inventory'])} inventory items")
        
        # Process each specification group separately
        cut_rolls_generated = []
        new_pending_orders = []
        jumbo_rolls_needed = 0
        all_high_trims = []
        
        # NEW: Initialize assignment tracker for proper source distribution
        assignment_tracker = {}
        
        for spec_key, group_data in spec_groups.items():
            orders = group_data['orders']
            inventory = group_data['inventory']
            spec = group_data['spec']
            
            logger.info(f"🔧 OPTIMIZER: Processing Paper Spec: GSM={spec['gsm']}, Shade={spec['shade']}, BF={spec['bf']}")
            logger.info(f"   📦 Orders to fulfill: {orders}")
            logger.info(f"   📋 Available Inventory: {len(inventory)} items")
            for inv_idx, inv_item in enumerate(inventory):
                logger.debug(f"     📦 Inventory {inv_idx+1}: width={inv_item.get('width', 'N/A')}\", id={inv_item.get('id', 'N/A')}")
            
            total_order_quantity = sum(orders.values())
            logger.info(f"   📊 Total order quantity for this spec: {total_order_quantity} rolls")
            
            # First, try to fulfill orders using available inventory
            orders_copy = orders.copy()
            inventory_used = []
            
            logger.info(f"   🔄 OPTIMIZER: Starting inventory fulfillment phase...")
            logger.debug(f"   📦 Orders copy before inventory: {orders_copy}")
            
            for inv_idx, inv_item in enumerate(inventory):
                inv_width = float(inv_item['width'])
                print(f"     Checking inventory item {inv_idx+1}: width={inv_width}\"")
                
                if inv_width in orders_copy and orders_copy[inv_width] > 0:
                    # Use this inventory item
                    print(f" MATCH! Using inventory for {inv_width}\" (had {orders_copy[inv_width]} orders)")
                    cut_rolls_generated.append({
                        'width': inv_width,
                        'quantity': 1,
                        'gsm': spec['gsm'],
                        'bf': spec['bf'],
                        'shade': spec['shade'],
                        'source': 'inventory',
                        'inventory_id': inv_item.get('id')
                    })
                    orders_copy[inv_width] -= 1
                    if orders_copy[inv_width] <= 0:
                        print(f"     📝 Fully satisfied {inv_width}\" orders, removing from list")
                        del orders_copy[inv_width]
                    else:
                        print(f"     📝 Still need {orders_copy[inv_width]} more {inv_width}\" rolls")
                    inventory_used.append(inv_item)
                else:
                    if inv_width not in orders_copy:
                        print(f"  No orders for {inv_width}\" width")
                    else:
                        print(f"  Already fulfilled all {inv_width}\" orders")
            
            print(f"   [ORDERS] Remaining after inventory: {orders_copy}")
            print(f"   [INVENTORY] Items used: {len(inventory_used)}")
            
            # Remove used inventory from available list
            remaining_inventory = [inv for inv in inventory if inv not in inventory_used]
            
            # Run the matching algorithm for remaining orders
            individual_118_rolls_needed = 0
            if orders_copy:
                logger.info(f"   🔪 OPTIMIZER: Running cutting algorithm for remaining orders: {orders_copy}")
                used, pending, high_trims = self.match_combos(orders_copy, interactive, algorithm)
                logger.info(f"   📊 CUTTING RESULTS: {len(used)} patterns used, {len(list(pending.keys()))} pending widths")
                
                # Debug: Show what went to pending and why
                if pending:
                    logger.warning(f"   🔍 PENDING DEBUG: Items that couldn't be optimized:")
                    for width, qty in pending.items():
                        logger.warning(f"     • {width}\" x{qty} remaining - checking why this couldn't be optimized...")
                        
                        # Show some combinations that could work with this width
                        test_combos = []
                        for other_width in orders_copy.keys():
                            if other_width != width:
                                # Test 2-piece combo
                                combo_2 = width + other_width
                                trim_2 = 118 - combo_2
                                if 0 <= trim_2 <= 20:
                                    test_combos.append(f"({width}, {other_width}) = {combo_2}\", trim={trim_2}\"")
                                
                                # Test 3-piece combo
                                for third_width in orders_copy.keys():
                                    combo_3 = width + other_width + third_width
                                    trim_3 = 118 - combo_3
                                    if 0 <= trim_3 <= 20:
                                        test_combos.append(f"({width}, {other_width}, {third_width}) = {combo_3}\", trim={trim_3}\"")
                        
                        if test_combos:
                            logger.warning(f"       → Potential valid combos found:")
                            for combo in test_combos[:3]:  # Show first 3 potential combos
                                logger.warning(f"         {combo}")
                        else:
                            logger.warning(f"       → No valid combinations found within 0-20\" trim range")
                
                # Process successful cutting patterns (each pattern = 1 individual 118" roll)
                for pattern_idx, (combo, trim) in enumerate(used):
                    individual_118_rolls_needed += 1
                    logger.info(f"     ✂️ Pattern {pattern_idx+1}: {combo} → trim={trim}\" (Roll #{individual_118_rolls_needed})")
                    
                    # Add cut rolls from this pattern
                    for width in combo:
                        # NEW: Determine source information for this width with proper distribution
                        source_info = self._get_source_info_for_width(width, spec_groups[spec_key]['source_tracking'], assignment_tracker)
                        
                        cut_roll = {
                            'width': width,
                            'quantity': 1,
                            'gsm': spec['gsm'],
                            'bf': spec['bf'],
                            'shade': spec['shade'],
                            'source': 'cutting',
                            'individual_roll_number': individual_118_rolls_needed,
                            'trim_left': trim,
                            # NEW: Add source tracking fields
                            'source_type': source_info.get('source_type', 'regular_order'),
                            'source_order_id': source_info.get('source_order_id'),
                            'source_pending_id': source_info.get('source_pending_id'),
                            'order_id': source_info.get('source_order_id')  # Keep existing field for backward compatibility
                        }
                        cut_rolls_generated.append(cut_roll)
            else:
                logger.info(f"   ✅ OPTIMIZER: All orders fulfilled from inventory, no cutting needed")
            
            # JUMBO ROLL CALCULATION: Show ALL rolls to user, let them decide
            # Don't auto-move anything to pending - USER CHOICE!
            logger.info(f"   📊 JUMBO ROLL CALCULATION for spec {spec_key}:")
            logger.info(f"     🎯 Individual 118\" rolls generated: {individual_118_rolls_needed}")
            logger.info(f"     📦 Complete jumbo rolls possible: {individual_118_rolls_needed // 3}")
            if individual_118_rolls_needed % 3 > 0:
                logger.info(f"     ℹ️  Extra 118\" rolls available: {individual_118_rolls_needed % 3} (user can choose)")
            logger.info(f"     👤 USER DECIDES: All {individual_118_rolls_needed} rolls shown to user for selection")
            
            # Note: We don't auto-calculate jumbo_rolls_needed here anymore
            # It will be calculated based on user's actual selection in frontend
            
            # Add orders that couldn't be fulfilled to pending
            # CRITICAL: Only create new pending orders from unfulfilled REGULAR orders
            # Do NOT create duplicates of existing pending orders
            if orders_copy:
                logger.info(f"🔍 PENDING CONVERSION DEBUG: pending dict = {dict(pending)}")
                for width, qty in pending.items():
                    # Check source tracking to see if this unfulfilled order came from regular orders
                    source_tracking = spec_groups[spec_key]['source_tracking'].get(width, [])
                    regular_order_qty = 0
                    
                    # Count how many of these unfulfilled orders came from regular orders (not existing pending orders)
                    for source in source_tracking:
                        if source.get('source_type') == 'regular_order':
                            regular_order_qty += source.get('quantity', 0)
                    
                    # Only create pending orders for the portion that came from regular orders
                    pending_qty_to_create = min(qty, regular_order_qty)
                    
                    if pending_qty_to_create > 0:
                        logger.info(f"🔍 Creating pending order: {width}\" x{pending_qty_to_create} (from regular orders only)")
                        
                        # Find source order for this pending requirement
                        source_order_info = self._find_source_order_for_pending(width, spec_key, spec_groups)
                        
                        new_pending_orders.append({
                            'width': width,
                            'quantity': pending_qty_to_create,
                            'gsm': spec['gsm'],
                            'bf': spec['bf'],
                            'shade': spec['shade'],
                            'reason': 'waste_too_high',
                            'source_order_id': source_order_info.get('order_id'),
                            'source_type': 'regular_order'
                        })
                    else:
                        logger.info(f"🔍 SKIPPING pending order creation: {width}\" x{qty} (all from existing pending orders - no duplication)")
                        
                    # Log the breakdown for debugging
                    existing_pending_qty = qty - pending_qty_to_create
                    if existing_pending_qty > 0:
                        logger.info(f"     📋 Breakdown: {pending_qty_to_create} from regular orders, {existing_pending_qty} from existing pending orders")
                
                # Track high trim approvals
                for combo, trim in high_trims:
                    all_high_trims.append({
                        'combo': combo,
                        'trim': trim,
                        'waste_percentage': round((trim / self.jumbo_roll_width) * 100, 2),
                        'paper_spec': spec
                    })
        
        # Calculate summary statistics
        total_cut_rolls = len(cut_rolls_generated)
        total_pending = sum(order['quantity'] for order in new_pending_orders)
        total_individual_118_rolls = len([roll for roll in cut_rolls_generated if roll['source'] == 'cutting'])
        
        # Show total rolls available - user will decide how many to use
        # Don't auto-calculate jumbo_rolls_needed, let frontend calculate based on selection
        jumbo_rolls_needed = 0  # User choice - will be calculated when they select rolls
        
        # Log final results
        logger.info(f"🎯 OPTIMIZER RESULTS:")
        logger.info(f"   📦 Total cut rolls generated: {total_cut_rolls}")
        logger.info(f"   🎯 Total individual 118\" rolls: {total_individual_118_rolls}")
        logger.info(f"   👤 USER CHOICE: {total_individual_118_rolls} individual 118\" rolls available for selection")
        logger.info(f"   📦 MAX JUMBOS POSSIBLE: {total_individual_118_rolls} jumbo rolls (1-3 rolls each, flexible)")
        logger.info(f"   ⏳ Total pending orders: {len(new_pending_orders)}")
        logger.info(f"   📊 Total pending quantity: {total_pending}")
        logger.info(f"   🔧 Specification groups processed: {len(spec_groups)}")
        logger.info(f"   ⚠️  High trim patterns: {len(all_high_trims)}")
        
        # Log detailed cut rolls
        logger.info(f"📋 DETAILED CUT ROLLS:")
        for i, roll in enumerate(cut_rolls_generated, 1):
            logger.info(f"   Roll {i}: {roll['width']}\" - GSM:{roll['gsm']}, BF:{roll['bf']}, Shade:{roll['shade']}, Source:{roll['source']}")
        
        # Log pending orders if any (consolidated to avoid duplicates)
        if new_pending_orders:
            logger.warning(f"⏳ PENDING ORDERS (>20\" trim):")
            logger.info(f"🔍 RAW PENDING ORDERS COUNT: {len(new_pending_orders)}")
            for i, pending in enumerate(new_pending_orders):
                logger.info(f"🔍 Raw pending {i+1}: {pending['width']}\" x{pending['quantity']}")
            
            # Consolidate pending orders by width, GSM, shade, BF to avoid duplicate logging
            consolidated_pending = {}
            for pending in new_pending_orders:
                key = (pending['width'], pending['gsm'], pending['bf'], pending['shade'], pending.get('reason', 'high_trim'))
                if key in consolidated_pending:
                    logger.info(f"🔍 CONSOLIDATING: {pending['width']}\" x{pending['quantity']} added to existing x{consolidated_pending[key]['quantity']}")
                    consolidated_pending[key]['quantity'] += pending['quantity']
                else:
                    logger.info(f"🔍 NEW PENDING: {pending['width']}\" x{pending['quantity']}")
                    consolidated_pending[key] = {
                        'width': pending['width'],
                        'quantity': pending['quantity'],
                        'gsm': pending['gsm'],
                        'bf': pending['bf'],
                        'shade': pending['shade'],
                        'reason': pending.get('reason', 'high_trim')
                    }
            
            # Log consolidated pending orders (no more duplicates!)
            for i, (key, pending_info) in enumerate(consolidated_pending.items(), 1):
                logger.warning(f"   Pending {i}: {pending_info['width']}\" x{pending_info['quantity']} - GSM:{pending_info['gsm']}, Reason:{pending_info['reason']}")
                
            # CRITICAL: Check what we're actually returning vs logging
            logger.info(f"🔍 FINAL PENDING ORDERS TO RETURN: {len(new_pending_orders)} items")
            for i, pending in enumerate(new_pending_orders):
                logger.info(f"🔍 Final return {i+1}: {pending}")
        
        # NEW FLOW: Return 3 distinct outputs (removed waste inventory)
        result = {
            'cut_rolls_generated': cut_rolls_generated,
            'jumbo_rolls_needed': jumbo_rolls_needed,  # FLEXIBLE: 1 jumbo roll = 1-3 rolls (user choice)
            'pending_orders': new_pending_orders,
            'summary': {
                'total_cut_rolls': total_cut_rolls,
                'total_individual_118_rolls': total_individual_118_rolls,
                'total_jumbo_rolls_needed': jumbo_rolls_needed,  # FLEXIBLE: Each jumbo roll produces 1-3×118" rolls
                'total_pending_orders': len(new_pending_orders),
                'total_pending_quantity': total_pending,
                'specification_groups_processed': len(spec_groups),
                'high_trim_patterns': len(all_high_trims),
                'algorithm_note': 'OR-TOOLS ENHANCED: 1-20" trim accepted, >20" goes to pending, 3.1x faster optimization'
            },
            'high_trim_approved': all_high_trims
        }
        
        # Log detailed result structure before returning
        logger.info(f"🎯 OPTIMIZER COMPLETED: Returning result with {len(result)} main sections")
        logger.info(f"🔍 RESULT STRUCTURE: Keys = {list(result.keys())}")
        logger.info(f"🔍 cut_rolls_generated: Type = {type(result['cut_rolls_generated'])}, Length = {len(result['cut_rolls_generated'])}")
        logger.info(f"🔍 jumbo_rolls_needed: {result['jumbo_rolls_needed']}")
        logger.info(f"🔍 pending_orders: Length = {len(result['pending_orders'])}")
        
        if result['cut_rolls_generated']:
            logger.info(f"🔍 SAMPLE CUT ROLL: {result['cut_rolls_generated'][0]}")
        else:
            logger.warning("🚨 cut_rolls_generated is EMPTY!")
            
        return result

    def generate_optimized_plan(
        self,
        order_requirements: List[Dict],
        interactive: bool = False
    ) -> Dict:
        """
        Generate an optimized cutting plan using the new algorithm.
        This is now an alias for optimize_with_new_algorithm for backward compatibility.
        
        Args:
            order_requirements: List of order dicts with width, quantity, etc.
            interactive: Whether to prompt user for high trim decisions
            
        Returns:
            Optimized cutting plan with jumbo rolls used and pending orders
        """
        return self.optimize_with_new_algorithm(
            order_requirements=order_requirements,
            pending_orders=[],
            available_inventory=[],
            interactive=interactive
        )

    def _get_source_info_for_width(self, width: float, source_tracking: Dict, assignment_tracker: Dict) -> Dict:
        """
        Get source information for a specific width from the source tracking data.
        PROPERLY DISTRIBUTES cut rolls across pending orders based on their quantities.
        
        Args:
            width: Width of the cut roll being assigned
            source_tracking: Source tracking data for this specification group
            assignment_tracker: Tracks how many cut rolls have been assigned to each source
        """
        if width in source_tracking and source_tracking[width]:
            sources = source_tracking[width]
            
            # Initialize tracking key for this width if not exists
            width_key = f"width_{width}"
            if width_key not in assignment_tracker:
                assignment_tracker[width_key] = {}
            
            # PRIORITIZE pending orders - distribute them properly based on quantity
            pending_sources = [s for s in sources if s.get('source_type') == 'pending_order']
            if pending_sources:
                # Find a pending order that hasn't exceeded its quantity limit
                for source in pending_sources:
                    source_id = source.get('source_pending_id')
                    if source_id:
                        # Track assignments for this specific pending order
                        current_assignments = assignment_tracker[width_key].get(source_id, 0)
                        max_quantity = source.get('quantity', 1)
                        
                        # If this pending order can still accept more cut rolls, use it
                        if current_assignments < max_quantity:
                            assignment_tracker[width_key][source_id] = current_assignments + 1
                            logger.debug(f"🎯 SOURCE ASSIGNMENT: Assigned cut roll {current_assignments + 1}/{max_quantity} to pending order {str(source_id)[:8]}...")
                            return source
                        else:
                            logger.debug(f"🚫 SOURCE SKIP: Pending order {str(source_id)[:8]}... already at capacity ({current_assignments}/{max_quantity})")
            
            # If no pending orders available or all at capacity, use regular order sources
            regular_sources = [s for s in sources if s.get('source_type') == 'regular_order']
            if regular_sources:
                return regular_sources[0]
            
            # Fallback to first source if no other option
            return sources[0]
        
        # Default fallback for width with no source tracking
        return {
            'source_type': 'regular_order',
            'source_order_id': None,
            'source_pending_id': None
        }

    def _find_source_order_for_pending(self, width: float, spec_key: tuple, spec_groups: Dict) -> Dict:
        """
        Find the source order for a pending requirement to maintain client attribution.
        Uses the source tracking data to identify which order this pending requirement should be attributed to.
        """
        try:
            if spec_key in spec_groups and 'source_tracking' in spec_groups[spec_key]:
                source_tracking = spec_groups[spec_key]['source_tracking']
                
                if width in source_tracking and source_tracking[width]:
                    # Prioritize regular orders for pending order creation
                    regular_sources = [s for s in source_tracking[width] if s.get('source_type') == 'regular_order']
                    if regular_sources:
                        # Return the first regular order source (could be enhanced to distribute proportionally)
                        source = regular_sources[0]
                        logger.debug(f"🎯 PENDING SOURCE: Found source order {str(source.get('source_order_id', 'None')[:8])}... for {width}\" pending requirement")
                        return {
                            'order_id': source.get('source_order_id'),
                            'source_type': 'regular_order'
                        }
            
            logger.warning(f"⚠️ PENDING SOURCE: No source tracking found for {width}\" pending requirement")
            return {'order_id': None, 'source_type': 'regular_order'}
            
        except Exception as e:
            logger.error(f"❌ Error finding source order for pending: {e}")
            return {'order_id': None, 'source_type': 'regular_order'}

    def create_plan_from_orders(
        self,
        db: Session,
        order_ids: List[uuid.UUID],
        created_by_id: uuid.UUID,
        plan_name: Optional[str] = None,
        interactive: bool = False
    ) -> models.PlanMaster:
        """
        Create a cutting plan from order IDs using the master-based architecture.
        
        Args:
            db: Database session
            order_ids: List of order IDs to include in the plan
            created_by_id: ID of user creating the plan
            plan_name: Optional name for the plan
            interactive: Whether to prompt user for high trim decisions
            
        Returns:
            Created PlanMaster instance
        """
        # Fetch orders from database
        orders = []
        for order_id in order_ids:
            order = crud_operations.get_order(db, order_id)
            if not order:
                raise ValueError(f"Order with ID {order_id} not found")
            orders.append(order)
        
        # Convert orders to optimizer format
        order_requirements = []
        for order in orders:
            # Get paper specifications
            paper = crud_operations.get_paper(db, order.paper_id)
            if not paper:
                raise ValueError(f"Paper not found for order {order.id}")
            
            order_requirements.append({
                'width': float(order.width_inches),
                'quantity': order.quantity_rolls,
                'gsm': paper.gsm,
                'bf': paper.bf,
                'shade': paper.shade,
                'order_id': str(order.id)
            })
        
        # Generate optimization result
        optimization_result = self.optimize_with_new_algorithm(order_requirements, interactive)
        
        # Create plan in database
        plan_data = schemas.PlanMasterCreate(
            name=plan_name or f"Auto Plan {datetime.now().strftime('%Y%m%d_%H%M%S')}",
            cut_pattern=optimization_result['jumbo_rolls_used'],
            expected_waste_percentage=optimization_result['summary']['overall_waste_percentage'],
            created_by_id=created_by_id,
            order_ids=order_ids,
            inventory_ids=[]  # Will be populated when inventory is allocated
        )
        
        return crud_operations.create_plan(db, plan_data=plan_data)


# Example usage and testing
def test_optimizer():
    optimizer = CuttingOptimizer()
    
    # Test with mixed specifications to demonstrate proper grouping
    sample_orders = [
        # White paper, GSM 90, BF 18.0 - GROUP 1
        {"width": 29.5, "quantity": 2, "gsm": 90, "bf": 18.0, "shade": "white", "min_length": 1500},
        {"width": 32.5, "quantity": 3, "gsm": 90, "bf": 18.0, "shade": "white", "min_length": 1600},
        {"width": 38, "quantity": 2, "gsm": 90, "bf": 18.0, "shade": "white", "min_length": 1600},
        
        # Blue paper, GSM 90, BF 18.0 - GROUP 2 (different shade)
        {"width": 32.5, "quantity": 2, "gsm": 90, "bf": 18.0, "shade": "blue", "min_length": 1600},
        {"width": 46, "quantity": 1, "gsm": 90, "bf": 18.0, "shade": "blue", "min_length": 1600},
        
        # White paper, GSM 120, BF 18.0 - GROUP 3 (different GSM)
        {"width": 38, "quantity": 2, "gsm": 120, "bf": 18.0, "shade": "white", "min_length": 1600},
        {"width": 48, "quantity": 3, "gsm": 120, "bf": 18.0, "shade": "white", "min_length": 1600},
        
        # White paper, GSM 90, BF 20.0 - GROUP 4 (different BF)
        {"width": 51, "quantity": 2, "gsm": 90, "bf": 20.0, "shade": "white", "min_length": 1600},
        {"width": 54, "quantity": 2, "gsm": 90, "bf": 20.0, "shade": "white", "min_length": 1600}
    ]
    
    print("=== CUTTING OPTIMIZER RESULTS ===")
    result = optimizer.generate_optimized_plan(
        order_requirements=sample_orders,
        interactive=False  # Set to True for interactive mode
    )
    
    print("\n✅ Cut Rolls Generated:")
    for i, roll in enumerate(result.get('cut_rolls_generated', []), 1):
        print(f"Roll #{i}: {roll['width']}\" - GSM {roll['gsm']}, Shade: {roll['shade']}")
    
    if result.get('pending_orders'):
        print("\n⏳ Pending Orders:")
        for pending in result['pending_orders']:
            print(f"• {pending['quantity']} roll(s) of size {pending['width']}\" - {pending.get('reason', 'high trim')}")
    else:
        print("\n🎯 All orders fulfilled!")
    
    if result.get('high_trim_approved'):
        print("\n📋 High Trim Patterns (6–20\"): ")
        for high_trim in result['high_trim_approved']:
            print(f"• {high_trim['combo']} → Trim: {high_trim['trim']}\"")
    
    print(f"\n[SUMMARY]:")
    print(f"Total Cut Rolls: {result.get('summary', {}).get('total_cut_rolls', 0)}")
    print(f"Total Jumbo Rolls Needed: {result.get('jumbo_rolls_needed', 0)}")
    print(f"Total Pending Orders: {result.get('summary', {}).get('total_pending_orders', 0)}")
    print(f"Algorithm: {result.get('summary', {}).get('algorithm_note', 'Updated algorithm')}")
    
    return result

if __name__ == "__main__":
    test_optimizer()