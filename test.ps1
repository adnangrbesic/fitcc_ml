# BuyGuardian E2E Pipeline Test Script (PowerShell)

Write-Host "[*] Starting BuyGuardian Pipeline Test..."

Write-Host "[+] Ollama models are now managed via docker-compose."

# 2. Clear old data from Redis queue
Write-Host "[+] Clearing 'olx:raw_listings' queue..."
docker exec fitcc_ml-redis-1 redis-cli DEL olx:raw_listings

# 3. Inject mock listing into Redis raw queue
Write-Host "[+] Injecting mock listing into Redis 'olx:raw_listings'..."
$payload = '{"item_id": "999999", "title": "iPhone 15 Pro Test", "description": "Perfect condition, 12 months warranty", "price": 1500.0, "seller_id": "test_seller_123", "scraped_at": "2026-04-26T12:00:00Z"}'
$payload | docker exec -i fitcc_ml-redis-1 redis-cli -x LPUSH olx:raw_listings

Write-Host "[...] Waiting for enrichment and processing (20s)..."
Start-Sleep -Seconds 20

# 4. Check RabbitMQ listing_scrape queue
Write-Host "[+] Checking RabbitMQ queue status..."
docker exec fitcc_ml-rabbitmq-1 rabbitmqctl list_queues | Select-String "listing_scrape"

# 5. Check Postgres for the new listing
Write-Host "[+] Querying Postgres for the new listing..."
"SELECT * FROM ""Listings"" WHERE ""ItemId"" = '999999';" | docker exec -i fitcc_ml-db-1 psql -U postgres -d buyguardian

# 6. Check for Product creation
Write-Host "[+] Checking for Product creation..."
"SELECT * FROM ""Products"" WHERE ""CanonicalName"" ILIKE '%iPhone%';" | docker exec -i fitcc_ml-db-1 psql -U postgres -d buyguardian

# 7. Check Analyze endpoint
Write-Host "[+] Testing Analyze API endpoint..."
$listingIdRaw = "SELECT ""Id"" FROM ""Listings"" WHERE ""ItemId"" = '999999';" | docker exec -i fitcc_ml-db-1 psql -U postgres -d buyguardian -t
if ($listingIdRaw -and $listingIdRaw.Trim()) {
    $cleanId = $listingIdRaw.Trim()
    $uri = "http://localhost:5000/api/analyze/$cleanId"
    Write-Host "Fetching: $uri"
    try {
        $response = Invoke-RestMethod -Uri $uri
        $response | ConvertTo-Json -Depth 10
    } catch {
        Write-Host "[-] API Call failed: $($_.Exception.Message)" -ForegroundColor Red
    }
} else {
    Write-Host "[-] Could not find Listing ID in database. Check 'enricher' logs for errors." -ForegroundColor Red
}

Write-Host "[!] Test complete!" -ForegroundColor Green
