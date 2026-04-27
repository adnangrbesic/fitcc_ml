#!/bin/bash

# BuyGuardian E2E Pipeline Test Script

echo "🚀 Starting BuyGuardian Pipeline Test..."

# 1. Inject mock listing into Redis raw queue
echo "📥 Injecting mock listing into Redis 'olx:raw_listings'..."
docker exec fitcc_ml-redis-1 redis-cli LPUSH olx:raw_listings '{"item_id": "999999", "title": "iPhone 15 Pro Test", "description": "Perfect condition, 12 months warranty", "price": 1500.0, "seller_id": "test_seller_123", "scraped_at": "2026-04-26T12:00:00Z"}'

echo "⏳ Waiting for enrichment and processing (15s)..."
sleep 15

# 2. Check RabbitMQ listing_scrape queue (should be empty if processed)
echo "🐰 Checking RabbitMQ queue status..."
docker exec fitcc_ml-rabbitmq-1 rabbitmqctl list_queues | grep listing_scrape

# 3. Check Postgres for the new listing
echo "🐘 Querying Postgres for the new listing..."
docker exec fitcc_ml-db-1 psql -U postgres -d buyguardian -c "SELECT \"ItemId\", \"Title\", \"Price\", \"TrustScore\" FROM \"Listings\" WHERE \"ItemId\" = '999999';"

# 4. Check for Product creation (pgvector)
echo "🔍 Checking for Product creation..."
docker exec fitcc_ml-db-1 psql -U postgres -d buyguardian -c "SELECT \"CanonicalName\" FROM \"Products\" WHERE \"CanonicalName\" ILIKE '%iPhone%';"

# 5. Check Analyze endpoint
echo "📊 Testing Analyze API endpoint..."
curl -s http://localhost:5000/api/analyze/$(docker exec fitcc_ml-db-1 psql -U postgres -d buyguardian -t -c "SELECT \"Id\" FROM \"Listings\" WHERE \"ItemId\" = '999999';" | xargs) | jq .

echo "✅ Test complete!"
