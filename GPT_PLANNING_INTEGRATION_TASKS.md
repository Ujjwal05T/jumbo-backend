# GPT + Cutting Optimizer Integration Tasks

## Overview
Add GPT-powered intelligent planning as a new option in the frontend. GPT will analyze orders and suggest optimal batches, then your existing cutting optimizer will process them.

## Implementation Tasks

### Phase 1: Backend Service Development
- [ ] **Create GPT Planning Service** (`app/services/gpt_planner.py`)
  - [ ] Initialize OpenAI client with API key
  - [ ] Create order data collection methods
  - [ ] Design GPT prompt system for order batch selection
  - [ ] Build response parsing and validation
  - [ ] Integrate with existing CuttingOptimizer class

- [ ] **Add Configuration Management**
  - [ ] Add OpenAI API key to environment variables
  - [ ] Create GPT settings (model, temperature, max tokens)
  - [ ] Add enable/disable toggle for GPT features

- [ ] **Create API Endpoint** (`app/api/gpt_planning.py`)
  - [ ] POST `/planning/gpt-suggest-batch` endpoint
  - [ ] Input: list of order IDs, planning parameters
  - [ ] Output: GPT recommendations + optimization results
  - [ ] Error handling and fallback to traditional optimization

### Phase 2: Database Integration
- [ ] **Add GPT Planning Tables** (optional for logging)
  - [ ] `gpt_planning_sessions` table (track GPT suggestions)
  - [ ] `gpt_accuracy_metrics` table (measure GPT performance)
  - [ ] Migration scripts for new tables

- [ ] **Extend Existing Models**
  - [ ] Add `planning_method` field to plans ('traditional', 'gpt_assisted')
  - [ ] Add `gpt_reasoning` text field to store GPT explanations
  - [ ] Add `gpt_confidence` score field

### Phase 3: Frontend Integration
- [ ] **Add Smart Plan Button**
  - [ ] Add "Smart Plan" button next to existing "Generate Plan" button
  - [ ] Same order selection interface (no changes to checkboxes)
  - [ ] Smart Plan button only shows when OpenAI API key is configured

- [ ] **Enhance Results Display**
  - [ ] Show GPT reasoning/explanation in results
  - [ ] Display confidence score from GPT
  - [ ] Show which orders GPT selected from user's candidates
  - [ ] Display optimization results as usual

- [ ] **Update Results Display**
  - [ ] Indicate when plan was created with GPT assistance
  - [ ] Show GPT's original reasoning
  - [ ] Display accuracy metrics (predicted vs actual results)

### Phase 4: Integration Points

#### Backend Files to Modify:
```
app/
├── services/
│   ├── gpt_planner.py              # NEW - Main GPT service
│   └── cutting_optimizer.py       # MODIFY - Add GPT integration hooks
├── api/
│   ├── gpt_planning.py            # NEW - GPT planning endpoints
│   └── plans.py                   # MODIFY - Add GPT planning option
├── models/
│   └── __init__.py                # MODIFY - Add GPT-related fields
└── config/
    └── settings.py                # MODIFY - Add OpenAI configuration
```

#### Frontend Files to Modify:
```
src/app/planning/
├── page.tsx                       # MODIFY - Add GPT planning option
├── components/
│   ├── PlanningMethodSelector.tsx # NEW - GPT vs Traditional toggle
│   ├── GPTReasoningDisplay.tsx    # NEW - Show GPT explanations
│   └── OrderBatchPreview.tsx      # NEW - Preview GPT suggestions
└── hooks/
    └── useGPTPlanning.ts         # NEW - GPT planning API calls
```

### Phase 5: Configuration & Deployment
- [ ] **Environment Setup**
  - [ ] Add `OPENAI_API_KEY` to environment variables
  - [ ] Add `GPT_PLANNING_ENABLED=true/false` toggle
  - [ ] Add GPT model configuration (`GPT_MODEL=gpt-4`)

- [ ] **Settings UI** (optional)
  - [ ] Admin page to configure GPT settings
  - [ ] Test GPT connection button
  - [ ] View GPT usage/costs

### Phase 6: Testing & Validation
- [ ] **Unit Tests**
  - [ ] Test GPT service with mock responses
  - [ ] Test API endpoints
  - [ ] Test error handling and fallbacks

- [ ] **Integration Tests**
  - [ ] Test full workflow: GPT suggestion → optimization → results
  - [ ] Test with various order combinations
  - [ ] Test fallback when GPT fails

- [ ] **Performance Testing**
  - [ ] Measure GPT response times
  - [ ] Compare results: GPT-assisted vs traditional
  - [ ] Monitor API costs

## User Experience Flow

### Traditional Planning (Current):
1. User selects orders to process
2. User clicks "Generate Plan"
3. System runs cutting optimizer
4. User gets optimization results

### Smart Planning (New):
1. User selects candidate orders (same interface)
2. User clicks "Smart Plan" button
3. GPT analyzes selected orders + pending orders
4. GPT selects optimal subset from user's selection
5. System runs cutting optimizer on GPT's selection
6. User gets optimization results + GPT insights

## API Design

### New Endpoint: `/planning/smart-plan`
```json
// Request
{
  "candidate_order_ids": ["ORD-001", "ORD-002", "POI-003"],
  "include_pending": true,
  "max_batch_size": 8,
  "planning_criteria": {
    "prioritize_pending": true,
    "max_pending_days": 7,
    "prefer_complete_orders": true
  }
}

// Response
{
  "status": "success",
  "gpt_analysis": {
    "recommended_orders": ["ORD-001", "POI-003"],
    "deferred_orders": ["ORD-002"],
    "reasoning": "Selected orders complement each other well...",
    "confidence": 0.87,
    "expected_pending": 0
  },
  "optimization_result": {
    // Your existing optimization result format
  },
  "performance_metrics": {
    "gpt_response_time": 2.3,
    "optimization_time": 0.15,
    "total_time": 2.45
  }
}
```

## Configuration

### Environment Variables:
```bash
# GPT Configuration
OPENAI_API_KEY=sk-...
GPT_PLANNING_ENABLED=true
GPT_MODEL=gpt-4
GPT_MAX_TOKENS=1500
GPT_TEMPERATURE=0.3

# Planning Parameters  
MAX_BATCH_SIZE=10
PENDING_ORDER_PRIORITY_DAYS=5
```

## Success Metrics
- [ ] **Functionality**: GPT suggestions result in fewer pending orders
- [ ] **Performance**: Total time (GPT + optimization) < 5 seconds
- [ ] **Accuracy**: GPT predictions match actual optimization results >80%
- [ ] **User Adoption**: Users prefer GPT-assisted planning for complex scenarios
- [ ] **Cost**: OpenAI API costs are reasonable for business value

## Timeline Estimate
- **Phase 1-2**: 3-4 days (Backend core functionality)
- **Phase 3**: 2-3 days (Frontend integration) 
- **Phase 4-6**: 2-3 days (Testing, refinement)
- **Total**: 1-2 weeks for complete implementation

## Risk Mitigation
- **GPT Unavailable**: Always fallback to traditional optimization
- **High API Costs**: Add usage limits and monitoring
- **Poor GPT Suggestions**: User can always override or disable GPT
- **Integration Issues**: Keep GPT as optional enhancement, not replacement