import sys
import redis
import os

def main():
    if len(sys.argv) < 2:
        print("Usage: python test_url.py <url>")
        sys.exit(1)
    
    url = sys.argv[1].strip()
    if not url:
        print("[-] Error: URL is empty")
        sys.exit(1)
        
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
    
    try:
        # Connect to Redis
        r = redis.from_url(redis_url)
        # Push to the queue that the scraper worker consumes from
        r.lpush("olx:urls", url)
        print(f"[+] Successfully pushed URL to Redis queue 'olx:urls': {url}")
        print("[+] Scraper worker should pick it up shortly.")
    except Exception as e:
        print(f"[-] Error connecting to Redis or pushing URL: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
