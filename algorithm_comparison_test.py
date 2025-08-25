#!/usr/bin/env python3
"""
Algorithm Comparison Test Script
Compares ILP Algorithm vs User's Smart Tracking Algorithm

This script tests both algorithms on various scenarios and provides detailed comparison.
"""

import time
import logging
from collections import Counter
from typing import Dict, List, Tuple

# Add the app directory to Python path
import sys
sys.path.append('.')

from app.services.cutting_optimizer import CuttingOptimizer

def setup_logging():
    """Setup logging to capture algorithm details"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s: %(message)s'
    )

def run_single_test(test_name: str, order_requirements: List[Dict], optimizer: CuttingOptimizer) -> Dict:
    """Run both algorithms on a single test case and return comparison results"""
    
    print(f"\n{'='*50}")
    print(f" TEST: {test_name}")
    print(f"{'='*50}")
    
    # Display test demand
    total_demand = sum(req['quantity'] for req in order_requirements)
    widths = [req['width'] for req in order_requirements]
    quantities = [req['quantity'] for req in order_requirements]
    
    print(f"📋 Demand: {dict(zip(widths, quantities))} (Total: {total_demand} rolls)")
    
    results = {}
    
    # Test ILP Algorithm
    print(f"\n Testing ILP Algorithm...")
    start_time = time.time()
    try:
        ilp_result = optimizer.optimize_with_new_algorithm(
            order_requirements=order_requirements,
            pending_orders=[],
            available_inventory=[],
            interactive=False,
            algorithm="ilp"
        )
        ilp_time = time.time() - start_time
        
        # Calculate ILP metrics
        ilp_rolls = len(ilp_result["cut_rolls_generated"])
        ilp_jumbos = len(ilp_result["jumbo_rolls_needed"])
        ilp_waste = sum(j.get('trim', 0) for j in ilp_result["jumbo_rolls_needed"])
        ilp_avg_waste = ilp_waste / ilp_jumbos if ilp_jumbos > 0 else 0
        
        results['ilp'] = {
            'success': True,
            'rolls_produced': ilp_rolls,
            'jumbo_rolls': ilp_jumbos,
            'total_waste': ilp_waste,
            'avg_waste': ilp_avg_waste,
            'execution_time': ilp_time,
            'accuracy': abs(ilp_rolls - total_demand) == 0
        }
        
        print(f"   ILP: {ilp_rolls} rolls, {ilp_jumbos} jumbos, {ilp_waste:.1f}\" total waste, {ilp_avg_waste:.1f}\" avg")
        
    except Exception as e:
        results['ilp'] = {'success': False, 'error': str(e), 'execution_time': time.time() - start_time}
        print(f"  ILP Failed: {e}")
    
    # Test User's Tracking Algorithm
    print(f"\n Testing User's Tracking Algorithm...")
    start_time = time.time()
    try:
        tracking_result = optimizer.optimize_with_new_algorithm(
            order_requirements=order_requirements,
            pending_orders=[],
            available_inventory=[],
            interactive=False,
            algorithm="tracking"
        )
        tracking_time = time.time() - start_time
        
        # Calculate Tracking metrics
        tracking_rolls = len(tracking_result["cut_rolls_generated"])
        tracking_jumbos = len(tracking_result["jumbo_rolls_needed"])
        tracking_waste = sum(j.get('trim', 0) for j in tracking_result["jumbo_rolls_needed"])
        tracking_avg_waste = tracking_waste / tracking_jumbos if tracking_jumbos > 0 else 0
        
        results['tracking'] = {
            'success': True,
            'rolls_produced': tracking_rolls,
            'jumbo_rolls': tracking_jumbos,
            'total_waste': tracking_waste,
            'avg_waste': tracking_avg_waste,
            'execution_time': tracking_time,
            'accuracy': abs(tracking_rolls - total_demand) == 0
        }
        
        print(f"    Tracking: {tracking_rolls} rolls, {tracking_jumbos} jumbos, {tracking_waste:.1f}\" total waste, {tracking_avg_waste:.1f}\" avg")
        
    except Exception as e:
        results['tracking'] = {'success': False, 'error': str(e), 'execution_time': time.time() - start_time}
        print(f"    Tracking Failed: {e}")
    
    # Comparison Summary
    if results.get('ilp', {}).get('success') and results.get('tracking', {}).get('success'):
        print(f"\n Comparison Summary:")
        
        ilp = results['ilp']
        track = results['tracking']
        
        # Roll accuracy
        ilp_accurate = ilp['accuracy']
        track_accurate = track['accuracy']
        print(f" Roll Accuracy: ILP={'✅' if ilp_accurate else '❌'}, Tracking={'✅' if track_accurate else '❌'}")
        
        # Waste comparison
        if ilp['total_waste'] < track['total_waste']:
            waste_winner = "ILP"
            waste_diff = track['total_waste'] - ilp['total_waste']
        elif track['total_waste'] < ilp['total_waste']:
            waste_winner = "Tracking"
            waste_diff = ilp['total_waste'] - track['total_waste']
        else:
            waste_winner = "Tie"
            waste_diff = 0
            
        print(f"  Waste Winner: {waste_winner}" + (f" (by {waste_diff:.1f}\")" if waste_diff > 0 else ""))
        
        # Speed comparison
        speed_ratio = ilp['execution_time'] / track['execution_time']
        if speed_ratio > 1.1:
            speed_winner = f"Tracking ({speed_ratio:.1f}x faster)"
        elif speed_ratio < 0.9:
            speed_winner = f"ILP ({1/speed_ratio:.1f}x faster)"
        else:
            speed_winner = "Similar speed"
            
        print(f" Speed: {speed_winner}")
        
        # Overall winner
        ilp_score = (1 if ilp_accurate else 0) + (1 if waste_winner == "ILP" else 0.5 if waste_winner == "Tie" else 0)
        track_score = (1 if track_accurate else 0) + (1 if waste_winner == "Tracking" else 0.5 if waste_winner == "Tie" else 0)
        
        if ilp_score > track_score:
            overall_winner = "ILP"
        elif track_score > ilp_score:
            overall_winner = "Tracking"
        else:
            overall_winner = "Tie"
            
        print(f" Overall Winner: {overall_winner}")
    
    results['test_name'] = test_name
    results['demand'] = total_demand
    return results

def main():
    """Run comprehensive algorithm comparison tests"""
    setup_logging()
    
    print(" ALGORITHM COMPARISON TEST")
    print("=" * 50)
    print("Comparing ILP Algorithm vs User's Smart Tracking Algorithm")
    
    optimizer = CuttingOptimizer()
    
    # Test Cases
    test_cases = [
        # {
        #     'name': 'Original Problem (172 rolls)',
        #     'orders': [
        #         {'width': 25.0, 'quantity': 62, 'gsm': 210, 'bf': 16.0, 'shade': 'Natural', 'min_length': 1000},
        #         {'width': 28.0, 'quantity': 82, 'gsm': 210, 'bf': 16.0, 'shade': 'Natural', 'min_length': 1000},
        #         {'width': 30.0, 'quantity': 28, 'gsm': 210, 'bf': 16.0, 'shade': 'Natural', 'min_length': 1000}
        #     ]
        # },
        # {
        #     'name': 'Small Even Distribution',
        #     'orders': [
        #         {'width': 24.0, 'quantity': 20, 'gsm': 80, 'bf': 1.2, 'shade': 'White', 'min_length': 1000},
        #         {'width': 30.0, 'quantity': 20, 'gsm': 80, 'bf': 1.2, 'shade': 'White', 'min_length': 1000},
        #         {'width': 36.0, 'quantity': 20, 'gsm': 80, 'bf': 1.2, 'shade': 'White', 'min_length': 1000}
        #     ]
        # },
        # {
        #     'name': 'Uneven Distribution',
        #     'orders': [
        #         {'width': 22.0, 'quantity': 5, 'gsm': 120, 'bf': 2.0, 'shade': 'Blue', 'min_length': 1000},
        #         {'width': 30.0, 'quantity': 45, 'gsm': 120, 'bf': 2.0, 'shade': 'Blue', 'min_length': 1000},
        #         {'width': 33.0, 'quantity': 10, 'gsm': 120, 'bf': 2.0, 'shade': 'Blue', 'min_length': 1000}
        #     ]
        # },
        {
            'name': 'Large Numbers',
            'orders': [
                {'width': 20.0, 'quantity': 100, 'gsm': 150, 'bf': 1.5, 'shade': 'Green', 'min_length': 1000},
                {'width': 25.0, 'quantity': 80, 'gsm': 150, 'bf': 1.5, 'shade': 'Green', 'min_length': 1000},
                {'width': 35.0, 'quantity': 120, 'gsm': 150, 'bf': 1.5, 'shade': 'Green', 'min_length': 1000}
            ]
        },
        {
            'name': 'Challenging Widths',
            'orders': [
                {'width': 23.5, 'quantity': 15, 'gsm': 90, 'bf': 1.8, 'shade': 'Yellow', 'min_length': 1000},
                {'width': 31.7, 'quantity': 25, 'gsm': 90, 'bf': 1.8, 'shade': 'Yellow', 'min_length': 1000},
                {'width': 39.2, 'quantity': 10, 'gsm': 90, 'bf': 1.8, 'shade': 'Yellow', 'min_length': 1000}
            ]
        }
    ]
    
    all_results = []
    
    # Run all tests
    for test_case in test_cases:
        result = run_single_test(test_case['name'], test_case['orders'], optimizer)
        all_results.append(result)
        
        # Brief pause between tests
        time.sleep(1)
    
    # Final Summary
    print(f"\n{'='*60}")
    print(" FINAL COMPARISON SUMMARY")
    print(f"{'='*60}")
    
    ilp_wins = 0
    tracking_wins = 0
    ties = 0
    
    ilp_total_waste = 0
    tracking_total_waste = 0
    ilp_total_time = 0
    tracking_total_time = 0
    
    print(f"{'Test Name':<25} {'ILP Rolls':<10} {'Track Rolls':<12} {'ILP Waste':<10} {'Track Waste':<12} {'Winner':<10}")
    print(f"{'-'*80}")
    
    for result in all_results:
        if result.get('ilp', {}).get('success') and result.get('tracking', {}).get('success'):
            ilp = result['ilp']
            track = result['tracking']
            
            # Determine winner for this test
            ilp_better_waste = ilp['total_waste'] < track['total_waste']
            track_better_waste = track['total_waste'] < ilp['total_waste']
            both_accurate = ilp['accuracy'] and track['accuracy']
            
            if both_accurate:
                if ilp_better_waste:
                    winner = "ILP"
                    ilp_wins += 1
                elif track_better_waste:
                    winner = "Tracking"
                    tracking_wins += 1
                else:
                    winner = "Tie"
                    ties += 1
            else:
                winner = "ILP" if ilp['accuracy'] else "Tracking" if track['accuracy'] else "Both Failed"
                if winner == "ILP":
                    ilp_wins += 1
                elif winner == "Tracking":
                    tracking_wins += 1
            
            # Add to totals
            ilp_total_waste += ilp['total_waste']
            tracking_total_waste += track['total_waste']
            ilp_total_time += ilp['execution_time']
            tracking_total_time += track['execution_time']
            
            # Print row
            print(f"{result['test_name'][:24]:<25} {ilp['rolls_produced']:<10} {track['rolls_produced']:<12} {ilp['total_waste']:<10.1f} {track['total_waste']:<12.1f} {winner:<10}")
    
    print(f"{'-'*80}")
    print(f"{'TOTALS':<25} {'':<10} {'':<12} {ilp_total_waste:<10.1f} {tracking_total_waste:<12.1f}")
    
    print(f"\n OVERALL RESULTS:")
    print(f"   ILP Algorithm wins: {ilp_wins}")
    print(f"   Tracking Algorithm wins: {tracking_wins}")
    print(f"   Ties: {ties}")
    
    print(f"\n AGGREGATE METRICS:")
    print(f"   Total Waste - ILP: {ilp_total_waste:.1f}\", Tracking: {tracking_total_waste:.1f}\"")
    print(f"   Total Time - ILP: {ilp_total_time:.2f}s, Tracking: {tracking_total_time:.2f}s")
    
    if ilp_total_waste < tracking_total_waste:
        waste_savings = tracking_total_waste - ilp_total_waste
        print(f" ILP saves {waste_savings:.1f}\" of waste overall")
    elif tracking_total_waste < ilp_total_waste:
        waste_savings = ilp_total_waste - tracking_total_waste
        print(f" Tracking saves {waste_savings:.1f}\" of waste overall")
    else:
        print(f" Both algorithms produce identical total waste")
    
    if tracking_total_time < ilp_total_time:
        speed_ratio = ilp_total_time / tracking_total_time
        print(f" Tracking is {speed_ratio:.1f}x faster overall")
    else:
        speed_ratio = tracking_total_time / ilp_total_time
        print(f" ILP is {speed_ratio:.1f}x faster overall")
    
    print(f"\n Algorithm comparison complete!")

if __name__ == "__main__":
    main()