using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace BuyGuardian.Api.Migrations
{
    /// <inheritdoc />
    public partial class UpdateSellerMetadata : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.AddColumn<bool>(
                name: "IsAddressVerified",
                table: "Sellers",
                type: "boolean",
                nullable: false,
                defaultValue: false);

            migrationBuilder.AddColumn<bool>(
                name: "IsEmailVerified",
                table: "Sellers",
                type: "boolean",
                nullable: false,
                defaultValue: false);

            migrationBuilder.AddColumn<bool>(
                name: "IsPhoneVerified",
                table: "Sellers",
                type: "boolean",
                nullable: false,
                defaultValue: false);

            migrationBuilder.AddColumn<int>(
                name: "NegativeFeedback",
                table: "Sellers",
                type: "integer",
                nullable: false,
                defaultValue: 0);

            migrationBuilder.AddColumn<int>(
                name: "NeutralFeedback",
                table: "Sellers",
                type: "integer",
                nullable: false,
                defaultValue: 0);

            migrationBuilder.AddColumn<int>(
                name: "SuccessfulDeliveries",
                table: "Sellers",
                type: "integer",
                nullable: false,
                defaultValue: 0);
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropColumn(
                name: "IsAddressVerified",
                table: "Sellers");

            migrationBuilder.DropColumn(
                name: "IsEmailVerified",
                table: "Sellers");

            migrationBuilder.DropColumn(
                name: "IsPhoneVerified",
                table: "Sellers");

            migrationBuilder.DropColumn(
                name: "NegativeFeedback",
                table: "Sellers");

            migrationBuilder.DropColumn(
                name: "NeutralFeedback",
                table: "Sellers");

            migrationBuilder.DropColumn(
                name: "SuccessfulDeliveries",
                table: "Sellers");
        }
    }
}
