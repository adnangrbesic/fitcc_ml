using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace BuyGuardian.Api.Migrations
{
    /// <inheritdoc />
    public partial class AddIsNewAndListingCount : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.AddColumn<bool>(
                name: "IsNew",
                table: "Listings",
                type: "boolean",
                nullable: false,
                defaultValue: false);

            migrationBuilder.AddColumn<int>(
                name: "ListingCount",
                table: "Categories",
                type: "integer",
                nullable: false,
                defaultValue: 0);
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropColumn(
                name: "IsNew",
                table: "Listings");

            migrationBuilder.DropColumn(
                name: "ListingCount",
                table: "Categories");
        }
    }
}
