"""
OR-Tools Enhanced Cutting Optimizer
===================================

Provides superior performance and constraint handling using Google OR-Tools CP-SAT solver.
This is an enhanced version of the existing cutting optimizer with significant performance improvements.
"""

import logging
from collections import Counter, defaultdict
from typing import List, Dict, Tuple, Optional, Any
import time
from dataclasses import dataclass

# OR-Tools imports
try:
    from ortools.sat.python import cp_model
    ORTOOLS_AVAILABLE = True
    logger = logging.getLogger(__name__)
    logger.info("📊 OR-Tools CP-SAT solver available - enhanced optimization enabled")
except ImportError:
    ORTOOLS_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning("⚠️ OR-Tools not available - falling back to original algorithm")

@dataclass
class CuttingPattern:
    """Enhanced pattern representation for OR-Tools optimization."""
    pieces: Tuple[float, ...]  # Widths in this pattern
    total_width: float         # Sum of all pieces
    trim: float               # Waste (jumbo_width - total_width)
    efficiency: float         # Material utilization (0-1)
    piece_count: int         # Number of pieces
    pattern_id: int          # Unique identifier
    
    def __post_init__(self):
        """Calculate efficiency after initialization."""
        if not hasattr(self, 'efficiency') or self.efficiency is None:
            jumbo_width = 118.0  # Default jumbo width
            self.efficiency = (jumbo_width - self.trim) / jumbo_width

