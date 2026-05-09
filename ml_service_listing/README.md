# ML Trust Scoring Service

## Setup

1. Install dependencies:

```
pip install -r requirements.txt
```

2. Create a local env file:

```
cp .env.example .env
```

## Run scoring once

```
python -m ml_service_listing.main --once
```

## Run with polling

```
python -m ml_service_listing.main --poll --interval 300
```

## Training and evaluation example

```
python -m ml_service_listing.training.train --input data/listings.json --output model.cbm --eval-split 0.2 --metrics-out metrics.json
```

## Run API service

```
uvicorn ml_service_listing.service:app --host 0.0.0.0 --port 8010
```

## Predict trust score (API)

```
curl -X POST http://localhost:8010/api/trust-score/predict \
	-H "Content-Type: application/json" \
	-d '{"listing": {"id": "123", "itemId": "123", "title": "Sample", "price": 100}}'
```
