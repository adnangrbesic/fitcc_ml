# BuyGuardian API

.NET 8 Minimal API with Clean Architecture, PostgreSQL, and pgvector.

## Prerequisites

- [.NET 8 SDK](https://dotnet.microsoft.com/download/dotnet/8.0)
- [Docker Desktop](https://www.docker.com/products/docker-desktop)

## Getting Started

1. **Start Infrastructure**:
   ```bash
   # Run this from the root directory
   docker-compose -f ../../docker-compose.yml up -d
   ```

2. **Database Migrations**:
   ```bash
   dotnet ef migrations add InitialCreate
   dotnet ef database update
   ```

3. **Run the API**:
   ```bash
   dotnet run
   ```

4. **Explore Swagger**:
   Open `https://localhost:5001/swagger` (or the port shown in your terminal).

## Key Features

- **Clean Architecture**: Separation of concerns with MediatR.
- **pgvector Integration**: Support for vector embeddings in PostgreSQL.
- **Redis Ready**: Caching interface implemented and ready for production.
- **Minimal API**: Performance-oriented design.
- **JSON Columns**: Full support for dynamic metadata using `Dictionary<string, object>`.

## Project Structure

- `Controllers/`: API Endpoints.
- `Data/`: Entity Framework Core context and configurations.
- `Features/`: MediatR commands, queries, and handlers.
- `Models/`: Domain entities.
- `Interfaces/`: Common interfaces for services.
