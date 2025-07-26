# Implementation Task Order & File Updates

## Phase 1: Core Algorithm Updates (Foundation)

### Task 1: Update CuttingOptimizer Algorithm  
**File:** `app/services/cutting_optimizer.py`  
**Priority:** CRITICAL  
**Changes Required:**
- [ ] Modify `optimize_with_new_algorithm()` method signature to accept 3 inputs:
  - `order_requirements`: `List[Dict]` (new orders)
  - `pending_orders`: `List[Dict]` (from previous cycles)
  - `available_inventory`: `List[Dict]` (20-25" waste rolls)

  
- [ ] Update waste logic:
  - **Current:** `waste > 20"` → pending  
  - **New:** `20" ≤ waste ≤ 25"` → inventory, `waste > 25"` → pending
- [ ] Change return structure to 4 outputs:
  - `cut_rolls_generated` (what gets fulfilled)
  - `jumbo_rolls_needed` (number to procure)
  - `pending_orders` (can't fulfill)
  - `inventory_remaining` (20-25" waste)
- [ ] Add inventory consumption logic when using existing 20-25" rolls
- [ ] Update `test_algorithm_with_sample_data()` to demonstrate new flow

### Task 2: Update Algorithm Helper Methods  
**File:** `app/services/cutting_optimizer.py`  
**Priority:** CRITICAL  
**Changes Required:**
- [ ] Create `process_inventory_input()` method to handle existing inventory
- [ ] Create `generate_inventory_from_waste()` method for 20-25" waste
- [ ] Update `_group_by_specifications()` to include inventory items
- [ ] Modify waste calculation logic in cutting pattern generation
- [ ] Add inventory tracking in optimization results

## Phase 2: Data Model & Schema Updates (Support New Flow)

### Task 3: Update Pydantic Schemas  
**File:** `app/schemas.py`  
**Priority:** HIGH  
**Changes Required:**
- [ ] Create new optimizer input schema:
```python
class OptimizerInput(BaseModel):
    orders: List[Dict]
    pending_orders: List[Dict]
    available_inventory: List[Dict]
```
- [ ] Create new optimizer output schema:
```python
class OptimizerOutput(BaseModel):
    cut_rolls_generated: List[Dict]
    jumbo_rolls_needed: int
    pending_orders: List[Dict]
    inventory_remaining: List[Dict]
```

### Task 4: Update Database Models (if needed)  
**File:** `app/models.py`  
**Priority:** MEDIUM  
**Changes Required:**
- [ ] Verify `PendingOrderMaster` has `order_id` foreign key (should exist)
- [ ] Verify `InventoryMaster` supports `roll_type="cut"` (should exist)
- [ ] Add any missing fields for tracking waste rolls
- [ ] Ensure `ProductionOrderMaster` supports bulk jumbo procurement

## Phase 3: Service Layer Updates (Business Logic)

### Task 5: Update WorkflowManager  
**File:** `app/services/workflow_manager.py`  
**Priority:** CRITICAL  
**Changes Required:**
- [ ] Remove inventory checking from `process_multiple_orders()`
- [ ] Always go directly to plan generation
- [ ] Update `create_plan_from_orders()` to:
  - Fetch pending orders for same paper specs
  - Fetch available inventory (20-25" rolls)
  - Pass all 3 inputs to optimizer
- [ ] Create `process_optimizer_output()` method to handle 4 outputs:
  - Create `PlanMaster`
  - Create `PendingOrderMaster` records
  - Create `InventoryMaster` records (from waste)
  - Create `ProductionOrderMaster` (for jumbos)
  - Update `OrderMaster` status (NOT `quantity_fulfilled`)
- [ ] Update order status to `"processing"` (ready for fulfillment)

### Task 6: Update OrderFulfillment Service  
**File:** `app/services/order_fulfillment.py`  
**Priority:** HIGH  
**Changes Required:**
- [ ] Remove automatic plan generation from `fulfill_order()`
- [ ] Make `fulfill_order()` purely user-controlled:
  - Only update `quantity_fulfilled`
  - Only update order status to `"completed"`
  - Remove inventory allocation logic
- [ ] Remove `_handle_remaining_quantity_legacy()` (if exists)
- [ ] Simplify to focus only on manual fulfillment tracking

### Task 7: Update PendingOrderService  
**File:** `app/services/pending_order_service.py`  
**Priority:** MEDIUM  
**Changes Required:**
- [ ] Add method to fetch pending orders by paper specifications
- [ ] Add method to cleanup pending orders when original order is fulfilled
- [ ] Update pending order creation to link to original `order_id`
- [ ] Add support for multiple active plan cycles

## Phase 4: CRUD Operations (Database Layer)

### Task 8: Update CRUD Functions  
**File:** `app/crud.py`  
**Priority:** HIGH  
**Changes Required:**
- [ ] Add `get_pending_orders_by_paper_specs()` function
- [ ] Add `get_available_inventory_by_paper_specs()` function
- [ ] Add `create_inventory_from_waste()` function
- [ ] Add `bulk_create_pending_orders()` function
- [ ] Add `cleanup_fulfilled_pending_orders()` function
- [ ] Update `create_plan_with_links()` to handle new flow

## Phase 5: API Endpoints (Interface Layer)

### Task 9: Update Optimizer Endpoints  
**File:** `app/api.py`  
**Priority:** CRITICAL  
**Changes Required:**
- [ ] Update `/optimizer/create-plan` to:
  - Fetch pending orders for same paper specs
  - Fetch available inventory
  - Pass 3 inputs to optimizer
  - Process 4 outputs
- [ ] Update `/optimizer/test-with-orders` to demonstrate new flow
- [ ] Update `/optimizer/test-frontend` to support new input/output structure
- [ ] Add `/optimizer/test-full-cycle` to test complete flow

### Task 10: Update Workflow Endpoints  
**File:** `app/api.py`  
**Priority:** HIGH  
**Changes Required:**
- [ ] Update `/workflow/generate-plan` to use new flow
- [ ] Update `/workflow/process-orders` to skip inventory checking
- [ ] Add `/workflow/get-plan-inputs` to show what goes into planning
- [ ] Add `/workflow/process-plan-outputs` to handle 4 outputs

### Task 11: Add Order Fulfillment Endpoints  
**File:** `app/api.py`  
**Priority:** MEDIUM  
**Changes Required:**
- [ ] Ensure `/orders/{order_id}/fulfill` exists and works correctly
- [ ] Add `/orders/{order_id}/partial-fulfill` for partial fulfillment
- [ ] Add `/orders/bulk-fulfill` for multiple order fulfillment
- [ ] Add validation to prevent over-fulfillment

## Phase 6: Testing & Documentation (Quality Assurance)

### Task 12: Update Test Data  
**File:** `app/services/cutting_optimizer.py`  
**Priority:** LOW  
**Changes Required:**
- [ ] Update `test_algorithm_with_sample_data()` to show:
  - Orders with pending from previous cycle
  - Available inventory (20-25" rolls)
  - 4 outputs generated
- [ ] Add test scenarios for edge cases

### Task 13: Update Documentation  
**File:** `DATA_FLOW_ARCHITECTURE.md`  
**Priority:** LOW  
**Changes Required:**
- [ ] Update Phase 2 to reflect direct plan generation
- [ ] Update Phase 3 to show 4 optimizer outputs
- [ ] Add inventory creation from waste documentation
- [ ] Update workflow examples with new flow

### Task 14: Update Postman Collection  
**File:** `Paper_Roll_Management_API.postman_collection.json`  
**Priority:** LOW  
**Changes Required:**
- [ ] Update optimizer test requests to show new flow
- [ ] Add test sequences for complete cycle
- [ ] Add examples with pending orders and inventory

## 🎯 Critical Implementation Order

### Must Complete First (Critical Path):
- [ ] Task 1: Update CuttingOptimizer Algorithm
- [ ] Task 2: Update Algorithm Helper Methods
- [ ] Task 5: Update WorkflowManager
- [ ] Task 9: Update Optimizer Endpoints

### Can Be Done in Parallel:
- [ ] Task 3: Update Pydantic Schemas
- [ ] Task 6: Update OrderFulfillment Service
- [ ] Task 8: Update CRUD Functions
- [ ] Task 10: Update Workflow Endpoints

### Final Phase:
- [ ] Task 4: Update Database Models
- [ ] Task 7: Update PendingOrderService
- [ ] Task 11: Add Order Fulfillment Endpoints
- [ ] Tasks 12–14: Testing & Documentation