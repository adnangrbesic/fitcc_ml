using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace BuyGuardian.Api.Migrations
{
    /// <inheritdoc />
    public partial class AddVotesAndAlerts : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            // NOTE: Removed auto-generated DropIndex/CreateIndex for Products
            // because existing data has duplicate (CanonicalName, CategoryId) pairs.
            // These index changes are unrelated to AnalysisVotes/PriceAlerts.

            migrationBuilder.CreateTable(
                name: "AnalysisVotes",
                columns: table => new
                {
                    Id = table.Column<Guid>(type: "uuid", nullable: false),
                    ItemId = table.Column<string>(type: "character varying(128)", maxLength: 128, nullable: false),
                    Vote = table.Column<string>(type: "character varying(4)", maxLength: 4, nullable: false),
                    UserFingerprint = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                    ModelTrustScore = table.Column<double>(type: "double precision", nullable: true),
                    CreatedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: false),
                    Weight = table.Column<double>(type: "double precision", nullable: false),
                    ListingId = table.Column<Guid>(type: "uuid", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_AnalysisVotes", x => x.Id);
                    table.ForeignKey(
                        name: "FK_AnalysisVotes_Listings_ListingId",
                        column: x => x.ListingId,
                        principalTable: "Listings",
                        principalColumn: "Id");
                });

            migrationBuilder.CreateTable(
                name: "PriceAlerts",
                columns: table => new
                {
                    Id = table.Column<Guid>(type: "uuid", nullable: false),
                    ItemId = table.Column<string>(type: "character varying(128)", maxLength: 128, nullable: false),
                    UserFingerprint = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                    SubscribedPrice = table.Column<decimal>(type: "numeric(18,2)", nullable: false),
                    TargetPrice = table.Column<decimal>(type: "numeric(18,2)", nullable: true),
                    IsActive = table.Column<bool>(type: "boolean", nullable: false),
                    Triggered = table.Column<bool>(type: "boolean", nullable: false),
                    CreatedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: false),
                    LastCheckedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: true),
                    TriggeredAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: true),
                    ListingId = table.Column<Guid>(type: "uuid", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_PriceAlerts", x => x.Id);
                    table.ForeignKey(
                        name: "FK_PriceAlerts_Listings_ListingId",
                        column: x => x.ListingId,
                        principalTable: "Listings",
                        principalColumn: "Id");
                });

            // NOTE: Products index change removed — unrelated to this migration.

            migrationBuilder.CreateIndex(
                name: "IX_AnalysisVotes_ItemId",
                table: "AnalysisVotes",
                column: "ItemId");

            migrationBuilder.CreateIndex(
                name: "IX_AnalysisVotes_ItemId_UserFingerprint",
                table: "AnalysisVotes",
                columns: new[] { "ItemId", "UserFingerprint" },
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_AnalysisVotes_ListingId",
                table: "AnalysisVotes",
                column: "ListingId");

            migrationBuilder.CreateIndex(
                name: "IX_PriceAlerts_IsActive",
                table: "PriceAlerts",
                column: "IsActive");

            migrationBuilder.CreateIndex(
                name: "IX_PriceAlerts_ItemId",
                table: "PriceAlerts",
                column: "ItemId");

            migrationBuilder.CreateIndex(
                name: "IX_PriceAlerts_ListingId",
                table: "PriceAlerts",
                column: "ListingId");

            migrationBuilder.CreateIndex(
                name: "IX_PriceAlerts_UserFingerprint",
                table: "PriceAlerts",
                column: "UserFingerprint");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropTable(
                name: "AnalysisVotes");

            migrationBuilder.DropTable(
                name: "PriceAlerts");
        }
    }
}
