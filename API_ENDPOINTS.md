# API Endpoints Documentation

## Client Master Endpoints

- `POST /clients/` - Create a new client in Client Master
- `GET /clients/` - Get all clients with pagination and status filter
- `GET /clients/{client_id}` - Get client by ID
- `PUT /clients/{client_id}` - Update client information
- `DELETE /clients/{client_id}` - Delete (deactivate) client

## User Master Endpoints

- `GET /users/` - Get all users with pagination and role filter
- `GET /users/{user_id}` - Get user by ID
- `PUT /users/{user_id}` - Update user information

## Paper Master Endpoints

- `POST /papers/` - Create a new paper specification in Paper Master
- `GET /papers/` - Get all paper specifications with pagination and status filter
- `GET /papers/{paper_id}` - Get paper specification by ID
- `GET /papers/search` - Search paper by specifications (GSM, BF, Shade, Type)
- `PUT /papers/{paper_id}` - Update paper specification
- `DELETE /papers/{paper_id}` - Delete (deactivate) paper specification

## Order Master Endpoints

- `POST /orders/` - Create a new order with multiple order items
- `GET /orders/` - Get all orders with pagination and filters
- `GET /orders/{order_id}` - Get order by ID with related data
- `PUT /orders/{order_id}` - Update order information
- `POST /orders/{order_id}/fulfill/{item_id}` - Fulfill specific order item with quantity
- `POST /orders/bulk-fulfill` - Bulk fulfill multiple order items
- `POST /orders/{order_id}/items` - Create a new order item for an existing order
- `GET /orders/{order_id}/items` - Get all items for a specific order
- `GET /order-items/{item_id}` - Get specific order item by ID
- `PUT /order-items/{item_id}` - Update order item
- `DELETE /order-items/{item_id}` - Delete order item

## Pending Order Endpoints

- `POST /pending-order-items/` - Create a new pending order item
- `GET /pending-order-items/` - Get all pending order items with pagination
- `GET /pending-order-items/summary` - Get summary statistics for pending order items
- `GET /pending-order-items/debug` - Debug endpoint to check pending items data
- `GET /pending-order-items/consolidation` - Get consolidation opportunities for pending items
- `GET /pending-orders/` - Legacy endpoint - redirects to pending-order-items

## Inventory Master Endpoints

- `POST /inventory/` - Create a new inventory item
- `GET /inventory/` - Get all inventory items with pagination and filters
- `GET /inventory/{inventory_id}` - Get inventory item by ID
- `PUT /inventory/{inventory_id}` - Update inventory item
- `GET /inventory/jumbo-rolls` - Get jumbo rolls from inventory
- `GET /inventory/cut-rolls` - Get cut rolls from inventory
- `GET /inventory/available` - Get available inventory for cutting optimization

## Plan Master Endpoints

- `POST /plans/` - Create a new cutting plan
- `GET /plans/` - Get all cutting plans with pagination
- `GET /plans/{plan_id}` - Get cutting plan by ID
- `PUT /plans/{plan_id}` - Update cutting plan status

## Cutting Optimization Endpoints

- `POST /optimizer/create-plan` - Create cutting plan from order specifications
- `POST /optimizer/generate-plan` - Generate cutting plan from workflow
- `POST /optimizer/process-orders` - Process multiple orders together for optimal cutting plans
- `GET /optimizer/workflow-status` - Get overall workflow status and metrics
- `GET /optimizer/orders-with-relationships` - Get orders with their relationships for planning
- `PUT /optimizer/plans/{plan_id}/status` - Update plan status and actual waste percentage
- `POST /optimizer/plans/{plan_id}/execute` - Execute a cutting plan by updating status to in_progress
- `POST /optimizer/plans/{plan_id}/complete` - Complete a cutting plan by updating status to completed
- `POST /optimizer/plans/{plan_id}/inventory-links` - Link inventory items to a cutting plan
- `GET /optimizer/plans/{plan_id}/inventory-links` - Get inventory links for a cutting plan
- `DELETE /optimizer/plans/{plan_id}/inventory-links/{link_id}` - Remove an inventory link from a cutting plan
- `PUT /optimizer/inventory/{inventory_id}/status` - Update inventory item status

## Authentication Endpoints

- `POST /auth/register` - Register a new user in UserMaster
- `POST /auth/login` - Authenticate user and return user information

## Cutting Algorithm Endpoints

- `POST /cutting/generate-plan` - Generate cutting plan from roll specifications
- `POST /cutting/validate-plan` - Validate a cutting plan against constraints
- `GET /cutting/algorithms` - Get information about available optimization algorithms and their parameters

## Cut Roll Production Endpoints

- `POST /cut-rolls/select` - Select cut rolls from plan generation results for production
- `GET /cut-rolls/production/{plan_id}` - Get summary of cut roll production for a specific plan
- `GET /qr/{qr_code}` - Scan QR code and return cut roll details
- `PUT /qr/update-weight` - Update cut roll weight via QR code scan
- `POST /cutting/generate-with-selection` - Generate plan with cut roll selection in one step