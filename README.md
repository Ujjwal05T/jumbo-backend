# Paper Roll Management System - Backend

FastAPI backend for the Paper Roll Management System.

## Directory Structure

```
backend/
├── app/                    # Main application package
│   ├── api/                # API endpoints
│   │   ├── v1/             # API version 1
│   │   │   ├── endpoints/  # API endpoint modules
│   │   │   └── router.py   # API router
│   ├── core/               # Core modules
│   │   ├── config.py       # Configuration settings
│   │   ├── security.py     # Security utilities
│   │   └── logging.py      # Logging configuration
│   ├── db/                 # Database
│   │   ├── base.py         # Base models
│   │   ├── session.py      # Database session
│   │   └── init_db.py      # Database initialization
│   ├── models/             # SQLAlchemy models
│   ├── schemas/            # Pydantic schemas
│   ├── services/           # Business logic services
│   │   ├── order.py        # Order service
│   │   ├── cutting.py      # Cutting optimization service
│   │   ├── inventory.py    # Inventory service
│   │   ├── qrcode.py       # QR code service
│   │   └── whatsapp.py     # WhatsApp parser service
│   ├── utils/              # Utility functions
│   └── main.py             # FastAPI application creation
├── alembic/                # Database migrations
│   ├── versions/           # Migration versions
│   └── env.py              # Alembic environment
├── tests/                  # Test modules
│   ├── api/                # API tests
│   ├── services/           # Service tests
│   └── conftest.py         # Test configuration
├── .env                    # Environment variables
├── .env.example            # Example environment variables
├── requirements.txt        # Production dependencies
├── requirements-dev.txt    # Development dependencies
└── pyproject.toml          # Project metadata
```

## Setup

1. Create a virtual environment:
   ```
   python -m venv venv
   venv\Scripts\activate
   ```

2. Install dependencies:
   ```
   pip install -r requirements.txt
   pip install -r requirements-dev.txt
   ```

3. Set up environment variables:
   ```
   copy .env.example .env
   ```
   Edit the `.env` file with your MS SQL Server connection details.

4. Run the application:
   ```
   uvicorn app.main:app --reload
   ```

5. Access the API documentation:
   - Swagger UI: http://localhost:8000/docs
   - ReDoc: http://localhost:8000/redoc