class ORToolsOptimizer:
    """
    Enhanced cutting optimizer using Google OR-Tools CP-SAT solver.
    Provides significant performance improvements over PuLP-based approach.
    """
    
    def __init__(self, jumbo_width: float = 118.0, max_trim: float = 20.0):
        """
        Initialize OR-Tools optimizer.
        
        Args:
            jumbo_width: Width of jumbo rolls
            max_trim: Maximum acceptable trim waste
        """
        self.jumbo_width = jumbo_width
        self.max_trim = max_trim
        
        if not ORTOOLS_AVAILABLE:
            raise ImportError("OR-Tools is required but not available. Install with: pip install ortools")
    
    def generate_enhanced_patterns(self, 
                                  widths: List[float], 
                                  max_pieces: int = 4,
                                  trim_cap: float = 10.0) -> List[CuttingPattern]:
        """
        Generate cutting patterns using smarter enumeration approach.
        More efficient than brute-force pattern generation.
        
        Args:
            widths: Available widths to cut
            max_pieces: Maximum pieces per pattern
            trim_cap: Maximum trim to consider
            
        Returns:
            List of viable cutting patterns
        """
        patterns = []
        pattern_id = 0
        
        # Sort widths by descending size for better pattern generation
        sorted_widths = sorted(set(widths), reverse=True)
        
        logger.info(f"🔧 Generating patterns for {len(sorted_widths)} unique widths: {sorted_widths}")
        
        # Generate patterns with 1 to max_pieces
        for num_pieces in range(1, max_pieces + 1):
            patterns_for_size = self._generate_patterns_for_size(
                sorted_widths, num_pieces, trim_cap, pattern_id
            )
            patterns.extend(patterns_for_size)
            pattern_id += len(patterns_for_size)
        
        # Sort by efficiency (low trim first, then high piece count)
        patterns.sort(key=lambda p: (p.trim, -p.piece_count, -p.efficiency))
        
        logger.info(f"✅ Generated {len(patterns)} viable patterns (trim ≤ {trim_cap}\")")
        return patterns[:200]  # Limit to best 200 patterns for performance
    
    def _generate_patterns_for_size(self, 
                                   widths: List[float], 
                                   num_pieces: int, 
                                   trim_cap: float,
                                   start_id: int) -> List[CuttingPattern]:
        """Generate all valid patterns with exactly num_pieces."""
        from itertools import combinations_with_replacement
        
        patterns = []
        pattern_id = start_id
        
        for combination in combinations_with_replacement(widths, num_pieces):
            total_width = sum(combination)
            
            if total_width <= self.jumbo_width:
                trim = self.jumbo_width - total_width
                
                if trim <= trim_cap:
                    pattern = CuttingPattern(
                        pieces=tuple(sorted(combination, reverse=True)),
                        total_width=total_width,
                        trim=trim,
                        efficiency=(total_width / self.jumbo_width),
                        piece_count=num_pieces,
                        pattern_id=pattern_id
                    )
                    patterns.append(pattern)
                    pattern_id += 1
        
        return patterns
    
    def solve_cutting_optimization(self, 
                                  demand: Dict[float, int],
                                  time_limit_seconds: int = 30) -> Dict[str, Any]:
        """
        Solve cutting optimization using OR-Tools CP-SAT solver.
        
        Args:
            demand: Dictionary of {width: quantity_needed}
            time_limit_seconds: Maximum solving time
            
        Returns:
            Optimization result with patterns and statistics
        """
        if not demand or not any(demand.values()):
            return self._empty_solution()
        
        logger.info(f"🚀 OR-Tools optimization starting: {sum(demand.values())} pieces, {len(demand)} widths")
        start_time = time.time()
        
        # Generate patterns
        widths = list(demand.keys())
        patterns = self.generate_enhanced_patterns(widths)
        
        if not patterns:
            logger.warning("❌ No viable patterns generated")
            return self._infeasible_solution("No viable patterns found")
        
        # Create CP-SAT model
        model = cp_model.CpModel()
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = time_limit_seconds
        
        # Decision variables: how many times to use each pattern
        pattern_vars = {}
        for pattern in patterns:
            pattern_vars[pattern.pattern_id] = model.NewIntVar(
                0, sum(demand.values()), f"pattern_{pattern.pattern_id}"
            )
        
        # Constraints: satisfy demand exactly
        for width in demand:
            width_constraint = []
            for pattern in patterns:
                # Count how many pieces of this width the pattern produces
                width_count = pattern.pieces.count(width)
                if width_count > 0:
                    width_constraint.append(pattern_vars[pattern.pattern_id] * width_count)
            
            if width_constraint:
                model.Add(sum(width_constraint) == demand[width])
            else:
                logger.warning(f"⚠️ No patterns can produce width {width}")
                return self._infeasible_solution(f"No patterns for width {width}")
        
        # Objective: minimize total trim waste
        total_trim = []
        for pattern in patterns:
            total_trim.append(pattern_vars[pattern.pattern_id] * int(pattern.trim * 100))  # Scale for integer math
        
        model.Minimize(sum(total_trim))
        
        # Solve
        logger.info(f"🧮 Solving with {len(patterns)} patterns, {len(demand)} constraints...")
        status = solver.Solve(model)
        solve_time = time.time() - start_time
        
        # Process results
        if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
            return self._build_solution(patterns, pattern_vars, solver, demand, solve_time, status)
        else:
            logger.warning(f"❌ OR-Tools solver failed with status: {solver.StatusName(status)}")
            return self._infeasible_solution(f"Solver status: {solver.StatusName(status)}")
    
    def _build_solution(self, 
                       patterns: List[CuttingPattern],
                       pattern_vars: Dict,
                       solver: cp_model.CpSolver,
                       demand: Dict[float, int],
                       solve_time: float,
                       status) -> Dict[str, Any]:
        """Build the solution dictionary from OR-Tools results."""
        
        # Extract solution
        used_patterns = []
        total_trim = 0.0
        total_patterns = 0
        
        for pattern in patterns:
            pattern_count = solver.Value(pattern_vars[pattern.pattern_id])
            if pattern_count > 0:
                for _ in range(pattern_count):
                    used_patterns.append({
                        'pattern': pattern.pieces,
                        'used_width': pattern.total_width,
                        'trim': pattern.trim,
                        'efficiency': pattern.efficiency,
                        'pieces': pattern.piece_count
                    })
                    total_trim += pattern.trim
                    total_patterns += 1
        
        # Sort patterns for better sequencing
        used_patterns.sort(key=lambda x: (x['trim'], -x['used_width']))
        
        # Calculate production summary
        produced = Counter()
        for pattern_dict in used_patterns:
            for width in pattern_dict['pattern']:
                produced[width] += 1
        
        # Verify demand satisfaction
        demand_satisfied = all(produced[width] >= demand[width] for width in demand)
        
        avg_trim = total_trim / total_patterns if total_patterns > 0 else 0
        avg_efficiency = sum(p['efficiency'] for p in used_patterns) / len(used_patterns) if used_patterns else 0
        
        solution = {
            'status': 'Optimal' if status == cp_model.OPTIMAL else 'Feasible',
            'solver': 'OR-Tools CP-SAT',
            'solve_time': round(solve_time, 3),
            'patterns_used': len(used_patterns),
            'total_trim': round(total_trim, 2),
            'avg_trim': round(avg_trim, 2),
            'avg_efficiency': round(avg_efficiency * 100, 1),  # As percentage
            'demand_satisfied': demand_satisfied,
            'sets': used_patterns,
            'summary': {
                'total_sets': len(used_patterns),
                'total_trim': round(total_trim, 2),
                'avg_trim': round(avg_trim, 2),
                'avg_efficiency_percent': round(avg_efficiency * 100, 1)
            },
            'demand_vs_produced': {
                width: {
                    'demand': demand[width],
                    'produced': produced[width]
                }
                for width in demand
            }
        }
        
        logger.info(f"✅ OR-Tools solution: {len(used_patterns)} patterns, {avg_trim:.1f}\" avg trim, {solve_time:.2f}s")
        return solution
    
    def _empty_solution(self) -> Dict[str, Any]:
        """Return empty solution for no demand."""
        return {
            'status': 'Optimal',
            'solver': 'OR-Tools CP-SAT',
            'solve_time': 0.0,
            'patterns_used': 0,
            'total_trim': 0.0,
            'avg_trim': 0.0,
            'sets': [],
            'summary': {'total_sets': 0, 'total_trim': 0.0, 'avg_trim': 0.0},
            'demand_vs_produced': {}
        }
    
    def _infeasible_solution(self, reason: str) -> Dict[str, Any]:
        """Return infeasible solution with error message."""
        return {
            'status': 'Infeasible',
            'solver': 'OR-Tools CP-SAT',
            'solve_time': 0.0,
            'error_message': reason,
            'patterns_used': 0,
            'sets': [],
            'summary': {'total_sets': 0, 'total_trim': 0.0, 'avg_trim': 0.0}
        }

    def compare_with_pulp_solution(self, demand: Dict[float, int]) -> Dict[str, Any]:
        """
        Compare OR-Tools solution with PuLP solution for benchmarking.
        
        Args:
            demand: Demand dictionary
            
        Returns:
            Comparison results
        """
        logger.info("🆚 Running OR-Tools vs PuLP comparison...")
        
        # OR-Tools solution
        ortools_start = time.time()
        ortools_result = self.solve_cutting_optimization(demand)
        ortools_time = time.time() - ortools_start
        
        # Try to get PuLP solution (if available)
        pulp_result = None
        pulp_time = 0
        
        try:
            from .cutting_optimizer import CuttingOptimizer
            pulp_optimizer = CuttingOptimizer(self.jumbo_width)
            
            pulp_start = time.time()
            pulp_result = pulp_optimizer._solve_cutting_with_ilp(demand, trim_cap=10.0)
            pulp_time = time.time() - pulp_start
            
        except Exception as e:
            logger.warning(f"Could not run PuLP comparison: {e}")
        
        # Build comparison
        comparison = {
            'ortools': {
                'status': ortools_result.get('status', 'Unknown'),
                'solve_time': ortools_time,
                'patterns': ortools_result.get('patterns_used', 0),
                'total_trim': ortools_result.get('total_trim', 0),
                'avg_trim': ortools_result.get('avg_trim', 0)
            }
        }
        
        if pulp_result:
            comparison['pulp'] = {
                'status': pulp_result.get('status', 'Unknown'),
                'solve_time': pulp_time,
                'patterns': pulp_result.get('summary', {}).get('total_sets', 0),
                'total_trim': pulp_result.get('summary', {}).get('total_trim', 0),
                'avg_trim': pulp_result.get('summary', {}).get('avg_trim', 0)
            }
            
            # Performance metrics
            if ortools_time > 0 and pulp_time > 0:
                speedup = pulp_time / ortools_time
                comparison['performance'] = {
                    'ortools_faster': speedup > 1.1,
                    'speedup_factor': round(speedup, 2) if speedup > 1 else round(1/speedup, 2),
                    'winner': 'OR-Tools' if speedup > 1.1 else 'PuLP' if speedup < 0.9 else 'Similar'
                }
        
        return comparison


# Test function for the enhanced optimizer
def test_ortools_optimizer():
    """Test the OR-Tools optimizer with sample data."""
    if not ORTOOLS_AVAILABLE:
        print("❌ OR-Tools not available for testing")
        return
    
    optimizer = ORToolsOptimizer()
    
    # Test case: challenging cutting problem
    test_demand = {
        25.0: 15,
        30.0: 20,
        35.0: 18,
        40.0: 12
    }
    
    print("🧪 Testing OR-Tools Optimizer")
    print(f"📋 Demand: {test_demand}")
    print(f"📊 Total pieces: {sum(test_demand.values())}")
    
    result = optimizer.solve_cutting_optimization(test_demand)
    
    print(f"\n✅ Result: {result['status']}")
    print(f"⏱️ Solve time: {result['solve_time']}s")
    print(f"📦 Patterns used: {result['patterns_used']}")
    print(f"🗑️ Total trim: {result['total_trim']}\"")
    print(f"📈 Avg efficiency: {result.get('avg_efficiency', 0)}%")
    
    return result

if __name__ == "__main__":
    test_ortools_optimizer()