param (
    [Parameter(Mandatory=$true)]
    [string]$Url
)

Write-Host "[+] Sending URL to Scraper Engine: $Url" -ForegroundColor Cyan

# Run the python script inside the scraper container
docker-compose exec -T scraper python test_url.py "$Url"

Write-Host "[+] Done! Check 'enricher' and 'api' logs for progress." -ForegroundColor Green
Write-Host "[+] Tip: docker-compose logs -f enricher api" -ForegroundColor Yellow
