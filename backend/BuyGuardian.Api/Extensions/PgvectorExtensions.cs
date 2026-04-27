using BuyGuardian.Api.Models;
using Microsoft.EntityFrameworkCore;
using Pgvector;
using Pgvector.EntityFrameworkCore;

namespace BuyGuardian.Api.Extensions;

public static class PgvectorExtensions
{
    /// <summary>
    /// Searches for products similar to the given vector using cosine similarity.
    /// </summary>
    /// <param name="products">The product queryable.</param>
    /// <param name="vector">The search vector.</param>
    /// <param name="threshold">The similarity threshold (0.0 to 1.0). Default 0.92.</param>
    /// <returns>Queryable of products with similarity above the threshold, ordered by similarity descending.</returns>
    public static IQueryable<Product> SearchBySimilarity(this IQueryable<Product> products, Vector vector, double threshold = 0.92)
    {
      
        double distanceThreshold = 1.0 - threshold;

        return products
            .Where(p => p.ProductVector != null && p.ProductVector.CosineDistance(vector) <= distanceThreshold)
            .OrderBy(p => p.ProductVector!.CosineDistance(vector));
    }
}
