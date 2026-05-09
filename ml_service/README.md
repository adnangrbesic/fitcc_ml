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
