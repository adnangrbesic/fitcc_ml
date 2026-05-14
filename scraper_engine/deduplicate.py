import redis
import json

r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)

# Fetch all items
items = r.lrange('olx:raw_listings', 0, -1)
print(f"Found {len(items)} items in olx:raw_listings")

seen = set()
deduped = []

for i in items:
    try:
        data = json.loads(i)
        item_id = data.get('item_id')
        # If item_id is present and we've seen it, skip
        # But also check if there's more feedback in this variant
        feedback = data.get('positive_feedback', 0)
        
        if item_id in seen:
            # We already added one variant.
            # Find existing in deduped and compare feedback if we want, but let's just keep first one for simplicity or replace if better.
            print(f"Duplicate found: {item_id}. Skipping.")
            continue
        
        seen.add(item_id)
        deduped.append(i)
    except Exception as e:
        print(f"Error parsing item: {e}")
        deduped.append(i)

# Clear queue and write back
if len(deduped) < len(items):
    r.delete('olx:raw_listings')
    for item in reversed(deduped):  # push to head so it keeps original order
        r.lpush('olx:raw_listings', item)
    print(f"Successfully deduplicated queue. New length: {len(deduped)}")
else:
    print("No duplicates found to remove.")
