# Live Car API

A FastAPI-based service for managing live car data.

## Getting Started

### Prerequisites
- Python 3.8+
- pip

### Installation

1. Clone the repository
```bash
git clone <repository-url>
cd live-car-api
```

2. Create a virtual environment
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies
```bash
pip install -r requirements.txt
```

4. Set up environment variables
```bash
cp .env.example .env
```

### Running the Application

Start the development server:
```bash
python -m app.main
```

Or using uvicorn directly:
```bash
uvicorn app.main:app --reload
```

The API will be available at `http://localhost:8000`

### API Documentation

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

### Running Tests

```bash
pytest
```

## Project Structure

```
live-car-api/
├── app/
│   ├── api/              # API endpoints/routers
│   │   ├── health.py
│   │   └── __init__.py
│   ├── models/           # Pydantic models
│   │   └── __init__.py
│   ├── config.py         # Configuration settings
│   ├── main.py           # FastAPI application
│   └── __init__.py
├── tests/                # Test suite
│   ├── test_health.py
│   └── __init__.py
├── .env                  # Environment variables (local)
├── .env.example          # Environment variables template
├── .gitignore            # Git ignore rules
├── requirements.txt      # Python dependencies
└── README.md            # This file
```

## Development

### Adding New Routes

1. Create a new router file in `app/api/`
2. Define your endpoints using FastAPI decorators
3. Include the router in `app/main.py`

Example:
```python
from fastapi import APIRouter

router = APIRouter(prefix="/cars", tags=["cars"])

@router.get("/")
async def list_cars():
    return {"cars": []}
```

## License

See LICENSE file for details.
