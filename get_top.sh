psql -U postgres -d buyguardian -c "SELECT \"OlxId\", \"Username\", \"TrustScore\" FROM \"Sellers\" ORDER BY \"TrustScore\" DESC LIMIT 5;"
