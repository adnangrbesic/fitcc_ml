using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace BuyGuardian.Api.Migrations
{
    /// <inheritdoc />
    public partial class AddAnomalyFields : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.AlterColumn<DateTime>(
                name: "NextScrape",
                table: "SearchQueries",
                type: "timestamp with time zone",
                nullable: false,
                oldClrType: typeof(DateTime),
                oldType: "timestamp without time zone");

            migrationBuilder.AlterColumn<DateTime>(
                name: "LastScrape",
                table: "SearchQueries",
                type: "timestamp with time zone",
                nullable: true,
                oldClrType: typeof(DateTime),
                oldType: "timestamp without time zone",
                oldNullable: true);

            migrationBuilder.AlterColumn<DateTime>(
                name: "RecordedAt",
                table: "PriceHistories",
                type: "timestamp with time zone",
                nullable: false,
                oldClrType: typeof(DateTime),
                oldType: "timestamp without time zone");

            migrationBuilder.AlterColumn<DateTime>(
                name: "ScrapedAt",
                table: "Listings",
                type: "timestamp with time zone",
                nullable: false,
                oldClrType: typeof(DateTime),
                oldType: "timestamp without time zone");

            migrationBuilder.AddColumn<double>(
                name: "AnomalyScore",
                table: "Listings",
                type: "double precision",
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "AnomalyType",
                table: "Listings",
                type: "text",
                nullable: true);

            migrationBuilder.AddColumn<bool>(
                name: "IsAnomaly",
                table: "Listings",
                type: "boolean",
                nullable: true);

            migrationBuilder.AddColumn<double>(
                name: "IFContamination",
                table: "Categories",
                type: "double precision",
                nullable: false,
                defaultValue: 0.0);
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropColumn(
                name: "AnomalyScore",
                table: "Listings");

            migrationBuilder.DropColumn(
                name: "AnomalyType",
                table: "Listings");

            migrationBuilder.DropColumn(
                name: "IsAnomaly",
                table: "Listings");

            migrationBuilder.DropColumn(
                name: "IFContamination",
                table: "Categories");

            migrationBuilder.AlterColumn<DateTime>(
                name: "NextScrape",
                table: "SearchQueries",
                type: "timestamp without time zone",
                nullable: false,
                oldClrType: typeof(DateTime),
                oldType: "timestamp with time zone");

            migrationBuilder.AlterColumn<DateTime>(
                name: "LastScrape",
                table: "SearchQueries",
                type: "timestamp without time zone",
                nullable: true,
                oldClrType: typeof(DateTime),
                oldType: "timestamp with time zone",
                oldNullable: true);

            migrationBuilder.AlterColumn<DateTime>(
                name: "RecordedAt",
                table: "PriceHistories",
                type: "timestamp without time zone",
                nullable: false,
                oldClrType: typeof(DateTime),
                oldType: "timestamp with time zone");

            migrationBuilder.AlterColumn<DateTime>(
                name: "ScrapedAt",
                table: "Listings",
                type: "timestamp without time zone",
                nullable: false,
                oldClrType: typeof(DateTime),
                oldType: "timestamp with time zone");
        }
    }
}
